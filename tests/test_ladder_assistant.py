"""The assistant keeps the ladder's order even when the model does not."""
import pytest

from server import ladder
from server.assistant import Assistant
from server.ladder import DECISION_IDS
from server.providers import ProviderRegistry
from server.store import HistoryStore, NoteStore
from server.vault import Vault

NOTE = "# Not senkronu\n\nNotlar hem telefonda hem masaüstünde duracak.\n"


class Broker:
    def __init__(self):
        self.events = []

    def publish(self, kind, data):
        self.events.append((kind, data))

    def of(self, kind):
        return [data for k, data in self.events if k == kind]


@pytest.fixture
def assistant(tmp_path):
    vault = Vault(tmp_path / "vault")
    return Assistant(vault, NoteStore(vault), HistoryStore(vault), Broker(),
                     ProviderRegistry(path=tmp_path / "providers.json"))


def note(assistant, text=NOTE):
    return assistant.vault.create_note("", "senkron", text)


def ask(assistant, rel, *questions, known=None, mode="yazilim"):
    result = {"type": "questions", "questions": [{"text": t, "kind": k} for k, t in questions]}
    if known:
        result["known"] = known
    content = assistant.vault.read_note(rel)["content"]
    assistant._apply_result(rel, content, None, result, assistant.notes.open_questions(rel), mode)


def asked(assistant, rel):
    return [(n["kind"], n["text"]) for n in assistant.notes.open_questions(rel)]


# ---------------------------------------------------------------- order
def test_a_question_that_skips_ahead_is_dropped(assistant):
    rel = note(assistant)
    ask(assistant, rel, ("platform", "Web mi, masaüstü mü, mobil mi olacak?"),
        ("teknoloji", "Hangi veritabanını kullanacaksın?"))
    assert asked(assistant, rel) == [("platform", "Web mi, masaüstü mü, mobil mi olacak?")]


def test_an_untagged_or_curiosity_question_is_not_asked_on_a_software_note(assistant):
    rel = note(assistant)
    ask(assistant, rel, ("soru", "Bu fikir sana ne hissettiriyor?"),
        ("ilham", "Benzer bir proje düşündün mü?"))
    # neither is asked; the rung's own first question is asked instead
    assert asked(assistant, rel) == [("amac", ladder.ASK["amac"])]


def test_when_the_model_asks_nothing_usable_the_ladder_still_moves(assistant):
    rel = note(assistant)
    content = assistant.vault.read_note(rel)["content"]
    assistant._apply_result(rel, content, None, {"type": "net"}, [], "yazilim")
    assert asked(assistant, rel) == [("amac", ladder.ASK["amac"])]
    # and it is not asked a second time while it waits for an answer
    assistant._apply_result(rel, content, None, {"type": "net"}, [], "yazilim")
    assert len(asked(assistant, rel)) == 1


def test_the_same_decision_is_not_asked_twice_while_waiting_for_an_answer(assistant):
    rel = note(assistant)
    ask(assistant, rel, ("platform", "Web mi, mobil mi?"))
    ask(assistant, rel, ("platform", "Hangi platformda çalışacak?"))
    assert [k for k, _ in asked(assistant, rel)] == ["platform"]


def test_what_the_note_already_says_is_not_asked(assistant):
    rel = note(assistant)
    ask(assistant, rel, ("platform", "Web mi, mobil mi?"), known=["platform", "calisma"])
    assert assistant.ladder_for(rel)["open"] == ["amac", "kullanici"]
    assert [kind for kind, _ in asked(assistant, rel)] == ["amac"]      # not platform


def test_an_idea_note_keeps_its_curiosity_questions(assistant):
    rel = note(assistant, "---\ntur: fikir\n---\n# Kafe\n\nKöşede masalar olsun.")
    ask(assistant, rel, ("ilham", "Bir kütüphane kafesi nasıl olurdu?"), mode="fikir")
    assert asked(assistant, rel) == [("ilham", "Bir kütüphane kafesi nasıl olurdu?")]


# ---------------------------------------------------------------- answers decide
def test_answering_a_decision_question_marks_the_decision(assistant):
    rel = note(assistant)
    ask(assistant, rel, ("platform", "Web mi, mobil mi?"))
    question = assistant.notes.open_questions(rel)[0]
    assistant.resolve(rel, question["id"], by="chat")
    decided = assistant.notes.load(rel)["decisions"]["platform"]
    assert decided["by"] == "cevap" and decided["question"] == question["id"]


def test_once_scope_is_settled_the_questions_come_from_architecture(assistant):
    rel = note(assistant)
    ask(assistant, rel, known=["amac", "kullanici", "platform", "calisma"])
    ask(assistant, rel, ("platform", "Web mi?"), ("veri", "Notlar nerede duracak, sahibi kim?"))
    kinds = [kind for kind, _ in asked(assistant, rel)]
    assert kinds == ["parcalar", "veri"]          # architecture only; the platform is not re-asked
    change = assistant.broker.of("ladder")[-1]["transition"]
    assert change["title"] == "Kapsam netleşti"


# ---------------------------------------------------------------- the product phase
def test_the_product_phase_is_announced_once_when_it_is_reached(assistant):
    rel = note(assistant)
    assistant.set_decisions(rel, {d: True for d in DECISION_IDS[:-1]}, by="sen")
    assistant.set_decisions(rel, {DECISION_IDS[-1]: True}, by="cevap")
    assert assistant.ladder_for(rel)["phase"] == "urun"
    reached = [e for e in assistant.broker.of("ladder") if (e["transition"] or {}).get("phase") == "urun"]
    assert len(reached) == 1
    assert any(f["title"] == "Ürün evresi" for f in assistant.broker.of("flash"))
    assert assistant.history.items[0]["type"] == "phase"

    assistant.set_decisions(rel, {DECISION_IDS[-1]: True}, by="cevap")   # nothing new
    assert len([e for e in assistant.broker.of("ladder")
                if (e["transition"] or {}).get("phase") == "urun"]) == 1


def test_the_writer_can_take_a_decision_back(assistant):
    rel = note(assistant)
    assistant.set_decisions(rel, {"platform": True}, by="sen")
    assistant.set_decisions(rel, {"platform": False}, by="sen")
    assert "platform" in assistant.ladder_for(rel)["open"]


def test_an_unknown_decision_name_changes_nothing(assistant):
    rel = note(assistant)
    before = assistant.ladder_for(rel)
    assert assistant.set_decisions(rel, {"hangi-kutuphane": True}, by="sen") == before
    assert assistant.broker.of("ladder") == []
