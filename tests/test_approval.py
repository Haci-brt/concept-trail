"""Nothing reaches the note without the writer saying yes.

The assistant never writes the file itself: approving a proposal publishes an
`append_note` (or `apply_edit`) event and the editor applies it. So the gate is
tested from both sides — the file stays byte-identical until approval, and
approval is what puts the text on the wire.
"""
import asyncio

import pytest

from core import llm_client
from server.assistant import MAX_OPEN_QUESTIONS, Assistant
from server.errors import ApiError
from server.providers import ProviderRegistry
from server.store import HistoryStore, NoteStore
from server.vault import Vault

NOTE = """# Tarif Defteri

Ailemden kalan yemek tariflerini tek yerde toplamak istiyorum.

## Fotoğraflar

Her tarifin yanına bir de fotoğraf koymak isterim.
"""


class FakeBroker:
    """Records what the server would have pushed to the browser."""

    def __init__(self):
        self.sent: list[tuple[str, dict]] = []

    def publish(self, kind, payload=None):
        self.sent.append((kind, payload))

    def of(self, kind: str) -> list[dict]:
        return [payload for k, payload in self.sent if k == kind]


@pytest.fixture
def app(tmp_path):
    vault = Vault(tmp_path / "notes")
    (vault.root / "tarif.md").write_text(NOTE, encoding="utf-8")
    broker = FakeBroker()
    assistant = Assistant(vault, NoteStore(vault), HistoryStore(vault), broker,
                          ProviderRegistry(tmp_path / "providers.json"))
    return assistant, broker, vault


def note_text(vault) -> str:
    return (vault.root / "tarif.md").read_text(encoding="utf-8")


def answered_question(assistant, text="Kaç tarif toplamayı düşünüyorsun?"):
    question = assistant.notes.add_node("tarif.md", "question", text, status="open", kind="kapsam", section="")
    assistant.notes.add_node("tarif.md", "chat-user", "Yaklaşık 50 tarif, sadece kendi ailem için.",
                             parent_id=question["id"])
    return question


def propose(assistant, monkeypatch, question, text="Defter yaklaşık 50 aile tarifini toplayacak."):
    monkeypatch.setattr(llm_client, "summarize_for_note", lambda *a, **k: text)
    return asyncio.run(assistant.summarize("tarif.md", question["id"]))


# ---------------------------------------------------------------- the gate
def test_a_conclusion_is_proposed_not_written(app, monkeypatch):
    assistant, broker, vault = app
    question = answered_question(assistant)

    result = propose(assistant, monkeypatch, question)

    assert result["proposal"]["status"] == "pending"
    assert result["text"] == "Defter yaklaşık 50 aile tarifini toplayacak."
    assert note_text(vault) == NOTE                 # the file has not moved
    assert broker.of("append_note") == []           # and nothing was sent to the editor


def test_approving_is_what_sends_the_text_to_the_editor(app, monkeypatch):
    assistant, broker, vault = app
    question = answered_question(assistant)
    proposal = propose(assistant, monkeypatch, question)["proposal"]

    assistant.hud_action(proposal["id"], "approve")

    sent = broker.of("append_note")
    assert len(sent) == 1
    assert sent[0]["text"] == "Defter yaklaşık 50 aile tarifini toplayacak."
    assert assistant.history.find(proposal["id"])["status"] == "approved"
    assert assistant.notes.find_node("tarif.md", proposal["node_id"])["status"] == "approved"


def test_approving_a_conclusion_closes_the_question_it_came_from(app, monkeypatch):
    assistant, _, _ = app
    question = answered_question(assistant)
    proposal = propose(assistant, monkeypatch, question)["proposal"]

    assistant.hud_action(proposal["id"], "approve")

    assert assistant.notes.find_node("tarif.md", question["id"])["status"] == "resolved"


def test_rejecting_leaves_the_note_and_the_question_alone(app, monkeypatch):
    assistant, broker, vault = app
    question = answered_question(assistant)
    proposal = propose(assistant, monkeypatch, question)["proposal"]

    assistant.hud_action(proposal["id"], "reject")

    assert broker.of("append_note") == []
    assert note_text(vault) == NOTE
    assert assistant.history.find(proposal["id"])["status"] == "rejected"
    assert assistant.notes.find_node("tarif.md", question["id"])["status"] == "open"   # still yours to answer


def test_a_proposal_cannot_be_decided_twice(app, monkeypatch):
    assistant, broker, _ = app
    proposal = propose(assistant, monkeypatch, answered_question(assistant))["proposal"]
    assistant.hud_action(proposal["id"], "approve")

    with pytest.raises(ApiError) as err:
        assistant.hud_action(proposal["id"], "approve")

    assert err.value.status == 409
    assert len(broker.of("append_note")) == 1       # not appended a second time


def test_an_unknown_proposal_is_refused(app):
    assistant, _, _ = app
    with pytest.raises(ApiError) as err:
        assistant.hud_action("yok-boyle-bir-id", "approve")
    assert err.value.status == 404


def test_there_is_nothing_to_write_up_before_the_writer_has_answered(app, monkeypatch):
    assistant, _, _ = app
    question = assistant.notes.add_node("tarif.md", "question", "Kaç tarif?", status="open")
    monkeypatch.setattr(llm_client, "summarize_for_note", lambda *a, **k: "bir şeyler")

    with pytest.raises(ApiError) as err:
        asyncio.run(assistant.summarize("tarif.md", question["id"]))

    assert err.value.status == 400


def test_an_empty_write_up_is_not_offered(app, monkeypatch):
    assistant, broker, _ = app
    question = answered_question(assistant)
    monkeypatch.setattr(llm_client, "summarize_for_note", lambda *a, **k: "   ")

    with pytest.raises(ApiError):
        asyncio.run(assistant.summarize("tarif.md", question["id"]))
    assert broker.of("append_note") == []


# ---------------------------------------------------------------- edits
def test_an_edit_is_applied_only_after_approval(app):
    assistant, broker, vault = app
    assistant._apply_result("tarif.md", NOTE, None, {
        "type": "edit", "original": "tek yerde toplamak istiyorum",
        "replacement": "tek defterde toplamak istiyorum", "reason": "daha somut"}, [])

    node_id = assistant.notes.load("tarif.md")["nodes"][-1]["id"]
    proposal = assistant.history.find_by_node("tarif.md", node_id, "edit")
    assert proposal["status"] == "pending"
    assert broker.of("apply_edit") == []
    assert note_text(vault) == NOTE

    assistant.hud_action(proposal["id"], "approve")
    assert broker.of("apply_edit")[0]["replacement"] == "tek defterde toplamak istiyorum"


def test_an_edit_quoting_text_that_is_not_in_the_note_is_dropped(app):
    assistant, broker, _ = app
    assistant._apply_result("tarif.md", NOTE, None, {
        "type": "edit", "original": "böyle bir cümle yok", "replacement": "bir şey"}, [])

    assert assistant.notes.load("tarif.md")["nodes"] == []      # silently, no card for the user
    assert broker.of("apply_edit") == []


# ---------------------------------------------------------------- questions
def test_a_question_is_filed_with_its_kind_and_section(app):
    assistant, _, _ = app
    assistant._apply_result("tarif.md", NOTE, None, {"type": "questions", "questions": [
        {"text": "Fotoğrafları telefonla mı çekeceksin?", "kind": "derinlestirme"}]}, [])

    node = assistant.notes.open_questions("tarif.md")[0]
    assert node["kind"] == "derinlestirme"
    assert node["section"] == "Fotoğraflar"


def test_the_same_question_in_new_words_is_not_asked_again(app):
    assistant, _, _ = app
    first = {"type": "questions",
             "questions": [{"text": "Tarifleri hangi düzende sıralayacaksın?", "kind": "kapsam"}]}
    again = {"type": "questions",
             "questions": [{"text": "Sıralama düzenini tariflerde nasıl kuracaksın?", "kind": "kapsam"}]}

    assistant._apply_result("tarif.md", NOTE, None, first, [])
    assistant._apply_result("tarif.md", NOTE, None, again, assistant.notes.open_questions("tarif.md"))

    assert len(assistant.notes.open_questions("tarif.md")) == 1


def test_the_assistant_stops_asking_once_enough_questions_are_waiting(app):
    assistant, _, _ = app
    for i in range(MAX_OPEN_QUESTIONS + 2):
        assistant.notes.add_node("tarif.md", "question", f"Bekleyen soru {i}?", status="open")

    assistant._apply_result("tarif.md", NOTE, None, {"type": "questions", "questions": [
        {"text": "Bambaşka yepyeni bir konuda soru?", "kind": "ilham"}]}, [])

    assert len(assistant.notes.open_questions("tarif.md")) == MAX_OPEN_QUESTIONS + 2


def test_a_quiet_pass_records_a_check_without_bothering_anyone(app):
    assistant, broker, _ = app
    assistant._apply_result("tarif.md", NOTE, None, {"type": "net"}, [])

    assert assistant.notes.open_questions("tarif.md") == []
    assert [e["type"] for e in assistant.history.items][:1] == ["checked"]
    assert assistant.queue == []                    # nothing pops up in the HUD
