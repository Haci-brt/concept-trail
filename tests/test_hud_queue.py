"""The assistant card's line: "Sonraki" passes an item over without losing it,
and an answered question does not stay on the card as if it were not."""
import pytest

from server.assistant import Assistant
from server.providers import ProviderRegistry
from server.store import HistoryStore, NoteStore
from server.vault import Vault


class Broker:
    def __init__(self):
        self.events = []

    def publish(self, kind, data):
        self.events.append((kind, data))


@pytest.fixture
def assistant(tmp_path):
    vault = Vault(tmp_path / "vault")
    return Assistant(vault, NoteStore(vault), HistoryStore(vault), Broker(),
                     ProviderRegistry(path=tmp_path / "providers.json"))


QUESTIONS = ["Bunu kim kullanacak?", "Hangi platformda çalışacak?", "Veriler nerede duracak?"]


def asked(assistant) -> str:
    """A note the assistant has just put three questions on the card about."""
    rel = assistant.vault.create_note("", "bitki", "# Bitki\n\nSulamayı unutuyorum.")
    content = assistant.vault.read_note(rel)["content"]
    assistant._apply_result(rel, content, None,
                            {"type": "questions", "questions": [{"text": q} for q in QUESTIONS]}, [])
    return rel


def shown(assistant) -> tuple[str, int]:
    hud = assistant.hud()
    return hud["event"]["text"], hud["remaining"]


def next_(assistant):
    assistant.hud_action(assistant.hud()["event"]["id"], "next")


def test_next_goes_round_the_line_and_loses_nothing(assistant):
    asked(assistant)
    seen = []
    for _ in range(len(QUESTIONS) + 1):
        seen.append(shown(assistant))
        next_(assistant)
    assert [text for text, _ in seen] == QUESTIONS + QUESTIONS[:1]
    assert {remaining for _, remaining in seen} == {2}               # the count never shrinks by looking
    assert assistant.broker.events[-1] == ("hud", assistant.hud())


def test_next_on_the_last_one_keeps_it(assistant):
    rel = assistant.vault.create_note("", "tek", "# Tek\n\nBir cümle.")
    proposal = assistant.propose_text(rel, "Tek öneri.")["proposal"]
    assistant.hud_action(proposal["id"], "next")
    assert assistant.hud() == {"event": proposal, "remaining": 0}


def test_an_answer_puts_its_proposal_where_the_question_stood(assistant):
    rel = asked(assistant)
    first = assistant.hud()["event"]
    # what the chat does once it understood the answer
    node = assistant.notes.add_node(rel, "summary", "- Yalnız ben kullanacağım.", parent_id=first["node_id"],
                                    status="pending")
    assistant._record(assistant._event("summary", rel, text=node["text"], node_id=node["id"],
                                       question_id=first["node_id"], question=first["text"], status="pending"))
    assert shown(assistant) == ("- Yalnız ben kullanacağım.", 2)
    assert [e["type"] for e in assistant.queue] == ["summary", "question", "question"]

    # approved somewhere else (the panel, the chat): the card moves on, one fewer
    assistant.hud_action(assistant.hud()["event"]["id"], "approve")
    assert shown(assistant) == (QUESTIONS[1], 1)
    assert assistant.notes.find_node(rel, first["node_id"])["status"] == "resolved"


def test_a_proposal_for_a_question_not_on_the_card_joins_the_end(assistant):
    rel = asked(assistant)
    other = assistant.notes.add_node(rel, "question", "Sessiz geçişin sorusu?", status="open")
    node = assistant.notes.add_node(rel, "summary", "Metin.", parent_id=other["id"], status="pending")
    assistant._record(assistant._event("summary", rel, text="Metin.", node_id=node["id"],
                                       question_id=other["id"], status="pending"))
    assert [e["type"] for e in assistant.queue] == ["question", "question", "question", "summary"]


def test_close_still_clears_the_card(assistant):
    asked(assistant)
    next_(assistant)
    assistant.hud_action(assistant.hud()["event"]["id"], "dismiss")
    assert assistant.hud() == {"event": None, "remaining": 0}
