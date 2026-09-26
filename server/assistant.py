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
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
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
from server.vault import fold, split_frontmatter

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
        if node["type"] == "question":
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


_QUESTION_FILLER = {"hangi", "nasil", "neden", "niye", "olara", "olarak", "icin",
                    "bunun", "bunla", "bunu", "daha", "sonra", "neden", "fikri",
                    "fikir", "proje", "baska", "hangi", "sence", "olmal", "yapar"}


def _topic_stems(text: str) -> set[str]:
    """Small, local relevance signal; model-supplied parent ids take priority."""
    return {word[:5] for word in re.findall(r"\w{5,}", fold(text))
            if word[:5] not in _QUESTION_FILLER}


def related_question_parent(text: str, section: str, nodes: list[dict]) -> str | None:
    """Conservative fallback when the analysis model did not supply a parent id.

    Use earlier question and answer terms, not merely the shared section. The
    latter would turn every independent question in a section into one chain.
    """
    terms = _topic_stems(text)
    if len(terms) < 2:
        return None
    best_id, best_score = None, 0.0
    for node in nodes:
        if node.get("type") != "question":
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
        if node["type"] == "question":
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


def looks_like_question(text: str) -> bool:
    """A message that asks something must not be swallowed as an answer."""
    stripped = fold(text.strip())
    return stripped.endswith("?") or stripped.startswith(QUESTION_STARTS)


def under_path(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(f"{prefix}/")


MIN_NEW_CHARS = 40
THINKING_THROTTLE_S = 0.4
CHAT_THROTTLE_S = 0.12
MAX_FOLLOWUPS = 3  # keep asking until the answer makes sense — but never pester forever
MAX_OPEN_QUESTIONS = 3  # unanswered questions pile up fast; stop nagging past this
HEALTH_INTERVAL_UP_S = 15
HEALTH_INTERVAL_DOWN_S = 5
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


def diff_new_text(old: str, new: str) -> tuple[str, int, list[int] | None]:
    """What changed since the last analysis.

    Returns (new_part, changed_chars, [start, end]). new_part is whole changed
    lines so the model gets readable context; changed_chars counts only the
    characters actually typed, so fixing one typo in a long paragraph doesn't
    look like 300 new characters. The old PyQt app only looked at text past
    the previous length, so anything written above the end was never seen.
    """
    if old == new:
        return "", 0, None
    if new.startswith(old):
        added = new[len(old):]
        line_start = new.rfind("\n", 0, len(old)) + 1
        return new[line_start:].strip(), len(added.strip()), [line_start, len(new)]

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
        segment = "".join(after_lines[j1:j2])
        parts.append(segment.strip("\n"))
        start = offsets[j1] if start is None else min(start, offsets[j1])
        end = offsets[j2] if end is None else max(end, offsets[j2])
        if tag == "insert":
            changed += len(segment.strip())
            continue
        replaced = "".join(before_lines[i1:i2])
        if len(replaced) * len(segment) > 4_000_000:
            changed += len(segment.strip())
            continue
        inner = difflib.SequenceMatcher(None, replaced, segment, autojunk=False)
        changed += sum(k2 - k1 for op, _, _, k1, k2 in inner.get_opcodes() if op in ("insert", "replace"))

    new_part = "\n".join(p for p in parts if p.strip()).strip()
    return new_part, changed, ([start, end] if start is not None else None)


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
        self._run_id = 0          # bumped to abandon an analysis whose answer is stale
        self._cancelled: set[int] = set()
        self._tasks: set[asyncio.Task] = set()
        self._wake = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

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
            return False
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
            self.queue.append(event)
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
        while True:
            providers = self.providers.all()
            results = await asyncio.gather(
                *(asyncio.to_thread(llm_client.is_server_up, provider) for provider in providers),
                return_exceptions=True,
            )
            changed = False
            for provider, up in zip(providers, results):
                changed |= self.providers.set_health(provider.id, up is True)
            if changed:
                self._publish_status()
                self.broker.publish("providers", self.providers.public())
            all_up = all(self.providers.health.get(p.id) for p in providers) if providers else False
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(),
                                       HEALTH_INTERVAL_UP_S if all_up else HEALTH_INTERVAL_DOWN_S)
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
        if not content.strip():
            return {"status": "skipped"}

        state = self.notes.load(rel)
        new_part, changed, span = diff_new_text(state.get("analyzed_text", ""), content)
        if not force and changed < MIN_NEW_CHARS:
            if not new_part:
                with self.notes.lock:  # only deletions — resync silently, like the old app did
                    state["analyzed_text"] = content
                    self.notes.save(rel)
            return {"status": "skipped"}
        if not new_part:
            new_part = content[-800:]
            span = [max(0, len(content) - 800), len(content)]

        self.busy = rel
        self._busy_content = content
        self._busy_quiet = not force
        self._run_id += 1
        self._publish_status()
        self._spawn(self._run_analysis(rel, content, new_part, span, self._run_id))
        return {"status": "started"}

    async def _run_analysis(self, rel: str, content: str, new_part: str, span, run_id: int):
        open_nodes = self.notes.open_questions(rel)
        nodes = self.notes.load(rel)["nodes"]
        mode = ladder.note_mode(content)
        roadmap = ladder.roadmap(self.ladder_for(rel)) if mode == "yazilim" else ""
        span = focus_span(content, nodes, span)
        coverage = section_coverage(content, nodes)
        focus = section_of(content, span)
        if coverage:
            coverage += f"\n\nŞu an şu bölüme bakıyorsun: {focus or '(giriş)'} — sorularını buradan seç."
        branches = self._question_branches(rel, nodes)
        if branches:
            coverage += "\n\n[MEVCUT SORU DALLARI]\n" + branches
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
                )
            except llm_client.Cancelled:
                return
            except llm_client.ProviderError as exc:
                # the watch retries at the next pause; only a pass you asked
                # for owes you an explanation
                if not self._busy_quiet:
                    self.broker.publish("flash", {"kind": "error", "path": rel,
                                                  "title": "Model isteği reddedildi", "body": str(exc)})
                self.check_now()
                return
            except Exception:
                if not self._busy_quiet:
                    self.broker.publish("flash", {"kind": "error", "path": rel, "title": "Model yanıt vermedi",
                                                  "body": "Model sunucusu çalışıyor mu kontrol et."})
                self.check_now()
                return
            if cancelled():
                return
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

    def _question_branches(self, rel: str, nodes: list[dict]) -> str:
        """Give the analysis model real ids and settled details from earlier turns."""
        lines = []
        for question in (n for n in nodes if n.get("type") == "question"):
            parent = question.get("parentId")
            line = f"- {question['id']}"
            if parent:
                line += f" (üst soru: {parent})"
            line += f": {question.get('text', '')[:150]}"
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

        kind = result.get("type")
        if climbing and kind in ("net", "questions", "question"):
            rung = self.ladder_for(rel)
            usable = self._climb(rung, result.get("questions") or [], set(pending))
            if not usable and not pending & set(rung["open"]) and rung["open"]:
                # nothing to ask from the model, and nothing of this rung is
                # waiting for an answer: ask the rung's own next question
                first = rung["open"][0]
                result = {**result, "type": "questions",
                          "questions": [{"text": ladder.ASK[first], "kind": first}]}
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
            room = MAX_OPEN_QUESTIONS - len(open_now)
            if room <= 0:
                return  # already waiting on enough; the pass can still resolve or suggest edits
            asked = {fold(n["text"]) for n in open_now}
            asked.add(fold(state.get("last_question", "")))
            previous_questions = [n for n in state["nodes"] if n["type"] == "question"]
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
                asked.add(folded)
                with self.notes.lock:
                    state["last_question"] = text
                section = section_for(content, text, span)
                requested_parent = item.get("parent_id") or item.get("related_to")
                parent = next((n["id"] for n in previous_questions
                               if n["id"] == requested_parent), None)
                if parent is None:
                    parent = related_question_parent(text, section, state["nodes"])
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

    def resolve(self, rel: str, node_id: str, by: str = "user") -> dict:
        node = self.notes.find_node(rel, node_id)
        if node is None or node["type"] != "question":
            raise ApiError(404, "Soru bulunamadı.")
        if node.get("status") == "resolved":
            return node
        node = self.notes.update_node(rel, node_id, status="resolved", resolved_at=now_iso())
        self._publish_node(rel, node)
        if node.get("kind") in ladder.DECISIONS:
            # the writer answered the question that asked for this decision
            self.set_decisions(rel, {node["kind"]: True}, by="cevap", question=node_id)
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
            self.queue.clear()
        elif action == "next":
            self._drop_from_queue(lambda e: e["id"] == event_id)
        elif action == "chat":
            if event["type"] != "question":
                raise ApiError(400, "Sadece sorular için sohbet açılabilir.")
            self._drop_from_queue(lambda e: e["id"] == event_id)
            self.broker.publish("open_chat", event)
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
                        self.resolve(event["path"], event["question_id"], by="chat")
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

        loop = asyncio.get_running_loop()
        updates: asyncio.Queue = asyncio.Queue()
        last_emit = 0.0

        def on_chunk(accumulated: str):
            nonlocal last_emit
            now = time.monotonic()
            if now - last_emit >= CHAT_THROTTLE_S:
                last_emit = now
                loop.call_soon_threadsafe(updates.put_nowait, ("progress", accumulated))

        # only the assistant's own follow-up questions count toward the cap;
        # answering the user's questions should never run the thread out
        asked_before = sum(1 for n in self.notes.thread(rel, node_id)
                           if n["type"] == "chat-assistant" and n.get("mode") == "question")
        user_asked = looks_like_question(message)

        def on_step(record: dict):
            """A tool finished on the worker thread — show it while the rest runs."""
            loop.call_soon_threadsafe(updates.put_nowait, ("tool", record))

        async def answer():
            # saving happens here rather than in the generator, so the reply
            # is kept even if the page is closed while the model is writing
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

            if raw is None:
                call = llm_client.chat_answer if user_asked else llm_client.chat_reply
                try:
                    raw = await asyncio.to_thread(call, messages, note_text, on_chunk,
                                                  provider, self.budget.record)
                except Exception:
                    self.check_now()
                    await updates.put(("error", "Model yanıt vermedi, model çalışıyor mu kontrol et."))
                    return

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
            # it may keep asking until the answer makes sense, but not forever
            if result["type"] == "question" and asked_before < MAX_FOLLOWUPS:
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
                                                          self.budget.record)).strip()
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
        try:
            with self._conversing():
                text = (await asyncio.to_thread(llm_client.summarize_for_note, messages,
                                                self.provider_for("summary", rel), self.budget.record)).strip()
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
