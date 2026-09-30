"""A note renamed while the model reads it keeps what the model then says:
the questions used to land under the old name, a note that no longer existed."""
import asyncio
import threading

import pytest

from core import llm_client
from server.assistant import Assistant
from server.providers import ProviderRegistry
from server.store import HistoryStore, NoteStore
from server.vault import Vault

NOTE = "# Kahve\n\nKüçük bir kafe için sipariş ekranı istiyorum; iki kişi çalışıyoruz.\n"


class Broker:
    def publish(self, kind, data):
        pass


@pytest.fixture
def assistant(tmp_path, monkeypatch):
    vault = Vault(tmp_path / "vault")
    made = Assistant(vault, NoteStore(vault), HistoryStore(vault), Broker(),
                     ProviderRegistry(path=tmp_path / "providers.json"))
    monkeypatch.setattr(made, "provider_for", lambda *a, **k: object())
    monkeypatch.setattr(made, "check_now", lambda *a, **k: None)
    monkeypatch.setattr(type(made), "model_up", property(lambda self: True))
    return made


def rename(assistant, rel, name):
    new = assistant.vault.rename(rel, name)
    assistant.moved(rel, new)
    return new


@pytest.mark.anyio
async def test_questions_of_a_pass_go_to_the_renamed_note(assistant, monkeypatch):
    rel = assistant.vault.create_note("", "Ad değişecek", NOTE)
    reading, go_on = threading.Event(), threading.Event()

    def slow(*args, **kwargs):
        reading.set()
        go_on.wait(5)
        return {"type": "questions", "questions": [{"text": "Siparişi kim alacak?", "kind": "kullanici"}]}

    monkeypatch.setattr(llm_client, "ask_about_note", slow)
    await assistant.analyze(rel, NOTE, force=True)
    await asyncio.to_thread(reading.wait, 5)
    new = rename(assistant, rel, "Kafe")
    go_on.set()
    for task in list(assistant._tasks):
        await task

    asked = [n["text"] for n in assistant.notes.load(new)["nodes"] if n["type"] == "question"]
    assert "Siparişi kim alacak?" in asked
    assert not (assistant.vault.meta_dir / "notes" / f"{rel}.json").exists()
    assert {e["path"] for e in assistant.history.items if e["type"] == "question"} == {new}


@pytest.mark.anyio
async def test_a_chat_reply_goes_to_the_renamed_note(assistant, monkeypatch):
    rel = assistant.vault.create_note("", "Eski ad", NOTE)
    question = assistant.notes.add_node(rel, "question", "Kim kullanacak?", status="open")
    renamed = {}

    def reply(*args, **kwargs):
        renamed["to"] = rename(assistant, rel, "Yeni ad")
        return "ANLADIM\nNOT: İki çalışan kullanacak."

    monkeypatch.setattr(llm_client, "chat_reply", reply)
    updates = [u async for u in assistant.chat_stream(rel, question["id"], "İki çalışan kullanacak")]
    done = next(u for u in updates if u["type"] == "done")
    assert done["proposal"]["path"] == renamed["to"]
    kinds = [n["type"] for n in assistant.notes.load(renamed["to"])["nodes"]]
    assert kinds.count("summary") == 1 and "chat-assistant" in kinds


def test_a_new_note_under_the_old_name_starts_clean(assistant):
    rel = assistant.vault.create_note("", "Taslak", NOTE)
    assistant.notes.add_node(rel, "question", "Eski soru?", status="open")
    new = rename(assistant, rel, "Proje")
    again = assistant.vault.create_note("", "Taslak", "# Taslak\n\nBaşka bir şey.\n")
    assert again == rel
    assert assistant.notes.load(again)["nodes"] == []
    assert len(assistant.notes.load(new)["nodes"]) == 1
