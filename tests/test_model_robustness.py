"""What the measurement on a real small model (Qwen3-4B, 2026-09-29) showed,
kept: the writer's language said first and last, ladder replies read however
the model dressed them, a bold tag still a tag, and a brake on questions
piling up unanswered."""
import pytest

from core import llm_client
from server import assistant as assistant_module
from server.assistant import Assistant
from server.providers import ProviderRegistry
from server.store import HistoryStore, NoteStore
from server.vault import Vault

EN_NOTE = ("# Expense tracker\n\nI want to build a phone app that photographs receipts. My family will use it "
           "too. It must work without internet, and the data should stay on the phone.\n")
OPEN = ["amac", "kullanici", "platform", "calisma"]


@pytest.fixture(autouse=True)
def turkish_after():
    yield
    llm_client.set_output_language("tr")


def test_the_language_is_said_first_and_last():
    llm_client.set_output_language("en")
    system = llm_client.localized("/no_think\nSen bir asistansın.")
    assert system.startswith("/no_think\nLANGUAGE: the writer works in English.")   # the switch stays first
    assert "no JSON" in system and system.rstrip().endswith("kendi kelimeleriyle yaz.")
    llm_client.set_output_language("de")
    assert llm_client.localized("Sen.").startswith("SPRACHE:")
    assert "Deutsch" in llm_client.language_reminder()
    llm_client.set_output_language("tr")
    assert llm_client.localized("Sen.") == "Sen." and llm_client.language_reminder() == ""


def test_the_note_pass_ends_with_the_reminder(monkeypatch):
    seen = {}
    monkeypatch.setattr(llm_client, "_complete_thinking_capped",
                        lambda messages, **k: seen.update(user=messages[1]["content"]) or "NET")
    llm_client.set_output_language("fr")
    llm_client.ask_about_note(EN_NOTE, EN_NOTE, [], mode="yazilim", open_decisions=OPEN)
    assert seen["user"].rstrip().endswith("écris chaque question en français.)")


def test_a_tag_in_front_of_a_decision_line_is_read_through():
    raw = ("SORU: amac: What specific problem does the expense tracker solve?\n"
           "BİLİNİYOR: kullanici: My family will use it too\n"
           "ÖNERİ: platform: Phone app\n"
           "ARAŞTIR: calisma: Works without internet, data stays on the phone")
    result = llm_client.parse_ladder(raw, OPEN, EN_NOTE)
    assert result["questions"] == [{"text": "What specific problem does the expense tracker solve?", "kind": "amac"}]
    assert set(result["known"]) == {"kullanici", "platform", "calisma"}
    assert "suggestion" not in result and "research" not in result      # not taken for a suggestion


def test_a_ladder_reply_in_json_is_read_as_lines():
    flat = '```json\n{"kullanici": "My family will use it too", "platform": "Web or mobile?"}\n```'
    result = llm_client.parse_ladder(flat, OPEN, EN_NOTE)
    assert result["known"] == ["kullanici"] and result["questions"][0]["kind"] == "platform"
    listed = '{"acik_kararlar": [{"id": "amac", "deger": "photographs receipts"}, {"id": "calisma", "value": "work without internet"}]}'
    assert set(llm_client.parse_ladder(listed, OPEN, EN_NOTE)["known"]) == {"amac", "calisma"}
    assert llm_client._json_ladder("kullanici: tek başıma") is None


def test_a_bold_tag_in_a_chat_reply_is_still_the_tag():
    reply = "Tamam, anlaşıldı.\n\n**NOT:** Raf girişteki posta kutularının yanında duracak."
    assert llm_client.parse_chat_reply(reply) == {"type": "understood",
                                                  "note": "Raf girişteki posta kutularının yanında duracak."}
    assert llm_client.parse_chat_reply("**SORU:** Rafı kim toplayacak?") == {"type": "question",
                                                                            "text": "Rafı kim toplayacak?"}


class Broker:
    def publish(self, *args):
        pass


@pytest.fixture
def assistant(tmp_path):
    vault = Vault(tmp_path / "vault")
    return Assistant(vault, NoteStore(vault), HistoryStore(vault), Broker(),
                     ProviderRegistry(path=tmp_path / "providers.json"))


def ask(assistant, rel, texts):
    content = assistant.vault.read_note(rel)["content"]
    result = {"type": "questions", "questions": [{"text": t, "kind": "derinlestirme"} for t in texts]}
    assistant._apply_result(rel, content, None, result, assistant.notes.open_questions(rel), "fikir")


NEW = ["Kitaplar kaybolursa ne olur?", "Raf yağmurda ıslanır mı?", "Çocuk köşesi hangi yaşlara göre?",
       "Buluşma hangi gün olur?", "Defteri kim tutar?", "Yönetici ne der?"]


def test_questions_piling_up_unanswered_slow_the_pace_to_one(assistant):
    rel = assistant.vault.create_note("", "kulup", "---\ntur: fikir\n---\n# Kitap takası\n\nApartmana bir raf.\n")
    ask(assistant, rel, NEW[:5])
    assert len(assistant.notes.open_questions(rel)) == 5 == assistant_module.BACKLOG
    ask(assistant, rel, ["Raf kaç rafa bölünür?", "Kapak rengi ne olur?", "Takas kaç gün sürer?"])
    assert len(assistant.notes.open_questions(rel)) == 6                 # only the first of three


def test_a_writer_who_answers_is_never_held_back(assistant):
    rel = assistant.vault.create_note("", "kulup", "---\ntur: fikir\n---\n# Kitap takası\n\nApartmana bir raf.\n")
    ask(assistant, rel, NEW[:5])
    assistant.resolve(rel, assistant.notes.open_questions(rel)[0]["id"])
    ask(assistant, rel, ["Raf kaç rafa bölünür?", "Kapak rengi ne olur?", "Takas kaç gün sürer?"])
    assert len(assistant.notes.open_questions(rel)) == 7                 # 4 waiting + all 3 new
