"""The app's defences: who may talk to it, which files it serves and how,
what it keeps secret, and what it does with a damaged file of its own."""
import asyncio
import json
import os
import stat
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from server import store
from server import vault as vault_module
from server.budget import Budget
from server.errors import ApiError
from server.preferences import Preferences
from server.providers import Provider, ProviderRegistry, write_private
from server.render import render
from server.store import HistoryStore, NoteStore
from server.tools import ToolSettings
from server.vault import Vault

UNEXPECTED = "Beklenmeyen bir hata oldu; işlem yapılmadı."


@pytest.fixture(autouse=True)
def fresh_notices(monkeypatch):
    """Each test sees only the damaged files it made itself."""
    monkeypatch.setattr(store, "RECOVERED", [])
    monkeypatch.setattr(store, "_notify", None)


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("FIKIR_CONFIG_DIR", str(tmp_path / "config"))
    from server.app import create_app
    from server.settings import Settings
    return create_app(Settings(vault=tmp_path / "vault", port=8765))


@pytest.fixture
def client(app):
    return TestClient(app, base_url="http://127.0.0.1:8765", headers={"X-Fikir": "1"},
                      raise_server_exceptions=False)


def set_aside_copies(path):
    return sorted(path.parent.glob(path.name + ".corrupt-*"))


# ---------------------------------------------------------------- who may ask
def test_a_foreign_host_is_turned_away(client):
    assert client.get("/api/state").status_code == 200
    assert client.get("/api/state", headers={"host": "localhost:8765"}).status_code == 200
    for host in ("evil.example", "127.0.0.1:8765.evil.example", "127.0.0.1:9999", "localhost"):
        reply = client.get("/api/state", headers={"host": host})
        assert reply.status_code == 403, host
        assert reply.json() == {"detail": "Host not allowed"}


def test_a_write_without_the_page_header_is_refused(app, tmp_path):
    bare = TestClient(app, base_url="http://127.0.0.1:8765")
    reply = bare.post("/api/notes/create", json={"dir": "", "name": "Sızma"})
    assert reply.status_code == 403 and reply.json() == {"detail": "Missing X-Fikir header"}
    assert bare.put("/api/session", json={}).status_code == 403
    assert bare.post("/api/notes/create", json={"dir": "", "name": "Sızma"},
                     headers={"X-Fikir": "0"}).status_code == 403
    assert not (tmp_path / "vault" / "Sızma.md").exists()
    assert bare.get("/api/vault/tree").status_code == 200      # reading needs no header
    ok = bare.post("/api/notes/create", json={"dir": "", "name": "Kendi"}, headers={"X-Fikir": "1"})
    assert ok.status_code == 200 and (tmp_path / "vault" / "Kendi.md").is_file()


# ---------------------------------------------------------------- vault paths
@pytest.mark.parametrize("rel", ["../dışarı.md", "a/../../dışarı.md", "..\\dışarı.md", "a\\..\\..\\x.md", ".."])
def test_a_path_cannot_climb_out_of_the_vault(tmp_path, rel):
    vault = Vault(tmp_path / "vault")
    with pytest.raises(ApiError) as caught:
        vault.resolve(rel)
    assert caught.value.status == 400


@pytest.mark.parametrize("rel", [".assistant/history.json", ".assistant", ".trash/eski.md", ".git/config",
                                 ".obsidian/app.json", "/.assistant/notes/a.md.json", ".assistant\\usage.json"])
def test_the_app_s_own_folders_are_out_of_reach(tmp_path, rel):
    vault = Vault(tmp_path / "vault")
    with pytest.raises(ApiError) as caught:
        vault.resolve(rel)
    assert caught.value.status == 403


def test_ordinary_paths_resolve_inside_the_vault(tmp_path):
    vault = Vault(tmp_path / "vault")
    assert vault.resolve("") == vault.root
    assert vault.resolve("klasör/not.md") == vault.root / "klasör" / "not.md"
    assert vault.resolve("/not.md") == vault.root / "not.md"


def test_the_endpoints_refuse_the_same_paths(client, tmp_path):
    (tmp_path / "gizli.png").write_bytes(b"\x89PNG")
    (tmp_path / "vault" / ".assistant").mkdir(parents=True, exist_ok=True)
    (tmp_path / "vault" / ".assistant" / "resim.png").write_bytes(b"\x89PNG")
    assert client.get("/api/notes", params={"path": "../dışarı.md"}).status_code == 400
    assert client.get("/api/notes", params={"path": ".assistant/history.json"}).status_code in (400, 403)
    assert client.get("/vault-file/.assistant/resim.png").status_code == 403
    assert client.get("/vault-file/..%2Fgizli.png").status_code in (400, 404)


# ---------------------------------------------------------------- framing
@pytest.mark.parametrize("url", ["/", "/hud", "/api/state", "/static/js/api.js"])
def test_no_other_site_may_frame_the_app(client, url):
    reply = client.get(url)
    assert reply.status_code == 200
    assert reply.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in reply.headers["content-security-policy"]
    assert reply.headers["cache-control"] == "no-cache"


def test_a_vault_image_is_served_sandboxed(client, tmp_path):
    vault = tmp_path / "vault"
    (vault / "çizim.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(document.cookie)</script>'
                                     '</svg>', encoding="utf-8")
    (vault / "resim.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    for name in ("çizim.svg", "resim.png"):
        reply = client.get(f"/vault-file/{name}")
        assert reply.status_code == 200
        policy = [part.strip() for part in reply.headers["content-security-policy"].split(";")]
        assert "sandbox" in policy and "frame-ancestors 'none'" in policy
        assert reply.headers["x-content-type-options"] == "nosniff"
        assert reply.headers["x-frame-options"] == "DENY"
    assert client.get("/vault-file/çizim.svg").headers["content-type"].startswith("image/svg+xml")


# ---------------------------------------------------------------- secrets
def test_the_api_key_stays_out_of_the_repr():
    provider = Provider(id="uzak", label="Uzak", base_url="https://api.example", api_key="sk-cok-gizli",
                        kind="remote", model="m")
    assert "sk-cok-gizli" not in repr(provider) and "sk-cok-gizli" not in str(provider)
    assert "uzak" in repr(provider)
    assert vars(provider)["api_key"] == "sk-cok-gizli"                # still saved
    assert provider.headers() == {"Authorization": "Bearer sk-cok-gizli"}


def test_a_key_file_is_written_whole_and_read_back(tmp_path):
    path = tmp_path / "ayar" / "providers.json"
    (tmp_path / "ayar").mkdir()
    (tmp_path / "ayar" / "providers.tmp").write_text("yarım kalmış", encoding="utf-8")  # a crashed write
    registry = ProviderRegistry(path=path)
    registry.replace({"providers": [{"id": "uzak", "base_url": "https://api.example", "kind": "remote",
                                     "health": "models", "model": "m", "api_key": "sk-geri"}],
                      "roles": {"chat": ["uzak"]}})
    assert ProviderRegistry(path=path).get("uzak").api_key == "sk-geri"
    assert not (tmp_path / "ayar" / "providers.tmp").exists()
    write_private(tmp_path / "token.json", '{"a": 1}')
    assert json.loads((tmp_path / "token.json").read_text(encoding="utf-8")) == {"a": 1}


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes; Windows keeps the profile's own ACL")
def test_key_files_are_readable_by_this_user_only(tmp_path, monkeypatch):
    modes_while_writing = []
    real_fdopen = os.fdopen

    def watching_fdopen(fd, *args, **kwargs):
        modes_while_writing.append(stat.S_IMODE(os.fstat(fd).st_mode))
        return real_fdopen(fd, *args, **kwargs)

    monkeypatch.setattr(os, "fdopen", watching_fdopen)
    old_umask = os.umask(0o022)
    try:
        providers = tmp_path / "providers.json"
        providers.write_text("{}", encoding="utf-8")
        os.chmod(providers, 0o644)                       # left readable by an older build
        leftover = tmp_path / "providers.tmp"
        leftover.write_text("", encoding="utf-8")
        os.chmod(leftover, 0o666)
        ProviderRegistry(path=providers).save()
        tokens = tmp_path / "tool-settings.json"
        ToolSettings(tokens).replace({"github_token": "ghp_gizli"})
    finally:
        os.umask(old_umask)
    assert stat.S_IMODE(providers.stat().st_mode) == 0o600
    assert stat.S_IMODE(tokens.stat().st_mode) == 0o600
    # from the moment it existed, before the key went in
    assert len(modes_while_writing) >= 2 and all(mode & 0o077 == 0 for mode in modes_while_writing)


# ---------------------------------------------------------------- damaged files
def test_a_damaged_note_state_is_set_aside_not_overwritten(tmp_path):
    vault = Vault(tmp_path / "vault")
    state_file = vault.meta_dir / "notes" / "Fikir.md.json"
    state_file.parent.mkdir(parents=True)
    state_file.write_text('{"nodes": [{"id": "q1", "text": "kurtarılacak"', encoding="utf-8")
    notes = NoteStore(vault)
    assert notes.load("Fikir.md")["nodes"] == []
    notes.add_node("Fikir.md", "question", "Yeni soru")
    [kept] = set_aside_copies(state_file)
    assert "kurtarılacak" in kept.read_text(encoding="utf-8")
    assert json.loads(state_file.read_text(encoding="utf-8"))["nodes"][0]["text"] == "Yeni soru"
    assert [n["moved_to"] for n in store.RECOVERED] == [str(kept)]


@pytest.mark.parametrize("damage", ['[{"id": "e1"', '{"bir": "sözlük"}', "\x00\xff"])
def test_a_damaged_history_is_set_aside(tmp_path, damage):
    vault = Vault(tmp_path / "vault")
    vault.meta_dir.mkdir()
    (vault.meta_dir / "history.json").write_bytes(damage.encode("latin-1"))
    history = HistoryStore(vault)
    assert history.items == []
    history.add({"id": "e2", "type": "question"})
    [kept] = set_aside_copies(vault.meta_dir / "history.json")
    assert kept.read_bytes() == damage.encode("latin-1")


def test_damaged_providers_keep_their_keys(tmp_path):
    path = tmp_path / "providers.json"
    path.write_text('{"providers": [{"id": "uzak", "api_key": "sk-kurtar"', encoding="utf-8")
    registry = ProviderRegistry(path=path)
    assert [p.id for p in registry.all()] == ["local-chat"]         # the defaults, for now
    registry.save()                                                  # the save that used to lose the key
    [kept] = set_aside_copies(path)
    assert "sk-kurtar" in kept.read_text(encoding="utf-8")
    assert len(store.RECOVERED) == 1


def test_damaged_usage_files_are_set_aside(tmp_path):
    vault = Vault(tmp_path / "vault")
    vault.meta_dir.mkdir()
    (vault.meta_dir / "usage.json").write_text("{yarım", encoding="utf-8")
    (vault.meta_dir / "usage-limits.json").write_text('{"daily_usd": 3', encoding="utf-8")
    budget = Budget(vault)
    assert budget.data["calls"] == 0 and budget.limits["daily_usd"] == 0.50
    budget.set_limits({"daily_usd": 1.0})
    assert set_aside_copies(vault.meta_dir / "usage.json")
    [kept] = set_aside_copies(vault.meta_dir / "usage-limits.json")
    assert kept.read_text(encoding="utf-8") == '{"daily_usd": 3'


def test_damaged_preferences_and_tokens_are_set_aside(tmp_path):
    prefs = tmp_path / "preferences.json"
    prefs.write_text('{"ui_language": "en"', encoding="utf-8")
    assert Preferences(prefs).data["ui_language"] == "tr"
    assert set_aside_copies(prefs)
    tokens = tmp_path / "tool-settings.json"
    tokens.write_text('{"github_token": "ghp_kurtar"', encoding="utf-8")
    assert ToolSettings(tokens).data == {}
    [kept] = set_aside_copies(tokens)
    assert "ghp_kurtar" in kept.read_text(encoding="utf-8")


def test_a_missing_or_hand_edited_file_is_not_damaged(tmp_path):
    vault = Vault(tmp_path / "vault")
    NoteStore(vault).load("yok.md")
    HistoryStore(vault)
    Budget(vault)
    ProviderRegistry(path=tmp_path / "providers.json")
    ToolSettings(tmp_path / "tool-settings.json")
    prefs = tmp_path / "preferences.json"
    assert Preferences(prefs).data["ui_language"] == "tr"
    prefs.write_bytes(b"\xef\xbb\xbf" + json.dumps({"ui_language": "en"}).encode())   # Notepad's BOM
    assert Preferences(prefs).data["ui_language"] == "en"
    assert store.RECOVERED == []
    assert not list(tmp_path.rglob("*.corrupt-*"))


def test_two_damaged_copies_in_one_second_both_survive(tmp_path):
    path = tmp_path / "preferences.json"
    for text in ("{bir", "{iki"):
        path.write_text(text, encoding="utf-8")
        Preferences(path)
    assert sorted(p.read_text(encoding="utf-8") for p in set_aside_copies(path)) == ["{bir", "{iki"]


def test_each_page_is_told_once_and_a_late_reload_is_not(tmp_path):
    path = tmp_path / "preferences.json"
    path.write_text("{", encoding="utf-8")
    Preferences(path)
    assert [n["file"] for n in store.notices_to_tell()] == [str(path)]
    assert len(store.notices_to_tell()) == 1               # the HUD, a moment after the window
    assert store.notices_to_tell(window=0) == []           # a reload later on


def _events_until(app, marker: bytes, timeout: float = 10.0) -> str:
    """Read the page's event stream until `marker` arrives, then hang up."""
    async def run():
        body, seen = bytearray(), asyncio.Event()

        async def receive():
            await seen.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.body":
                body.extend(message.get("body", b""))
                if marker in body:
                    seen.set()

        scope = {"type": "http", "method": "GET", "path": "/api/events", "raw_path": b"/api/events",
                 "root_path": "", "query_string": b"", "http_version": "1.1", "scheme": "http",
                 "headers": [(b"host", b"127.0.0.1:8765")], "server": ("127.0.0.1", 8765),
                 "client": ("127.0.0.1", 50000)}
        task = asyncio.create_task(app(scope, receive, send))
        try:
            await asyncio.wait_for(seen.wait(), timeout)
        finally:
            seen.set()
            await asyncio.wait_for(task, 5)
        return body.decode("utf-8")

    return asyncio.run(run())


def test_the_page_hears_about_a_damaged_file_as_a_flash(tmp_path, monkeypatch):
    config = tmp_path / "config" / "ConceptTrail"
    config.mkdir(parents=True)
    (config / "preferences.json").write_text("{bozuk", encoding="utf-8")
    monkeypatch.setenv("FIKIR_CONFIG_DIR", str(tmp_path / "config"))
    from server.app import create_app
    from server.settings import Settings
    app = create_app(Settings(vault=tmp_path / "vault", port=8765))
    stream = _events_until(app, b"event: flash")
    data = json.loads(stream.split("event: flash\ndata: ", 1)[1].split("\n", 1)[0])
    assert data["kind"] == "error" and data["title"] == "Bozuk dosya kenara alındı"
    assert data["body"].startswith("preferences.json okunamadı; preferences.json.corrupt-")
    assert data["body"].endswith("adıyla saklandı, varsayılanlarla devam ediliyor.")
    assert "event: snapshot" in stream.split("event: flash")[0]


# ---------------------------------------------------------------- trash
def test_two_items_trashed_in_one_second_both_survive(tmp_path, monkeypatch):
    class OneSecond(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 30, 12, 0, 0)

    monkeypatch.setattr(vault_module, "datetime", OneSecond)
    vault = Vault(tmp_path / "vault")
    names = []
    for text in ("birinci", "ikinci", "üçüncü"):
        (vault.root / "Not.md").write_text(text, encoding="utf-8")
        names.append(vault.trash("Not.md"))
    for _ in range(2):
        (vault.root / "Klasör").mkdir()
        (vault.root / "Klasör" / "iç.md").write_text("iç", encoding="utf-8")
        names.append(vault.trash("Klasör"))
    assert len(set(names)) == 5
    assert sorted((vault.trash_dir / n).read_text(encoding="utf-8") for n in names[:3]) == \
        ["birinci", "ikinci", "üçüncü"]
    for name in names[3:]:
        assert (vault.trash_dir / name / "iç.md").is_file()     # side by side, not one inside the other
    assert names[0] == "20260930-120000 Not.md"


# ---------------------------------------------------------------- errors
def test_an_unexpected_error_is_a_sentence_not_a_traceback(client, monkeypatch):
    def broken(self):
        raise RuntimeError("C:\\Users\\gizli\\yol iç ayrıntı")

    monkeypatch.setattr(Vault, "tags", broken)
    reply = client.get("/api/vault/tags")
    assert reply.status_code == 500
    assert reply.headers["content-type"].startswith("application/json")
    assert reply.json() == {"detail": UNEXPECTED}
    assert "gizli" not in reply.text and "Traceback" not in reply.text
    assert reply.headers["x-frame-options"] == "DENY"


def test_known_errors_keep_their_own_status(client):
    assert client.post("/api/providers/bind", json={"role": "yok", "providers": []}).json() == \
        {"detail": "Bilinmeyen görev: yok"}
    assert client.post("/api/assistant/chat", json={}).status_code == 422
    assert client.get("/api/notes", params={"path": "yok.md"}).status_code == 404


@pytest.mark.parametrize("limits", [{"daily_usd": "çok"}, {"daily_calls": "1.5"}, {"daily_usd": "1e999"},
                                    {"daily_tokens": None}, ["daily_usd"]])
def test_bad_usage_limits_are_a_400(client, limits):
    before = client.get("/api/usage").json()["limits"]
    reply = client.put("/api/usage/limits", json=limits)
    assert reply.status_code == 400
    assert reply.json()["detail"] in ("Kullanım sınırları sayı olmalı.", "Geçersiz sınır verisi.")
    assert client.get("/api/usage").json()["limits"] == before
    assert client.put("/api/usage/limits", json={"daily_usd": "2.5", "daily_calls": 10}).json()["limits"]["daily_usd"] == 2.5


@pytest.mark.parametrize("timeout", ["çabuk", -5, "nan", "inf", [1]])
def test_a_bad_provider_timeout_is_a_400(client, timeout):
    reply = client.put("/api/providers", json={
        "providers": [{"id": "yerel", "base_url": "http://127.0.0.1:8899", "timeout": timeout}], "roles": {}})
    assert reply.status_code == 400
    assert reply.json()["detail"] == "“yerel” için zaman aşımı sıfırdan büyük bir sayı (saniye) olmalı."


def test_a_good_provider_timeout_is_kept(tmp_path):
    registry = ProviderRegistry(path=tmp_path / "providers.json")
    registry.replace({"providers": [{"id": "yerel", "base_url": "http://127.0.0.1:8899", "timeout": "45"}]})
    assert registry.get("yerel").timeout == 45.0
    registry.replace({"providers": [{"id": "yerel", "base_url": "http://127.0.0.1:8899"}]})
    assert registry.get("yerel").timeout == 120.0


# ---------------------------------------------------------------- the preview
def test_raw_html_in_a_note_is_shown_not_run():
    out = render('<script>alert(1)</script>\n\nMetin <img src=x onerror="alert(1)"> ve '
                 '<b onclick="x()">kalın</b>\n\n<iframe src="https://evil.example"></iframe>\n\n'
                 "[bağ](javascript:alert(1)) ![r](javascript:alert(2))", "a.md")["html"]
    for tag in ("<script", "<img src=x", "<b ", "<iframe"):
        assert tag not in out, tag
    assert "&lt;script&gt;" in out and "&lt;b onclick" in out and "&lt;iframe" in out
    assert 'href="javascript:' not in out and 'src="javascript:' not in out


def test_frontmatter_html_is_not_rendered():
    out = render("---\nbaşlık: <script>x</script>\n---\n# Başlık\n")
    assert "<script" not in out["html"] and out["meta"]["başlık"] == "<script>x</script>"
