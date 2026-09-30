"""What stops the assistant stays in sight. A dead OpenRouter key used to keep
the light green all day (its model list answers anyone) while every pass
failed without a word."""
import pytest

from core import llm_client
from server.assistant import PROBLEMS, Assistant
from server.errors import ApiError
from server.providers import Provider, ProviderRegistry
from server.store import HistoryStore, NoteStore
from server.vault import Vault

OPENROUTER = Provider(id="or", label="OpenRouter", base_url="https://openrouter.ai/api", model="x",
                      api_key="k", kind="remote", health="models")


class Answer:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body or {}

    def json(self):
        return self._body


class Broker:
    def __init__(self):
        self.events = []

    def publish(self, kind, data):
        self.events.append((kind, data))


@pytest.fixture
def assistant(tmp_path):
    vault = Vault(tmp_path / "vault")
    made = Assistant(vault, NoteStore(vault), HistoryStore(vault), Broker(),
                     ProviderRegistry(path=tmp_path / "providers.json"))
    made.providers.providers["or"] = OPENROUTER
    made.providers.roles = {"analysis": ["or"], "chat": ["or"], "summary": ["or"]}
    return made


@pytest.mark.parametrize("status,body,expected", [
    (401, {}, {"up": False, "problem": "key"}),
    (402, {}, {"up": False, "problem": "credit"}),
    (200, {"data": {"limit_remaining": 0}}, {"up": False, "problem": "credit"}),
    (200, {"data": {"limit_remaining": None}}, {"up": True, "problem": None}),
    (503, {}, {"up": False, "problem": "down"}),
])
def test_openrouter_is_asked_about_the_key_not_its_model_list(monkeypatch, status, body, expected):
    asked = []

    def get(url, headers, timeout):
        asked.append(url)
        return Answer(status, body)

    monkeypatch.setattr(llm_client.requests, "get", get)
    assert llm_client.check_server(OPENROUTER) == expected
    assert asked == ["https://openrouter.ai/api/v1/key"]


def test_a_local_server_keeps_its_own_health_check(monkeypatch):
    asked = []
    monkeypatch.setattr(llm_client.requests, "get", lambda url, headers, timeout: asked.append(url) or Answer(200))
    local = Provider(id="l", label="Yerel", base_url="http://127.0.0.1:8899", kind="local", health="llama")
    assert llm_client.check_server(local)["up"] and asked == ["http://127.0.0.1:8899/health"]
    assert llm_client.is_server_up(local) is True


def test_a_refused_key_stays_on_show_until_a_call_gets_through(assistant):
    assert assistant.status()["problem"] is None
    told = assistant.note_problem(OPENROUTER, 401)
    assert told == PROBLEMS["key"]
    problem = assistant.status()["problem"]
    assert problem["kind"] == "key" and problem["provider"] == "OpenRouter"
    assert any(kind == "status" for kind, _ in assistant.broker.events)
    assert assistant.note_problem(OPENROUTER, 500) is None           # a server hiccup is not a standing problem
    assistant.budget.record(OPENROUTER, {"total_tokens": 10})         # an answer came back
    assert assistant.status()["problem"] is None


def test_a_spent_budget_is_named_not_reported_as_a_silent_model(assistant, monkeypatch):
    monkeypatch.setattr(assistant.budget, "check", lambda provider: "Bugünkü bütçe doldu.")
    assert assistant.status()["problem"] == {"kind": "budget", "message": "Bugünkü bütçe doldu.",
                                             "provider": "OpenRouter"}


@pytest.mark.anyio
async def test_a_chat_on_a_dead_key_says_so(assistant, monkeypatch):
    rel = assistant.vault.create_note("", "n", "# N\n\nBir fikir.\n")
    question = assistant.notes.add_node(rel, "question", "Kim kullanacak?", status="open")

    def refused(*args, **kwargs):
        raise llm_client.ProviderError("API anahtarı reddedildi. User not found", status=401)

    monkeypatch.setattr(llm_client, "chat_reply", refused)
    monkeypatch.setattr(assistant, "check_now", lambda *a, **k: None)
    updates = [u async for u in assistant.chat_stream(rel, question["id"], "Ailem kullanacak")]
    error = next(u for u in updates if u["type"] == "error")
    assert error["message"] == PROBLEMS["key"]
    assert assistant.status()["problem"]["kind"] == "key"


@pytest.mark.anyio
async def test_a_pass_you_asked_for_names_a_spent_budget(assistant, monkeypatch):
    rel = assistant.vault.create_note("", "n", "# N\n\nBir fikir, biraz da uzun anlatılmış bir fikir metni.\n")
    monkeypatch.setattr(type(assistant), "model_up", property(lambda self: True))

    def blocked(role, rel=None):
        raise ApiError(429, "Bugünkü bütçe doldu.")

    monkeypatch.setattr(assistant, "provider_for", blocked)
    await assistant.analyze(rel, assistant.vault.read_note(rel)["content"], force=True)
    for task in list(assistant._tasks):
        await task
    flashes = [data for kind, data in assistant.broker.events if kind == "flash"]
    assert flashes and flashes[-1]["body"] == "Bugünkü bütçe doldu."
