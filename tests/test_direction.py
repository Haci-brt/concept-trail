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
