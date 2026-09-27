"""The written guidelines: the model's own suggestion, a research it asks for,
perspectives in turn, and answers that become the decisions' values."""
import pytest

from core import llm_client
from server import ladder
from server.assistant import Assistant
from server.providers import ProviderRegistry
from server.store import HistoryStore, NoteStore
from server.vault import Vault

NOTE = "# Harcama takibi\n\nFişleri fotoğrafla çeken bir telefon uygulaması. Ailem de kullanacak.\n"


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


def note(assistant):
    return assistant.vault.create_note("", "harcama", NOTE)


def apply(assistant, rel, result):
    content = assistant.vault.read_note(rel)["content"]
    assistant._apply_result(rel, content, None, result, assistant.notes.open_questions(rel), "yazilim")


# ---------------------------------------------------------------- the reply
def test_the_reply_may_carry_a_suggestion_and_a_research_request():
    raw = ("kullanici: ailem\n"
           "platform: Telefon uygulaması mı, web mi?\n"
           "ÖNERİ: Aile ortak kullanacağı için harcamalar kişi bazında etiketlenmeli.\n"
           "ARAŞTIR: fiş fotoğrafından tutar okuma | hazır OCR kütüphaneleri var\n")
    result = llm_client.parse_ladder(raw, ["kullanici", "platform"], NOTE)
    assert result["suggestion"].startswith("Aile ortak")
    assert result["research"] == {"topic": "fiş fotoğrafından tutar okuma", "why": "hazır OCR kütüphaneleri var"}
    assert [q["kind"] for q in result["questions"]] == ["platform"]


# ---------------------------------------------------------------- "Modelin önerisi"
def test_the_model_suggestion_waits_for_approval_and_is_not_repeated(assistant):
    rel = note(assistant)
    text = "Aile ortak kullanacağı için harcamalar kişi bazında etiketlenmeli."
    apply(assistant, rel, {"type": "net", "suggestion": text})
    pending = [n for n in assistant.notes.load(rel)["nodes"] if n["type"] == "summary"]
    assert len(pending) == 1 and pending[0]["source"] == "model" and pending[0]["status"] == "pending"
    assert NOTE == assistant.vault.read_note(rel)["content"]            # the note itself is untouched

    apply(assistant, rel, {"type": "net", "suggestion": text})           # the same again: not twice
    assert len([n for n in assistant.notes.load(rel)["nodes"] if n["type"] == "summary"]) == 1


def test_a_suggestion_the_note_already_makes_is_not_offered(assistant):
    rel = note(assistant)
    apply(assistant, rel, {"type": "net", "suggestion": "Ailem de kullanacak."})
    assert not [n for n in assistant.notes.load(rel)["nodes"] if n["type"] == "summary"]


# ---------------------------------------------------------------- research the model asks for
def test_a_research_request_is_an_offer_until_accepted(assistant):
    rel = note(assistant)
    apply(assistant, rel, {"type": "net", "research": {"topic": "fişten tutar okuma", "why": "OCR"}})
    offer = next(e for e in assistant.history.items if e["type"] == "research")
    assert offer["status"] == "pending" and assistant.broker.of("start_research") == []

    assistant.hud_action(offer["id"], "approve")
    assert assistant.broker.of("start_research") == [{"path": rel, "focus": "fişten tutar okuma"}]
    assert offer["status"] == "approved"


def test_the_same_research_is_not_asked_for_twice(assistant):
    rel = note(assistant)
    apply(assistant, rel, {"type": "net", "research": {"topic": "fişten tutar okuma", "why": ""}})
    offer = next(e for e in assistant.history.items if e["type"] == "research")
    assistant.hud_action(offer["id"], "reject")
    apply(assistant, rel, {"type": "net", "research": {"topic": "Fişten tutar okuma", "why": ""}})
    assert len([e for e in assistant.history.items if e["type"] == "research"]) == 1


# ---------------------------------------------------------------- perspectives
def test_each_pass_looks_through_the_next_lens(assistant):
    rel = note(assistant)
    seen = [assistant._next_lens(rel)[0] for _ in range(5)]
    assert seen == ["mimar", "urun", "guvenlik", "gelistirici", "mimar"]
    assert "Mimar gözüyle" in ladder.lens_line(ladder.LENSES[0])


def test_a_suggestion_remembers_the_lens_it_came_through(assistant):
    rel = note(assistant)
    apply(assistant, rel, {"type": "net", "lens": "guvenlik",
                           "suggestion": "Fiş fotoğrafları telefonda şifreli durmalı, aile üyeleri ayrı görmeli."})
    offer = next(e for e in assistant.history.items if e["type"] == "summary")
    assert offer["lens"] == "guvenlik" and offer["source"] == "model"


def test_vague_advice_is_not_a_suggestion():
    assert llm_client.parse_extras("ÖNERİ: Güvenlik hakkında daha fazla düşünmek faydalı olabilir.") == {}
    # Turkish letters: fold() left "önemlidir" unmatched by the ASCII pattern (live run)
    assert llm_client.parse_extras("ÖNERİ: SQLite yapısının iyi tasarlanması ve senkronun yönetilmesi önemlidir.") == {}
    assert llm_client.parse_extras("ÖNERİ: Veri akışı için API entegrasyonları düşünülmelidir.") == {}
    assert llm_client.parse_extras("ARAŞTIR: Güvenlik | önemli") == {}
    assert llm_client.parse_extras("YOK") == {}


NOTE = "# Harcama\n\nFişleri fotoğrafla çeken bir telefon uygulaması. Ailem de kullanacak. İnternet yokken de çalışmalı."


def test_a_suggestion_names_two_things_in_the_note():
    raw = "ÖNERİ: Her fiş, kimin harcaması olduğuyla etiketlenmeli. | ailem de kullanacak + fişleri fotoğrafla"
    assert llm_client.parse_extras(raw, NOTE) == {
        "suggestion": "Her fiş, kimin harcaması olduğuyla etiketlenmeli.",
        "basis": "ailem de kullanacak + fişleri fotoğrafla"}


def test_a_suggestion_without_a_basis_in_the_note_is_dropped():
    assert llm_client.parse_extras("ÖNERİ: Her fiş, kimin harcaması olduğuyla etiketlenmeli.", NOTE) == {}
    assert llm_client.parse_extras("ÖNERİ: Kullanıcılar rol tabanlı yetkilendirilmeli. | ekip yönetimi + "
                                   "kurumsal müşteriler", NOTE) == {}


def test_the_basis_is_shown_with_the_suggestion(assistant):
    rel = note(assistant)
    apply(assistant, rel, {"type": "net", "suggestion": "Her fiş kimin harcaması olduğuyla etiketlenmeli.",
                           "basis": "ailem de kullanacak + fişleri fotoğrafla"})
    offer = next(e for e in assistant.history.items if e["type"] == "summary")
    assert offer["why"] == "ailem de kullanacak + fişleri fotoğrafla"


# ---------------------------------------------------------------- answers become values
def test_an_answer_becomes_the_decisions_value(assistant):
    """Questions branch on earlier answers: the roadmap the next pass reads
    carries what was answered, not only that something was."""
    rel = note(assistant)
    apply(assistant, rel, {"type": "questions",
                           "questions": [{"text": "Web mi, telefon mu?", "kind": "platform"}]})
    question = assistant.notes.open_questions(rel)[0]
    assistant.notes.add_node(rel, "chat-user", "Sadece Android telefon uygulaması", parent_id=question["id"])
    assistant.resolve(rel, question["id"], by="chat")
    decided = assistant.notes.load(rel)["decisions"]["platform"]
    assert decided["by"] == "cevap" and decided["value"] == "Sadece Android telefon uygulaması"
    assert "Sadece Android" in ladder.roadmap(assistant.ladder_for(rel))
