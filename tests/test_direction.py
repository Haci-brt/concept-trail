"""A writer's correction replaces stale assistant work and guides the next pass."""
import pytest

from core import llm_client
from server.assistant import Assistant
from server.errors import ApiError
from server.providers import ProviderRegistry
from server.store import HistoryStore, NoteStore
from server.vault import Vault


class Broker:
    def __init__(self):
        self.events = []

    def publish(self, kind, data):
        self.events.append((kind, data))


@pytest.fixture
def writer(tmp_path):
    vault = Vault(tmp_path / "vault")
    assistant = Assistant(vault, NoteStore(vault), HistoryStore(vault), Broker(),
                          ProviderRegistry(path=tmp_path / "providers.json"))
    rel = vault.create_note("", "fikir", "# Fikir\n\nBireysel not uygulaması.")
    return assistant, rel


def test_direction_closes_stale_work_and_persists(writer):
    assistant, rel = writer
    assistant.set_decisions(rel, {"amac": True, "kullanici": True}, by="sen")
    question = assistant.notes.add_node(rel, "question", "Ekip paylaşımı olacak mı?",
                                        status="open", kind="platform")
    proposal = assistant.notes.add_node(rel, "edit", "Ekip ekranı ekle", status="pending")

    result = assistant.set_direction(rel, "kapsam", "İlk sürüm yalnızca bireysel notlar için olsun.")

    assert result["closed_questions"] == 1
    assert result["discarded_proposals"] == 1
    assert assistant.notes.find_node(rel, question["id"])["status"] == "dismissed"
    assert assistant.notes.find_node(rel, proposal["id"])["status"] == "rejected"
    assert assistant.notes.load(rel)["decisions"] == {}
    assert NoteStore(assistant.vault).load(rel)["direction"] == result["direction"]


def test_output_correction_keeps_project_decisions_and_records_previous_direction(writer):
    assistant, rel = writer
    assistant.set_decisions(rel, {"amac": True}, by="sen")
    first = assistant.set_direction(rel, "cikti", "Sorulara kısa seçenekler ekle.")
    assistant.set_direction(rel, "cikti", "Her seçenek için bir örnek de göster.")

    state = assistant.notes.load(rel)
    assert "amac" in state["decisions"]
    assert state["direction_history"] == [first["direction"]]
    with pytest.raises(ApiError):
        assistant.set_direction(rel, "cikti", " ")


def test_dismissed_question_does_not_block_a_new_question(writer):
    assistant, rel = writer
    assistant.notes.add_node(rel, "question", "Notları nasıl gruplarsın?",
                             status="open", kind="derinlestirme")
    assistant.set_direction(rel, "cikti", "Soruları daha kısa sor.")
    content = assistant.vault.read_note(rel)["content"]

    assistant._apply_result(rel, content, None,
                            {"type": "questions", "questions": [
                                {"text": "Notları nasıl gruplarsın?", "kind": "derinlestirme"}]},
                            [], "fikir")

    assert [n["text"] for n in assistant.notes.open_questions(rel)] == ["Notları nasıl gruplarsın?"]


def test_analysis_reads_latest_direction_and_can_ground_its_decision(monkeypatch):
    captured = {}

    def fake(messages, **kwargs):
        captured["messages"] = messages
        return "amac: Ekip işlerini kolaylaştırmak"

    monkeypatch.setattr(llm_client, "_complete_thinking_capped", fake)
    result = llm_client.ask_about_note(
        "# Fikir\n\nBireysel not uygulaması.", "Bireysel not uygulaması.", [],
        mode="yazilim", open_decisions=["amac"],
        direction="Ekip işlerini kolaylaştırmak istiyorum.",
    )

    assert "[KULLANICININ SON YÖNÜ" in captured["messages"][1]["content"]
    assert "eski notla çeliştiğinde son yönü esas al" in captured["messages"][0]["content"]
    assert result["known"] == ["amac"]


# ---------------------------------------------------------------- the model reads the correction
@pytest.mark.anyio
async def test_only_what_the_correction_affects_is_reopened(writer, monkeypatch):
    """A small correction must not throw away a 12/15 roadmap."""
    assistant, rel = writer
    assistant.set_decisions(rel, {"amac": True, "kullanici": True, "platform": True}, by="sen")
    keep = assistant.notes.add_node(rel, "question", "Veriler nerede duracak?", status="open", kind="calisma")
    stale = assistant.notes.add_node(rel, "question", "Ekip rolleri ne olacak?", status="open", kind="kullanici")

    def plan(note, category, text, decisions, questions, proposals, previous, provider, on_usage):
        assert set(decisions) == {"amac", "kullanici", "platform"}
        return {"summary": "Artık yalnız bireysel kullanım için soruyorum.",
                "reopen": ["kullanici"], "drop_questions": [stale["id"]], "drop_proposals": []}

    monkeypatch.setattr(llm_client, "plan_direction", plan)
    preview = await assistant.preview_direction(rel, "kullanici", "Ekip yok, sadece ben kullanacağım.")
    assert preview["summary"].startswith("Artık yalnız")
    assert set(preview["items"]) == {"kullanici", stale["id"]}
    assert "kullanici" in assistant.notes.load(rel)["decisions"]      # nothing changed yet

    assistant.set_direction(rel, "kullanici", "Ekip yok, sadece ben kullanacağım.", preview)
    state = assistant.notes.load(rel)
    assert set(state["decisions"]) == {"amac", "platform"}
    assert assistant.notes.find_node(rel, keep["id"])["status"] == "open"
    assert assistant.notes.find_node(rel, stale["id"])["status"] == "dismissed"
    assert state["direction"]["summary"].startswith("Artık yalnız")


def test_ids_the_model_made_up_are_ignored():
    raw = '{"ozet": "Kapsam daraldı.", "kararlar": ["platform", "hayali"], "sorular": ["q9"], "oneriler": []}'
    plan = llm_client.parse_direction_plan(raw, {"platform": "Platform"}, {"q1": "soru"}, {})
    assert plan == {"summary": "Kapsam daraldı.", "update": {}, "reopen": ["platform"],
                    "drop_questions": [], "drop_proposals": [], "ask": []}


def test_the_questions_a_new_course_raises_are_read_once_and_briefly():
    raw = ('{"ozet": "Araçlar abonelikle, ekrandan yönetilecek.", "yeni_sorular": ['
           '"Hangi abonelikli araçları yöneteceksin", "Hangi abonelikli araçları yöneteceksin?", '
           '"Veriler nerede duracak?", "kısa", {"soru": "Araçlar aynı dosyaya yazarsa ne olacak?"}]}')
    plan = llm_client.parse_direction_plan(raw, {}, {"q4": "[veri] Veriler nerede duracak?"}, {})
    # the question already waiting is not asked twice; at most two, each a question
    assert plan["ask"] == ["Hangi abonelikli araçları yöneteceksin?", "Araçlar aynı dosyaya yazarsa ne olacak?"]


@pytest.mark.anyio
async def test_a_correction_that_stales_nothing_still_asks_about_the_new_course(writer, monkeypatch):
    """Seen by the writer: a correction left every question standing, the
    ladder let no pass ask about the new course, and nothing changed at all."""
    assistant, rel = writer
    keep = assistant.notes.add_node(rel, "question", "Projeyi kim kullanacak?", status="open", kind="kullanici")
    monkeypatch.setattr(llm_client, "plan_direction", lambda *a, **k: llm_client.parse_direction_plan(
        '{"ozet": "İki aracı ekrandan yöneteceğiz.", "guncelle": {}, "kararlar": [], "sorular": [], '
        '"oneriler": [], "yeni_sorular": ["Hangi abonelikli araçları yöneteceksin?", '
        '"Araçlar aynı dosyaya yazarsa ne olacak?"]}', {}, {keep["id"]: keep["text"]}, {}))
    preview = await assistant.preview_direction(rel, "diger", "Araçları computer use ile yönetsin.")
    assert [q["id"] for q in preview["ask"]] == ["yeni1", "yeni2"]
    assert preview["items"]["yeni1"] == "Hangi abonelikli araçları yöneteceksin?"
    assert not [n for n in assistant.notes.load(rel)["nodes"] if n.get("kind") == "yon"]  # not before approval

    # the writer unticked the second one
    plan = {**preview, "ask": [preview["ask"][0]["text"]]}
    result = assistant.set_direction(rel, "diger", "Araçları computer use ile yönetsin.", plan)
    asked = [n for n in assistant.notes.load(rel)["nodes"] if n.get("kind") == "yon"]
    assert result["asked"] == 1 and [n["text"] for n in asked] == ["Hangi abonelikli araçları yöneteceksin?"]
    assert asked[0]["status"] == "open" and assistant.notes.find_node(rel, keep["id"])["status"] == "open"
    assert any(kind == "node" and data["node"]["id"] == asked[0]["id"] for kind, data in assistant.broker.events)
    assert any(e["type"] == "question" and e.get("node_id") == asked[0]["id"] for e in assistant.history.items)


@pytest.mark.anyio
async def test_a_value_the_correction_states_is_taken_not_asked_again(writer, monkeypatch):
    """Measured on GPT-4o-mini: 'sadece ben kullanacağım' contradicted
    'Kullanıcı = ekipteki herkes' — the answer is in the correction itself."""
    assistant, rel = writer
    assistant.set_decisions(rel, {"kullanici": True}, by="not", values={"kullanici": "ekipteki herkes"})
    monkeypatch.setattr(llm_client, "plan_direction", lambda *a, **k: llm_client.parse_direction_plan(
        '{"ozet": "Bireysel kullanım.", "guncelle": {"kullanici": "sadece ben", "uydurma": "x"}, '
        '"kararlar": ["kullanici"], "sorular": [], "oneriler": []}', {"kullanici": "Kullanıcı"}, {}, {}))
    preview = await assistant.preview_direction(rel, "kullanici", "Sadece ben kullanacağım.")
    assert preview["update"] == {"kullanici": "sadece ben"} and preview["reopen"] == []
    assistant.set_direction(rel, "kullanici", "Sadece ben kullanacağım.", preview)
    decided = assistant.notes.load(rel)["decisions"]["kullanici"]
    assert decided["by"] == "rota" and decided["value"] == "sadece ben"


@pytest.mark.anyio
async def test_correcting_the_audience_always_offers_that_decision(writer, monkeypatch):
    assistant, rel = writer
    assistant.set_decisions(rel, {"kullanici": True}, by="not", values={"kullanici": "ekip"})
    monkeypatch.setattr(llm_client, "plan_direction", lambda *a, **k: {
        "summary": "Bireysel.", "update": {}, "reopen": [], "drop_questions": [], "drop_proposals": []})
    preview = await assistant.preview_direction(rel, "kullanici", "Tek kişilik olsun.")
    assert preview["reopen"] == ["kullanici"]
    assert llm_client.parse_direction_plan("anlaşılmadı", {}, {}, {}) is None


@pytest.mark.anyio
async def test_without_a_model_the_preview_says_so_and_stays_cautious(writer, monkeypatch):
    assistant, rel = writer
    assistant.set_decisions(rel, {"amac": True}, by="sen")

    def down(*args, **kwargs):
        raise llm_client.ProviderError("kapalı")

    monkeypatch.setattr(llm_client, "plan_direction", down)
    preview = await assistant.preview_direction(rel, "kapsam", "İlk sürüm çok küçük olsun.")
    assert preview["fallback"] is True and preview["reopen"] == ["amac"]


def test_updates_that_repeat_a_decision_or_were_never_said_are_dropped():
    """Measured on DeepSeek V4 Flash for "Sipariş kısmı olmasın, sadece stok takibi
    yapalım": guncelle came back with every decision as it was, plus a platform
    of "stok takibi yapılacak" and parts of "Sadece biz iki çalışan"."""
    decisions = {"kullanici": "Kapsam · Kullanıcı = iki kişilik ekip kullanacak",
                 "platform": "Kapsam · Platform = telefon ve tezgâh ekranı",
                 "parcalar": "Mimari · Ana parçalar = Sadece biz iki çalışan kullanacak",
                 "amac": "Kapsam · Amaç = sipariş ve stok takibi"}
    raw = ('{"ozet": "Yalnız stok takibi.", "guncelle": {"kullanici": "iki kişilik ekip kullanacak", '
           '"platform": "stok takibi yapılacak", "parcalar": "Sadece biz iki çalışan kullanacak", '
           '"amac": "sadece stok takibi"}, "kararlar": [], "sorular": [], "oneriler": []}')
    plan = llm_client.parse_direction_plan(raw, decisions, {}, {}, "kapsam",
                                           correction="Sipariş kısmı olmasın, sadece stok takibi yapalım.")
    assert plan["update"] == {"amac": "sadece stok takibi"}
