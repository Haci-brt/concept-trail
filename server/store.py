"""Persistence for everything the assistant produces.

Per-note state lives in <vault>/.assistant/notes/<note path>.json so the vault
itself stays a clean folder of markdown files. A note's state is its idea
tree: questions, edit suggestions, chat messages and summaries, each a node
whose parentId is either None (hangs off the note) or another node.
"""
import json
import os
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

HISTORY_LIMIT = 400
WAITING_LIMIT = 600      # waiting events kept past HISTORY_LIMIT, a bound all the same


def still_waiting(event: dict) -> bool:
    if event.get("type") == "question":
        return event.get("status") == "open"
    return event.get("type") in ("summary", "edit", "research") and event.get("status") == "pending"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _atomic_write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


# Damaged files met this run, oldest first. Each was set aside, not overwritten;
# the app tells the pages about them as a flash (notices_to_tell).
RECOVERED: list[dict] = []
_recovered_lock = threading.Lock()
_notify = None


def set_recovery_notifier(callback) -> None:
    """Called after every set_aside, so a page already open hears at once."""
    global _notify
    _notify = callback


def set_aside(path: Path) -> Path | None:
    """A file that exists but cannot be parsed is renamed to
    <name>.corrupt-<time> before the caller goes on with defaults: the next
    save would otherwise overwrite whatever could still be rescued from it
    (for providers.json, the API keys). A missing file never comes here."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.name}.corrupt-{stamp}")
    n = 2
    while target.exists():
        target = path.with_name(f"{path.name}.corrupt-{stamp}-{n}")
        n += 1
    try:
        os.replace(path, target)
    except OSError:
        try:
            shutil.copy2(path, target)      # locked by another program: a copy still saves it
        except OSError:
            return None
    with _recovered_lock:
        RECOVERED.append({"file": str(path), "moved_to": str(target), "time": now_iso(), "told": None})
    if _notify is not None:
        try:
            _notify()
        except Exception:
            pass
    return target


def notices_to_tell(window: float = 60.0) -> list[dict]:
    """The damaged files a page connecting now should hear about: those not yet
    told, and those first told under a minute ago — the desktop's window and
    its HUD connect a moment apart, and only one of them shows flashes. A
    reload later on does not bring the notice back."""
    now = time.monotonic()
    with _recovered_lock:
        fresh = [notice for notice in RECOVERED if notice["told"] is None or now - notice["told"] < window]
        for notice in fresh:
            if notice["told"] is None:
                notice["told"] = now
    return fresh


def read_json(path: Path, expect: type = dict):
    """The parsed file, or None when it is missing or damaged — a damaged one
    (unparseable, or not the expected shape) is set aside first."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None                         # missing, or locked right now: not damaged
    try:
        data = json.loads(raw.decode("utf-8-sig"))  # a BOM from a hand edit in Notepad is fine
    except ValueError:                      # bad JSON or bad UTF-8
        data = None
    if not isinstance(data, expect):
        set_aside(path)
        return None
    return data


MAX_ASSISTANT_TEXTS = 60     # a long note's worth; the oldest drop off


def empty_state() -> dict:
    return {"version": 2, "counter": 0, "nodes": [], "analyzed_text": "", "last_question": "",
            "direction": None, "direction_history": []}


def _migrate_legacy(data: dict) -> dict:
    """Convert the PyQt app's <note>.tree.json sidecar into the current shape."""
    state = empty_state()
    open_ids = set(data.get("open_question_ids", []))
    for node in data.get("tree_nodes", []):
        kind = node.get("type")
        parent = node.get("parentId")
        migrated = {
            "id": node["id"],
            "parentId": None if parent in (None, "root") else parent,
            "type": "question" if kind == "resolved" else kind,
            "text": node.get("label", ""),
            "created": now_iso(),
        }
        if kind in ("question", "resolved"):
            migrated["status"] = "open" if node["id"] in open_ids and kind == "question" else "resolved"
        elif kind == "edit":
            migrated["status"] = "pending"
        state["nodes"].append(migrated)
    state["counter"] = data.get("node_counter", len(state["nodes"]))
    return state


class NoteStore:
    def __init__(self, vault):
        self.vault = vault
        self.dir = vault.meta_dir / "notes"
        self.lock = threading.RLock()
        self._cache: dict[str, dict] = {}
        self._moved: dict[str, str] = {}   # old path -> new, for work that started before a rename

    def _file(self, rel: str) -> Path:
        return self.dir / f"{rel}.json"

    def current(self, rel: str) -> str:
        """Where a note is now. A pass or a chat that began before a rename
        still holds the old path; its questions used to land there, under a
        note that no longer existed. Followed only while nothing is at the
        old path again — a new note of that name starts clean."""
        with self.lock:
            for _ in range(8):
                if (self.vault.root / rel).exists():
                    return rel
                moved = next(((old, new) for old, new in self._moved.items()
                              if rel == old or rel.startswith(old + "/")), None)
                if moved is None:
                    return rel
                rel = moved[1] + rel[len(moved[0]):]
            return rel

    def load(self, rel: str) -> dict:
        with self.lock:
            rel = self.current(rel)
            if rel in self._cache:
                return self._cache[rel]
            state = read_json(self._file(rel))
            if state is None:
                legacy = (self.vault.root / rel).with_suffix(".tree.json")
                if legacy.is_file():
                    try:
                        state = _migrate_legacy(json.loads(legacy.read_text(encoding="utf-8")))
                    except (OSError, json.JSONDecodeError, KeyError):
                        state = None
            state = state or empty_state()
            self._cache[rel] = state
            return state

    def save(self, rel: str) -> None:
        with self.lock:
            state = self._cache.get(self.current(rel))
            rel = self.current(rel)
            if state is None:
                return
            try:
                _atomic_write_json(self._file(rel), state)
            except OSError:
                pass  # persistence is a nice-to-have, never block the UI on it

    def add_node(self, rel: str, node_type: str, text: str, parent_id: str | None = None, **fields) -> dict:
        with self.lock:
            state = self.load(rel)
            state["counter"] += 1
            node = {
                "id": f"{node_type[0]}{state['counter']}",
                "parentId": parent_id,
                "type": node_type,
                "text": text,
                "created": now_iso(),
                **fields,
            }
            state["nodes"].append(node)
            self.save(rel)
            return node

    def update_node(self, rel: str, node_id: str, **fields) -> dict | None:
        with self.lock:
            node = self.find_node(rel, node_id)
            if node is None:
                return None
            node.update(fields)
            self.save(rel)
            return node

    def find_node(self, rel: str, node_id: str) -> dict | None:
        for node in self.load(rel)["nodes"]:
            if node["id"] == node_id:
                return node
        return None

    def open_questions(self, rel: str) -> list[dict]:
        return [n for n in self.load(rel)["nodes"] if n["type"] == "question" and n.get("status") == "open"]

    def thread(self, rel: str, node_id: str) -> list[dict]:
        return [n for n in self.load(rel)["nodes"]
                if n.get("parentId") == node_id and n["type"] in ("chat-user", "chat-assistant")]

    def question_lineage(self, rel: str, node_id: str) -> list[dict]:
        """The question's ancestors, oldest first, including the question itself.

        Old state files may contain missing parents or a malformed cycle. Stop
        at either boundary so a damaged tree cannot hang a chat request.
        """
        nodes = {n["id"]: n for n in self.load(rel)["nodes"]}
        lineage, seen = [], set()
        current = nodes.get(node_id)
        while current and current.get("type") == "question" and current["id"] not in seen:
            lineage.append(current)
            seen.add(current["id"])
            current = nodes.get(current.get("parentId"))
        return list(reversed(lineage))

    # ---- keeping state attached to notes as they move ----
    def moved(self, old_rel: str, new_rel: str) -> None:
        """A note or folder was renamed/moved; carry its state along."""
        with self.lock:
            self._moved[old_rel] = new_rel
            self._moved.pop(new_rel, None)           # moved back: the old way round no longer holds
            for rel in list(self._cache):
                if rel == old_rel or rel.startswith(old_rel + "/"):
                    self._cache[new_rel + rel[len(old_rel):]] = self._cache.pop(rel)
            src_file, src_dir = self._file(old_rel), self.dir / old_rel
            try:
                if src_file.is_file():
                    dst = self._file(new_rel)
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(src_file, dst)
                elif src_dir.is_dir():
                    dst = self.dir / new_rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src_dir), str(dst))
            except OSError:
                pass

    def trashed(self, rel: str, trash_name: str) -> None:
        """A note or folder went to the trash; its state follows it there so a
        new note with the same name starts with a clean tree."""
        with self.lock:
            for key in list(self._cache):
                if key == rel or key.startswith(rel + "/"):
                    del self._cache[key]
            state_dir = self.vault.trash_dir / ".state"
            for src in (self._file(rel), self.dir / rel):
                if src.exists():
                    try:
                        state_dir.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(src), str(state_dir / f"{trash_name}{src.suffix if src.is_file() else ''}"))
                    except OSError:
                        pass


class HistoryStore:
    def __init__(self, vault):
        self.path = vault.meta_dir / "history.json"
        self.lock = threading.RLock()
        self.items: list[dict] = read_json(self.path, expect=list) or []

    def add(self, event: dict) -> None:
        with self.lock:
            self.items.insert(0, event)
            # only what is settled ages out: a question still waiting for its
            # answer, or a proposal for its approval, dropped out of the panel
            # after a few busy notes while the tree still showed it
            if len(self.items) > HISTORY_LIMIT:
                waiting = [e for e in self.items[HISTORY_LIMIT:] if still_waiting(e)]
                self.items[HISTORY_LIMIT:] = waiting[:WAITING_LIMIT]
            self._save()

    def find(self, event_id: str) -> dict | None:
        return next((e for e in self.items if e["id"] == event_id), None)

    def find_by_node(self, path: str, node_id: str, event_type: str) -> dict | None:
        return next((e for e in self.items
                     if e.get("path") == path and e.get("node_id") == node_id and e["type"] == event_type), None)

    def update(self, event: dict, **fields) -> dict:
        with self.lock:
            event.update(fields)
            self._save()
            return event

    def moved(self, old_rel: str, new_rel: str) -> None:
        with self.lock:
            for event in self.items:
                path = event.get("path", "")
                if path == old_rel or path.startswith(old_rel + "/"):
                    event["path"] = new_rel + path[len(old_rel):]
                    event["note"] = Path(event["path"]).stem
            self._save()

    def _save(self) -> None:
        try:
            _atomic_write_json(self.path, self.items)
        except OSError:
            pass
