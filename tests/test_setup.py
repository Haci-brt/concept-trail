"""First start: connecting the assistant to a model without knowing where Settings is."""
import pytest
from fastapi.testclient import TestClient

from core import llm_client
from server import setup
from server.errors import ApiError
from server.preferences import Preferences
from server.providers import ProviderRegistry


@pytest.fixture
def registry(tmp_path):
    return ProviderRegistry(path=tmp_path / "providers.json")


def test_a_fresh_install_needs_a_model(registry):
    """The default llama-server at 127.0.0.1:8899 is only on the machine this was built on."""
    assert setup.status(registry, False)["needed"] is True
    registry.set_health("local-chat", True)                  # but if it does answer here, it is enough
    assert setup.status(registry, False)["needed"] is False


def test_a_remote_provider_with_a_key_is_enough(registry):
    setup.install(registry, setup.build({"preset": "openrouter", "api_key": "sk-or-test"}))
    assert setup.status(registry, True) == {**setup.status(registry, True), "needed": False, "dismissed": True}


def test_the_three_ways_in_are_built_and_checked():
    openrouter = setup.build({"preset": "openrouter", "api_key": " sk-or-1 "})
    assert (openrouter.base_url, openrouter.model, openrouter.api_key, openrouter.kind) == \
        ("https://openrouter.ai/api", "openai/gpt-4o-mini", "sk-or-1", "remote")
    with pytest.raises(ApiError, match="anahtar"):
        setup.build({"preset": "openrouter"})

    ollama = setup.build({"preset": "local", "id": "ollama", "label": "Ollama", "health": "models",
                          "base_url": "http://127.0.0.1:11434/v1", "model": "qwen2.5:7b"})
    assert (ollama.base_url, ollama.kind, ollama.model, ollama.health) == \
        ("http://127.0.0.1:11434", "local", "qwen2.5:7b", "models")      # the /v1 is the chat path's
    with pytest.raises(ApiError, match="127.0.0.1"):
        setup.build({"preset": "local", "base_url": "http://192.168.1.5:11434"})

    custom = setup.build({"preset": "custom", "base_url": "https://api.openai.com", "api_key": "k",
                          "model": "gpt-4o-mini"})
    assert custom.kind == "remote" and custom.api_key == "k"
    with pytest.raises(ApiError, match="https"):
        setup.build({"preset": "custom", "base_url": "http://api.example.com", "api_key": "k", "model": "m"})
    with pytest.raises(ApiError, match="anahtar"):
        setup.build({"preset": "custom", "base_url": "https://api.example.com", "model": "m"})
    with pytest.raises(ApiError, match="Model"):
        setup.build({"preset": "custom", "base_url": "https://api.example.com", "api_key": "k"})


def test_a_new_provider_does_every_job_and_the_old_ones_stay_behind_it(registry):
    registry.replace({"providers": [{"id": "or-old", "label": "Eski", "base_url": "https://x.example", "kind": "remote",
                                     "health": "none", "model": "m", "api_key": "old-secret"}],
                      "roles": {"analysis": ["or-old"], "chat": ["or-old"], "summary": ["or-old"]}})
    setup.install(registry, setup.build({"preset": "openrouter", "api_key": "new-secret"}))
    public = registry.public()
    assert all(chain[0] == "openrouter" and "or-old" in chain for chain in public["roles"].values())
    assert registry.get("or-old").api_key == "old-secret"           # the other key is not lost
    assert registry.get("openrouter").api_key == "new-secret"
    assert "new-secret" not in str(public)                           # nor shown


class Reply:
    def __init__(self, status, data=None):
        self.status_code, self._data = status, data

    def json(self):
        return self._data


def test_models_running_here_are_found_with_their_models():
    def get(url):
        if url.startswith("http://127.0.0.1:11434"):
            return Reply(200, {"data": [{"id": "qwen2.5:7b"}, {"id": "llama3.2"}]})
        if url.startswith("http://127.0.0.1:1234"):
            return Reply(404)
        raise ConnectionError("refused")

    found = setup.detect(get)
    assert found == [{"id": "ollama", "label": "Ollama", "base_url": "http://127.0.0.1:11434", "health": "models",
                      "models": ["qwen2.5:7b", "llama3.2"]}]


def test_what_went_wrong_is_said_in_words():
    provider = setup.build({"preset": "openrouter", "api_key": "k", "model": "yok/boyle-model"})
    assert "Anahtar kabul edilmedi" in setup.friendly(llm_client.ProviderError("x", status=401), provider)
    assert "kredi" in setup.friendly(llm_client.ProviderError("x", status=402), provider)
    assert "yok/boyle-model" in setup.friendly(llm_client.ProviderError("x", status=404), provider)
    local = setup.build({"preset": "local", "base_url": "http://127.0.0.1:11434", "model": "m"})
    assert "ulaşılamadı" in setup.friendly(ConnectionError("Connection refused"), local)


def test_putting_the_wizard_aside_is_remembered(tmp_path):
    prefs = Preferences(tmp_path / "preferences.json")
    assert prefs.data["setup_dismissed"] is False
    prefs.update({"setup_dismissed": True})
    assert Preferences(tmp_path / "preferences.json").data["setup_dismissed"] is True
    with pytest.raises(ApiError):
        prefs.update({"setup_dismissed": "evet"})


# ---------------------------------------------------------------- the endpoints
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FIKIR_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(llm_client, "is_server_up", lambda provider=None, timeout=2.0: False)
    from server.app import create_app
    from server.settings import Settings
    # the app answers only to its own address, and writes only with the page's own header
    return TestClient(create_app(Settings(vault=tmp_path / "vault", port=8765)), base_url="http://127.0.0.1:8765",
                      headers={"X-Fikir": "1"})


def test_nothing_is_saved_until_the_model_answers(client, monkeypatch):
    assert client.get("/api/setup").json()["needed"] is True

    def refuse(provider, timeout=30.0):
        raise llm_client.ProviderError("API anahtarı reddedildi.", status=401)

    monkeypatch.setattr(llm_client, "probe", refuse)
    reply = client.post("/api/setup/connect", json={"preset": "openrouter", "api_key": "wrong"}).json()
    assert reply["ok"] is False and "Anahtar kabul edilmedi" in reply["error"]
    assert "openrouter" not in {p["id"] for p in client.get("/api/providers").json()["providers"]}

    monkeypatch.setattr(llm_client, "probe", lambda provider, timeout=30.0: "tamam")
    reply = client.post("/api/setup/connect", json={"preset": "openrouter", "api_key": "right"}).json()
    assert reply["ok"] is True and reply["model"] == "openai/gpt-4o-mini" and reply["remote"] is True
    providers = client.get("/api/providers").json()
    assert providers["roles"]["chat"][0] == "openrouter" and providers["roles"]["master"][0] == "openrouter"
    assert client.get("/api/setup").json()["needed"] is False


def test_the_wizard_put_aside_stays_aside(client):
    assert client.get("/api/setup").json()["dismissed"] is False
    client.post("/api/setup/dismiss")
    assert client.get("/api/setup").json()["dismissed"] is True
