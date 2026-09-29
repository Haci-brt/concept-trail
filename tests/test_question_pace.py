"""How many questions to ask is the model's call; the code only keeps fuses."""
import pytest

from core import llm_client
from server import assistant as assistant_module
from server.assistant import FOLLOWUP_FUSE, OPEN_QUESTION_FUSE, Assistant
from server.providers import ProviderRegistry
from server.store import HistoryStore, NoteStore
from server.vault import Vault

IDEA = "# Kitap kulübü\n\nMahallede kitap takası yapan küçük bir kulüp; kitaplar bir rafta durur.\n"
SOFTWARE = "# Not senkronu\n\nBir yazılım: notlar hem telefonda hem masaüstünde duracak.\n"


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


def apply(assistant, rel, questions, mode="fikir"):
    content = assistant.vault.read_note(rel)["content"]
    result = {"type": "questions", "questions": [{"text": t, "kind": k} for k, t in questions]}
    assistant._apply_result(rel, content, None, result, assistant.notes.open_questions(rel), mode)


def test_a_pass_asks_as_many_questions_as_the_model_found(assistant):
    rel = assistant.vault.create_note("", "kulup", IDEA)
    questions = [("derinlestirme", "Raf nerede duracak, kim bakacak?"),
                 ("alternatif", "Raf yerine bir dolap olsaydı ne değişirdi?"),
                 ("sonuc", "Kulüp büyürse mahallede ne değişir?"),
                 ("kapsam", "Takasın en küçük hâli ne?"),
                 ("ilham", "Kütüphanelerin ödünç sistemi buraya uyar mı?")]
    apply(assistant, rel, questions)
    assert len(assistant.notes.open_questions(rel)) == 5          # no longer cut at three
    apply(assistant, rel, [("derinlestirme", "Kitaplar kaybolursa ne olacak?")])
    assert len(assistant.notes.open_questions(rel)) == 6          # nor held back by three waiting


def test_a_software_note_asks_every_open_decision_of_its_rung(assistant):
    rel = assistant.vault.create_note("", "senkron", SOFTWARE)
    apply(assistant, rel, [("amac", "Hangi sorunu çözüyor?"), ("kullanici", "Kim kullanacak?"),
                           ("platform", "Telefon uygulaması mı, web mi?"),
                           ("calisma", "Çevrimdışı da çalışacak mı?")], mode="yazilim")
    assert [n["kind"] for n in assistant.notes.open_questions(rel)] == ["amac", "kullanici", "platform", "calisma"]


def test_the_fuse_still_stops_a_model_gone_wrong(assistant):
    rel = assistant.vault.create_note("", "kulup", IDEA)
    words = ["raf", "kapak", "anahtar", "defter", "gönüllü", "bağış", "yağmur", "çocuk", "roman", "sözlük",
             "etiket", "sıra", "kayıp", "iade", "tatil", "okul", "kafe", "harita", "şiir", "dergi"]
    runaway = [("derinlestirme", " ".join(words[(i * 7 + j * 3) % len(words)] for j in range(5)) + f" {i}?")
               for i in range(30)]
    apply(assistant, rel, runaway)
    assert len(assistant.notes.open_questions(rel)) == OPEN_QUESTION_FUSE
    parsed = llm_client.parse_response("\n".join(f"SORU[derinlestirme]: Soru {i}?" for i in range(30)))
    assert len(parsed["questions"]) == llm_client.QUESTION_FUSE


def test_the_model_is_told_how_the_writer_keeps_up(assistant):
    rel = assistant.vault.create_note("", "kulup", IDEA)
    assert assistant._tempo(rel) == "Cevap bekleyen soru: 0. Son 30 dakikada sonuçlanan soru: 0."
    apply(assistant, rel, [("derinlestirme", "Raf nerede duracak?"), ("kapsam", "En küçük hâli ne?")])
    first = assistant.notes.open_questions(rel)[0]
    assistant.resolve(rel, first["id"])
    tempo = assistant._tempo(rel)
    assert tempo.startswith("Cevap bekleyen soru: 1 (en eskisi 1 dakikadır bekliyor)")
    assert tempo.endswith("Son 30 dakikada sonuçlanan soru: 1.")


def test_the_tempo_reaches_the_prompt_of_an_idea_note_only(monkeypatch):
    seen = {}

    def fake(messages, **kwargs):
        seen["user"] = messages[1]["content"]
        seen["system"] = messages[0]["content"]
        return "NET"

    monkeypatch.setattr(llm_client, "_complete_thinking_capped", fake)
    llm_client.ask_about_note("# Not\nmetin", "metin", [], tempo="Cevap bekleyen soru: 4.")
    assert "[TEMPO]\nCevap bekleyen soru: 4." in seen["user"]
    assert "en fazla 3" not in seen["system"] and "KAÇ soru" in seen["system"]
    llm_client.ask_about_note("# Not\nmetin", "metin", [], mode="yazilim", tempo="Cevap bekleyen soru: 4.")
    assert "[TEMPO]" not in seen["user"]       # the ladder asks one line per open decision anyway


def test_a_chat_knows_how_many_follow_ups_it_has_asked(monkeypatch):
    seen = {}

    def fake(messages, **kwargs):
        seen["system"] = messages[0]["content"]
        return "ANLADIM\nNOT: tamam"

    monkeypatch.setattr(llm_client, "_complete", fake)
    llm_client.chat_reply([{"role": "user", "content": "raf kapıda"}], "not", asked=4)
    assert "Bu sohbette şimdiye kadar 4 netleştirme sorusu sordun." in seen["system"]
    assert "sen karar ver" in seen["system"]


@pytest.mark.anyio
async def test_a_chat_keeps_asking_past_three_while_the_model_wants_to(assistant, monkeypatch):
    rel = assistant.vault.create_note("", "kulup", IDEA)
    question = assistant.notes.add_node(rel, "question", "Raf nerede duracak?", status="open")
    for i in range(4):
        assistant.notes.add_node(rel, "chat-user", f"cevap {i}", parent_id=question["id"])
        assistant.notes.add_node(rel, "chat-assistant", f"netleştirme {i}?", parent_id=question["id"], mode="question")
    seen = {}

    def reply(history, note, on_chunk=None, provider=None, on_usage=None, asked=0, wants_ideas=False):
        seen["asked"] = asked
        return "SORU: Rafı kim açıp kapatacak?"

    monkeypatch.setattr(assistant, "provider_for", lambda *a, **k: object())
    monkeypatch.setattr(llm_client, "chat_reply", reply)
    updates = [u async for u in assistant.chat_stream(rel, question["id"], "Kapının yanında.")]
    done = next(u for u in updates if u["type"] == "done")
    assert seen["asked"] == 4
    assert done["node"]["mode"] == "question"                     # the fifth follow-up is asked
    assert FOLLOWUP_FUSE > 4 and assistant_module.OPEN_QUESTION_FUSE > 3
