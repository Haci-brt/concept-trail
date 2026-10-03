"""What still waits for the writer never ages out of the panel, and a proposal
can be decided from the tree even when its history event is gone."""
import pytest

from server import store as store_module
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


def test_settled_events_age_out_waiting_ones_stay(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "HISTORY_LIMIT", 5)
    history = HistoryStore(Vault(tmp_path / "v"))
    history.add({"id": "q", "type": "question", "status": "open", "path": "a.md"})
    history.add({"id": "s", "type": "summary", "status": "pending", "path": "a.md"})
    history.add({"id": "old", "type": "summary", "status": "approved", "path": "a.md"})
    for i in range(10):
        history.add({"id": f"n{i}", "type": "resolved", "path": "b.md"})
    ids = [e["id"] for e in history.items]
    assert {"q", "s"} <= set(ids) and "old" not in ids
    assert ids[:5] == ["n9", "n8", "n7", "n6", "n5"]


def test_a_proposal_without_its_event_is_decided_by_its_node(assistant):
    rel = assistant.vault.create_note("", "n", "# N\n\nMetin.\n")
    question = assistant.notes.add_node(rel, "question", "Kim kullanacak?", status="open")
    summary = assistant.notes.add_node(rel, "summary", "Ailem kullanacak.", parent_id=question["id"],
                                       status="pending")
    assert not assistant.history.items                      # an old vault: no event for it
    assistant.decide_node(rel, summary["id"], "approve")
    assert assistant.notes.find_node(rel, summary["id"])["status"] == "approved"
    assert "Ailem kullanacak." in assistant.written(rel)
    appended = [data for kind, data in assistant.broker.events if kind == "append_note"]
    assert appended and appended[0]["text"] == "Ailem kullanacak."
    assert assistant.notes.find_node(rel, question["id"])["status"] == "resolved"
    with pytest.raises(ApiError):
        assistant.decide_node(rel, summary["id"], "approve")  # decided once


def test_an_edit_is_rejected_by_its_node_and_bad_input_refused(assistant):
    rel = assistant.vault.create_note("", "n", "# N\n\neski cümle\n")
    edit = assistant.notes.add_node(rel, "edit", "eski → yeni", original="eski cümle",
                                    replacement="yeni cümle", status="pending")
    assistant.decide_node(rel, edit["id"], "reject")
    assert assistant.notes.find_node(rel, edit["id"])["status"] == "rejected"
    with pytest.raises(ApiError):
        assistant.decide_node(rel, edit["id"], "sil")
    with pytest.raises(ApiError):
        assistant.decide_node(rel, "yok", "approve")
