"""Snapshots: what gets kept, what gets skipped, and what "geri al" restores."""
import time

import pytest

from server.vault import Vault, VaultError
from server.versions import KEEP_PER_NOTE, Versions


@pytest.fixture
def versions(tmp_path):
    vault = Vault(tmp_path / "notes")
    (vault.root / "rota.md").write_text("ilk hâli", encoding="utf-8")
    return Versions(vault)


# ---------------------------------------------------------------- what is kept
def test_the_first_snapshot_of_a_note_is_always_kept(versions):
    assert versions.save("rota.md", "ilk hâli", "yazma")["reason"] == "yazma"


def test_the_same_text_twice_is_not_kept_twice(versions):
    versions.save("rota.md", "aynı metin", "asistan")
    assert versions.save("rota.md", "aynı metin", "asistan") is None


def test_ordinary_typing_does_not_snapshot_on_every_keystroke(versions):
    versions.save("rota.md", "bir", "yazma")
    assert versions.save("rota.md", "bir iki", "yazma") is None      # same writing session
    assert len(versions.list("rota.md")) == 1


def test_an_assistant_write_is_always_kept_however_recent(versions):
    versions.save("rota.md", "bir", "yazma")
    assert versions.save("rota.md", "bir iki", "asistan") is not None
    assert versions.save("rota.md", "bir iki üç", "duzenleme") is not None
    assert versions.save("rota.md", "bir iki üç dört", "geri") is not None


def test_nothing_is_kept_for_an_empty_note(versions):
    assert versions.save("rota.md", "", "asistan") is None
    assert versions.save("rota.md", None, "asistan") is None


def test_an_unknown_reason_is_filed_as_ordinary_writing(versions):
    assert versions.save("rota.md", "bir şey", "uydurma")["reason"] == "yazma"


# ---------------------------------------------------------------- order and pruning
def test_the_newest_snapshot_comes_first_even_within_the_same_second(versions):
    # you save, the assistant appends: both land in the same second
    versions.save("rota.md", "senin yazdığın", "yazma")
    versions.save("rota.md", "senin yazdığın + asistanınki", "asistan")
    assert [v["reason"] for v in versions.list("rota.md")] == ["asistan", "yazma"]


def test_only_the_most_recent_snapshots_are_kept(versions):
    for i in range(KEEP_PER_NOTE + 5):
        versions.save("rota.md", f"{i}. hâli", "asistan")
    kept = versions.list("rota.md")
    assert len(kept) == KEEP_PER_NOTE
    assert versions.read("rota.md", kept[0]["id"]) == f"{KEEP_PER_NOTE + 4}. hâli"


# ---------------------------------------------------------------- reading back
def test_a_snapshot_reads_back_exactly(versions):
    text = "# Başlık\n\nÜçüncü satırda ş, ı, ğ var.\n"
    saved = versions.save("rota.md", text, "asistan")
    assert versions.read("rota.md", saved["id"]) == text


@pytest.mark.parametrize("bad", ["../../../gizli", "20260101-000000-asistan/../x", "", "rastgele"])
def test_a_made_up_version_id_is_refused(versions, bad):
    versions.save("rota.md", "bir şey", "asistan")
    with pytest.raises(VaultError):
        versions.read("rota.md", bad)


def test_a_note_with_no_history_lists_nothing(versions):
    assert versions.list("rota.md") == []


def test_snapshots_cannot_be_asked_for_outside_the_vault(versions):
    with pytest.raises(VaultError):
        versions.list("../../gizli.md")


# ---------------------------------------------------------------- following the note
def test_renaming_a_note_takes_its_history_along(versions):
    versions.save("rota.md", "eski metin", "asistan")
    versions.moved("rota.md", "rota-2.md")
    assert len(versions.list("rota-2.md")) == 1
    assert versions.list("rota.md") == []


def test_moving_a_whole_folder_takes_the_history_along(versions):
    versions.save("fikirler/rota.md", "klasördeki not", "asistan")
    versions.moved("fikirler", "arsiv")
    assert len(versions.list("arsiv/rota.md")) == 1


def test_a_trashed_note_leaves_a_clean_slate_but_keeps_its_snapshots(versions):
    versions.save("rota.md", "silinmeden önceki metin", "asistan")
    versions.trashed("rota.md")

    assert versions.list("rota.md") == []          # a new note with this name starts fresh
    leftovers = list(versions.dir.glob("* (silindi *)/*.md"))
    assert len(leftovers) == 1                     # but the old text is still on disk
    assert leftovers[0].read_text(encoding="utf-8") == "silinmeden önceki metin"


def test_snapshots_live_in_the_vaults_own_metadata_folder(versions):
    saved = versions.save("rota.md", "bir metin", "asistan")
    assert saved is not None
    assert versions.dir == versions.vault.meta_dir / "versions"
    assert (versions.dir / "rota" / f"{saved['id']}.md").is_file()


def test_a_write_that_cannot_be_snapshotted_does_not_raise(versions, monkeypatch):
    # the safety net must never be the thing that breaks saving
    def boom(*a, **k):
        raise OSError("disk dolu")

    monkeypatch.setattr("pathlib.Path.mkdir", boom)
    assert versions.save("rota.md", "bir metin", "asistan") is None


def test_a_later_writing_session_gets_its_own_snapshot(versions, monkeypatch):
    versions.save("rota.md", "bir", "yazma")
    an_hour_later = time.time() + 3600
    monkeypatch.setattr(time, "time", lambda: an_hour_later)
    assert versions.save("rota.md", "çok sonra yazılan", "yazma") is not None
