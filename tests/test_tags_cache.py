"""The tag list is asked for again after saves. A note that has not changed
since the last call is not read again; one that changed, appeared, moved or
went is seen on the next call, with the same counts as reading everything."""
import builtins
import os
import time
from collections import Counter

import pytest

import server.vault as vault_module
from server.vault import Vault, note_tags

OLD = time.time() - 3600          # well past the window in which a fresh write is not trusted


def write(vault, rel, text, mtime=OLD):
    path = vault.root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


def counts(vault):
    return {t["tag"]: t["count"] for t in vault.tags()}


def read_everything(vault):
    """What the list must say: every note read from scratch."""
    total = Counter()
    for path in vault.iter_notes():
        total.update(note_tags(path.read_text(encoding="utf-8-sig")))
    return dict(total)


@pytest.fixture
def opened(monkeypatch):
    """The files tags() opened, in order."""
    seen = []

    def spy(file, *args, **kwargs):
        seen.append(os.path.basename(str(file)))
        return builtins.open(file, *args, **kwargs)

    monkeypatch.setattr(vault_module, "open", spy, raising=False)
    return seen


@pytest.fixture
def vault(tmp_path):
    v = Vault(tmp_path / "kasa")
    write(v, "a.md", "---\ntags: [proje, fikir]\n---\n# A\n#mimari")
    write(v, "alt/b.md", "#proje ve `#kod` değil")
    write(v, "alt/Büyük.MD", "#Proje")
    write(v, ".trash/c.md", "#cop")                 # hidden folders do not count
    write(v, "resim.txt", "#txt")                   # nor anything but notes
    return v


def test_an_unchanged_vault_is_not_read_again(vault, opened):
    assert counts(vault) == {"proje": 3, "fikir": 1, "mimari": 1} == read_everything(vault)
    assert sorted(opened) == sorted(["a.md", "b.md", "Büyük.MD"])
    opened.clear()
    assert counts(vault) == {"proje": 3, "fikir": 1, "mimari": 1}
    assert counts(vault) == {"proje": 3, "fikir": 1, "mimari": 1}
    assert opened == []


def test_a_changed_note_is_read_again_and_only_it(vault, opened):
    counts(vault)
    opened.clear()
    write(vault, "a.md", "#yenietiket", mtime=OLD + 10)           # new time
    assert counts(vault) == {"proje": 2, "yenietiket": 1} == read_everything(vault)
    assert opened == ["a.md"]
    opened.clear()
    write(vault, "a.md", "#yenietiket #ikinci", mtime=OLD + 10)   # same time, new size
    assert counts(vault) == {"proje": 2, "yenietiket": 1, "ikinci": 1}
    assert opened == ["a.md"]


def test_notes_that_appear_move_or_go_are_seen(vault, opened):
    counts(vault)
    opened.clear()
    (vault.root / "alt" / "b.md").unlink()
    write(vault, "yeni.md", "#taze")
    os.replace(vault.root / "a.md", vault.root / "alt" / "a2.md")
    assert counts(vault) == {"proje": 2, "fikir": 1, "mimari": 1, "taze": 1} == read_everything(vault)
    assert sorted(opened) == ["a2.md", "yeni.md"]


def test_a_note_written_just_now_is_read_every_time(tmp_path, opened):
    """Two writes inside one mtime tick with the same size look identical by
    (mtime, size); a note is only trusted from the cache once it has settled."""
    vault = Vault(tmp_path / "kasa")
    path = write(vault, "a.md", "#aa", mtime=time.time())
    assert counts(vault) == {"aa": 1}
    stamp = path.stat().st_mtime_ns
    path.write_text("#bb", encoding="utf-8")
    os.utime(path, ns=(stamp, stamp))
    assert counts(vault) == {"bb": 1}
    assert opened == ["a.md", "a.md"]
