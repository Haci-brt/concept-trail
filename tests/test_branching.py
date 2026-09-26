"""A later question keeps its parent and receives that branch's conversation."""
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
def assistant(tmp_path):
    vault = Vault(tmp_path / "vault")
    return Assistant(vault, NoteStore(vault), HistoryStore(vault), Broker(),
                     ProviderRegistry(path=tmp_path / "providers.json"))


def note(assistant):
    return assistant.vault.create_note("", "idea", "# Fikir\n\n## Araştırma\n\nGitHub depoları ve bakım durumu.")


def test_explicit_parent_is_persisted_and_invalid_parent_is_ignored(assistant):
    rel = note(assistant)
    parent = assistant.notes.add_node(rel, "question", "Hangi depoları incelemeliyiz?",
                                      section="Araştırma", status="resolved")
    content = assistant.vault.read_note(rel)["content"]
    assistant._apply_result(rel, content, None,
                            {"type": "questions", "questions": [
                                {"text": "Bu depoların bakımını nasıl değerlendireceğiz?", "parent_id": parent["id"]},
                                {"text": "Katılımı hangi ekranda göstereceğiz?", "parent_id": "missing"},
                            ]}, [])
    questions = [n for n in assistant.notes.load(rel)["nodes"] if n["type"] == "question"]
    assert questions[1]["parentId"] == parent["id"]
    assert questions[2]["parentId"] is None
    reloaded = NoteStore(assistant.vault)
    assert reloaded.find_node(rel, questions[1]["id"])["parentId"] == parent["id"]


def test_fallback_uses_conversation_terms_but_section_alone_does_not_link(assistant):
    rel = note(assistant)
    parent = assistant.notes.add_node(rel, "question", "GitHub depolarını nasıl araştıracağız?",
                                      section="Araştırma", status="resolved")
    assistant.notes.add_node(rel, "chat-user", "Lisans ve bakım durumuna bakacağım.",
                             parent_id=parent["id"])
    content = assistant.vault.read_note(rel)["content"]
    assistant._apply_result(rel, content, None,
                            {"type": "questions", "questions": [
                                {"text": "Lisans ve bakım durumunu hangi ölçütlerle kıyaslayacağız?"},
                                {"text": "Kullanıcı giriş ekranını nasıl sadeleştireceğiz?"},
                            ]}, [])
    questions = [n for n in assistant.notes.load(rel)["nodes"] if n["type"] == "question"]
    assert questions[1]["parentId"] == parent["id"]
    assert questions[2]["parentId"] is None


def test_child_conversation_has_ancestor_turns_and_no_sibling_turns(assistant):
    rel = note(assistant)
    parent = assistant.notes.add_node(rel, "question", "Hangi depoları incelemeliyiz?", status="resolved")
    assistant.notes.add_node(rel, "chat-user", "Önce etkin depoları.", parent_id=parent["id"])
    assistant.notes.add_node(rel, "chat-assistant", "Lisanslarını da kontrol edelim.", parent_id=parent["id"])
    sibling = assistant.notes.add_node(rel, "question", "Bağımsız soru?", status="open")
    assistant.notes.add_node(rel, "chat-user", "Gizli kardeş yanıtı.", parent_id=sibling["id"])
    child = assistant.notes.add_node(rel, "question", "Bu depoları nasıl kıyaslarız?",
                                     parent_id=parent["id"], status="open")
    _, messages = assistant._conversation(rel, child["id"])
    assert "Önce etkin depoları" in messages[0]["content"]
    assert "Lisanslarını da kontrol edelim" in messages[0]["content"]
    assert "Gizli kardeş" not in messages[0]["content"]
    assert "Bu depoları nasıl kıyaslarız?" in messages[0]["content"]


def test_analysis_branch_overview_carries_both_sides_of_prior_chat(assistant):
    rel = note(assistant)
    parent = assistant.notes.add_node(rel, "question", "Hangi depoları incelemeliyiz?", status="resolved")
    assistant.notes.add_node(rel, "chat-user", "Etkin depoları inceleyelim.", parent_id=parent["id"])
    assistant.notes.add_node(rel, "chat-assistant", "Lisans ve sürüm geçmişini karşılaştırabiliriz.",
                             parent_id=parent["id"])
    overview = assistant._question_branches(rel, assistant.notes.load(rel)["nodes"])
    assert parent["id"] in overview
    assert "Etkin depoları" in overview
    assert "Lisans ve sürüm" in overview
    assert len(overview) <= 2500


@pytest.mark.anyio
async def test_chat_model_receives_ancestor_context(assistant, monkeypatch):
    rel = note(assistant)
    parent = assistant.notes.add_node(rel, "question", "Hangi depoları incelemeliyiz?", status="resolved")
    assistant.notes.add_node(rel, "chat-user", "Etkin depoları.", parent_id=parent["id"])
    child = assistant.notes.add_node(rel, "question", "Bunları nasıl sıralayacağız?",
                                     parent_id=parent["id"], status="open")
    seen = {}

    def reply(history, *args, **kwargs):
        seen["history"] = history
        return "ANLADIM\nNOT: Etkin depolar önce sıralanır."

    monkeypatch.setattr(assistant, "provider_for", lambda *args, **kwargs: object())
    monkeypatch.setattr(llm_client, "chat_reply", reply)
    updates = [u async for u in assistant.chat_stream(rel, child["id"], "Etkinliğe göre.")]
    assert any(u["type"] == "done" for u in updates)
    assert "Etkin depoları" in seen["history"][0]["content"]
    assert seen["history"][-1] == {"role": "user", "content": "Etkinliğe göre."}


@pytest.mark.anyio
async def test_ancestor_answer_does_not_enable_summary_without_child_chat(assistant):
    rel = note(assistant)
    parent = assistant.notes.add_node(rel, "question", "İlk soru?", status="resolved")
    assistant.notes.add_node(rel, "chat-user", "İlk yanıt.", parent_id=parent["id"])
    child = assistant.notes.add_node(rel, "question", "Sonraki soru?",
                                     parent_id=parent["id"], status="open")
    with pytest.raises(ApiError) as error:
        await assistant.summarize(rel, child["id"])
    assert error.value.status == 400


def test_research_text_waits_for_approval(assistant):
    rel = note(assistant)
    original = assistant.vault.read_note(rel)["content"]
    result = assistant.propose_text(rel, "## Araç\n\nÖnce şu aracı değerlendir.")
    assert result["node"]["status"] == "pending"
    assert result["proposal"]["status"] == "pending"
    assert result["proposal"]["source"] == "research"
    assert assistant.vault.read_note(rel)["content"] == original
    assistant.hud_action(result["proposal"]["id"], "reject")
    assert assistant.vault.read_note(rel)["content"] == original


def test_corrupt_parent_cycle_stops_lineage(assistant):
    rel = note(assistant)
    a = assistant.notes.add_node(rel, "question", "A")
    b = assistant.notes.add_node(rel, "question", "B", parent_id=a["id"])
    assistant.notes.update_node(rel, a["id"], parentId=b["id"])
    lineage = assistant.notes.question_lineage(rel, b["id"])
    assert len(lineage) == 2
