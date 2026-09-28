"""FastAPI app: JSON API, Server-Sent Events and the static frontend.

Bound to 127.0.0.1 only. LocalOnlyGuard additionally rejects foreign Host
headers (DNS rebinding) and state-changing requests without the X-Fikir
header, which a web page on another origin can't send without a CORS
preflight this server never approves — so other sites can't write notes or
launch the model through the user's browser.
"""
import asyncio
import html
import json
import re
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core import llm_client
from server import ladder
from server.assistant import Assistant
from server.broker import Broker
from server.errors import ApiError
from server.masterprompt import MasterPrompts
from server.providers import ProviderRegistry
from server.render import render
from server.research import ResearchRunner
from server.settings import APP_ID, LAUNCH_SCRIPTS, VERSION, WEB_DIR, Settings
from server.store import HistoryStore, NoteStore, _atomic_write_json
from server.tools import ToolHub
from server.vault import Vault


class LocalOnlyGuard:
    SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

    def __init__(self, app, port: int):
        self.app = app
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        host = headers.get(b"host", b"").decode("latin-1").lower()
        if host not in self.hosts:
            return await self._deny(send, "Host not allowed")
        if scope["method"] not in self.SAFE_METHODS and headers.get(b"x-fikir") != b"1":
            return await self._deny(send, "Missing X-Fikir header")

        async def send_no_cache(message):
            if message["type"] == "http.response.start":
                names = {name.lower() for name, _ in message.get("headers", [])}
                if b"cache-control" not in names:
                    message["headers"] = [*message.get("headers", []), (b"cache-control", b"no-cache")]
            await send(message)

        await self.app(scope, receive, send_no_cache)

    @staticmethod
    async def _deny(send, reason: str):
        body = json.dumps({"detail": reason}).encode()
        await send({"type": "http.response.start", "status": 403,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


class NoteWrite(BaseModel):
    path: str
    content: str


class CreateNote(BaseModel):
    dir: str = ""
    name: str = "Adsız Not"
    content: str = ""


class CreateFolder(BaseModel):
    dir: str = ""
    name: str


class RenameBody(BaseModel):
    path: str
    name: str


class MoveBody(BaseModel):
    path: str
    dir: str


class PathBody(BaseModel):
    path: str


class ApplyEditBody(BaseModel):
    path: str
    original: str
    replacement: str
    event_id: str


class AppendBody(BaseModel):
    path: str
    text: str
    event_id: str


class RenderBody(BaseModel):
    content: str
    path: str | None = None


class AnalyzeBody(BaseModel):
    path: str
    content: str
    force: bool = False


class HudBody(BaseModel):
    event_id: str
    action: str


class EventBody(BaseModel):
    event_id: str


class DecisionBody(BaseModel):
    path: str
    decision: str
    decided: bool = True


class DirectionBody(BaseModel):
    path: str
    category: str
    text: str
    plan: dict | None = None     # what the writer approved from the preview


class NodeBody(BaseModel):
    path: str
    node_id: str


class MasterPromptBody(BaseModel):
    path: str
    language: str = "tr"
    content: str | None = None


class ChatBody(NodeBody):
    message: str


class LaunchBody(BaseModel):
    name: str | None = None


class ToolCallBody(BaseModel):
    name: str
    arguments: dict | None = None


class ToolSettingsBody(BaseModel):
    github_token: str | None = None


class ResearchBody(BaseModel):
    path: str
    content: str | None = None
    focus: str | None = None
    web: bool = True


class ResearchChoice(BaseModel):
    type: str
    id: str


class ResearchProposalBody(BaseModel):
    path: str
    items: list[ResearchChoice]


class BindBody(BaseModel):
    role: str
    providers: list[str]


class ProviderTestBody(BaseModel):
    id: str


def _research_proposal_text(result: dict, choices: list[ResearchChoice]) -> str:
    """Build note text only from selected, saved research evidence."""
    if result.get("status") != "done":
        raise ApiError(409, "Önce araştırmayı tamamla.")
    if not 1 <= len(choices) <= 8:
        raise ApiError(400, "Nota önermek için 1–8 araştırma sonucu seç.")

    lookup = {
        "project": {str(row.get("repo")): row for row in result.get("candidates", [])},
        "tool": {str(row.get("id")): row for row in result.get("tools", [])},
        "opportunity": {str(row.get("id")): row for row in result.get("opportunities", [])},
        "source": {str(row.get("url")): row for row in result.get("sources", [])
                   if row.get("verified")},
        "insight": {str(row.get("id")): row for row in
                    [*((result.get("deep") or {}).get("differentiators") or []),
                     *((result.get("deep") or {}).get("arguments") or [])]},
    }

    def line(value, limit):
        # Search snippets and fetched pages are untrusted, multi-line input.
        # Keep each selected finding on one legible Markdown list item.
        plain = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
        return " ".join(plain.split())[:limit].rstrip()

    lines = ["## Araştırma bulguları"]
    seen = set()
    for choice in choices:
        key = (choice.type, choice.id)
        if key in seen:
            continue
        seen.add(key)
        row = lookup.get(choice.type, {}).get(choice.id)
        if row is None:
            raise ApiError(404, "Seçilen araştırma sonucu bulunamadı; araştırmayı yenile.")

        if choice.type == "project":
            name = line(row.get("repo") or choice.id, 120)
            detail = line(row.get("description"), 350)
            lines.append(f"- **Benzer proje: {name}** — {detail}" if detail else f"- **Benzer proje: {name}**")
        elif choice.type == "source":
            name = line(row.get("title") or "Kaynak", 120)
            detail = line(row.get("excerpt") or row.get("snippet"), 350)
            lines.append(f"- **Okunan kaynak: {name}** — {detail}" if detail else f"- **Okunan kaynak: {name}**")
        elif choice.type == "insight":
            label = "Ayrışma" if row.get("kind") == "ayrisma" else "Argüman"
            lines.append(f"- **{label}:** {line(row.get('text'), 400)}")
            continue
        elif choice.type == "tool":
            name = line(row.get("name") or row.get("repo") or choice.id, 120)
            detail = line(row.get("why") or row.get("description"), 350)
            lines.append(f"- **Araç: {name}** — {detail}" if detail else f"- **Araç: {name}**")
        else:
            title = line(row.get("title") or "Geliştirme fikri", 120)
            detail = line(row.get("detail"), 350)
            lines.append(f"- **{title}** — {detail}" if detail else f"- **{title}**")

        urls = row.get("source_urls") or ([row.get("url")] if row.get("url") else [])
        for url in list(urls)[:1]:
            parsed = urlparse(str(url))
            if parsed.scheme in ("http", "https") and parsed.netloc and len(str(url)) <= 220:
                lines.append(f"  Kaynak: {url}")
    return "\n".join(lines)


def create_app(settings: Settings) -> FastAPI:
    vault = Vault(settings.vault)
    notes = NoteStore(vault)
    history = HistoryStore(vault)
    broker = Broker()
    providers = ProviderRegistry()
    tool_hub = ToolHub()
    assistant = Assistant(vault, notes, history, broker, providers, tool_hub)
    research = ResearchRunner(vault, notes, broker, tool_hub, assistant.provider_for,
                              assistant.budget.record, assistant.is_private)
    master = MasterPrompts(vault, notes, assistant)
    session_file = vault.meta_dir / "session.json"

    @asynccontextmanager
    async def lifespan(_app):
        broker.bind(asyncio.get_running_loop())
        # the research servers are separate processes: started once here and
        # kept open, never one per call, and shut down with the app
        await tool_hub.start()
        assistant.start()
        yield
        await assistant.stop()
        await tool_hub.stop()

    app = FastAPI(title="Concept Trail", version=VERSION, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(ApiError)
    async def api_error(_request: Request, exc: ApiError):
        return JSONResponse({"detail": exc.message}, status_code=exc.status)

    def client_of(request: Request) -> str | None:
        return request.headers.get("x-client-id")

    # ---- app / realtime ----
    @app.get("/api/state")
    async def state():
        return {"app": APP_ID, "version": VERSION, "vault": vault.name,
                "scripts": list(LAUNCH_SCRIPTS), **assistant.snapshot(),
                "providers": providers.public()}

    # ---- research tools (two MCP stdio servers) ----
    @app.get("/api/tools")
    async def list_tools():
        """What was discovered at startup — names and schemas come from the
        servers themselves — plus whether the bound providers could use them."""
        bound = [(role, providers.pick(role)) for role in ("chat", "analysis", "summary")]
        bound = [(role, provider) for role, provider in bound if provider is not None]
        # probed together, not one after another: each probe waits on a model
        # server that may be down, and the settings dialog waits on this reply
        reports = await asyncio.gather(
            *(asyncio.to_thread(llm_client.supports_tools, provider) for _, provider in bound))
        support = {role: {"provider": provider.id, "enabled": provider.tools, "endpoint_reports": report}
                   for (role, provider), report in zip(bound, reports)}
        return {**tool_hub.public(), "definitions": tool_hub.function_tools(), "providers": support}

    @app.post("/api/tools/call")
    async def call_tool(body: ToolCallBody):
        """Run one tool by hand (no model involved). A tool that reports an
        error comes back with ok=false — never dressed up as a success."""
        return await tool_hub.call(body.name, body.arguments or {})

    @app.put("/api/tools/settings")
    async def put_tool_settings(body: ToolSettingsBody):
        """Save the research tokens. A server reads its token from the
        environment once, at startup, so saving one is only half the job —
        the servers come back up here or the new token would do nothing."""
        tool_hub.settings.replace(body.model_dump(exclude_none=True))
        return await tool_hub.restart()

    @app.post("/api/tools/restart")
    async def restart_tools():
        """Also the way to pick up a corrected path without restarting the app."""
        return await tool_hub.restart()

    # ---- model providers (what the API-key binder edits) ----
    @app.get("/api/providers")
    async def get_providers():
        return providers.public()

    @app.put("/api/providers")
    async def put_providers(request: Request):
        result = providers.replace(await request.json())
        assistant.check_now()
        broker.publish("providers", result)
        broker.publish("status", assistant.status())
        return result

    @app.post("/api/providers/bind")
    async def bind_role(body: BindBody):
        result = providers.bind(body.role, body.providers)
        assistant.check_now()
        broker.publish("providers", result)
        broker.publish("status", assistant.status())
        return result

    @app.get("/api/usage")
    async def get_usage():
        return assistant.usage()

    @app.put("/api/usage/limits")
    async def put_limits(request: Request):
        result = assistant.budget.set_limits(await request.json())
        broker.publish("status", assistant.status())
        return result

    @app.post("/api/providers/test")
    async def test_provider(body: ProviderTestBody):
        return await assistant.test_provider(body.id)

    @app.get("/api/events")
    async def events():
        queue = broker.subscribe()

        async def stream():
            try:
                yield "retry: 1500\n\n"
                yield Broker.format("snapshot", assistant.snapshot())
                while True:
                    try:
                        message = await asyncio.wait_for(queue.get(), timeout=15)
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
                        continue
                    if message is None:
                        break
                    yield message
            finally:
                broker.unsubscribe(queue)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/session")
    def get_session():
        try:
            return json.loads(session_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    @app.put("/api/session")
    async def put_session(request: Request):
        data = await request.json()
        if not isinstance(data, dict):
            raise ApiError(400, "Geçersiz oturum verisi.")
        _atomic_write_json(session_file, data)
        return {"ok": True}

    # ---- vault ----
    @app.get("/api/vault/tree")
    def vault_tree():
        return {"name": vault.name, "tree": vault.tree()}

    @app.get("/api/vault/tags")
    def vault_tags():
        return vault.tags()

    @app.get("/api/vault/search")
    def vault_search(q: str = ""):
        return vault.search(q)

    @app.post("/api/folders/create")
    def create_folder(body: CreateFolder):
        rel = vault.create_folder(body.dir, body.name)
        broker.publish("vault_changed", {"created": rel})
        return {"path": rel}

    @app.post("/api/vault/rename")
    async def rename(body: RenameBody):
        new_rel = vault.rename(body.path, body.name)
        if new_rel != body.path:
            assistant.moved(body.path, new_rel)
            broker.publish("vault_changed", {"renamed": [body.path, new_rel]})
        return {"path": new_rel}

    @app.post("/api/vault/move")
    async def move(body: MoveBody):
        new_rel = vault.move(body.path, body.dir)
        assistant.moved(body.path, new_rel)
        broker.publish("vault_changed", {"renamed": [body.path, new_rel]})
        return {"path": new_rel}

    @app.post("/api/vault/trash")
    async def trash(body: PathBody):
        trash_name = vault.trash(body.path)
        assistant.trashed(body.path, trash_name)
        broker.publish("vault_changed", {"trashed": body.path})
        return {"ok": True}

    @app.get("/vault-file/{rel:path}")
    def vault_file(rel: str):
        return FileResponse(vault.asset_path(rel))

    # ---- notes ----
    @app.get("/api/notes")
    def read_note(path: str):
        return vault.read_note(path)

    @app.put("/api/notes")
    def write_note(body: NoteWrite, request: Request):
        result = vault.write_note(body.path, body.content)
        broker.publish("note_changed", {**result, "client": client_of(request)})
        return result

    @app.post("/api/notes/create")
    def create_note(body: CreateNote):
        rel = vault.create_note(body.dir, body.name, body.content)
        broker.publish("vault_changed", {"created": rel})
        return {"path": rel}

    @app.post("/api/notes/apply-edit")
    async def apply_edit(body: ApplyEditBody):
        if not assistant.claim(body.event_id):
            return {"applied": False}
        content = vault.read_note(body.path)["content"]
        if body.original not in content:
            return {"applied": False}
        result = vault.write_note(body.path, content.replace(body.original, body.replacement, 1))
        broker.publish("note_changed", {**result, "client": None})
        return {"applied": True}

    @app.post("/api/notes/append")
    async def append_to_note(body: AppendBody):
        """Fallback for when no open page claimed the assistant's write-up."""
        if not assistant.claim(body.event_id):
            return {"applied": False}
        content = vault.read_note(body.path)["content"]
        gap = "" if not content or content.endswith("\n\n") else ("\n" if content.endswith("\n") else "\n\n")
        result = vault.write_note(body.path, f"{content}{gap}{body.text.strip()}\n")
        broker.publish("note_changed", {**result, "client": None})
        return {"applied": True}

    @app.post("/api/render")
    def render_markdown(body: RenderBody):
        return render(body.content, body.path)

    # ---- assistant ----
    @app.get("/api/assistant/history")
    def get_history():
        return history.items

    @app.get("/api/assistant/nodes")
    def get_nodes(path: str):
        state = notes.load(path)
        # `written` is what the assistant put in the note with your approval;
        # the editor uses it to keep its words visually apart from yours
        try:
            mode = ladder.note_mode(vault.read_note(path)["content"])
        except Exception:
            mode = "yazilim"
        return {"nodes": state["nodes"], "busy": assistant.busy == path,
                "written": list(state.get("assistant_text") or []),
                "mode": mode, "ladder": assistant.ladder_for(path),
                "direction": state.get("direction")}

    @app.post("/api/assistant/direction/preview")
    async def preview_direction(body: DirectionBody):
        """What the correction would change, for the writer to approve first."""
        return await assistant.preview_direction(body.path, body.category, body.text)

    @app.post("/api/assistant/direction")
    def set_direction(body: DirectionBody):
        return assistant.set_direction(body.path, body.category, body.text, body.plan)

    @app.post("/api/assistant/decision")
    def set_decision(body: DecisionBody):
        """The writer marks a decision made, or opens it again — the model can
        misread the note, and the ladder is the writer's to correct."""
        if body.decision not in ladder.DECISIONS:
            raise ApiError(400, "Bilinmeyen karar.")
        return assistant.set_decisions(body.path, {body.decision: body.decided}, by="sen")

    @app.post("/api/assistant/analyze")
    async def analyze(body: AnalyzeBody):
        vault.note_path(body.path)
        return await assistant.analyze(body.path, body.content, body.force)

    @app.post("/api/assistant/hud")
    async def hud_action(body: HudBody):
        return assistant.hud_action(body.event_id, body.action)

    @app.post("/api/assistant/claim")
    async def claim(body: EventBody):
        return {"ok": assistant.claim(body.event_id)}

    @app.post("/api/assistant/resolve")
    async def resolve(body: NodeBody):
        return assistant.resolve(body.path, body.node_id)

    @app.post("/api/assistant/chat")
    async def chat(body: ChatBody):
        message = body.message.strip()
        if not message:
            raise ApiError(400, "Mesaj boş olamaz.")
        vault.note_path(body.path)
        assistant._conversation(body.path, body.node_id)  # 404 before the stream starts, not inside it

        async def stream():
            async for update in assistant.chat_stream(body.path, body.node_id, message):
                yield json.dumps(update, ensure_ascii=False) + "\n"

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    @app.post("/api/assistant/summarize")
    async def summarize(body: NodeBody):
        return await assistant.summarize(body.path, body.node_id)

    # ---- the master prompt: build instructions for a coding agent ----
    @app.get("/api/master-prompt")
    def master_prompt_state(path: str):
        vault.note_path(path)
        _, stats = master.material(path)
        return {"last": master.last(path) or None, "stats": stats,
                "busy": path in master.running}

    @app.post("/api/master-prompt")
    async def master_prompt(body: MasterPromptBody):
        vault.note_path(body.path)
        if body.language not in llm_client.MASTER_LANGUAGES:
            raise ApiError(400, "Bilinmeyen dil.")

        async def stream():
            async for update in master.stream(body.path, body.language, body.content):
                yield json.dumps(update, ensure_ascii=False) + "\n"

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    # ---- prior-art research (has this idea been built already?) ----
    @app.get("/api/research")
    def research_state(path: str):
        vault.note_path(path)
        return {**research.state(path), "busy": research.busy(path)}

    @app.post("/api/research/start")
    async def research_start(body: ResearchBody):
        """Search similar work and useful tools; report progress over SSE."""
        vault.note_path(body.path)
        content = body.content if body.content is not None else vault.read_note(body.path)["content"]
        if not content.strip():
            raise ApiError(400, "Bos not arastirilamaz.")
        return await research.start(body.path, content, focus=body.focus, web=body.web)

    @app.post("/api/research/propose")
    async def research_propose(body: ResearchProposalBody):
        """Put selected findings through the same approval gate as chat summaries."""
        vault.note_path(body.path)
        text = _research_proposal_text(research.state(body.path), body.items)
        return assistant.propose_text(body.path, text, source="research")

    @app.post("/api/model/launch")
    async def launch_model(body: LaunchBody):
        assistant.launch_model(body.name or next(iter(LAUNCH_SCRIPTS)))
        return {"ok": True}

    @app.post("/api/model/check")
    async def check_model():
        assistant.check_now()
        return {"ok": True}

    # ---- frontend ----
    @app.get("/")
    async def index():
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/hud")
    async def hud_page():
        return FileResponse(WEB_DIR / "hud.html")

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return LocalOnlyGuard(app, settings.port)
