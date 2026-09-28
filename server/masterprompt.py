"""The master prompt: a note's whole design, written up as the instructions a
coding agent needs to build it without asking a single question.

Everything the app knows about the note goes in — the note itself, the
decisions on the ladder, the questions answered and how, the suggestions the
writer approved and the ones they turned down, the research — and one model
call writes the instructions. What is still open the model decides itself,
listing those decisions in their own section; a second, small call settles
any line that still leaves something open. The last one is kept with the
note, so it is there again without paying for it twice.
"""
import asyncio
import time

from core import llm_client
from server import ladder
from server.errors import ApiError
from server.store import now_iso
from server.vault import split_frontmatter

NOTE_CHARS = 24000          # the note itself; far more than any design note
THREAD_CHARS = 900          # one answered question's conversation
THROTTLE_S = 0.15


def _clip(text, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def research_digest(research: dict) -> str:
    """What the research found, as background: competitors and what they are
    weak at, the arguments drawn from them, tools worth using."""
    if (research or {}).get("status") != "done":
        return ""
    lines = []
    verdict = (research.get("verdict") or {}).get("verdict")
    if verdict:
        lines.append(f"Sonuç: {_clip(verdict, 300)}")
    deep = research.get("deep") or {}
    for project in (deep.get("projects") or [])[:5]:
        stars = f" ({project['stars']} yıldız)" if project.get("stars") not in (None, "") else ""
        weak = "; ".join(_clip(w, 90) for w in (project.get("weak") or [])[:3])
        lines.append(f"- Rakip {project.get('repo')}{stars}: {_clip(project.get('summary') or project.get('description'), 220)}"
                     + (f" Zayıf yanları: {weak}" if weak else ""))
    for argument in (deep.get("arguments") or [])[:5]:
        lines.append(f"- Rakipten ders: {_clip(argument.get('text'), 320)}")
    for item in (deep.get("differentiators") or [])[:4]:
        lines.append(f"- Fark: {_clip(item.get('text') if isinstance(item, dict) else item, 200)}")
    for tool in [t for t in (research.get("tools") or []) if t.get("recommended")][:6]:
        lines.append(f"- İşe yarayabilecek araç {tool.get('name') or tool.get('repo')}: {_clip(tool.get('why'), 160)}")
    for chance in (research.get("opportunities") or [])[:5]:
        lines.append(f"- Fırsat: {_clip(chance.get('title'), 90)} — {_clip(chance.get('detail'), 200)}")
    return "\n".join(lines)


class MasterPrompts:
    def __init__(self, vault, notes, assistant):
        self.vault = vault
        self.notes = notes
        self.assistant = assistant
        self.running: set[str] = set()

    def last(self, rel: str) -> dict:
        return dict(self.notes.load(rel).get("master_prompt") or {})

    def material(self, rel: str, content: str | None = None) -> tuple[str, dict]:
        """The model's input, and the numbers the dialog shows beside it."""
        if content is None:
            content = self.vault.read_note(rel)["content"]
        _, body, _ = split_frontmatter(content)
        state = self.notes.load(rel)
        nodes = state.get("nodes") or []
        steps = ladder.state(state.get("decisions"))
        name = rel.rsplit("/", 1)[-1].removesuffix(".md")
        parts = [f"[NOTUN ADI]\n{name}", f"[NOT]\n{body.strip()[:NOTE_CHARS] or '(boş)'}",
                 ladder.brief(steps)]
        direction = (state.get("direction") or {}).get("text")
        if direction:
            parts.append(f"[KULLANICININ SON YÖNÜ — eski notla çelişirse bu geçerli]\n{direction}")

        children: dict = {}
        for node in nodes:
            children.setdefault(node.get("parentId"), []).append(node)
        answered, waiting = [], []
        for node in nodes:
            if node["type"] != "question" or node.get("status") == "dismissed":
                continue
            if node.get("status") == "open":
                waiting.append(f"- {_clip(node['text'], 300)}")
                continue
            kids = children.get(node["id"], [])
            settled = [k["text"] for k in kids if k["type"] == "summary" and k.get("status") == "approved"]
            talk = " / ".join(f"{'Yazar' if k['type'] == 'chat-user' else 'Asistan'}: {k['text']}"
                              for k in kids if k["type"] in ("chat-user", "chat-assistant"))
            line = f"- S: {_clip(node['text'], 300)}"
            if settled:
                line += f"\n  Sonuç: {_clip(' '.join(settled), THREAD_CHARS)}"
            elif talk:
                line += f"\n  Konuşma: {_clip(talk, THREAD_CHARS)}"
            answered.append(line)
        if answered:
            parts.append("[CEVAPLANMIŞ SORULAR]\n" + "\n".join(answered))
        if waiting:
            parts.append("[CEVAP BEKLEYEN SORULAR — kararı sen ver ve Varsayımlar bölümüne yaz]\n"
                         + "\n".join(waiting))
        approved = [n["text"] for n in nodes if n["type"] == "summary" and n.get("status") == "approved"
                    and not n.get("parentId")]
        if approved:
            parts.append("[YAZARIN ONAYLADIĞI ÖNERİLER]\n" + "\n".join(f"- {_clip(t, 400)}" for t in approved))
        rejected = [n.get("replacement") if n["type"] == "edit" else n.get("text") for n in nodes
                    if n["type"] in ("summary", "edit") and n.get("status") == "rejected"]
        rejected = [t for t in rejected if t]
        if rejected:
            parts.append("[YAZARIN REDDETTİĞİ ÖNERİLER — bunları yapma]\n"
                         + "\n".join(f"- {_clip(t, 300)}" for t in rejected))
        digest = research_digest(state.get("research") or {})
        if digest:
            parts.append("[ARAŞTIRMA — arka plan bilgisi, bağlayıcı değil]\n" + digest)
        stats = {"made": steps["made"], "total": steps["total"], "phase": steps["phase"],
                 "phase_label": steps["phase_label"], "waiting": len(waiting),
                 "answered": len(answered), "research": bool(digest)}
        return "\n\n".join(parts), stats

    async def stream(self, rel: str, language: str = "tr", content: str | None = None):
        """Updates for the dialog: the text as it is written, then the result."""
        if rel in self.running:
            yield {"type": "error", "message": "Bu not için master prompt zaten hazırlanıyor."}
            return
        try:
            material, stats = self.material(rel, content)
            provider = self.assistant.provider_for("master", rel)
        except ApiError as exc:
            yield {"type": "error", "message": exc.message}
            return
        # "OpenRouter · DeepSeek V4 Flash" already names its model; "Yerel" does not
        name = (provider.model or "").rsplit("/", 1)[-1].replace("-", " ").lower()
        model = (f"{provider.label} · {provider.model}"
                 if provider.model and name.split()[0] not in provider.label.lower() else provider.label)
        yield {"type": "start", "stats": stats, "provider": model}

        loop = asyncio.get_running_loop()
        updates: asyncio.Queue = asyncio.Queue()
        last_emit = 0.0
        record = self.assistant.budget.record

        def on_chunk(accumulated: str):
            nonlocal last_emit
            now = time.monotonic()
            if now - last_emit >= THROTTLE_S:
                last_emit = now
                loop.call_soon_threadsafe(updates.put_nowait, ("progress", accumulated))

        def write() -> tuple[str, int]:
            text = llm_client.master_prompt(material, language, provider, on_chunk, record)
            loop.call_soon_threadsafe(updates.put_nowait, ("checking", text))
            return llm_client.fix_master_prompt(text, provider, record)

        async def run():
            # the page may close mid-way: the writing goes on and is kept
            try:
                await write_and_keep()
            finally:
                self.running.discard(rel)

        async def write_and_keep():
            started = time.monotonic()
            try:
                text, fixed = await asyncio.to_thread(write)
            except Exception as exc:
                self.assistant.check_now()
                message = str(exc) if isinstance(exc, llm_client.ProviderError) else "Model yanıt vermedi."
                await updates.put(("error", f"Master prompt yazılamadı: {message}"))
                return
            if len(text.strip()) < 400:
                await updates.put(("error", "Model çok kısa bir metin döndürdü; tekrar dene."))
                return
            result = {"text": text, "language": language, "created": now_iso(), "stats": stats,
                      "provider": model, "fixed": fixed,
                      "open": len(llm_client.unresolved_lines(text)),
                      "assumptions": llm_client.master_assumptions(text),
                      "sections": sum(1 for line in text.splitlines() if line.startswith("## ")),
                      "seconds": round(time.monotonic() - started, 1)}
            with self.notes.lock:
                self.notes.load(rel)["master_prompt"] = result
                self.notes.save(rel)
            await updates.put(("done", result))

        self.running.add(rel)
        self.assistant._spawn(run())
        while True:
            kind, payload = await updates.get()
            if kind == "progress":
                yield {"type": "progress", "text": llm_client._strip_think(payload)}
            elif kind == "checking":
                yield {"type": "checking", "text": payload}
            elif kind == "done":
                yield {"type": "done", **payload}
                return
            else:
                yield {"type": "error", "message": payload}
                return
