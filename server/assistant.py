"""The assistant: note inspection, conversations and proposals.

A note is inspected when the writer asks, or — with live watching on — quietly,
after a 15-second pause or a paste (the browser decides when). A quiet pass
never interrupts: not a running pass, not a conversation, not the writer; its
questions wait in the panel instead of popping the HUD. Results become tree
nodes, history entries and HUD cards; note changes still require approval.
"""
import asyncio
import contextlib
import difflib
import functools
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path

from core import llm_client
from server.errors import ApiError
from server import ladder
from server.budget import Budget
from server.providers import ProviderRegistry
from server.settings import LAUNCH_SCRIPTS
from server.store import MAX_ASSISTANT_TEXTS, now_iso
from server.vault import fold, plain, split_frontmatter

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


def section_of(content: str, span) -> str:
    """The heading a change sits under, so suggestions can hang off the part of
    the note they are actually about instead of all off the note itself."""
    at = span[0] if span else len(content)
    current = ""
    for match in HEADING_RE.finditer(content):
        if match.start() > at:
            break
        # the top-level title is the note itself, not a section within it
        current = "" if len(match.group(1)) <= 1 else match.group(2).strip()
    return current


def sections_of(content: str) -> list[tuple[str, str]]:
    """[(heading, body)] for the note's sections, the intro first as ""."""
    return [(name, body) for name, body, _, _ in sections_with_spans(content)]


def sections_with_spans(content: str) -> list[tuple[str, str, int, int]]:
    """[(heading, body, start, end)] — spans let a pass look at one section."""
    parts: list[tuple[str, str, int, int]] = []
    last_name, last_at, heading_at = "", 0, 0
    for match in HEADING_RE.finditer(content):
        parts.append((last_name, content[last_at:match.start()], heading_at, match.start()))
        last_name = "" if len(match.group(1)) <= 1 else match.group(2).strip()
        last_at, heading_at = match.end(), match.start()
    parts.append((last_name, content[last_at:], heading_at, len(content)))
    return parts


def focus_span(content: str, nodes: list[dict], span) -> list[int] | None:
    """What this pass should look at.

    While the writer is editing, follow the edit. For a whole-note pass, take
    the section with the fewest questions so the assistant works its way across
    the note instead of circling the opening paragraph forever.
    """
    if span and (span[1] - span[0]) < len(content) * 0.6:
        return span
    counts: dict[str, int] = {}
    for node in nodes:
        if node["type"] == "question" and node.get("status") != "dismissed":
            counts[node.get("section") or ""] = counts.get(node.get("section") or "", 0) + 1
    candidates = [(name, start, end) for name, body, start, end in sections_with_spans(content) if body.strip()]
    if not candidates:
        return span
    name, start, end = min(enumerate(candidates), key=lambda p: (counts.get(p[1][0], 0), p[0]))[1]
    return [start, end]


def _stems(text: str) -> set[str]:
    """Turkish glues suffixes onto words ("konuşma" / "konuşarak"), so compare
    word beginnings rather than whole words."""
    return {w[:5] for w in re.findall(r"\w{5,}", fold(text))}


def _same_topic(new: set[str], old: set[str]) -> bool:
    """Two questions about the same thing, however differently worded.
    Measured against the shorter one, so padding a question out doesn't hide it."""
    if not new or not old:
        return False
    shared = len(new & old)
    return shared >= 2 and shared / min(len(new), len(old)) >= 0.5


# "yoksa" and "olacak" are in every either-or question: codlaud.md's data
# question hung under "Projeyi kim kullanacak?" on "yoksa" and "kullan" alone
_QUESTION_FILLER = {"hangi", "nasil", "neden", "niye", "olara", "olarak", "icin",
                    "bunun", "bunla", "bunu", "daha", "sonra", "neden", "fikri",
                    "fikir", "proje", "baska", "hangi", "sence", "olmal", "yapar",
                    "yoksa", "olaca"}

# How far below a question a follow-up may go: one step. A question may be
# followed up once; a follow-up of a follow-up is the narrowing itself — each
# new question about a smaller detail of the last answer (kaan.md: four
# questions, one after another, under q7, itself a follow-up of q1, all about
# the same notification screen).
MAX_FOLLOWUP_DEPTH = 1


def _topic_stems(text: str) -> set[str]:
    """Small, local relevance signal; model-supplied parent ids take priority."""
    return {word[:5] for word in re.findall(r"\w{5,}", fold(text))
            if word[:5] not in _QUESTION_FILLER}


def question_depth(node_id: str, nodes: list[dict]) -> int:
    """How many questions this one hangs under. A damaged tree (a missing
    parent, a cycle) ends the count instead of hanging it."""
    by_id = {n["id"]: n for n in nodes}
    depth, seen = 0, {node_id}
    current = by_id.get((by_id.get(node_id) or {}).get("parentId"))
    while current and current.get("type") == "question" and current["id"] not in seen:
        seen.add(current["id"])
        depth += 1
        current = by_id.get(current.get("parentId"))
    return depth


def may_follow_up(question: dict, nodes: list[dict]) -> bool:
    """May a new question hang under this one? Not under a follow-up, and not
    under a question that already has one (a dismissed one does not count):
    a second, third, fourth follow-up of the same answer is circling it
    instead of moving on, even if each waits for the last to be answered."""
    if question.get("type") != "question" or question.get("status") == "dismissed":
        return False
    if question_depth(question["id"], nodes) >= MAX_FOLLOWUP_DEPTH:
        return False
    return not any(n.get("type") == "question" and n.get("parentId") == question["id"]
                   and n.get("status") != "dismissed" for n in nodes)


def question_parent(item: dict, text: str, section: str, nodes: list[dict],
                    climbing: bool) -> tuple[str | None, bool]:
    """Where a new question hangs, and whether it is asked at all.

    A software note's question asks for a decision of its own, so it never
    hangs under another decision's answer (codlaud.md: the data and the
    external-services questions went under "who" and "online?"). On an idea
    note the model may name the question it follows up — a genuinely needed
    follow-up is its call — but only where may_follow_up allows: one that
    would go deeper is the narrowing, and is not asked. Without a name the
    guess below decides, and it never picks an answered question.
    """
    if climbing:
        return None, True
    requested = item.get("parent_id") or item.get("related_to")
    named = next((n for n in nodes if n.get("type") == "question" and n.get("id") == requested
                  and n.get("status") != "dismissed"), None)
    if named is not None:
        return (named["id"], True) if may_follow_up(named, nodes) else (None, False)
    return related_question_parent(text, section, nodes), True


def related_question_parent(text: str, section: str, nodes: list[dict]) -> str | None:
    """Conservative fallback when the analysis model did not supply a parent id.

    Use earlier question and answer terms, not merely the shared section. The
    latter would turn every independent question in a section into one chain.
    Only a question still waiting for its answer is a candidate: one already
    answered is settled, and a new question that shares its answer's words is
    usually about the write-up of that answer in the note — hung under it,
    every pass drilled one level deeper into what the writer had just said.
    """
    terms = _topic_stems(text)
    if len(terms) < 2:
        return None
    best_id, best_score = None, 0.0
    for node in nodes:
        if node.get("type") != "question" or node.get("status") != "open":
            continue
        if not may_follow_up(node, nodes):
            continue
        question_terms = _topic_stems(node.get("text", ""))
        messages = [m.get("text", "") for m in nodes
                    if m.get("parentId") == node.get("id") and m.get("type") in ("chat-user", "chat-assistant")]
        conversation_terms = _topic_stems(" ".join(messages[-4:]))
        shared_question = terms & question_terms
        shared_answer = terms & conversation_terms
        shared = shared_question | shared_answer
        if len(shared) < 2:
            continue
        score = len(shared_question) * 2 + len(shared_answer) + len(shared) / len(terms)
        if section and section == node.get("section"):
            score += 0.4
        if score > best_score:
            best_id, best_score = node["id"], score
    return best_id


def section_coverage(content: str, nodes: list[dict]) -> str:
    """Tell the model which parts of the note already have questions, so it
    stops circling the first paragraph."""
    counts: dict[str, int] = {}
    for node in nodes:
        if node["type"] == "question" and node.get("status") != "dismissed":
            counts[node.get("section") or ""] = counts.get(node.get("section") or "", 0) + 1
    lines = []
    for name, body in sections_of(content):
        if not body.strip():
            continue
        asked = counts.get(name, 0)
        lines.append(f"- {name or '(giriş)'}: {'henüz soru yok' if not asked else f'{asked} soru soruldu'}")
    return "\n".join(lines)


def section_for(content: str, text: str, span) -> str:
    """Which part of the note a suggestion is about.

    The edit position only helps while the writer is typing; on a note's first
    pass everything counts as new, so match the question's own wording against
    each section — a question mentioning "2 dakika konuşma" belongs wherever
    that phrase lives. No match means the note's opening, never the last
    heading that happened to be nearest the end.
    """
    asked = _stems(text)
    best_name, best_score = None, 0
    for name, body in sections_of(content):
        score = len(asked & _stems(body))
        if score > best_score:
            best_name, best_score = name, score
    if best_name is not None:
        return best_name
    return section_of(content, span) if span else ""


QUESTION_STARTS = ("neden", "niye", "nasil", "nasıl", "hangi", "kim", "kac", "kaç",
                   "nerede", "nereye", "ne ", "peki", "sence", "sen ne")


# the question particle, written apart ("var mı") or, often, glued on ("varmı")
QUESTION_PARTICLE = re.compile(r"\bm[iu](s[iu]n|s[iu]n[iu]z|y[iu]m|y[iu]z|d[iu]r)?\b"
                               r"|\b(var|yok|olur|olmaz|mumkun|dogru|iyi|lazim|gerek)m[iu]\b")
# "I don't know" and "what would you suggest": the writer wants ideas, not to
# have their not knowing written down as a decision
WANTS_IDEAS = re.compile(r"\b(bilmiyorum|bilmiyor olmam|bilemedim|bilmem\b|fikrim yok|hic fikrim|emin degilim|"
                         r"karar veremedim|karar veremiyorum|fikir ver|fikrin|fikirlerin|onerin|onerilerin|"
                         r"ne onerirsin|sen oner|onerir misin|ne yapilabilir|ne yapabiliriz|yardim et)"
                         # the writers of the other UI languages say the same (seen: an
                         # English "I don't know, any ideas?" was taken for a question)
                         r"|\b(i don'?t know|dunno|not sure|no idea|any ideas?|suggest|what would you|"
                         r"help me (decide|choose)|you decide|weiss (ich )?nicht|keine ahnung|nicht sicher|"
                         r"ideen?\b|vorschlag|schlag (du )?(etwas )?vor|no lo se|no se que|ni idea|no estoy segur|"
                         r"alguna idea|sugier|recomiend|je ne sais pas|aucune idee|pas sur\b|une idee|"
                         r"des idees|conseill)")
# a write-up that files the not knowing itself ("has no technical knowledge,
# needs guidance", "not settled yet, looking for ideas") — measured on
# DeepSeek V4 Flash — is not a decision
UNDECIDED_NOTE = re.compile(r"bilmiyor|bilmedig|emin degil|bilgisi yok|bilgiye sahip degil|sahip olmadig|"
                            r"rehberlig|fikir ariyor|netlesmedi|karar vermedi|karar veremedi"
                            r"|does(n'?t| not) know|is unsure|needs guidance|not (yet )?decided|"
                            r"weiss nicht|ist unsicher|noch nicht entschieden|no sabe|no esta segur|sin decidir|"
                            r"ne sait pas|pas encore decid")


def ascii_fold(text: str) -> str:
    """plain() and the other UI languages' accents too: "idée" is "idee",
    "weiß" is "weiss" — the patterns above are written without them."""
    return "".join(c for c in unicodedata.normalize("NFKD", plain(text)) if not unicodedata.combining(c))


def looks_like_question(text: str) -> bool:
    """A message that asks something must not be swallowed as an answer."""
    stripped = fold(text.strip())
    return (stripped.endswith("?") or stripped.startswith(QUESTION_STARTS)
            or bool(QUESTION_PARTICLE.search(plain(stripped))))

def asks_for_ideas(text: str) -> bool:
    return bool(WANTS_IDEAS.search(ascii_fold(text)))


def under_path(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(f"{prefix}/")


MIN_NEW_CHARS = 40
THINKING_THROTTLE_S = 0.4
CHAT_THROTTLE_S = 0.12
# How many questions to ask, and how long to keep asking in a chat, is the
# model's call: it sees how the writer is keeping up ([TEMPO]) and paces itself.
# A fixed three cut writers off just as they got going. These two are fuses
# for a model gone wrong, set well past anything a normal session reaches.
FOLLOWUP_FUSE = 8
OPEN_QUESTION_FUSE = 12
# Measured on Qwen3-4B (2026-09-29): told that 8 questions had waited 45
# minutes, it still asked 5 more each pass. So the one case where the pace is
# not the model's alone: this many unanswered and none settled lately — the
# writer is not keeping up — and a pass adds at most one question. A writer
# who answers is never held back by it.
BACKLOG = 5
HEALTH_INTERVAL_UP_S = 30
HEALTH_INTERVAL_DOWN_S = 5          # doubles while it stays down, up to the max
HEALTH_INTERVAL_MAX_S = 60
ROLES_WATCHED = ("analysis", "chat", "summary", "complete", "compare", "master")
# what a refused call says about the provider, in the writer's words
PROBLEM_OF_STATUS = {401: "key", 402: "credit", 403: "access", 429: "rate"}
PROBLEM_STATUS = {kind: status for status, kind in PROBLEM_OF_STATUS.items()}
PROBLEMS = {
    "key": "API anahtarı reddedildi. Ayarlar → Sihirbazla bağla ile yeni bir anahtar gir.",
    "credit": "Sağlayıcı hesabında kredi kalmadı. Kredi yükle ya da başka bir modele bağlan.",
    "access": "Bu anahtarın seçili modele erişimi yok. Ayarlar'dan başka bir model seç.",
    "rate": "Sağlayıcının hız sınırına takıldı; biraz sonra yeniden denenecek.",
}
RATE_PROBLEM_S = 90                 # a rate limit passes: shown only this long
LAUNCH_TIMEOUT_S = 240  # a 75 GB MoE checkpoint needs ~1 min cold, more on a busy disk


def msys_path(path: Path) -> str:
    """C:\\Users\\x\\run.sh → /c/Users/x/run.sh (what Git Bash expects)."""
    text = str(path).replace("\\", "/")
    if len(text) > 1 and text[1] == ":":
        text = f"/{text[0].lower()}{text[2:]}"
    return text


def find_bash() -> Path | None:
    """Git Bash — NOT C:\\Windows\\System32\\bash.exe, which only launches WSL and
    cannot run these scripts (Windows .exe paths, /d/... drive paths)."""
    override = os.environ.get("FIKIR_BASH")
    if override and Path(override).is_file():
        return Path(override)
    if sys.platform != "win32":
        found = shutil.which("bash")
        return Path(found) if found else None
    candidates = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Git/bin/bash.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Git/bin/bash.exe",
        Path(os.environ.get("LOCALAPPDATA", r"C:\Users\Default\AppData\Local")) / "Programs/Git/bin/bash.exe",
        Path(r"C:\Program Files\Git\usr\bin\bash.exe"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    found = shutil.which("bash")
    if found and "system32" not in found.lower() and "windowsapps" not in found.lower():
        return Path(found)
    return None


# shorter than this, a write-up cannot be told apart from anything else; the
# editor draws the same line (assistantRanges in web/js/editor.js)
WRITTEN_MIN_CHARS = 12
# the latest write-ups an idea note's pass is told are settled; a long note
# holds dozens, and the most recent are the ones a pass would dig into
SETTLED_SHOWN = 6


def written_ranges(text: str, written) -> list[tuple[int, int]]:
    """Where the sentences the assistant put in the note with the writer's
    approval (state["assistant_text"]) sit — found by their exact wording, as
    the editor finds them: a sentence the writer has since edited is theirs."""
    found = []
    for snippet in written or ():
        needle = (snippet or "").strip()
        if len(needle) < WRITTEN_MIN_CHARS:
            continue
        at = text.find(needle)
        while at != -1:
            found.append((at, at + len(needle)))
            at = text.find(needle, at + len(needle))
    merged: list[tuple[int, int]] = []
    for start, end in sorted(found):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _outside(text: str, start: int, end: int, ranges) -> str:
    """text[start:end] less whatever of it falls inside `ranges`."""
    kept, at = [], start
    for r_start, r_end in ranges:
        if r_end <= at or r_start >= end:
            continue
        if r_start > at:
            kept.append(text[at:r_start])
        at = r_end
    if at < end:
        kept.append(text[at:end])
    return "".join(kept)


def _writers_lines(text: str, start: int, end: int, ranges) -> tuple[str, list[int] | None]:
    """The whole lines text[start:end] less those that are nothing but an
    approved write-up, and the span of what the writer wrote among them.
    Blank lines stay: they keep the writer's paragraphs apart."""
    if not ranges:
        return text[start:end], [start, end]
    kept, first, last, at = [], None, None, start
    for line in text[start:end].splitlines(keepends=True):
        line_end = at + len(line)
        own = _outside(text, at, line_end, ranges)
        if own.strip():
            first = at if first is None else first
            last = line_end
        if own.strip() or not line.strip():
            kept.append(line)
        at = line_end
    return re.sub(r"\n{3,}", "\n\n", "".join(kept)), ([first, last] if first is not None else None)


def diff_new_text(old: str, new: str, written=()) -> tuple[str, int, list[int] | None]:
    """What changed since the last analysis.

    Returns (new_part, changed_chars, [start, end]). new_part is whole changed
    lines so the model gets readable context; changed_chars counts only the
    characters actually typed, so fixing one typo in a long paragraph doesn't
    look like 300 new characters. The old PyQt app only looked at text past
    the previous length, so anything written above the end was never seen.

    written: what the assistant put in the note with the writer's approval.
    It is the writer's answer in the assistant's words, and the decisions
    already record it: it stays in the note as context but is not new
    material. Counted, every approval woke a pass that asked about the
    details of the answer just given, and the scope narrowed pass by pass
    (kaan.md, 2026-09-26: eight of its ten paragraphs were the assistant's,
    each followed within a minute by a question about itself).
    """
    if old == new:
        return "", 0, None
    mine = written_ranges(new, written)
    if new.startswith(old):
        added = new[len(old):]
        own = _outside(new, len(old), len(new), mine)
        if added.strip() and not own.strip():
            return "", 0, None                  # only a write-up came in
        line_start = new.rfind("\n", 0, len(old)) + 1
        part, span = _writers_lines(new, line_start, len(new), mine)
        return part.strip(), len(own.strip()), span

    before_lines = old.splitlines(keepends=True)
    after_lines = new.splitlines(keepends=True)
    offsets = [0]
    for line in after_lines:
        offsets.append(offsets[-1] + len(line))

    parts, changed, start, end = [], 0, None, None
    matcher = difflib.SequenceMatcher(None, before_lines, after_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag not in ("insert", "replace"):
            continue
        at, stop = offsets[j1], offsets[j2]
        segment = new[at:stop]
        replaced = "".join(before_lines[i1:i2])
        if tag == "insert" or len(replaced) * len(segment) > 4_000_000:
            typed, own = segment, _outside(new, at, stop, mine)
            by_writer = len(own.strip())
        else:
            inner = difflib.SequenceMatcher(None, replaced, segment, autojunk=False)
            spans = [(at + k1, at + k2) for op, _, _, k1, k2 in inner.get_opcodes() if op in ("insert", "replace")]
            typed = "".join(new[a:b] for a, b in spans)
            own = "".join(_outside(new, a, b, mine) for a, b in spans)
            by_writer = len(own)
        if typed.strip() and not own.strip():
            continue                            # nothing here but a write-up
        changed += by_writer
        part, part_span = _writers_lines(new, at, stop, mine)
        parts.append(part.strip("\n"))
        if part_span:
            start = part_span[0] if start is None else min(start, part_span[0])
            end = part_span[1] if end is None else max(end, part_span[1])

    new_part = "\n".join(p for p in parts if p.strip()).strip()
    return new_part, changed, ([start, end] if start is not None else None)


def writers_tail(content: str, written, limit: int = 800) -> tuple[str, list[int]]:
    """What a pass you asked for looks at when nothing is new: the end of what
    you wrote yourself. The note's own end is, after a few approvals, the
    assistant's write-ups."""
    mine = written_ranges(content, written)
    if not mine:
        return content[-limit:], [max(0, len(content) - limit), len(content)]
    pieces, at = [], 0
    for start, end in [*mine, (len(content), len(content))]:
        if content[at:start].strip():           # the blank lines between write-ups are no one's
            pieces.append((at, start))
        at = max(at, end)
    taken, size = [], 0
    for start, end in reversed(pieces):
        if size >= limit:
            break
        start = max(start, end - (limit - size))
        taken.insert(0, (start, end))
        size += end - start
    text = re.sub(r"\n{3,}", "\n\n", "".join(content[s:e] for s, e in taken)).strip()
    if not text:                                # a note of write-ups only
        return content[-limit:], [max(0, len(content) - limit), len(content)]
    return text, [taken[0][0], taken[-1][1]]


def _tail(text: str, limit: int | None) -> str:
    if limit is None or len(text) <= limit:
        return text
    snippet = text[-limit:]
    return snippet.split(" ", 1)[-1] if " " in snippet else snippet  # don't start mid-word


def _drop_partial_tag(text: str, tag: str) -> str:
    """Tokens arrive a few characters at a time, so a tag can be cut mid-way ("...</thi")."""
    for size in range(min(len(tag) - 1, len(text)), 0, -1):
        if text.lower().endswith(tag[:size]):
            return text[:-size]
    return text


def strip_protocol(text: str) -> str:
    """Hide the ANLADIM / NOT: / SORU: markers while a reply streams in."""
    text = re.sub(r"^\s*ANLADIM\s*:?\s*", "", text, flags=re.IGNORECASE)
    return re.sub(r"^\s*(NOT|SORU)\s*:\s*", "", text, flags=re.IGNORECASE)


def thinking_preview(accumulated: str, limit: int | None = 220) -> dict:
    """Split a streaming reply into what the model is thinking vs. writing.
    Search tags in the original text: lowercasing shifts indices past 'İ'."""
    close = llm_client.THINK_CLOSE.search(accumulated)
    if close:
        answer = accumulated[close.end():].strip()
        return {"phase": "writing", "text": _tail(answer, limit)}
    opening = llm_client.THINK_OPEN.search(accumulated)
    if opening:
        thought = accumulated[opening.end():]
        return {"phase": "thinking", "text": _tail(_drop_partial_tag(thought, "</think>").strip(), 220)}
    if "<think>".startswith(accumulated.lstrip().lower()):
        return {"phase": "thinking", "text": ""}
    return {"phase": "writing", "text": _tail(accumulated.strip(), limit)}


class Assistant:
    def __init__(self, vault, notes, history, broker, providers: ProviderRegistry | None = None,
                 tool_hub=None):
        self.vault = vault
        self.notes = notes
        self.history = history
        self.broker = broker
        self.providers = providers or ProviderRegistry()
        self.tool_hub = tool_hub
        self.budget = Budget(vault)
        self.busy: str | None = None
        self.queue: list[dict] = []
        self._busy_content: str | None = None
        self._busy_quiet = False  # the running pass is the live watch's, not one you asked for
        self._next_force: tuple[str, str] | None = None  # asked for while a stale pass was stopping
        self._chatting = 0        # conversations in flight: they have the model, the watch waits
        self._claims: set[str] = set()
        self._focus: str | None = None   # the note the writer last asked about: its items lead the card
        self._run_id = 0          # bumped to abandon an analysis whose answer is stale
        self._cancelled: set[int] = set()
        self._tasks: set[asyncio.Task] = set()
        self._wake = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        # provider id -> what stops it (see PROBLEMS); shown until a call gets through
        self.problems: dict[str, dict] = {}
        record = self.budget.record

        def recorded(provider, *args, **kwargs):
            # a call that got an answer: whatever stopped this provider is over
            if self.problems.pop(provider.id, None) is not None:
                self._publish_status()
            return record(provider, *args, **kwargs)

        self.budget.record = recorded

    def note_problem(self, provider, status: int | None) -> str | None:
        """A refused call that will not fix itself by waiting — a dead key,
        no credit — stays on show instead of each pass failing unseen.
        Returns the words for the writer, or None when it is no such refusal."""
        kind = PROBLEM_OF_STATUS.get(status)
        if kind is None or provider is None:
            return None
        known = self.problems.get(provider.id)
        self.problems[provider.id] = {"kind": kind, "message": PROBLEMS[kind], "provider": provider.label,
                                      "at": time.monotonic()}
        if not known or known["kind"] != kind:
            self._publish_status()
        return PROBLEMS[kind]

    def problem(self) -> dict | None:
        """What stops the assistant now, for the status bar: the provider the
        jobs go to, then the day's budget."""
        for role in ("analysis", "chat"):
            for provider in self.providers.chain(role)[:1]:
                found = self.problems.get(provider.id)
                if found and not (found["kind"] == "rate" and time.monotonic() - found["at"] > RATE_PROBLEM_S):
                    return {key: value for key, value in found.items() if key != "at"}
                blocked = self.budget.check(provider)
                if blocked:
                    return {"kind": "budget", "message": blocked, "provider": provider.label}
        return None

    # ---- snapshot / publishing ----
    def usage(self) -> dict:
        return self.budget.public()

    def status(self) -> dict:
        analysis = self.providers.pick("analysis")
        chat = self.providers.pick("chat")
        return {
            "model_up": self.providers.is_up("analysis") or self.providers.is_up("chat"),
            "chat_up": self.providers.is_up("chat"),
            "fast_up": self.providers.is_up("analysis"),
            "endpoint": chat.display if chat else "—",
            "fast_endpoint": analysis.display if analysis else "—",
            "chat_provider": chat.label if chat else None,
            "analysis_provider": analysis.label if analysis else None,
            "chat_remote": bool(chat and chat.is_remote),
            "fast_remote": bool(analysis and analysis.is_remote),
            "remote_in_use": bool((chat and chat.is_remote) or (analysis and analysis.is_remote)),
            # one model does everything: the UI shows one light, not two
            "shared_model": bool(analysis and chat and analysis.id == chat.id),
            "usage": self.budget.public(),
            "problem": self.problem(),
            "busy": self.busy,
            "busy_quiet": bool(self.busy) and self._busy_quiet,
        }

    @property
    def model_up(self) -> bool:
        return self.providers.is_up("chat")

    @property
    def fast_up(self) -> bool:
        return self.providers.is_up("analysis")

    def hud(self) -> dict:
        return {"event": self.queue[0] if self.queue else None, "remaining": max(0, len(self.queue) - 1)}

    def snapshot(self) -> dict:
        return {"status": self.status(), "hud": self.hud()}

    def provider_for(self, role: str, rel: str | None = None):
        """Which provider does this job — never a remote one for a private note,
        and never a remote one once the day's budget is spent."""
        private = bool(rel) and self.is_private(rel)
        provider = self.providers.pick(role, local_only=private)
        if provider is None:
            raise ApiError(503, "Bu iş için tanımlı bir model sağlayıcısı yok."
                                + (" (Bu not gizli: sadece yerel modeller kullanılabilir.)" if private else ""))
        blocked = self.budget.check(provider)
        if blocked:
            local = self.providers.pick(role, local_only=True)
            if local is not None and not local.is_remote:
                return local
            raise ApiError(429, blocked)
        return provider

    async def test_provider(self, provider_id: str) -> dict:
        """Does this provider actually answer? Used when binding a key."""
        provider = self.providers.get(provider_id)
        if provider is None:
            raise ApiError(404, "Sağlayıcı bulunamadı.")
        started = time.monotonic()
        try:
            reply = await asyncio.to_thread(
                llm_client.probe, provider)
        except llm_client.ProviderError as exc:
            self.providers.set_health(provider.id, False)
            self._publish_status()
            return {"ok": False, "error": str(exc), "status": exc.status}
        except Exception as exc:
            self.providers.set_health(provider.id, False)
            self._publish_status()
            return {"ok": False, "error": f"Ulaşılamadı: {exc}"}
        self.providers.set_health(provider.id, True)
        self._publish_status()
        self.broker.publish("providers", self.providers.public())
        return {"ok": True, "latency_ms": round((time.monotonic() - started) * 1000), "reply": reply[:120]}

    def is_private(self, rel: str) -> bool:
        """`gizli: true` in a note's frontmatter keeps it off remote providers."""
        try:
            meta, _, _ = split_frontmatter(self.vault.read_note(rel)["content"])
        except Exception:
            return True     # unreadable: fail closed rather than send it out
        value = meta.get("gizli", meta.get("private", ""))
        return str(value).strip().lower() in ("true", "evet", "yes", "1")

    def tools_allowed(self, provider, rel: str) -> bool:
        """May this turn use the research tools?

        Three separate gates, all of which have to hold: the servers actually
        came up, the bound provider declares it can call tools (sending `tools`
        to one that cannot fails the whole request), and the note is not
        private — a web search leaves the machine just as surely as a remote
        provider does, so `gizli: true` rules it out even on a local model.
        """
        if self.tool_hub is None or not self.tool_hub.available:
            return False
        if not getattr(provider, "tools", False):
            return False
        return not self.is_private(rel)

    def _publish_status(self):
        self.broker.publish("status", self.status())

    def _publish_hud(self):
        self.broker.publish("hud", self.hud())

    def _publish_node(self, rel: str, node: dict):
        self.broker.publish("node", {"path": rel, "node": node})

    def _spawn(self, coro):
        try:
            task = asyncio.create_task(coro)
        except RuntimeError:  # called off the event loop (e.g. a threadpool route)
            if self._loop is None:
                coro.close()
                return
            self._loop.call_soon_threadsafe(self._spawn, coro)
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    @staticmethod
    def _event(event_type: str, rel: str, **fields) -> dict:
        return {"id": uuid.uuid4().hex[:12], "type": event_type, "path": rel, "note": Path(rel).stem,
                "created": datetime.now().isoformat(timespec="seconds"), **fields}

    def _record(self, event: dict, hud: bool = True):
        self.history.add(event)
        self.broker.publish("history", event)
        if hud:
            # the proposal an answer led to takes its question's place: the
            # card should not keep asking what was just answered
            asked = event.get("question_id")
            at = next((i for i, e in enumerate(self.queue)
                       if asked and e["type"] == "question" and e.get("path") == event.get("path")
                       and e.get("node_id") == asked), None)
            if at is not None:
                self.queue[at] = event
            elif event.get("path") and event.get("path") == self._focus:
                # the note you just asked about comes first, after its own earlier items
                lead = next((i for i, e in enumerate(self.queue) if e.get("path") != self._focus), len(self.queue))
                self.queue.insert(lead, event)
            else:
                self.queue.append(event)
            self._publish_hud()

    def focus_card(self, rel: str) -> None:
        """You asked about this note: its waiting items move to the front of
        the card (seen: Ctrl+Enter on one note, the card kept showing another
        note's question with "+19")."""
        self._focus = rel
        mine = [e for e in self.queue if e.get("path") == rel]
        if mine and self.queue[0].get("path") != rel:
            self.queue = mine + [e for e in self.queue if e.get("path") != rel]
            self._publish_hud()

    def _drop_from_queue(self, predicate) -> None:
        before = len(self.queue)
        self.queue = [e for e in self.queue if not predicate(e)]
        if len(self.queue) != before:
            self._publish_hud()

    # ---- model server ----
    def start(self):
        self._loop = asyncio.get_running_loop()
        self._spawn(self._health_loop())

    async def stop(self):
        for task in list(self._tasks):
            task.cancel()

    async def _health_loop(self):
        down_for = 0
        while True:
            # only providers a job is bound to: a default nobody uses kept the
            # loop at its fast pace all day, fetching a model catalogue each time
            bound = {pid for role in ROLES_WATCHED for pid in self.providers.roles.get(role, [])}
            providers = [p for p in self.providers.all() if p.id in bound]
            results = await asyncio.gather(
                *(asyncio.to_thread(llm_client.check_server, provider) for provider in providers),
                return_exceptions=True,
            )
            changed = False
            for provider, result in zip(providers, results):
                up = isinstance(result, dict) and result["up"]
                changed |= self.providers.set_health(provider.id, up)
                problem = result.get("problem") if isinstance(result, dict) else None
                if problem in ("key", "credit"):
                    self.note_problem(provider, PROBLEM_STATUS[problem])
                elif up and self.problems.get(provider.id, {}).get("kind") in ("key", "access"):
                    self.problems.pop(provider.id, None)       # a new key went in
                    changed = True
            if changed:
                self._publish_status()
                self.broker.publish("providers", self.providers.public())
            all_up = all(self.providers.health.get(p.id) for p in providers) if providers else False
            down_for = 0 if all_up else down_for + 1
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), HEALTH_INTERVAL_UP_S if all_up else
                                       min(HEALTH_INTERVAL_DOWN_S * 2 ** min(down_for - 1, 4), HEALTH_INTERVAL_MAX_S))
            except asyncio.TimeoutError:
                pass

    def check_now(self, delay: float = 0):
        if self._loop is None:
            return
        if delay:
            self._loop.call_soon_threadsafe(self._loop.call_later, delay, self._wake.set)
        else:
            self._loop.call_soon_threadsafe(self._wake.set)

    def launch_model(self, name: str):
        script = LAUNCH_SCRIPTS.get(name)
        if script is None:
            raise ApiError(404, "Bilinmeyen model.")
        if not script.exists():
            raise ApiError(404, f"Başlatma scripti bulunamadı: {script}")
        bash = find_bash()
        if bash is None:
            raise ApiError(500, "Git Bash bulunamadı. Kur ya da FIKIR_BASH ile yolunu ver "
                                "(Windows'un kendi bash.exe'si WSL'i açar, bu scriptleri çalıştıramaz).")

        log = self.vault.meta_dir / "model-launch.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        # ASCII only: the new console window uses the OEM codepage
        command = (
            f"{shlex.quote(msys_path(script))} 2>&1 | tee {shlex.quote(msys_path(log))}; "
            "code=${PIPESTATUS[0]}; echo; echo '[ model sunucusu durdu - cikis kodu:' $code ']'"
        )
        try:
            if sys.platform == "win32":
                # via cmd so its `pause` holds the window open on failure — otherwise
                # the console just blinks and the error is gone
                subprocess.Popen(f'cmd.exe /c ""{bash}" -c "{command}" & pause"',
                                 creationflags=subprocess.CREATE_NEW_CONSOLE, cwd=str(script.parent))
            else:
                subprocess.Popen([str(bash), "-c", command], cwd=str(script.parent))
        except OSError as exc:
            raise ApiError(500, f"Script çalıştırılamadı: {exc}")
        for delay in (3, 8, 15, 25):
            self.check_now(delay)
        self._spawn(self._watch_launch(log, fast="8901" in script.read_text(encoding="utf-8", errors="ignore")))

    async def _watch_launch(self, log: Path, fast: bool = False):
        """If the server never comes up, show why instead of leaving the user guessing."""
        for _ in range(int(LAUNCH_TIMEOUT_S / 2)):
            await asyncio.sleep(2)
            if (self.fast_up if fast else self.model_up):
                return
        if (self.fast_up if fast else self.model_up):
            return
        try:
            lines = [ln.strip() for ln in log.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
        except OSError:
            lines = []
        detail = lines[-1][:200] if lines else "Açılan konsol penceresindeki hatayı kontrol et."
        self.broker.publish("flash", {"kind": "error", "title": "Model hâlâ başlamadı", "body": detail})

    # ---- note inspection: asked for, or the quiet live watch ----
    def cancel_running(self, reason: str = "stale") -> None:
        """Stop reading the current answer — the note moved on without it."""
        if self.busy is None:
            return
        self._cancelled.add(self._run_id)
        self.broker.publish("thinking", {"path": self.busy, "phase": "done", "text": "", "reason": reason})

    async def analyze(self, rel: str, content: str, force: bool) -> dict:
        """force: the writer asked. Otherwise it is the live watch, which never
        interrupts anything. The big model spends 8-13 s thinking before every
        answer, so a pass takes 20-30 s: cancelling it whenever the writer typed
        on would mean a writer who pauses often never gets one finished."""
        if not (self.model_up or self.fast_up):
            return {"status": "model_down"}
        if self.busy:
            if not force or self.busy != rel:
                return {"status": "busy"}
            if content == self._busy_content:
                if self._busy_quiet:
                    # asked while the watch was already reading this very text:
                    # let that pass show itself instead of starting over
                    self._busy_quiet = False
                    self._publish_status()
                return {"status": "started"}
            # same note, newer text: this answer is out of date — stop it and
            # look again at what you asked about as soon as it has stopped
            self.cancel_running()
            self._next_force = (rel, content)
            return {"status": "started"}
        if not force and self._chatting:
            return {"status": "busy"}
        if force:
            self.focus_card(rel)
        if ladder.is_brief(content):
            return {"status": "brief"}
        if not content.strip():
            return {"status": "skipped"}

        state = self.notes.load(rel)
        # what the assistant wrote in with your approval is context, not news:
        # it neither wakes the watch nor becomes what the questions are about
        written = state.get("assistant_text") or []
        new_part, changed, span = diff_new_text(state.get("analyzed_text", ""), content, written)
        if not force and changed < MIN_NEW_CHARS:
            if not new_part:
                # only deletions, or only a write-up you approved — resync
                # silently, like the old app did
                with self.notes.lock:
                    state["analyzed_text"] = content
                    self.notes.save(rel)
            return {"status": "skipped"}
        if not new_part:
            new_part, span = writers_tail(content, written)

        self.busy = rel
        self._busy_content = content
        self._busy_quiet = not force
        self._run_id += 1
        self._publish_status()
        self._spawn(self._run_analysis(rel, content, new_part, span, self._run_id))
        return {"status": "started"}

    async def _run_analysis(self, rel: str, content: str, new_part: str, span, run_id: int):
        open_nodes = self.notes.open_questions(rel)
        note_state = self.notes.load(rel)
        nodes = note_state["nodes"]
        direction = (note_state.get("direction") or {}).get("text", "")
        mode = ladder.note_mode(content)
        roadmap = ladder.roadmap(self.ladder_for(rel)) if mode == "yazilim" else ""
        lens = self._next_lens(rel) if mode == "yazilim" else None
        span = focus_span(content, nodes, span)
        coverage = section_coverage(content, nodes)
        focus = section_of(content, span)
        if coverage:
            coverage += f"\n\nŞu an şu bölüme bakıyorsun: {focus or '(giriş)'} — sorularını buradan seç."
        branches = self._question_branches(rel, nodes)
        if branches:
            coverage += "\n\n[MEVCUT SORU DALLARI]\n" + branches
        # the write-ups you approved, named as settled: in the note they read
        # like anything else you wrote, and an idea note's questions went on
        # to dig into them. A software note's roadmap already says what is
        # decided, and the server drops any question about it.
        settled = [] if mode == "yazilim" else [
            text.strip()[:200] for text in (note_state.get("assistant_text") or [])
            if len(text.strip()) >= WRITTEN_MIN_CHARS and text.strip() in content][-SETTLED_SHOWN:]
        last_emit = 0.0
        cancelled = lambda: run_id in self._cancelled

        def on_chunk(accumulated: str):
            nonlocal last_emit
            now = time.monotonic()
            # a quiet pass does not stream its thinking at you; it starts to
            # the moment you ask for it (the flag is read on every chunk)
            if now - last_emit < THINKING_THROTTLE_S or cancelled() or self._busy_quiet:
                return
            last_emit = now
            self.broker.publish("thinking", {"path": rel, **thinking_preview(accumulated)})

        try:
            try:
                provider = self.provider_for("analysis", rel)
                climbing = mode == "yazilim"
                result = await asyncio.to_thread(
                    llm_client.ask_about_note, content, new_part,
                    [] if climbing else [n["text"] for n in open_nodes],
                    on_chunk, provider, span, cancelled, self.budget.record,
                    "" if climbing else coverage,
                    roadmap, mode, self.ladder_for(rel)["open"],
                    direction, tempo=self._tempo(rel), settled=settled,
                )
            except llm_client.Cancelled:
                return
            except llm_client.ProviderError as exc:
                # the watch retries at the next pause; only a pass you asked
                # for owes you an explanation — and a dead key or no credit
                # stays in the status bar either way (note_problem)
                told = self.note_problem(provider, exc.status)
                if not self._busy_quiet:
                    self.broker.publish("flash", {"kind": "error", "path": rel,
                                                  "title": "Model isteği reddedildi", "body": told or str(exc)})
                self.check_now()
                return
            except ApiError as exc:
                # no provider bound, or the day's budget spent: say that, not "not answering"
                if not self._busy_quiet:
                    self.broker.publish("flash", {"kind": "error", "path": rel,
                                                  "title": "Asistan çalışamadı", "body": exc.message})
                self._publish_status()
                return
            except Exception:
                if not self._busy_quiet:
                    self.broker.publish("flash", {"kind": "error", "path": rel, "title": "Model yanıt vermedi",
                                                  "body": "Model sunucusu çalışıyor mu kontrol et."})
                self.check_now()
                return
            if cancelled():
                return
            if climbing and lens and self._extras_wanted(rel):
                # the model's own suggestion and research request, in their own
                # call and through this pass's lens; a failure here never costs
                # the pass its questions
                try:
                    extras = await asyncio.to_thread(llm_client.offer_extras, content,
                                                     roadmap + ladder.lens_line(lens),
                                                     provider, self.budget.record)
                    result = {**extras, **result, "lens": lens[0]}
                except Exception:
                    pass
                if cancelled():
                    return
            # renamed while the model read it: the questions go to the note where it is now
            rel = self.notes.current(rel)
            self._apply_result(rel, content, span, result, open_nodes, mode, quiet=self._busy_quiet)
        finally:
            self._cancelled.discard(run_id)
            self.busy = None
            self._busy_content = None
            self._busy_quiet = False
            self.broker.publish("thinking", {"path": rel, "phase": "done", "text": ""})
            self._publish_status()
            queued, self._next_force = self._next_force, None
            if queued:
                self._spawn(self._analyze_queued(*queued))

    async def _analyze_queued(self, rel: str, content: str) -> None:
        """The pass you asked for while an out-of-date one was stopping."""
        try:
            self.vault.read_note(rel)
            await self.analyze(rel, content, True)
        except Exception:
            pass  # the note went away meanwhile; there is nothing left to look at

    def _tempo(self, rel: str) -> str:
        """How the writer is keeping up with the questions, for the model to
        pace itself by: how many wait, how long the oldest has waited, how
        many were settled lately."""
        return self._pace(rel)["line"]

    def _pace(self, rel: str) -> dict:
        questions = [n for n in self.notes.load(rel)["nodes"] if n["type"] == "question"]
        waiting = [n for n in questions if n.get("status") == "open"]
        now = datetime.now()

        def minutes_since(stamp) -> float:
            try:
                return (now - datetime.fromisoformat(stamp)).total_seconds() / 60
            except (TypeError, ValueError):
                return float("inf")

        settled = sum(1 for n in questions
                      if n.get("status") == "resolved" and minutes_since(n.get("resolved_at")) <= 30)
        line = f"Cevap bekleyen soru: {len(waiting)}"
        if waiting:
            oldest = max(minutes_since(n.get("created")) for n in waiting)
            if oldest != float("inf"):
                line += f" (en eskisi {max(1, round(oldest))} dakikadır bekliyor)"
        return {"waiting": len(waiting), "settled": settled,
                "line": f"{line}. Son 30 dakikada sonuçlanan soru: {settled}."}

    def _question_branches(self, rel: str, nodes: list[dict]) -> str:
        """Give the analysis model real ids and settled details from earlier
        turns — marked answered or waiting, and closed to follow-ups where the
        server would drop one (may_follow_up): the rule said, not just kept."""
        lines = []
        for question in (n for n in nodes if n.get("type") == "question"
                         and n.get("status") != "dismissed"):
            parent = question.get("parentId")
            line = f"- {question['id']}"
            if parent:
                line += f" (üst soru: {parent})"
            status = "cevaplandı, kapandı" if question.get("status") == "resolved" else "cevap bekliyor"
            if not may_follow_up(question, nodes):
                status += "; altına soru açılmaz"
            line += f" [{status}]: {question.get('text', '')[:150]}"
            thread = self.notes.thread(rel, question["id"])
            answers = [n.get("text", "") for n in thread if n.get("type") == "chat-user"]
            if answers:
                line += f" | Kullanıcının son yanıtı: {answers[-1][:180]}"
            replies = [n.get("text", "") for n in thread if n.get("type") == "chat-assistant"]
            if replies:
                line += f" | Asistanın son yanıtı: {replies[-1][:160]}"
            lines.append(line)
        return "\n".join(lines[-12:])[-2500:]

    def _apply_result(self, rel: str, content: str, span, result: dict, open_nodes: list[dict],
                      mode: str = "fikir", quiet: bool = False):
        """quiet: a live-watch pass. Its questions and edits wait in the panel
        rather than popping the HUD, and "nothing to add" is not announced —
        every 15-second pause saying so would be the nagging all over again."""
        with self.notes.lock:
            state = self.notes.load(rel)
            state["analyzed_text"] = content
            self.notes.save(rel)

        if result.get("type") == "unfinished":
            # the model never got past thinking. Not "nothing to ask": that
            # would put the rung's stock question up about things the note
            # may already settle. The watch waits for new text; a pass you
            # asked for says why it came back empty.
            if not quiet:
                self.broker.publish("flash", {"kind": "error", "path": rel, "title": "Sonuca varamadı",
                                              "body": "Model düşünürken sınıra takıldı; tekrar sormak için Ctrl+Enter."})
            return

        climbing = mode == "yazilim"
        if climbing and result.get("known"):
            # decisions the note already states: they are simply not asked —
            # and a question still open about one of them has been answered
            # in the note itself, so it closes
            self.set_decisions(rel, {d: True for d in result["known"]}, by="not",
                               values=result.get("values"), quiet=quiet)
            for waiting in self.notes.open_questions(rel):
                if waiting.get("kind") in result["known"]:
                    self.resolve(rel, waiting["id"], by="model")
        rung = self.ladder_for(rel) if climbing else None
        # one open question per decision: asking "web or mobile?" twice in a
        # row is the illogical-question problem all over again
        pending = {n.get("kind") for n in self.notes.open_questions(rel)}

        if result.get("suggestion"):
            self._offer_suggestion(rel, content, result["suggestion"], quiet, result.get("lens"),
                                   result.get("basis", ""))
        if result.get("research"):
            self._offer_research(rel, result["research"], quiet)

        kind = result.get("type")
        if climbing and kind in ("net", "questions", "question"):
            rung = self.ladder_for(rel)
            usable = self._climb(rung, result.get("questions") or [], set(pending))
            if not usable and not pending & set(rung["open"]) and rung["open"]:
                # nothing to ask from the model, and nothing of this rung is
                # waiting for an answer: ask the rung's own next question
                first = rung["open"][0]
                result = {**result, "type": "questions",
                          "questions": [{"text": ladder.ask(first, llm_client.output_language()),
                                         "kind": first}]}
                kind = "questions"
        if kind == "net":
            if not quiet:
                self.broker.publish("flash", {"kind": "checked", "path": rel, "title": "İncelendi",
                                              "body": "Şu an için eklenecek bir şey bulunamadı."})
                self._record(self._event("checked", rel, text="Not incelendi, eklenecek bir şey yok."), hud=False)

        elif kind == "resolved":
            index = result.get("resolved_index") or 0
            if 1 <= index <= len(open_nodes) and open_nodes[index - 1].get("status") == "open":
                self.resolve(rel, open_nodes[index - 1]["id"], by="model")

        elif kind in ("questions", "question"):
            asked_now = result.get("questions") or [
                {"text": t, "kind": "soru"} for t in (result.get("texts") or [result.get("text", "")])
            ]
            open_now = self.notes.open_questions(rel)
            room = OPEN_QUESTION_FUSE - len(open_now)
            if not climbing and len(open_now) >= BACKLOG and self._pace(rel)["settled"] == 0:
                room = min(room, 1)      # questions pile up unanswered: only the most important one
            if room <= 0:
                return  # the fuse: the pass can still resolve or suggest edits
            asked = {fold(n["text"]) for n in open_now}
            asked.add(fold(state.get("last_question", "")))
            previous_questions = [n for n in state["nodes"]
                                  if n["type"] == "question" and n.get("status") != "dismissed"]
            if climbing:
                asked_now = self._climb(rung, asked_now, pending)
            for item in asked_now[:room]:
                text = (item.get("text") or "").strip()
                folded = fold(text)
                if not text or folded in asked:
                    continue
                # Reworded repetitions of a still-unanswered question are noise.
                # A distinct follow-up after a conversation is valuable, even
                # when it shares its subject with the parent question.
                if any(difflib.SequenceMatcher(None, folded, fold(n["text"])).ratio() >= 0.89
                       and not self.notes.thread(rel, n["id"])
                       for n in previous_questions):
                    continue
                section = section_for(content, text, span)
                parent, keep = question_parent(item, text, section, state["nodes"], climbing)
                if not keep:
                    continue    # a follow-up one level too deep: the narrowing itself
                asked.add(folded)
                with self.notes.lock:
                    state["last_question"] = text
                node = self.notes.add_node(rel, "question", text, parent_id=parent, status="open",
                                           kind=item.get("kind", "soru"), section=section)
                previous_questions.append(node)
                self._publish_node(rel, node)
                self._record(self._event("question", rel, text=text, node_id=node["id"],
                                         range=span, status="open",
                                         kind=item.get("kind", "soru"), section=section,
                                         parent_id=parent), hud=not quiet)

        elif kind == "edit":
            original = result.get("original", "").strip()
            replacement = result.get("replacement", "").strip()
            if not original or not replacement or original == replacement or original not in content:
                return  # can't locate the quoted text — likely hallucinated, skip silently
            reason = result.get("reason", "").strip()
            at = content.find(original)
            section = section_for(content, original, [at, at + len(original)])
            node = self.notes.add_node(rel, "edit", f"{original} → {replacement}", original=original,
                                       replacement=replacement, reason=reason, status="pending",
                                       section=section)
            self._publish_node(rel, node)
            self._record(self._event("edit", rel, original=original, replacement=replacement, reason=reason,
                                     node_id=node["id"], range=[at, at + len(original)], status="pending",
                                     section=section), hud=not quiet)

    # ---- what the model offers besides questions ----
    def _next_lens(self, rel: str):
        """The perspective of this pass: the four lenses in turn, per note."""
        with self.notes.lock:
            state = self.notes.load(rel)
            turn = int(state.get("lens_turn") or 0)
            state["lens_turn"] = turn + 1
            self.notes.save(rel)
        return ladder.LENSES[turn % len(ladder.LENSES)]

    def _extras_wanted(self, rel: str) -> bool:
        """Only while nothing the model offered is still waiting for an answer."""
        nodes = self.notes.load(rel)["nodes"]
        suggestion_waits = any(n["type"] == "summary" and n.get("status") == "pending"
                               and n.get("source") == "model" for n in nodes)
        research_waits = any(e.get("path") == rel and e.get("type") == "research"
                             and e.get("status") == "pending" for e in self.history.items)
        return not (suggestion_waits and research_waits)

    @staticmethod
    def _similar(text: str, seen: list[str], cutoff: float = 0.72) -> bool:
        folded = fold(text)
        return any(difflib.SequenceMatcher(None, folded, fold(old)).ratio() >= cutoff for old in seen)

    def _offer_suggestion(self, rel: str, content: str, text: str, quiet: bool,
                          lens: str | None = None, basis: str = "") -> None:
        """"Modelin önerisi": an argument the model thinks the note should hold.
        A proposal like any other — only the writer's approval puts it in the
        note. One waits at a time, and nothing offered before is offered again."""
        with self.notes.lock:
            state = self.notes.load(rel)
            if any(n["type"] == "summary" and n.get("status") == "pending" and n.get("source") == "model"
                   for n in state["nodes"]):
                return
            offered = state.setdefault("model_suggestions", [])
            if self._similar(text, offered) or fold(text) in fold(content):
                return
            offered.append(text)
            del offered[:-40]
            self.notes.save(rel)
        seen_by = {"lens": lens} if lens else {}
        if basis:                       # what in the note it follows from
            seen_by["why"] = basis
        node = self.notes.add_node(rel, "summary", text, status="pending", source="model", **seen_by)
        self._publish_node(rel, node)
        self._record(self._event("summary", rel, text=text, node_id=node["id"], status="pending",
                                 source="model", **seen_by), hud=not quiet)

    def _offer_research(self, rel: str, request: dict, quiet: bool) -> None:
        """The model asks to research one heading of the idea. It is only an
        offer in the panel: the search starts when the writer accepts it."""
        topic = request.get("topic", "").strip()
        if len(topic) < 4:
            return
        with self.notes.lock:
            state = self.notes.load(rel)
            offered = state.setdefault("research_offers", [])
            if self._similar(topic, offered, 0.6):
                return
            offered.append(topic)
            del offered[:-40]
            self.notes.save(rel)
        if any(e.get("path") == rel and e.get("type") == "research" and e.get("status") == "pending"
               for e in self.history.items):
            return
        self._record(self._event("research", rel, text=topic, topic=topic, why=request.get("why", ""),
                                 status="pending"), hud=False)

    # ---- the decision ladder ----
    @staticmethod
    def _climb(rung: dict, questions: list[dict], pending: set) -> list[dict]:
        """The order is the server's to keep, not the model's: a question
        about a rung the note has not reached, about a decision already made,
        or about one already waiting for an answer is dropped however well it
        is worded."""
        allowed = []
        for item in questions:
            decision = item.get("kind")
            if ladder.may_ask(decision, rung) and decision not in pending:
                allowed.append(item)
                pending.add(decision)
        return allowed

    def ladder_for(self, rel: str) -> dict:
        return ladder.state(self.notes.load(rel).get("decisions"))

    DIRECTION_CATEGORIES = {"amac", "kullanici", "kapsam", "cikti", "diger"}

    def _check_direction(self, category: str, text: str) -> tuple[str, str]:
        category, text = category.strip(), text.strip()
        if category not in self.DIRECTION_CATEGORIES:
            raise ApiError(400, "Düzeltme alanı bilinmiyor.")
        if not text or len(text) > 2000:
            raise ApiError(400, "Yönlendirme 1–2000 karakter olmalı.")
        return category, text

    def _direction_targets(self, rel: str) -> tuple[dict, dict, dict]:
        """What a correction can touch: made decisions, open questions,
        pending proposals — each as {id: short description}."""
        state = self.notes.load(rel)
        rung = ladder.state(state.get("decisions"))
        decisions = {}
        for level in rung["levels"]:
            for decision in level["decisions"]:
                if decision["decided"]:
                    said = f" = {decision['value']}" if decision.get("value") else ""
                    decisions[decision["id"]] = f"{level['label']} · {decision['label']}{said}"
        questions = {n["id"]: f"[{n.get('kind') or 'soru'}] {n['text'][:200]}"
                     for n in state["nodes"] if n["type"] == "question" and n.get("status") == "open"}
        proposals = {n["id"]: n["text"][:200] for n in state["nodes"]
                     if n["type"] in ("edit", "summary") and n.get("status") == "pending"}
        return decisions, questions, proposals

    def _fallback_direction_plan(self, category, decisions, questions, proposals) -> dict:
        """Without a model: the old, cautious reading — everything waiting is
        stale, and any correction but the output style reopens every decision."""
        return {"summary": "Model şu an ulaşılamadığı için etkiler tek tek değerlendirilemedi: "
                           "bekleyen bütün sorular ve öneriler kapanacak"
                           + ("." if category == "cikti" else ", verilmiş kararlar yeniden sorulacak."),
                "update": {},
                "reopen": [] if category == "cikti" else list(decisions),
                "drop_questions": list(questions), "drop_proposals": list(proposals),
                "fallback": True}

    async def preview_direction(self, rel: str, category: str, text: str) -> dict:
        """The correction compared with the note's goal and decisions: a short
        summary of the new course and exactly what it would reopen or close.
        Nothing changes until the writer approves it (set_direction)."""
        category, text = self._check_direction(category, text)
        content = self.vault.read_note(rel)["content"]
        decisions, questions, proposals = self._direction_targets(rel)
        previous = (self.notes.load(rel).get("direction") or {}).get("text", "")
        plan = None
        try:
            provider = self.provider_for("analysis", rel)
            plan = await asyncio.to_thread(llm_client.plan_direction, content, category, text,
                                           decisions, questions, proposals, previous,
                                           provider, self.budget.record)
        except Exception:
            self.check_now()
        if plan is None:
            plan = self._fallback_direction_plan(category, decisions, questions, proposals)
        plan.setdefault("update", {})
        plan["ask"] = [{"id": f"yeni{i}", "text": text} for i, text in enumerate(plan.get("ask") or [], start=1)]
        # a correction of the goal or the audience is about that very decision,
        # even when the model does not say so (measured: it closed the team
        # question but kept "Kullanıcı = ekipteki herkes")
        if category in decisions and category not in plan["update"] and category not in plan["reopen"]:
            plan["reopen"] = [category, *plan["reopen"]]
        labels = {**decisions, **questions, **proposals, **{q["id"]: q["text"] for q in plan["ask"]}}
        for decision, value in plan["update"].items():
            labels[decision] = f"{ladder.DECISIONS[decision][1]}: {value}"
        return {**plan, "category": category, "text": text,
                "items": {key: labels[key] for key in
                          [*plan["update"], *plan["reopen"], *plan["drop_questions"], *plan["drop_proposals"],
                           *(q["id"] for q in plan["ask"])]}}

    def set_direction(self, rel: str, category: str, text: str, plan: dict | None = None) -> dict:
        """The writer's latest correction supersedes stale assistant work.

        plan: what the writer approved from preview_direction. Only those
        decisions reopen and only those questions and proposals close, ids
        checked again against the note as it is now. Without a plan, the old
        cautious reading applies (see _fallback_direction_plan)."""
        category, text = self._check_direction(category, text)
        content = self.vault.read_note(rel)["content"]
        if self.busy == rel:
            self.cancel_running("direction")
            self._next_force = (rel, content)

        if plan is None:
            plan = self._fallback_direction_plan(category, *self._direction_targets(rel))
        reopen = {str(item) for item in plan.get("reopen") or []}
        updates = {str(key): " ".join(str(value).split())[:160]
                   for key, value in (plan.get("update") or {}).items()
                   if str(key) in ladder.DECISIONS and str(value).strip()}
        drop = {str(item) for item in [*(plan.get("drop_questions") or []), *(plan.get("drop_proposals") or [])]}
        ask = [" ".join(str(q.get("text", "") if isinstance(q, dict) else q).split())[:220]
               for q in (plan.get("ask") or [])[:2]]
        ask = [q for q in ask if q]
        summary = " ".join(str(plan.get("summary") or "").split())[:500]
        entry = {"category": category, "text": text, "created": now_iso(),
                 **({"summary": summary} if summary else {})}
        closed, discarded = [], []
        with self.notes.lock:
            state = self.notes.load(rel)
            previous = state.get("direction")
            if previous:
                state.setdefault("direction_history", []).append(previous)
                del state["direction_history"][:-20]
            state["direction"] = entry
            state["last_question"] = ""
            state["analyzed_text"] = ""
            decided = state.setdefault("decisions", {})
            before = ladder.state(decided)
            for decision in reopen & set(decided):
                del decided[decision]
            for decision, value in updates.items():
                # the correction itself said it: no need to ask again
                decided[decision] = {"by": "rota", "at": now_iso(), "value": value}
            after = ladder.state(decided)
            state["phase"] = after["phase"]
            for node in state["nodes"]:
                if node["id"] not in drop:
                    continue
                if node["type"] == "question" and node.get("status") == "open":
                    node.update(status="dismissed", dismissed_at=now_iso(), dismissed_by="direction")
                    closed.append(node.copy())
                elif node["type"] in ("edit", "summary") and node.get("status") == "pending":
                    node.update(status="rejected", rejected_at=now_iso(), rejected_by="direction")
                    discarded.append(node.copy())
            self.notes.save(rel)

        for node in closed + discarded:
            self._publish_node(rel, node)
            event = self.history.find_by_node(rel, node["id"], node["type"])
            if event:
                self.history.update(event, status=node["status"])
                self.broker.publish("history_update", event)
        affected = {n["id"] for n in closed + discarded}
        self._drop_from_queue(lambda e: e.get("path") == rel and e.get("node_id") in affected)
        for text in ask:
            # the new course's own questions, there as soon as it is approved;
            # "yon" is no rung's decision, so the ladder never holds them back
            node = self.notes.add_node(rel, "question", text, status="open", kind="yon", section="")
            self._publish_node(rel, node)
            self._record(self._event("question", rel, text=text, node_id=node["id"], status="open",
                                     kind="yon", section="", parent_id=None))
        rung = self.ladder_for(rel)
        change = ladder.transition(before, after)
        self.broker.publish("ladder", {"path": rel, "ladder": rung, "transition": change})
        if change:
            self._record(self._event("phase", rel, text=change["body"], title=change["title"],
                                     phase=change["phase"]), hud=False)
        return {"direction": entry, "closed_questions": len(closed),
                "discarded_proposals": len(discarded), "asked": len(ask), "ladder": rung}

    def set_decisions(self, rel: str, changes: dict, by: str, question: str | None = None,
                      values: dict | None = None, quiet: bool = False) -> dict:
        """Mark decisions made (True) or open again (False). Announces a
        finished rung and, above all, the moment the note reaches the product
        phase — once, when it happens, not on every pass after. A quiet pass
        leaves a finished rung to the ladder card; the product phase is worth
        interrupting for either way."""
        with self.notes.lock:
            state = self.notes.load(rel)
            decided = state.setdefault("decisions", {})
            before = ladder.state(decided)
            changed = False
            for decision, made in changes.items():
                if decision not in ladder.DECISIONS:
                    continue
                if made and decision not in decided:
                    decided[decision] = {"by": by, "at": now_iso(),
                                         **({"question": question} if question else {}),
                                         **({"value": values[decision]} if values and values.get(decision) else {})}
                    changed = True
                elif not made and decision in decided:
                    del decided[decision]
                    changed = True
            after = ladder.state(decided)
            if changed:
                state["phase"] = after["phase"]
                self.notes.save(rel)
        if not changed:
            return after
        change = ladder.transition(before, after)
        self.broker.publish("ladder", {"path": rel, "ladder": after, "transition": change})
        if change:
            if not quiet or change["phase"] == "urun":
                self.broker.publish("flash", {"kind": "checked", "path": rel,
                                              "title": change["title"], "body": change["body"]})
            self._record(self._event("phase", rel, text=change["body"], title=change["title"],
                                     phase=change["phase"]), hud=False)
        return after

    # ---- questions ----
    def remember_written(self, rel: str, text: str) -> None:
        """Keep the exact wording of something the writer approved into the
        note, so the editor can show whose sentence it was."""
        text = (text or "").strip()
        if not text:
            return
        with self.notes.lock:
            state = self.notes.load(rel)
            written = state.setdefault("assistant_text", [])
            if text in written:
                return
            written.append(text)
            del written[:-MAX_ASSISTANT_TEXTS]
            self.notes.save(rel)
        self.broker.publish("written", {"path": rel, "texts": list(written)})

    def propose_text(self, rel: str, text: str, source: str = "research") -> dict:
        """Create a pending note addition; only hud_action(approve) may apply it."""
        self.vault.note_path(rel)
        text = (text or "").strip()
        if not text:
            raise ApiError(400, "Nota önerilecek metin boş olamaz.")
        if len(text) > 6000:
            raise ApiError(400, "Nota önerilecek metin çok uzun.")
        node = self.notes.add_node(rel, "summary", text, status="pending", source=source)
        self._publish_node(rel, node)
        proposal = self._event("summary", rel, text=text, node_id=node["id"],
                               status="pending", source=source)
        self._record(proposal)
        return {"text": text, "node": node, "proposal": proposal}

    def written(self, rel: str) -> list[str]:
        return list(self.notes.load(rel).get("assistant_text") or [])

    def resolve(self, rel: str, node_id: str, by: str = "user", value: str = "") -> dict:
        """value: what the decision now says — the write-up the writer
        approved. Without one, the last thing they said in the thread."""
        node = self.notes.find_node(rel, node_id)
        if node is None or node["type"] != "question":
            raise ApiError(404, "Soru bulunamadı.")
        if node.get("status") != "open":
            return node
        node = self.notes.update_node(rel, node_id, status="resolved", resolved_at=now_iso())
        self._publish_node(rel, node)
        if node.get("kind") in ladder.DECISIONS:
            # the writer answered the question that asked for this decision;
            # the answer is its value, so the next questions build on it
            # the approved write-up is the decision; the last chat line could
            # be "ilkini yapalım" or about something else altogether (measured:
            # a users answer under the parts question became "parts = we two")
            answers = [n.get("text", "") for n in self.notes.thread(rel, node_id) if n["type"] == "chat-user"]
            value = " ".join((value or (answers[-1] if answers else "")).split())[:160]
            self.set_decisions(rel, {node["kind"]: True}, by="cevap", question=node_id,
                               values={node["kind"]: value} if value else None)
        question_event = self.history.find_by_node(rel, node_id, "question")
        if question_event:
            self.history.update(question_event, status="resolved")
            self.broker.publish("history_update", question_event)
        self._drop_from_queue(lambda e: e.get("path") == rel and e.get("node_id") == node_id)
        self._record(self._event("resolved", rel, text=node["text"], node_id=node_id, by=by), hud=False)
        return node

    # ---- HUD ----
    def hud_action(self, event_id: str, action: str) -> dict:
        event = next((e for e in self.queue if e["id"] == event_id), None) or self.history.find(event_id)
        if event is None:
            raise ApiError(404, "Öneri bulunamadı.")

        if action == "dismiss":
            # closes this note's items; other notes' questions still wait their turn
            self.queue = [e for e in self.queue if e.get("path") != event.get("path")]
        elif action == "next":
            # passed over, not settled: it waits at the back of the line
            passed = [e for e in self.queue if e["id"] == event_id]
            self.queue = [e for e in self.queue if e["id"] != event_id] + passed
        elif action == "chat":
            if event["type"] != "question":
                raise ApiError(400, "Sadece sorular için sohbet açılabilir.")
            self._drop_from_queue(lambda e: e["id"] == event_id)
            self.broker.publish("open_chat", event)
        elif action in ("approve", "reject") and event["type"] == "research":
            if event.get("status") != "pending":
                raise ApiError(409, "Bu öneri zaten sonuçlandı.")
            status = "approved" if action == "approve" else "rejected"
            self.history.update(event, status=status)
            self.broker.publish("history_update", event)
            if action == "approve":
                # the page that owns the note starts it: it saves first and
                # shows the progress (see app.js start_research)
                self.broker.publish("start_research", {"path": event["path"], "focus": event["topic"]})
        elif action in ("approve", "reject") and event["type"] == "summary":
            if event.get("status") != "pending":
                raise ApiError(409, "Bu öneri zaten sonuçlandı.")
            status = "approved" if action == "approve" else "rejected"
            self.history.update(event, status=status)
            self.broker.publish("history_update", event)
            node = self.notes.update_node(event["path"], event["node_id"], status=status)
            if node:
                self._publish_node(event["path"], node)
            self._drop_from_queue(lambda e: e["id"] == event_id)
            if action == "approve":
                self.remember_written(event["path"], event["text"])
                self.broker.publish("append_note", event)
                if event.get("question_id"):
                    try:
                        self.resolve(event["path"], event["question_id"], by="chat", value=event.get("text", ""))
                    except ApiError:
                        pass
        elif action in ("approve", "reject"):
            if event["type"] != "edit":
                raise ApiError(400, "Bu bir düzenleme önerisi değil.")
            if event.get("status") != "pending":
                raise ApiError(409, "Bu öneri zaten sonuçlandı.")
            status = "approved" if action == "approve" else "rejected"
            self.history.update(event, status=status)
            self.broker.publish("history_update", event)
            node = self.notes.update_node(event["path"], event["node_id"], status=status)
            if node:
                self._publish_node(event["path"], node)
            self._drop_from_queue(lambda e: e["id"] == event_id)
            if action == "approve":
                self.remember_written(event["path"], event.get("replacement", ""))
                self.broker.publish("apply_edit", event)
        else:
            raise ApiError(400, "Bilinmeyen işlem.")

        self._publish_hud()
        return {"ok": True}

    def decide_node(self, rel: str, node_id: str, action: str) -> dict:
        """Approve or reject a proposal by its node — the tree's way in. Its
        history event may be gone (an old vault, one trimmed before waiting
        events were kept); one is made from the node, so it is decided
        exactly as from the card or the panel."""
        if action not in ("approve", "reject"):
            raise ApiError(400, "Bilinmeyen işlem.")
        node = self.notes.find_node(rel, node_id)
        if node is None or node["type"] not in ("summary", "edit"):
            raise ApiError(404, "Öneri bulunamadı.")
        event = self.history.find_by_node(rel, node_id, node["type"])
        if event is None:
            if node.get("status") != "pending":
                raise ApiError(409, "Bu öneri zaten sonuçlandı.")
            fields = ({"original": node.get("original", ""), "replacement": node.get("replacement", ""),
                       "reason": node.get("reason", "")} if node["type"] == "edit" else {"text": node["text"]})
            parent = self.notes.find_node(rel, node.get("parentId")) if node.get("parentId") else None
            if parent and parent["type"] == "question":
                fields.update(question_id=parent["id"], question=parent["text"])
            event = self._event(node["type"], rel, node_id=node_id, status="pending", **fields)
            self.history.add(event)
        return self.hud_action(event["id"], action)

    def claim(self, event_id: str) -> bool:
        """Several open pages hear the same apply_edit — only the first one applies it."""
        if event_id in self._claims:
            return False
        self._claims.add(event_id)
        return True

    # ---- chat ----
    @contextlib.contextmanager
    def _conversing(self):
        """A conversation has the model. One model does everything, so a quiet
        pass left running would hold your reply back 20-30 s: it gives way,
        and the watch looks again at the next pause."""
        if self.busy and self._busy_quiet:
            self.cancel_running("chat")
        self._chatting += 1
        try:
            yield
        finally:
            self._chatting -= 1

    def _ancestor_context(self, rel: str, node_id: str) -> str:
        lineage = self.notes.question_lineage(rel, node_id)[:-1]
        if not lineage:
            return ""
        lines = []
        for depth, ancestor in enumerate(lineage, start=1):
            lines.append(f"{depth}. Önceki soru: {ancestor.get('text', '')[:250]}")
            for turn in self.notes.thread(rel, ancestor["id"])[-6:]:
                who = "Kullanıcı" if turn["type"] == "chat-user" else "Asistan"
                lines.append(f"   {who}: {turn.get('text', '')[:300]}")
        return "\n".join(lines)[-3000:]

    def _conversation(self, rel: str, node_id: str) -> tuple[dict, list[dict]]:
        question = self.notes.find_node(rel, node_id)
        if question is None or question["type"] != "question":
            raise ApiError(404, "Soru bulunamadı.")
        context = self._ancestor_context(rel, node_id)
        seed = (f"[ÖNCEKİ SORU DALININ BAĞLAMI — aşağıdakiler bu sorunun cevabı değil]\n"
                f"{context}\n\n[ŞİMDİKİ SORU]\n{question['text']}") if context else question["text"]
        messages = [{"role": "assistant", "content": seed}]
        for node in self.notes.thread(rel, node_id):
            messages.append({"role": "user" if node["type"] == "chat-user" else "assistant",
                             "content": node["text"]})
        return question, messages

    async def chat_stream(self, rel: str, node_id: str, message: str):
        question, messages = self._conversation(rel, node_id)
        messages.append({"role": "user", "content": message})
        user_node = self.notes.add_node(rel, "chat-user", message, parent_id=node_id)
        self._publish_node(rel, user_node)
        try:
            note_text = self.vault.read_note(rel)["content"]
        except ApiError:
            note_text = ""
        direction = (self.notes.load(rel).get("direction") or {}).get("text", "")
        if direction:
            note_text += f"\n\n[KULLANICININ SON YÖNÜ — eski notla çelişirse bu geçerli]\n{direction}"

        loop = asyncio.get_running_loop()
        updates: asyncio.Queue = asyncio.Queue()
        last_emit = 0.0

        def on_chunk(accumulated: str):
            nonlocal last_emit
            now = time.monotonic()
            if now - last_emit >= CHAT_THROTTLE_S:
                last_emit = now
                loop.call_soon_threadsafe(updates.put_nowait, ("progress", accumulated))

        # the model is told how many follow-ups it has asked and decides when
        # to stop; answering the user's own questions never counts
        asked_before = sum(1 for n in self.notes.thread(rel, node_id)
                           if n["type"] == "chat-assistant" and n.get("mode") == "question")
        # "I don't know" and "any ideas?" get options to choose from — not a
        # three-sentence answer, and never the not knowing written up
        wants_ideas = asks_for_ideas(message)
        user_asked = looks_like_question(message) and not wants_ideas

        def on_step(record: dict):
            """A tool finished on the worker thread — show it while the rest runs."""
            loop.call_soon_threadsafe(updates.put_nowait, ("tool", record))

        async def answer():
            # saving happens here rather than in the generator, so the reply
            # is kept even if the page is closed while the model is writing
            nonlocal rel
            try:
                provider = self.provider_for("chat", rel)
            except ApiError as exc:
                # "no provider bound" / "daily budget spent" must say so, not
                # come back as a generic "the model did not answer"
                await updates.put(("error", exc.message))
                return

            raw = None
            used_tools: list[dict] = []
            if user_asked and self.tools_allowed(provider, rel):
                # the user asked us something: this is the one turn where
                # looking things up is worth a browser window and a few seconds
                try:
                    result = await asyncio.to_thread(
                        llm_client.chat_answer_with_tools, messages, note_text, provider,
                        self.tool_hub, on_step, self.budget.record)
                    raw = result["content"]
                    used_tools = [{"name": c["name"], "ok": c["ok"]} for c in result["calls"]]
                except (llm_client.ProviderError, llm_client.ToolBudget, ApiError):
                    raw = None      # answer without them rather than fail the turn
                except Exception:
                    raw = None
                if raw is not None and not raw.strip():
                    raw = None

            async def reply(ideas: bool):
                call = llm_client.chat_answer if user_asked else functools.partial(
                    llm_client.chat_reply, asked=asked_before, wants_ideas=ideas)
                return await asyncio.to_thread(call, messages, note_text, on_chunk,
                                               provider, self.budget.record)

            if raw is None:
                try:
                    raw = await reply(wants_ideas)
                except llm_client.ProviderError as exc:
                    self.check_now()
                    told = self.note_problem(provider, exc.status)
                    await updates.put(("error", told or f"Model isteği reddedildi: {exc}"))
                    return
                except Exception:
                    self.check_now()
                    await updates.put(("error", "Model yanıt vermedi, model çalışıyor mu kontrol et."))
                    return

            rel = self.notes.current(rel)          # renamed while the model was writing
            if user_asked:
                # the user asked something: answer it, keep the question open,
                # write nothing to the note
                answer = raw.strip() or "(Model boş yanıt döndürdü.)"
                # the tools that produced it are kept on the node, so reopening
                # the thread still shows where the answer came from
                node = self.notes.add_node(rel, "chat-assistant", answer, parent_id=node_id,
                                           mode="answer", tools=used_tools or None)
                self._publish_node(rel, node)
                await updates.put(("done", {"node": node, "understood": False, "answered": True,
                                            "tools": used_tools}))
                return

            result = llm_client.parse_chat_reply(raw)
            if result["type"] == "understood" and UNDECIDED_NOTE.search(ascii_fold(result["note"])):
                # it filed the writer's not knowing: ask once more, for options
                try:
                    if not wants_ideas:
                        result = llm_client.parse_chat_reply(await reply(True))
                except Exception:
                    pass
                if result["type"] == "understood" and UNDECIDED_NOTE.search(ascii_fold(result["note"])):
                    result = {"type": "ideas", "text": ""}
            if result["type"] == "ideas":
                # options offered: nothing for the note until one is chosen
                text = result["text"] or "Birkaç seçenek düşünelim: hangi yöne daha yakınsın?"
                node = self.notes.add_node(rel, "chat-assistant", text, parent_id=node_id, mode="ideas")
                self._publish_node(rel, node)
                await updates.put(("done", {"node": node, "understood": False, "answered": True}))
                return
            # it keeps asking while it judges the answer unclear; the fuse only
            # stops a model that never judges it clear
            if result["type"] == "question" and asked_before < FOLLOWUP_FUSE:
                node = self.notes.add_node(rel, "chat-assistant", result["text"], parent_id=node_id,
                                           mode="question")
                self._publish_node(rel, node)
                await updates.put(("done", {"node": node, "understood": False}))
                return

            note_entry = result.get("note", "").strip()
            if not note_entry:
                # gave up asking (or answered without a NOT: block) — write up the thread as it stands
                try:
                    note_entry = (await asyncio.to_thread(llm_client.summarize_for_note, messages,
                                                          self.provider_for("summary", rel),
                                                          self.budget.record, direction)).strip()
                except Exception:
                    note_entry = ""

            node = self.notes.add_node(
                rel, "chat-assistant",
                "Anladım — şunu notuna eklemeyi öneriyorum." if note_entry else "Anladım.",
                parent_id=node_id, mode="understood")
            self._publish_node(rel, node)
            proposal = None
            if note_entry:
                # the note is the user's; the assistant only proposes
                summary = self.notes.add_node(rel, "summary", note_entry, parent_id=node_id,
                                              status="pending")
                self._publish_node(rel, summary)
                proposal = self._event("summary", rel, text=note_entry, node_id=summary["id"],
                                       question_id=node_id, question=question["text"], status="pending")
                self._record(proposal)
            else:
                try:
                    self.resolve(rel, node_id, by="chat")
                except ApiError:
                    pass
            await updates.put(("done", {"node": node, "understood": True, "note": note_entry,
                                        "proposal": proposal}))

        async def run():
            with self._conversing():
                await answer()

        self._spawn(run())
        yield {"type": "user", "node": user_node}
        while True:
            kind, payload = await updates.get()
            if kind == "progress":
                preview = thinking_preview(payload, limit=None)
                if preview["phase"] == "writing":
                    preview["text"] = strip_protocol(preview["text"])
                yield {"type": "progress", **preview}
            elif kind == "tool":
                # the query goes out as the model wrote it, so the user can see
                # exactly what was searched for — and why a browser just opened
                query = payload["arguments"].get("query") if isinstance(payload["arguments"], dict) else None
                yield {"type": "tool", "name": payload["name"], "ok": payload["ok"],
                       "seconds": payload["seconds"], "query": query}
            elif kind == "done":
                yield {"type": "done", **payload}
                return
            else:
                yield {"type": "error", "message": payload}
                return

    async def summarize(self, rel: str, node_id: str) -> dict:
        question, messages = self._conversation(rel, node_id)
        if not any(n["type"] == "chat-user" for n in self.notes.thread(rel, node_id)):
            raise ApiError(400, "Önce biraz sohbet et — nota yazılacak bir sonuç yok.")
        provider = self.provider_for("summary", rel)
        try:
            direction = (self.notes.load(rel).get("direction") or {}).get("text", "")
            with self._conversing():
                text = (await asyncio.to_thread(llm_client.summarize_for_note, messages,
                                                provider, self.budget.record, direction)).strip()
        except llm_client.ProviderError as exc:
            self.check_now()
            raise ApiError(502, self.note_problem(provider, exc.status) or f"Model isteği reddedildi: {exc}")
        except Exception:
            self.check_now()
            raise ApiError(502, "Model yanıt vermedi, model çalışıyor mu kontrol et.")
        if not text:
            raise ApiError(502, "Model boş yanıt döndürdü, tekrar dene.")
        node = self.notes.add_node(rel, "summary", text, parent_id=node_id, status="pending")
        self._publish_node(rel, node)
        proposal = self._event("summary", rel, text=text, node_id=node["id"], question_id=node_id,
                               question=question["text"], status="pending")
        self._record(proposal)
        return {"text": text, "node": node, "proposal": proposal}

    # ---- vault bookkeeping ----
    def moved(self, old_rel: str, new_rel: str):
        self.notes.moved(old_rel, new_rel)
        self.history.moved(old_rel, new_rel)
        if self.busy and (self.busy == old_rel or self.busy.startswith(old_rel + "/")):
            self.busy = new_rel + self.busy[len(old_rel):]
        if self._next_force and under_path(self._next_force[0], old_rel):
            path, content = self._next_force
            self._next_force = (new_rel + path[len(old_rel):], content)
        self._publish_hud()

    def trashed(self, rel: str, trash_name: str):
        if self.busy and under_path(self.busy, rel):
            self.cancel_running("trashed")
        if self._next_force and under_path(self._next_force[0], rel):
            self._next_force = None
        self.notes.trashed(rel, trash_name)
        self._drop_from_queue(lambda e: e.get("path") == rel or e.get("path", "").startswith(rel + "/"))
