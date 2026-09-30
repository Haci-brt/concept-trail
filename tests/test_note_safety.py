"""Saving never costs the writer text: a locked file is tried again, a note
changed elsewhere is not overwritten blind, a gone note is told apart from
both, and what an overwrite replaces is kept as an earlier version."""
import os
import time

import pytest
from fastapi.testclient import TestClient

from server import vault as vault_module
from server.errors import ApiError
from server.vault import Vault


@pytest.fixture
def vault(tmp_path):
    made = Vault(tmp_path / "kasa")
    made.create_note("", "fikir", "# Fikir\n\nİlk hali.\n")
    return made


def mtime(vault):
    return vault.read_note("fikir.md")["mtime"]


def test_a_note_changed_elsewhere_is_not_overwritten_blind(vault):
    seen = mtime(vault)
    time.sleep(0.02)
    (vault.root / "fikir.md").write_text("# Fikir\n\nObsidian'da değişti.\n", encoding="utf-8")
    with pytest.raises(ApiError) as refused:
        vault.write_note("fikir.md", "# Fikir\n\nBenim yazdığım.\n", base_mtime=seen)
    assert refused.value.status == 409
    assert "Obsidian" in vault.read_note("fikir.md")["content"]
    # the same text is no conflict, and the page's own version saves as before
    now = mtime(vault)
    assert vault.write_note("fikir.md", "# Fikir\n\nObsidian'da değişti.\n", base_mtime=seen)["mtime"] == now
    vault.write_note("fikir.md", "# Fikir\n\nBenim yazdığım.\n", base_mtime=now)
    assert "Benim" in vault.read_note("fikir.md")["content"]


def test_a_gone_note_is_not_a_locked_one(vault, monkeypatch):
    os.remove(vault.root / "fikir.md")
    with pytest.raises(ApiError) as gone:
        vault.write_note("fikir.md", "metin")
    assert gone.value.status == 410

    vault.create_note("", "fikir", "eski")
    monkeypatch.setattr(vault_module, "LOCK_RETRY_S", (0, 0))
    real = os.replace
    monkeypatch.setattr(vault_module.os, "replace", lambda *a: (_ for _ in ()).throw(PermissionError()))
    with pytest.raises(ApiError) as locked:
        vault.write_note("fikir.md", "yeni")
    assert locked.value.status == 423 and vault.read_note("fikir.md")["content"] == "eski"
    assert not list(vault.root.glob(".*.tmp"))

    # held for a moment only: the retry gets through
    tries = []

    def busy_once(src, dst):
        tries.append(1)
        if len(tries) == 1:
            raise PermissionError()
        return real(src, dst)

    monkeypatch.setattr(vault_module.os, "replace", busy_once)
    vault.write_note("fikir.md", "yeni")
    assert vault.read_note("fikir.md")["content"] == "yeni" and len(tries) == 2


def test_what_an_overwrite_replaces_is_kept_now_and_then(vault):
    vault.write_note("fikir.md", "ikinci")
    vault.write_note("fikir.md", "üçüncü")                     # within ten minutes: no second copy
    kept = vault.versions("fikir.md")
    assert len(kept) == 1 and vault.read_version("fikir.md", kept[0]["id"]).startswith("# Fikir")
    time.sleep(1.1)
    vault.write_note("fikir.md", "dördüncü", keep_version=True)  # the writer overwrote a change: always kept
    assert [vault.read_version("fikir.md", v["id"]) for v in vault.versions("fikir.md")][0] == "üçüncü"
    with pytest.raises(ApiError):
        vault.read_version("fikir.md", "../../fikir")


def test_only_the_latest_versions_stay(vault, monkeypatch):
    monkeypatch.setattr(vault_module, "VERSION_EVERY_S", 0)
    monkeypatch.setattr(vault_module, "VERSIONS_KEPT", 3)
    folder = vault.versions_dir("fikir.md")
    for i in range(6):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"2026010{i}-000000.md").write_text(f"eski {i}", encoding="utf-8")
    vault.write_note("fikir.md", "yeni")
    assert len(vault.versions("fikir.md")) == 3


def test_versions_go_with_a_renamed_or_moved_note(vault):
    vault.write_note("fikir.md", "ikinci")
    renamed = vault.rename("fikir.md", "proje")
    assert len(vault.versions(renamed)) == 1 and not vault.versions("fikir.md")
    vault.create_folder("", "arsiv")
    moved = vault.move(renamed, "arsiv")
    assert len(vault.versions(moved)) == 1


def test_the_api_passes_the_version_and_lists_earlier_ones(tmp_path, monkeypatch):
    monkeypatch.setenv("FIKIR_CONFIG_DIR", str(tmp_path / "ayar"))
    from server.app import create_app
    from server.settings import Settings

    app = create_app(Settings(vault=tmp_path / "kasa", port=8765))
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        headers = {"X-Fikir": "1"}
        rel = client.post("/api/notes/create", json={"dir": "", "name": "n", "content": "bir"}, headers=headers).json()["path"]
        seen = client.get("/api/notes", params={"path": rel}).json()["mtime"]
        time.sleep(0.02)
        client.put("/api/notes", json={"path": rel, "content": "iki", "base_mtime": seen}, headers=headers)
        stale = client.put("/api/notes", json={"path": rel, "content": "üç", "base_mtime": seen}, headers=headers)
        assert stale.status_code == 409
        versions = client.get("/api/notes/versions", params={"path": rel}).json()
        assert client.get("/api/notes/version", params={"path": rel, "id": versions[0]["id"]}).json()["content"] == "bir"
