"""The assistant asks across the project, not into its own write-ups.

Measured on the writer's own notes (2026-09-26 to 30): every write-up the
writer approved woke a pass whose "new text" was that very sentence, and the
pass asked about its details; each such question then hung under the answer
it came from. kaan.md went q1 → q7 → four questions about one notification
screen; in codlaud.md the architecture rung's data and external-services
questions went under "who will use it?" and "online or offline?".

What the assistant wrote with approval stays in the note as context but is
not the writer's new material; a software note asks for its rung's decisions
side by side; on an idea note a follow-up goes one step deep, once — the
model's call, never a guess."""
import asyncio

import pytest

from core import llm_client
from server.assistant import MIN_NEW_CHARS, Assistant, diff_new_text, writers_tail
from server.providers import ProviderRegistry
from server.store import HistoryStore, NoteStore
from server.vault import Vault
from testkit.fake_model import FakeModel

IDEA = ("---\ntur: fikir\n---\n# Hastane sırası\n\n"
        "Hasta kabulde TC girilince doktorun odası, sıra ve bekleme süresi tek ekranda görünsün.\n")
# kaan.md's s26, as the assistant wrote it and the writer approved it
WRITE_UP = ("Tek bildirimdeki bilgi sırası: doktor ataması → oda konumu → sıra numarası → bekleme süresi; "
            "hepsi tek mesajda.")
MINE = "Görevli yardım edecek, cihaz girişte duracak ve herkes kendi kimliğini okutacak."
# codlaud.md, word for word
SOFTWARE = ("iki yapay zeka aracını aynı proje üzerinde çalıştırmak istiyorum. birini kodlama backend "
            "bölümüne birini tasarım ve frontend bölümüne koymak istiyorum.\n")


class Broker:
    def __init__(self):
        self.events = []

    def publish(self, kind, data):
        self.events.append((kind, data))


@pytest.fixture(scope="module")
def fake_model():
    model = FakeModel().start()
    yield model
    model.stop()


@pytest.fixture
def assistant(tmp_path, fake_model):
    vault = Vault(tmp_path / "vault")
    a = Assistant(vault, NoteStore(vault), HistoryStore(vault), Broker(),
                  ProviderRegistry(path=tmp_path / "providers.json"))
    local = a.providers.get("local-chat")
    local.base_url, local.health = fake_model.base_url, "models"
    a.providers.set_health("local-chat", True)
    return a


@pytest.fixture
def seen(monkeypatch):
    """What each pass was asked about; the stand-in model still answers it."""
    calls = []
    real = llm_client.ask_about_note

    def spy(*args, **kwargs):
        calls.append({"new_part": args[1], **kwargs})
        calls[-1]["reply"] = real(*args, **kwargs)
        return calls[-1]["reply"]

    monkeypatch.setattr(llm_client, "ask_about_note", spy)
    return calls


async def settle(assistant):
    for _ in range(50):
        if not assistant._tasks:
            return
        await asyncio.gather(*list(assistant._tasks), return_exceptions=True)


async def look(assistant, rel, content, force=False):
    status = (await assistant.analyze(rel, content, force=force))["status"]
    await settle(assistant)
    return status


def approve(assistant, rel, text):
    """What approving a write-up does: remembered, then appended by the editor."""
    assistant.remember_written(rel, text)
    content = assistant.vault.read_note(rel)["content"]
    gap = "" if content.endswith("\n\n") else "\n" if content.endswith("\n") else "\n\n"   # appendText
    content = f"{content}{gap}{text}\n"
    assistant.vault.write_note(rel, content)
    return content


def questions(assistant, rel):
    return [n for n in assistant.notes.load(rel)["nodes"] if n["type"] == "question"]


def answer(assistant, rel, question, text):
    assistant.notes.add_node(rel, "chat-user", text, parent_id=question["id"])
    assistant.resolve(rel, question["id"], by="chat")


def apply(assistant, rel, items, mode="fikir"):
    content = assistant.vault.read_note(rel)["content"]
    assistant._apply_result(rel, content, None, {"type": "questions", "questions": items},
                            assistant.notes.open_questions(rel), mode)


# ---------------------------------------------------------------- the write-up is not new text
def test_an_approved_write_up_is_not_new_text():
    new = f"{IDEA}\n{WRITE_UP}\n"
    assert diff_new_text(IDEA, new)[1] >= MIN_NEW_CHARS        # what used to wake a pass
    assert diff_new_text(IDEA, new, [WRITE_UP]) == ("", 0, None)
    middle = "# Raf\n\nRaf girişte duracak.\n\nKitaplar deftere yazılsın.\n"
    placed = middle.replace("\n\nKitaplar", f"\n\n{WRITE_UP}\n\nKitaplar")
    assert diff_new_text(middle, placed, [WRITE_UP]) == ("", 0, None)


def test_what_the_writer_wrote_beside_a_write_up_still_counts():
    for new in (f"{IDEA}{MINE}\n\n{WRITE_UP}\n", f"{IDEA}\n{WRITE_UP}\n\n{MINE}\n"):
        part, changed, span = diff_new_text(IDEA, new, [WRITE_UP])
        assert part == MINE and changed == len(MINE)
        assert new[span[0]:span[1]].strip() == MINE


def test_an_edit_the_writer_approved_is_not_new_text_either():
    old = "# Raf\n\nRaf apartmanın girişinde duracak, herkes kitap bırakabilecek.\n"
    replacement = "posta kutularının hemen yanında"
    assert diff_new_text(old, old.replace("girişinde", replacement), [replacement]) == ("", 0, None)


def test_without_write_ups_the_diff_reads_as_before():
    assert diff_new_text("abc", "abc def") == ("abc def", 3, [0, 7])
    assert diff_new_text("Bir.\nIki.\n", "Bir.\nİki satır.\nÜç.\n", [WRITE_UP]) == ("İki satır.\nÜç.", 11, [5, 20])
    assert diff_new_text("# X\n\nA\n\nB\n", "# X\n\nA\n\nyeni paragraf burada\n\nB\n") == \
        ("yeni paragraf burada", 20, [8, 30])
    assert writers_tail("x" * 900, []) == ("x" * 800, [100, 900])


def test_with_nothing_new_a_pass_you_ask_for_reads_your_own_words():
    note = f"{IDEA}\n{WRITE_UP}\n"
    text, span = writers_tail(note, [WRITE_UP])
    assert WRITE_UP not in text and "bekleme süresi tek ekranda" in text
    assert note[span[0]:span[1]].strip().endswith("tek ekranda görünsün.")


@pytest.mark.anyio
async def test_approving_a_write_up_does_not_wake_the_watch(assistant, seen):
    rel = assistant.vault.create_note("", "sira", IDEA)
    assert await look(assistant, rel, IDEA) == "started"
    approved = approve(assistant, rel, WRITE_UP)

    assert await look(assistant, rel, approved) == "skipped"
    assert len(seen) == 1
    assert assistant.notes.load(rel)["analyzed_text"] == approved   # taken in, quietly

    typed = f"{approved}\n{MINE}\n"
    assert await look(assistant, rel, typed) == "started"
    assert seen[-1]["new_part"] == MINE                            # only what you wrote is new
    assert seen[-1]["settled"] == [WRITE_UP]                       # the write-up is named settled
    asked = [q["text"] for q in questions(assistant, rel)][-2:]
    assert asked and not any(word in text for text in asked for word in ("bildirimdeki", "numarası"))


@pytest.mark.anyio
async def test_asking_with_nothing_new_looks_at_the_writers_words(assistant, seen):
    rel = assistant.vault.create_note("", "sira", IDEA)
    await look(assistant, rel, IDEA)
    approved = approve(assistant, rel, WRITE_UP)
    assert await look(assistant, rel, approved, force=True) == "started"
    assert WRITE_UP not in seen[-1]["new_part"] and "tek ekranda" in seen[-1]["new_part"]


# ---------------------------------------------------------------- breadth first
def test_a_decision_question_never_hangs_under_another_answer(assistant):
    """codlaud.md, 2026-09-30: q17 (data) went under q2 (who), q19
    (external services) under q4 (online) — a new rung's decisions filed as
    details of answers already given."""
    rel = assistant.vault.create_note("", "codlaud", SOFTWARE)
    assistant.set_decisions(rel, {"amac": True, "platform": True}, by="rota")
    apply(assistant, rel, [{"text": "Projeyi kim kullanacak?", "kind": "kullanici"},
                           {"text": "Çevrimiçi mi çevrimdışı mı çalışacak?", "kind": "calisma"}], "yazilim")
    who, online = questions(assistant, rel)
    assistant.notes.add_node(rel, "chat-user", "projeyi nasıl kim kullanacak", parent_id=who["id"])
    assistant.notes.add_node(rel, "chat-assistant", "Bu projeyi kullanacak kişiler kimler — örneğin sadece "
                             "siz mi, belirli bir ekip mi, yoksa genel kullanıcılar mı?", parent_id=who["id"])
    answer(assistant, rel, who, "tek bir kullanıcı")
    answer(assistant, rel, online, "iki yapay zekada internetle çalıştığı için çevrimiçi olacak tabi")
    assert assistant.ladder_for(rel)["current"] == "mimari"

    apply(assistant, rel, [
        {"text": "Proje verileri nerede saklanacak, kullanıcının kendi bilgisayarında mı yoksa sunucuda mı?",
         "kind": "veri"},
        {"text": "İki yapay zeka aracı da internetle çalıştığına göre hangi dış servisleri kullanacak?",
         "kind": "dis"}], "yazilim")
    asked = {q["kind"]: q for q in questions(assistant, rel)}
    assert asked["veri"]["parentId"] is None and asked["dis"]["parentId"] is None


def test_a_guess_never_hangs_a_question_under_an_answered_one(assistant):
    """kaan.md, 2026-09-26: the questions after each approval went under the
    question whose answer they dug into."""
    rel = assistant.vault.create_note("", "kaan", IDEA)
    apply(assistant, rel, [{"text": "TC'yi girdiğimde hangi doktora yönlendirileceğim nasıl belirlenir?",
                            "kind": "derinlestirme"}])
    first = questions(assistant, rel)[0]
    again = "TC'yi girdiğimde sistem, doktor atamasını doğrudan nasıl belirler?"

    apply(assistant, rel, [{"text": again, "kind": "derinlestirme"}])
    assert questions(assistant, rel)[-1]["parentId"] == first["id"]    # still talked about: grouped

    rel = assistant.vault.create_note("", "kaan 2", IDEA)
    apply(assistant, rel, [{"text": "TC'yi girdiğimde hangi doktora yönlendirileceğim nasıl belirlenir?",
                            "kind": "derinlestirme"}])
    first = questions(assistant, rel)[0]
    answer(assistant, rel, first, "bu zaten sisteme düşüyor bizim uygulamamıza gelecek bu bilgi kullanıcı "
                                  "randevu aldığı zaman.")
    apply(assistant, rel, [{"text": again, "kind": "derinlestirme"}])
    assert questions(assistant, rel)[-1]["parentId"] is None           # answered: settled, not a parent


def test_the_model_may_follow_up_an_answer_once_and_never_a_follow_up(assistant):
    rel = assistant.vault.create_note("", "sira", IDEA)
    apply(assistant, rel, [{"text": "Sıra ekranı nerede duracak?", "kind": "derinlestirme"}])
    root = questions(assistant, rel)[0]
    answer(assistant, rel, root, "Hasta kabulün sağındaki duvarda.")

    apply(assistant, rel, [{"text": "Duvardaki ekranı kim açıp kapatacak?", "kind": "derinlestirme",
                            "parent_id": root["id"]},
                           {"text": "Randevusuz gelen hasta sırayı nasıl görecek?", "kind": "kapsam"}])
    follow, other = questions(assistant, rel)[1:]
    assert follow["parentId"] == root["id"] and other["parentId"] is None

    apply(assistant, rel, [{"text": "Ekranın parlaklığı gece ne olacak?", "kind": "derinlestirme",
                            "parent_id": root["id"]}])                 # a second one of the same answer
    answer(assistant, rel, follow, "Hasta kabul görevlisi.")
    apply(assistant, rel, [{"text": "Görevli izne çıkınca kim açacak?", "kind": "derinlestirme",
                            "parent_id": follow["id"]},                # a follow-up of the follow-up
                           {"text": "Bekleme süresi neye göre hesaplanacak?", "kind": "derinlestirme"}])
    texts = [q["text"] for q in questions(assistant, rel)]
    assert "Ekranın parlaklığı gece ne olacak?" not in texts
    assert "Görevli izne çıkınca kim açacak?" not in texts
    assert texts[-1] == "Bekleme süresi neye göre hesaplanacak?"      # the rest of the pass still asks
    assert assistant.notes.load(rel)["last_question"] == texts[-1]


@pytest.mark.anyio
async def test_a_model_that_digs_into_every_answer_gets_one_follow_up(assistant, seen):
    """The stand-in model does what the real ones did: every pass it follows
    up the latest answer, id and all. One is asked; its own is not."""
    rel = assistant.vault.create_note("", "sira", IDEA)
    await look(assistant, rel, IDEA, force=True)
    first = questions(assistant, rel)[0]
    answer(assistant, rel, first, "Bekleme süresi ekranda dakika olarak yazacak.")

    content = f"{IDEA}\nEkran hasta kabulün sağındaki duvarda duracak, büyük harflerle okunacak.\n"
    await look(assistant, rel, content)
    follow = [q for q in questions(assistant, rel) if q["parentId"] == first["id"]]
    assert len(follow) == 1 and "ayrıntısı" in follow[0]["text"]
    answer(assistant, rel, follow[0], "Süre her hasta çağrıldığında yeniden hesaplanacak.")

    content += "\nRandevusuz gelenler için ayrı bir sıra numarası verilecek, kâğıda basılacak.\n"
    await look(assistant, rel, content)
    wanted = [q for q in seen[-1]["reply"]["questions"] if q.get("parent_id") == follow[0]["id"]]
    assert wanted                                                      # the model asked to dig deeper
    after = questions(assistant, rel)
    assert not [q for q in after if q["parentId"] == follow[0]["id"]]  # and it was not asked
    assert sum("ayrıntısı" in q["text"] for q in after) == 1


# ---------------------------------------------------------------- the model is told
def test_the_branches_say_what_is_settled_and_where_a_follow_up_may_go(assistant):
    rel = assistant.vault.create_note("", "sira", IDEA)
    apply(assistant, rel, [{"text": "Sıra ekranı nerede duracak?", "kind": "derinlestirme"},
                           {"text": "Randevusuz gelen hasta sırayı nasıl görecek?", "kind": "kapsam"}])
    root, waiting = questions(assistant, rel)
    answer(assistant, rel, root, "Hasta kabulün sağındaki duvarda.")
    apply(assistant, rel, [{"text": "Duvardaki ekranı kim açıp kapatacak?", "kind": "derinlestirme",
                            "parent_id": root["id"]}])
    follow = questions(assistant, rel)[-1]
    lines = assistant._question_branches(rel, assistant.notes.load(rel)["nodes"]).splitlines()
    line = {text.split()[1]: text for text in lines}
    assert "[cevaplandı, kapandı; altına soru açılmaz]" in line[root["id"]]      # followed up once
    assert "[cevap bekliyor]" in line[waiting["id"]]
    assert f"(üst soru: {root['id']}) [cevap bekliyor; altına soru açılmaz]" in line[follow["id"]]


def test_an_idea_pass_is_told_which_sentences_are_settled(monkeypatch):
    sent = {}

    def fake(messages, **kwargs):
        sent["system"], sent["user"] = messages[0]["content"], messages[1]["content"]
        return "NET"

    monkeypatch.setattr(llm_client, "_complete_thinking_capped", fake)
    note = f"{IDEA}\n{WRITE_UP}\n"
    llm_client.ask_about_note(note, MINE, [], settled=[WRITE_UP])
    block = sent["user"].split("[YAZARLA NETLEŞENLER]", 1)[1]
    assert f"- {WRITE_UP}" in block and block.index(WRITE_UP) < block.index("[YENİ EKLENEN]")
    assert "takip sorusunun takip sorusu olmaz" in sent["system"]
    assert "onun üstüne inşa et" not in sent["system"]                 # "build on it" dug into answers

    llm_client.ask_about_note(note, MINE, [], mode="yazilim", settled=[WRITE_UP])
    assert "[YAZARLA NETLEŞENLER]" not in sent["user"]                 # the roadmap says what is decided
    assert "Daralma seviyeden seviyeye olur, sorudan soruya değil" in sent["system"]
