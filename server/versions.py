"""A copy of a note as it was, taken just before something changes it.

The assistant never writes without approval — but approving is one click, and
"geri al" has to survive closing the tab, which Ctrl+Z does not. So every write
leaves the previous text behind: the assistant's writes always, ordinary typing
at most once per quiet period, so the folder stays short enough to read.

Snapshots live in the vault's .assistant/versions, mirroring the note's own
path, and are pruned to the most recent few per note.
"""
import re
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

from server.vault import VaultError

KEEP_PER_NOTE = 20
QUIET_S = 600.0        # one snapshot per ten minutes of ordinary typing
ID_RE = re.compile(r"^\d{8}-\d{6}(?:-\d+)?-[a-z]+$")
# a snapshot holds the text as it was *before* the write it is named after
LABELS = {"asistan": "asistan eklemeden önce", "duzenleme": "asistan düzeltmeden önce",
          "geri": "geri alınmadan önce", "yazma": "sen yazarken"}
ALWAYS = ("asistan", "duzenleme", "geri")   # never throttled: these are the ones you undo


class Versions:
    def __init__(self, vault):
        self.vault = vault
        self.dir = vault.meta_dir / "versions"
        self.lock = threading.RLock()

    def _folder(self, rel: str) -> Path:
        """Where a note's snapshots live: the same shape as the vault, one
        folder per note. resolve() is the vault's own guard, so a snapshot path
        can never climb out or reach into .assistant / .trash."""
        path = self.vault.resolve(rel)
        mirrored = self.dir / path.relative_to(self.vault.root)
        return mirrored.with_suffix("") if path.suffix.lower() == ".md" else mirrored

    @staticmethod
    def _files(folder: Path) -> list[Path]:
        """Oldest first. By write time, not by name: two snapshots can land in
        the same second (you save, the assistant appends) and the names would
        then sort alphabetically — putting the older one on top of the list."""
        try:
            return sorted(folder.glob("*.md"), key=lambda f: (f.stat().st_mtime_ns, f.name))
        except OSError:
            return []

    # ---- writing ----
    def save(self, rel: str, content: str | None, reason: str = "yazma") -> dict | None:
        """Keep `content` as the note's previous state. Returns the snapshot, or
        None when there was nothing worth keeping."""
        if not content:
            return None
        reason = reason if reason in LABELS else "yazma"
        with self.lock:
            folder = self._folder(rel)
            existing = self._files(folder)
            if existing:
                newest = existing[-1]
                try:
                    if newest.read_text(encoding="utf-8") == content:
                        return None     # nothing has changed since the last snapshot
                    if reason not in ALWAYS and time.time() - newest.stat().st_mtime < QUIET_S:
                        return None     # still the same writing session
                except OSError:
                    pass
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            name, extra = f"{stamp}-{reason}", 1
            while (folder / f"{name}.md").exists():
                name = f"{stamp}-{extra}-{reason}"
                extra += 1
            try:
                folder.mkdir(parents=True, exist_ok=True)
                (folder / f"{name}.md").write_text(content, encoding="utf-8")
            except OSError:
                return None             # a safety net must never block the save itself
            self._prune(folder)
            return self._describe(folder / f"{name}.md")

    def _prune(self, folder: Path) -> None:
        for old in self._files(folder)[:-KEEP_PER_NOTE]:
            old.unlink(missing_ok=True)

    # ---- reading ----
    @staticmethod
    def _describe(path: Path) -> dict:
        stem = path.stem
        stamp, reason = stem[:15], stem.rsplit("-", 1)[-1]
        try:
            created = datetime.strptime(stamp, "%Y%m%d-%H%M%S").isoformat(timespec="seconds")
        except ValueError:
            created = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
        return {"id": stem, "created": created, "reason": reason,
                "label": LABELS.get(reason, reason), "size": path.stat().st_size}

    def list(self, rel: str) -> list[dict]:
        with self.lock:
            return [self._describe(p) for p in reversed(self._files(self._folder(rel)))]

    def read(self, rel: str, version_id: str) -> str:
        if not ID_RE.match(version_id or ""):
            raise VaultError(400, "Geçersiz sürüm.")
        path = self._folder(rel) / f"{version_id}.md"
        if not path.is_file():
            raise VaultError(404, "Bu sürüm artık yok.")
        return path.read_text(encoding="utf-8")

    # ---- follow the note ----
    def moved(self, old_rel: str, new_rel: str) -> None:
        """Follows notes and whole folders — the mirror keeps the vault's shape."""
        with self.lock:
            old, new = self._folder(old_rel), self._folder(new_rel)
            if not old.is_dir() or old == new:
                return
            try:
                new.parent.mkdir(parents=True, exist_ok=True)
                if new.exists():
                    shutil.rmtree(new, ignore_errors=True)
                old.replace(new)
            except OSError:
                pass

    def trashed(self, rel: str) -> None:
        """Set the snapshots aside rather than deleting them — a note thrown away
        by mistake is exactly when its earlier text matters."""
        with self.lock:
            folder = self._folder(rel)
            if not folder.is_dir():
                return
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            try:
                folder.replace(folder.with_name(f"{folder.name} (silindi {stamp})"))
            except OSError:
                pass
