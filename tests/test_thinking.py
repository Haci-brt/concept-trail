"""The big model thinks before it answers; the answer must survive that."""
import pytest

from core import llm_client
from server.assistant import Assistant, thinking_preview
from server.providers import ProviderRegistry
from server.store import HistoryStore, NoteStore
from server.vault import Vault

# measured: every "HARİTASI" in the thinking cost the answer one letter
THOUGHT = "<think>\n[YOL HARİTASI] diyor ki Kapsam TAMAM. YOL HARİTASI: Mimari.\n</think>\n\n"


def test_an_i_with_a_dot_in_the_thinking_does_not_eat_the_answer():
    assert llm_client._strip_think(THOUGHT + "parcalar: tek uygulama") == "parcalar: tek uygulama"
    assert llm_client._strip_think("<THINK>İİİ</THINK>amac: fiş") == "amac: fiş"


def test_the_live_preview_splits_at_the_same_place():
    preview = thinking_preview(THOUGHT + "parcalar: tek uygulama", limit=None)
    assert preview == {"phase": "writing", "text": "parcalar: tek uygulama"}


def test_thinking_that_never_ends_is_no_answer():
    assert llm_client._strip_think("<think>" + "İ" * 50) == ""


# ---------------------------------------------------------------- the think budget
class Calls:
    """Stands in for _complete: the first call thinks forever, the second answers."""

    def __init__(self, answer="parcalar: tek uygulama"):
        self.answer = answer
        self.messages = []

    def __call__(self, messages, *, on_chunk=None, max_tokens=0, **kwargs):
        self.messages.append(messages)
        if len(self.messages) == 1:
            text = "<think>"
            while True:                                  # the model re-checking itself
                text += "Tekrar kontrol edeyim. "
                on_chunk(text)
        on_chunk(self.answer)
        return self.answer


@pytest.fixture
def local(tmp_path):
    return ProviderRegistry(path=tmp_path / "providers.json").get("local-chat")


def test_thinking_past_the_budget_is_handed_back_closed_to_answer_from(monkeypatch, local):
    calls = Calls()
    monkeypatch.setattr(llm_client, "_complete", calls)
    seen = []
    content = llm_client._complete_thinking_capped(
        [{"role": "user", "content": "not"}], temperature=0.3, max_tokens=2400,
        on_chunk=seen.append, provider=local)
    assert len(calls.messages) == 2
    prefill = calls.messages[1][-1]
    assert prefill["role"] == "assistant" and prefill["content"].rstrip().endswith("</think>")
    assert len(prefill["content"]) < llm_client.THINK_BUDGET_CHARS + 50
    assert llm_client._strip_think(content) == "parcalar: tek uygulama"
    assert seen[-1].endswith("parcalar: tek uygulama")        # the UI sees it answer


def test_a_remote_api_is_never_sent_a_prefill(monkeypatch, local):
    local.kind = "remote"
    sent = []
    monkeypatch.setattr(llm_client, "_complete", lambda messages, **kw: sent.append(messages) or "cevap")
    assert llm_client._complete_thinking_capped([{"role": "user", "content": "x"}], temperature=0.3,
                                                max_tokens=10, provider=local) == "cevap"
    assert len(sent) == 1


def test_a_pass_that_never_stopped_thinking_comes_back_unfinished(monkeypatch, local):
    monkeypatch.setattr(llm_client, "_complete_thinking_capped", lambda *a, **k: "<think>hâlâ düşünüyor")
    result = llm_client.ask_about_note("# Not\n\nMetin.", "Metin.", [], provider=local, mode="yazilim",
                                       roadmap="", open_decisions=["amac"])
    assert result == {"type": "unfinished"}


def test_an_unfinished_pass_does_not_ask_the_stock_question(tmp_path):
    vault = Vault(tmp_path / "vault")

    class Broker:
        events = []

        def publish(self, kind, data):
            self.events.append((kind, data))

    assistant = Assistant(vault, NoteStore(vault), HistoryStore(vault), Broker(),
                          ProviderRegistry(path=tmp_path / "providers.json"))
    rel = vault.create_note("", "harcama", "# Harcama\n\nTelefon uygulaması, ailem kullanacak.\n")
    content = vault.read_note(rel)["content"]
    assistant._apply_result(rel, content, None, {"type": "unfinished"}, [], "yazilim", quiet=True)
    assert assistant.notes.open_questions(rel) == []
    assert assistant.notes.load(rel)["analyzed_text"] == content   # the watch waits for new text
    assert Broker.events == []
