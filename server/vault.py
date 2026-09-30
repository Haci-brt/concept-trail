"""The notes vault on disk: a folder of markdown files, Obsidian-style.

Every path that comes in from the browser goes through Vault.resolve(), which
refuses anything outside the vault root and the app's own hidden folders.
"""
import os
import re
import shutil
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from server.errors import ApiError as VaultError

NOTE_SUFFIX = ".md"
HIDDEN_DIRS = {".assistant", ".trash", ".git", ".obsidian"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}
INVALID_NAME_CHARS = set('/\\:*?"<>|')
LOCK_RETRY_S = (0.05, 0.2, 0.5)     # waits before giving a locked file up for now
VERSION_EVERY_S = 600               # one kept copy per ten minutes of writing
VERSIONS_KEPT = 30

TR_LETTERS = "A-Za-zÇĞİÖŞÜçğıöşü"
TAG_RE = re.compile(rf"(?<![\w#/&])#([{TR_LETTERS}][\w{TR_LETTERS}/-]*)")
FENCE_RE = re.compile(r"^(```|~~~).*?^\1", re.S | re.M)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?\r?\n)?---[ \t]*(?:\r?\n|\Z)", re.S)
_TAG_CACHE_SETTLE_NS = 2_000_000_000  # Vault.tags() trusts a note's cached tags once it is this old


def fold(text: str) -> str:
    """Case- and dotted/dotless-i-insensitive form for searching Turkish text."""
    return text.translate({ord("İ"): "i", ord("I"): "i", ord("ı"): "i"}).casefold()


_TR_ASCII = str.maketrans("çğıöşüâî", "cgiosuai")


def plain(text: str) -> str:
    """fold() with the Turkish letters spelled in ASCII: the form patterns
    written without them ("onemlidir", "dusunmelisin") have to be matched
    against — fold() alone leaves "önemlidir" as it is."""
    return fold(text).translate(_TR_ASCII)


def split_frontmatter(text: str) -> tuple[dict, str, int]:
    """Return (meta, body, number of lines the frontmatter occupied)."""
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text, 0
    block = match.group(1) or ""
    meta: dict = {}
    current_list: list | None = None
    for line in block.splitlines():
        item = re.match(r"^\s*-\s+(.*)$", line)
        if item and current_list is not None:
            current_list.append(item.group(1).strip().strip("'\""))
            continue
        pair = re.match(r"^([\w-]+)\s*:\s*(.*)$", line)
        if not pair:
            continue
        key, value = pair.group(1), pair.group(2).strip()
        if value.startswith("[") and value.endswith("]"):
            meta[key] = [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]
            current_list = None
        elif value == "":
            meta[key] = current_list = []
        else:
            meta[key] = value.strip("'\"")
            current_list = None
    consumed = text[:match.end()].count("\n")
    return meta, text[match.end():], consumed


def note_tags(text: str) -> set[str]:
    meta, body, _ = split_frontmatter(text)
    tags = set()
    raw = meta.get("tags")
    if isinstance(raw, str):
        raw = [t for t in re.split(r"[,\s]+", raw) if t]
    for tag in raw or []:
        tag = str(tag).lstrip("#").strip()
        if tag:
            tags.add(tag)
    body = INLINE_CODE_RE.sub("", FENCE_RE.sub("", body))
    tags.update(TAG_RE.findall(body))
    return {t.casefold() for t in tags}


def clean_name(name: str, *, note: bool) -> str:
    name = (name or "").strip()
    if note and name.lower().endswith(NOTE_SUFFIX):
        name = name[: -len(NOTE_SUFFIX)].strip()
    if not name:
        raise VaultError(400, "İsim boş olamaz.")
    if name.startswith("."):
        raise VaultError(400, "İsim nokta ile başlayamaz.")
    if any(ch in INVALID_NAME_CHARS for ch in name):
        raise VaultError(400, 'İsim şu karakterleri içeremez: / \\ : * ? " < > |')
    if len(name) > 120:
        raise VaultError(400, "İsim çok uzun.")
    return name


class Vault:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.root = root.resolve()
        self.meta_dir = self.root / ".assistant"
        self.trash_dir = self.root / ".trash"
        # absolute note path -> (mtime_ns, size, tags); see tags()
        self._tag_cache: dict[str, tuple[int, int, frozenset]] = {}

    @property
    def name(self) -> str:
        return self.root.name

    # ---- paths ----
    def resolve(self, rel: str) -> Path:
        rel = (rel or "").replace("\\", "/").strip().strip("/")
        if any(part == ".." for part in rel.split("/")):
            raise VaultError(400, "Geçersiz yol.")
        path = (self.root / rel).resolve()
        if path != self.root and not path.is_relative_to(self.root):
            raise VaultError(400, "Geçersiz yol.")
        parts = path.relative_to(self.root).parts
        if parts and parts[0] in HIDDEN_DIRS:
            raise VaultError(403, "Bu klasöre erişilemez.")
        return path

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def note_path(self, rel: str, must_exist: bool = True) -> Path:
        path = self.resolve(rel)
        if path.suffix.lower() != NOTE_SUFFIX:
            raise VaultError(400, "Sadece .md notlar açılabilir.")
        if must_exist and not path.is_file():
            raise VaultError(404, "Not bulunamadı.")
        return path

    def dir_path(self, rel: str) -> Path:
        path = self.resolve(rel)
        if not path.is_dir():
            raise VaultError(404, "Klasör bulunamadı.")
        return path

    def iter_notes(self):
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for filename in filenames:
                if filename.lower().endswith(NOTE_SUFFIX):
                    yield Path(dirpath) / filename

    # ---- listing ----
    def tree(self) -> list[dict]:
        def walk(directory: Path) -> list[dict]:
            try:
                entries = list(os.scandir(directory))
            except OSError:
                return []
            dirs = sorted((e for e in entries if e.is_dir() and not e.name.startswith(".")),
                          key=lambda e: fold(e.name))
            notes = sorted((e for e in entries if e.is_file() and e.name.lower().endswith(NOTE_SUFFIX)),
                           key=lambda e: fold(e.name))
            items = []
            for entry in dirs:
                path = Path(entry.path)
                items.append({"type": "dir", "name": entry.name, "path": self.rel(path),
                              "children": walk(path)})
            for entry in notes:
                path = Path(entry.path)
                try:
                    mtime = entry.stat().st_mtime
                except OSError:
                    mtime = 0
                items.append({"type": "note", "name": entry.name[: -len(NOTE_SUFFIX)],
                              "path": self.rel(path), "mtime": mtime})
            return items

        return walk(self.root)

    def tags(self) -> list[dict]:
        """Tag counts over the whole vault. The page asks again after saves, so
        each note's tags are kept keyed by (path, mtime, size): a note that has
        not changed since the last call is not read again. Walks with scandir
        (the same notes as iter_notes()) because on Windows a DirEntry's stat
        comes with the directory listing, so an unchanged note costs nothing."""
        known = self._tag_cache
        cache: dict[str, tuple[int, int, frozenset]] = {}
        counts: Counter = Counter()
        # a note written within the last couple of seconds may change again
        # inside the same mtime tick without changing size: never trust those
        settled = time.time_ns() - _TAG_CACHE_SETTLE_NS
        stack = [self.root]
        while stack:
            try:
                entries = list(os.scandir(stack.pop()))
            except OSError:
                continue
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if not entry.name.startswith("."):
                            stack.append(Path(entry.path))
                        continue
                    if not (entry.name.lower().endswith(NOTE_SUFFIX) and entry.is_file()):
                        continue
                    st = entry.stat()
                except OSError:
                    continue
                hit = known.get(entry.path)
                if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
                    tags = hit[2]
                else:
                    try:
                        with open(entry.path, encoding="utf-8-sig", errors="ignore") as fh:
                            tags = frozenset(note_tags(fh.read()))
                    except OSError:
                        continue
                if st.st_mtime_ns < settled:
                    cache[entry.path] = (st.st_mtime_ns, st.st_size, tags)
                counts.update(tags)
        self._tag_cache = cache
        return [{"tag": tag, "count": n} for tag, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]

    def search(self, query: str, limit: int = 30) -> list[dict]:
        query = query.strip()
        if not query:
            return []
        results = []
        if query.startswith("#") and len(query) > 1:
            wanted = query[1:].casefold()
            for path in self.iter_notes():
                try:
                    text = path.read_text(encoding="utf-8-sig", errors="ignore")
                except OSError:
                    continue
                if wanted in note_tags(text):
                    results.append({"path": self.rel(path), "name": path.stem, "snippet": f"#{wanted}"})
            return results[:limit]

        needle = fold(query)
        for path in self.iter_notes():
            try:
                text = path.read_text(encoding="utf-8-sig", errors="ignore")
            except OSError:
                continue
            idx = fold(text).find(needle)
            if idx == -1:
                continue
            start = max(0, idx - 40)
            end = min(len(text), idx + len(query) + 60)
            snippet = text[start:end].replace("\n", " ").strip()
            results.append({
                "path": self.rel(path), "name": path.stem,
                "snippet": ("…" if start else "") + snippet + ("…" if end < len(text) else ""),
            })
            if len(results) >= limit:
                break
        return results

    # ---- note io ----
    def read_note(self, rel: str) -> dict:
        path = self.note_path(rel)
        try:
            content = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            content = path.read_text(encoding="utf-8-sig", errors="replace")
        return {"path": self.rel(path), "name": path.stem, "content": content,
                "mtime": path.stat().st_mtime}

    def write_note(self, rel: str, content: str, must_exist: bool = True,
                   base_mtime: float | None = None, keep_version: bool = False) -> dict:
        """must_exist guards against resurrection: a page that still has a note
        open must not recreate it after it was trashed or renamed elsewhere (410).

        base_mtime: the version the page last read or wrote. A file changed
        since — another window, Obsidian, a sync tool — is not overwritten
        blind (409; the page asks). A file another program holds open is tried
        again, then 423. Neither ever means the note is gone: a page used to
        take any refusal for that and close the tab with its unsaved text.
        keep_version: the writer chose to overwrite a changed file — what is
        there is kept whatever the last kept copy's age."""
        path = self.note_path(rel, must_exist=False)
        if must_exist and not path.is_file():
            raise VaultError(410, "Bu not artık yok — taşınmış ya da çöpe gitmiş olabilir.")
        if not path.parent.is_dir():
            raise VaultError(404, "Klasör bulunamadı.")
        if path.is_file():
            current = self._text_of(path)
            if current == content:
                return {"path": self.rel(path), "mtime": path.stat().st_mtime}
            if base_mtime is not None and path.stat().st_mtime != base_mtime:
                raise VaultError(409, "Bu not sen yazarken başka bir yerde değişti.")
            self._keep_version(path, current, force=keep_version)
        tmp = path.with_name(f".{path.name}.tmp")
        for wait in (*LOCK_RETRY_S, None):
            try:
                with open(tmp, "w", encoding="utf-8", newline="") as fh:
                    fh.write(content)
                os.replace(tmp, path)
                break
            except PermissionError:
                # OneDrive and virus scanners hold a file for a moment
                tmp.unlink(missing_ok=True)
                if wait is None:
                    raise VaultError(423, "Dosya başka bir program tarafından kilitli; yazdıkların "
                                          "sayfada duruyor, birazdan yeniden denenecek.")
                time.sleep(wait)
        return {"path": self.rel(path), "mtime": path.stat().st_mtime}

    @staticmethod
    def _text_of(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            return path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            return ""

    def versions_dir(self, rel: str) -> Path:
        return self.meta_dir / "versions" / rel.replace("/", "__")

    def _keep_version(self, path: Path, previous: str, force: bool = False) -> None:
        """What a write replaces, kept now and then: at most one copy per
        VERSION_EVERY_S of writing, the latest VERSIONS_KEPT. Whatever
        overwrites a note — a conflict resolved the wrong way, a sync tool,
        the assistant — the text before it can be found again."""
        if not previous.strip():
            return
        folder = self.versions_dir(self.rel(path))
        try:
            kept = sorted(folder.glob("*.md")) if folder.is_dir() else []
            if kept and not force and time.time() - kept[-1].stat().st_mtime < VERSION_EVERY_S:
                return
            folder.mkdir(parents=True, exist_ok=True)
            stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
            (folder / f"{stamp}.md").write_text(previous, encoding="utf-8")
            for old in sorted(folder.glob("*.md"))[:-VERSIONS_KEPT]:
                old.unlink(missing_ok=True)
        except OSError:
            pass                    # a copy that could not be kept never blocks the save

    def versions(self, rel: str) -> list[dict]:
        folder = self.versions_dir(rel)
        if not folder.is_dir():
            return []
        return [{"id": f.stem, "size": f.stat().st_size} for f in sorted(folder.glob("*.md"), reverse=True)]

    def read_version(self, rel: str, version: str) -> str:
        if not re.fullmatch(r"\d{8}-\d{6}", version or ""):
            raise VaultError(400, "Sürüm bulunamadı.")
        path = self.versions_dir(rel) / f"{version}.md"
        if not path.is_file():
            raise VaultError(404, "Sürüm bulunamadı.")
        return self._text_of(path)

    def create_note(self, dir_rel: str, name: str, content: str = "") -> str:
        directory = self.dir_path(dir_rel)
        base = clean_name(name, note=True)
        path = directory / f"{base}{NOTE_SUFFIX}"
        n = 2
        while path.exists():
            path = directory / f"{base} {n}{NOTE_SUFFIX}"
            n += 1
        path.write_text(content, encoding="utf-8")
        return self.rel(path)

    def create_folder(self, dir_rel: str, name: str) -> str:
        directory = self.dir_path(dir_rel)
        path = directory / clean_name(name, note=False)
        if path.exists():
            raise VaultError(409, "Bu isimde bir klasör zaten var.")
        path.mkdir()
        return self.rel(path)

    def rename(self, rel: str, new_name: str) -> str:
        path = self.resolve(rel)
        if path == self.root or not path.exists():
            raise VaultError(404, "Bulunamadı.")
        if path.is_file():
            target = path.with_name(f"{clean_name(new_name, note=True)}{NOTE_SUFFIX}")
        else:
            target = path.with_name(clean_name(new_name, note=False))
        if target == path:
            return rel
        # case-only renames on Windows: target "exists" because it is the same file
        if target.exists() and not (target.resolve() == path.resolve()):
            raise VaultError(409, "Bu isimde bir öğe zaten var.")
        path.rename(target)
        self._carry_versions(rel, self.rel(target))
        return self.rel(target)

    def move(self, rel: str, dir_rel: str) -> str:
        path = self.resolve(rel)
        directory = self.dir_path(dir_rel)
        if path == self.root or not path.exists():
            raise VaultError(404, "Bulunamadı.")
        if path.is_dir() and (directory == path or directory.is_relative_to(path)):
            raise VaultError(400, "Bir klasör kendi içine taşınamaz.")
        target = directory / path.name
        if target.exists():
            raise VaultError(409, "Hedefte aynı isimde bir öğe var.")
        shutil.move(str(path), str(target))
        self._carry_versions(rel, self.rel(target))
        return self.rel(target)

    def _carry_versions(self, old_rel: str, new_rel: str) -> None:
        """A note's kept copies go with it; a folder's stay under the old names."""
        old, new = self.versions_dir(old_rel), self.versions_dir(new_rel)
        if old.is_dir() and not new.exists():
            try:
                old.rename(new)
            except OSError:
                pass

    def trash(self, rel: str) -> str:
        """Move to <vault>/.trash instead of deleting — nothing is ever lost by a misclick."""
        path = self.resolve(rel)
        if path == self.root or not path.exists():
            raise VaultError(404, "Bulunamadı.")
        self.trash_dir.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = self.trash_dir / f"{stamp} {path.name}"
        # two items trashed in the same second: a clash would overwrite the
        # first (or move the folder inside the other), so count up instead
        n = 2
        while target.exists():
            target = self.trash_dir / f"{stamp}-{n} {path.name}"
            n += 1
        shutil.move(str(path), str(target))
        return target.name

    def asset_path(self, rel: str) -> Path:
        path = self.resolve(rel)
        if path.suffix.lower() not in IMAGE_SUFFIXES or not path.is_file():
            raise VaultError(404, "Dosya bulunamadı.")
        return path
