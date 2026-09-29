"""A writer who doesn't know, or asks for ideas, gets options to choose from —
never their not knowing written up as the answer (seen on DeepSeek V4 Flash:
"the user has no technical knowledge, needs guidance" offered for the note)."""
import pytest

from core import llm_client
from server.assistant import Assistant, asks_for_ideas, looks_like_question
from server.providers import ProviderRegistry
from server.store import HistoryStore, NoteStore
from server.vault import Vault

NOTE = "# İki yapay zeka\n\nİki yapay zeka aracını aynı projede çalıştırmak istiyorum: biri backend, biri frontend.\n"
OPTIONS = ("FİKİR:\n- Ortak bir API sözleşmesi: iki taraf ayrı çalışır, ama sözleşme önce yazılmalı.\n"
           "- Bir görev kuyruğu: işler sırayla dağıtılır, ama bir koordinatör gerekir.\n"
           "Bu proje için API sözleşmesini seçerdim. Hangisi sana uyar?")
UNDECIDED = ("ANLADIM\nNOT: Kullanıcı, iki aracın nasıl haberleşeceği konusunda teknik bilgiye sahip "
             "olmadığını belirtti. Bu konuda rehberliğe ihtiyaç duyuyor.")


class Broker:
    def __init__(self):
        self.events = []

    def publish(self, kind, data):
        self.events.append((kind, data))


@pytest.fixture
def assistant(tmp_path, monkeypatch):
    vault = Vault(tmp_path / "vault")
    made = Assistant(vault, NoteStore(vault), HistoryStore(vault), Broker(),
                     ProviderRegistry(path=tmp_path / "providers.json"))
    monkeypatch.setattr(made, "provider_for", lambda *a, **k: object())
    return made


def a_question(assistant):
    rel = assistant.vault.create_note("", "iki-ai", NOTE)
    return rel, assistant.notes.add_node(rel, "question", "İki araç birbiriyle nasıl haberleşecek?", status="open")


async def chat(assistant, rel, question, message):
    updates = [u async for u in assistant.chat_stream(rel, question["id"], message)]
    return next(u for u in updates if u["type"] == "done")


@pytest.mark.parametrize("message", ["hiçbir fikrim yok o konuda", "bilmiyor olmam", "senin bir önerin yokmu",
                                     "haberleşme için ne yapılabilir fikir ver",
                                     "hemen öneri gönderme. paralel çalışma için bir fikrin varmı",
                                     "Emin değilim, sen öner"])
def test_not_knowing_and_asking_for_ideas_are_heard(message):
    assert asks_for_ideas(message)


@pytest.mark.parametrize("message", ["masaüstü", "tek bir kullanıcı", "Kapının yanında.",
                                     "sistemi yerelde tutacağız", "ilkini yapalım"])
def test_an_answer_is_not_a_call_for_ideas(message):
    assert not asks_for_ideas(message) and not looks_like_question(message)


@pytest.mark.parametrize("message", ["bir fikrin varmı", "bu olur mu", "API mi kullanalım", "yardım edebilir misin"])
def test_the_question_particle_makes_a_question_even_without_a_mark(message):
    assert looks_like_question(message)


def test_the_ideas_tag_is_read_in_any_dress():
    assert llm_client.parse_chat_reply(OPTIONS)["type"] == "ideas"
    assert llm_client.parse_chat_reply("**FİKİR:** - A\n- B")["text"].startswith("- A")
    assert llm_client.parse_chat_reply("IDEAS: - A\n- B")["type"] == "ideas"


def test_the_model_is_told_when_the_writer_wants_ideas(monkeypatch):
    seen = {}

    def fake(messages, **kwargs):
        seen["system"] = messages[0]["content"]
        return OPTIONS

    monkeypatch.setattr(llm_client, "_complete", fake)
    llm_client.chat_reply([{"role": "user", "content": "bilmiyorum"}], "not", wants_ideas=True)
    assert "[BU TUR]" in seen["system"] and "FİKİR" in seen["system"]
    llm_client.chat_reply([{"role": "user", "content": "masaüstü"}], "not")
    assert "[BU TUR]" not in seen["system"]
    assert "ASLA NOT olarak yazma" in seen["system"]


@pytest.mark.anyio
async def test_i_dont_know_gets_options_and_nothing_for_the_note(assistant, monkeypatch):
    rel, question = a_question(assistant)
    calls = []

    def reply(history, note, on_chunk=None, provider=None, on_usage=None, asked=0, wants_ideas=False):
        calls.append(wants_ideas)
        return OPTIONS

    monkeypatch.setattr(llm_client, "chat_reply", reply)
    done = await chat(assistant, rel, question, "hiçbir fikrim yok o konuda")
    assert calls == [True]
    assert done["node"]["mode"] == "ideas" and "API sözleşmesi" in done["node"]["text"]
    assert not done.get("proposal") and done["understood"] is False
    assert assistant.notes.find_node(rel, question["id"])["status"] == "open"


@pytest.mark.anyio
async def test_a_write_up_of_not_knowing_is_asked_again_for_options(assistant, monkeypatch):
    rel, question = a_question(assistant)
    calls = []

    def reply(history, note, on_chunk=None, provider=None, on_usage=None, asked=0, wants_ideas=False):
        calls.append(wants_ideas)
        return OPTIONS if wants_ideas else UNDECIDED

    monkeypatch.setattr(llm_client, "chat_reply", reply)
    done = await chat(assistant, rel, question, "ama aynı anda geliştirilmesini istiyorum")
    assert calls == [False, True]
    assert done["node"]["mode"] == "ideas" and not done.get("proposal")


@pytest.mark.anyio
async def test_it_never_offers_not_knowing_for_the_note(assistant, monkeypatch):
    rel, question = a_question(assistant)
    monkeypatch.setattr(llm_client, "chat_reply", lambda *a, **k: UNDECIDED)
    done = await chat(assistant, rel, question, "bilmiyor olmam")
    assert done["node"]["mode"] == "ideas" and not done.get("proposal")
    assert not [n for n in assistant.notes.load(rel)["nodes"] if n["type"] == "summary"]


@pytest.mark.anyio
async def test_choosing_an_offered_option_is_the_decision(assistant, monkeypatch):
    rel, question = a_question(assistant)
    assistant.notes.add_node(rel, "chat-user", "bilmiyorum", parent_id=question["id"])
    assistant.notes.add_node(rel, "chat-assistant", OPTIONS[7:], parent_id=question["id"], mode="ideas")
    seen = {}

    def reply(history, note, on_chunk=None, provider=None, on_usage=None, asked=0, wants_ideas=False):
        seen["history"] = history
        return "ANLADIM\nNOT: İki araç ortak bir API sözleşmesi üzerinden haberleşecek."

    monkeypatch.setattr(llm_client, "chat_reply", reply)
    done = await chat(assistant, rel, question, "ilkini yapalım")
    assert done["understood"] is True and "API sözleşmesi" in done["proposal"]["text"]
    assert any("API sözleşmesi" in m["content"] for m in seen["history"] if m["role"] == "assistant")
