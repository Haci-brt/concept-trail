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


def test_key_format_identifies_only_distinct_prefixes_and_routes_safely():
    assert setup.identify_key("sk-or-v1-example")[1] == "OpenRouter"
    assert setup.identify_key("gsk_example")[1] == "Groq"
    assert setup.identify_key("xai-example")[1] == "xAI"
    assert setup.identify_key("sk-proj-example")[1] == "OpenAI"
    assert setup.identify_key("sk-svcacct-example")[1] == "OpenAI"
    assert setup.identify_key("AQ.example")[1] == "Google Gemini"
    assert setup.identify_key("AIza-example") is None  # Google keys are not Gemini-specific
    assert setup.identify_key("sk-something-else") is None
    assert setup.identify_key("opaque-token") is None

    groq = setup.build({"preset": "custom", "api_key": "gsk_example"})
    assert (groq.label, groq.base_url, groq.model) == \
        ("Groq", "https://api.groq.com/openai", "llama-3.3-70b-versatile")

    with pytest.raises(ApiError, match="Groq"):
        setup.build({"preset": "openrouter", "api_key": "gsk_example"})
    with pytest.raises(ApiError, match="Groq"):
        setup.build({"preset": "custom", "base_url": "https://api.openai.com", "model": "m",
                     "api_key": "gsk_example"})


def test_gemini_uses_googles_openai_compatibility_paths():
    gemini = setup.build({"preset": "gemini", "api_key": "AQ.example"})
    assert gemini.model == "gemini-3.5-flash-lite"
    assert gemini.kind == "remote"
    assert gemini.tools is True
    assert gemini.chat_url == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert gemini.health_url == "https://generativelanguage.googleapis.com/v1beta/openai/models"
    assert gemini.headers() == {"Authorization": "Bearer AQ.example"}
    assert setup.build({"preset": "gemini", "api_key": "AIza-example"}).id == "gemini"
    assert setup.build({"preset": "custom", "api_key": "AQ.example"}).base_url == gemini.base_url
    with pytest.raises(ApiError, match="Gemini anahtarını"):
        setup.build({"preset": "gemini"})
    with pytest.raises(ApiError, match="OpenRouter"):
        setup.build({"preset": "gemini", "api_key": "sk-or-v1-example"})
    with pytest.raises(ApiError, match="Google Gemini"):
        setup.build({"preset": "custom", "api_key": "AQ.example", "base_url": "https://api.openai.com"})
    with pytest.raises(ApiError, match="Google Gemini"):
        setup.build({"preset": "custom", "api_key": "AQ.example",
                     "base_url": "https://generativelanguage.googleapis.com"})

    ordinary = setup.build({"preset": "openrouter", "api_key": "plain-key"})
    assert ordinary.chat_url == "https://openrouter.ai/api/v1/chat/completions"
    assert ordinary.health_url == "https://openrouter.ai/api/v1/models"


def test_gemini_probe_posts_to_google_and_requires_visible_text(monkeypatch):
    sent = []

    class Response:
        ok = True

        def __init__(self, content):
            self.content = content

        def json(self):
            return {"choices": [{"message": {"content": self.content}}]}

    answer = "tamam"

    def post(url, **kwargs):
        sent.append((url, kwargs))
        return Response(answer)

    monkeypatch.setattr(llm_client.requests, "post", post)
    gemini = setup.build({"preset": "gemini", "api_key": "AQ.example"})
    assert llm_client.probe(gemini) == "tamam"
    assert sent[0][0] == gemini.chat_url
    assert sent[0][1]["json"]["model"] == gemini.model
    assert sent[0][1]["json"]["max_tokens"] == 128
    assert sent[0][1]["json"]["reasoning_effort"] == "low"
    assert sent[0][1]["headers"] == {"Authorization": "Bearer AQ.example"}

    answer = ""
    with pytest.raises(llm_client.ProviderError, match="boş yanıt"):
        llm_client.probe(gemini)


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
    gemini = setup.build({"preset": "gemini", "api_key": "AQ.example"})
    assert "Google AI Studio" in setup.friendly(llm_client.ProviderError("x", status=402), gemini)
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


def test_identified_key_is_not_probed_against_another_provider(client, monkeypatch):
    calls = []
    monkeypatch.setattr(llm_client, "probe", lambda *args, **kwargs: calls.append(args))
    reply = client.post("/api/setup/connect", json={"preset": "custom", "base_url": "https://api.openai.com",
                                                     "model": "gpt-4o-mini", "api_key": "gsk_example"})
    assert reply.status_code == 400
    assert "Groq" in reply.json()["detail"]
    assert calls == []


def test_gemini_setup_installs_the_verified_provider(client, monkeypatch):
    seen = []

    def probe(provider, timeout=30.0):
        seen.append(provider)
        return "tamam"

    monkeypatch.setattr(llm_client, "probe", probe)
    reply = client.post("/api/setup/connect", json={"preset": "gemini", "api_key": "AQ.example"})
    assert reply.status_code == 200
    assert reply.json()["provider"] == "gemini"
    assert seen[0].chat_url == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    saved = client.get("/api/providers").json()
    gemini = next(p for p in saved["providers"] if p["id"] == "gemini")
    assert gemini["model"] == "gemini-3.5-flash-lite"
    assert gemini["has_key"] and "AQ.example" not in str(saved)
    assert saved["roles"]["chat"][0] == "gemini"


def test_the_wizard_put_aside_stays_aside(client):
    assert client.get("/api/setup").json()["dismissed"] is False
    client.post("/api/setup/dismiss")
    assert client.get("/api/setup").json()["dismissed"] is True
