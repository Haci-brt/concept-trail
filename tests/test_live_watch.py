"""The live watch: a quiet pass at natural breaks that never interrupts."""
import asyncio
import threading

import pytest

from core import llm_client
from server.assistant import Assistant
from server.ladder import DECISION_IDS
from server.providers import ProviderRegistry
from server.store import HistoryStore, NoteStore
from server.vault import Vault

SOFTWARE = "# Not senkronu\n\nNotlar hem telefonda hem masaüstünde duracak, ikisi de aynı anda.\n"
IDEA = "---\ntur: fikir\n---\n# Kafe\n\nKöşede masalar olsun, herkes kendi kitabını getirsin.\n"


class Broker:
    def __init__(self):
        self.events = []

    def publish(self, kind, data):
        self.events.append((kind, data))

    def of(self, kind):
        return [data for k, data in self.events if k == kind]


class Model:
    """Stands in for ask_about_note. Blocks until released when told to, and
    stops like the real client does once the pass has been cancelled."""

    def __init__(self, result):
        self.result = result
        self.seen = []          # the note text of every call
        self.gate = None

    def hold(self):
        self.gate = threading.Event()

    def release(self):
        self.gate.set()

    def __call__(self, *args, **kwargs):
        content, should_cancel = args[0], args[6]
        self.seen.append(content)
        if self.gate is not None:
            self.gate.wait(5)
        if should_cancel and should_cancel():
            raise llm_client.Cancelled()
        return self.result


@pytest.fixture
def assistant(tmp_path):
    vault = Vault(tmp_path / "vault")
    a = Assistant(vault, NoteStore(vault), HistoryStore(vault), Broker(),
                  ProviderRegistry(path=tmp_path / "providers.json"))
    a.providers.set_health("local-chat", True)
    return a


@pytest.fixture
def model(monkeypatch):
    fake = Model({"type": "questions", "questions": [{"text": "Web mi, mobil mi olacak?", "kind": "platform"}]})
    monkeypatch.setattr(llm_client, "ask_about_note", fake)
    return fake


async def settle(assistant):
    """Let every spawned pass (and the one it queues) run to the end."""
    for _ in range(50):
        if not assistant._tasks:
            return
        await asyncio.gather(*list(assistant._tasks), return_exceptions=True)


async def running(assistant):
    for _ in range(100):
        if assistant.busy:
            return
        await asyncio.sleep(0.01)


def note(assistant, text=SOFTWARE):
    return assistant.vault.create_note("", "senkron", text)


# ---------------------------------------------------------------- one model
def test_one_model_does_every_job_by_default(assistant):
    status = assistant.status()
    assert status["shared_model"] is True
    assert all(assistant.providers.chain(role)[0].id == "local-chat" for role in ("analysis", "chat", "summary"))
    assert not assistant.providers.get("local-fast").enabled


# ---------------------------------------------------------------- quiet
@pytest.mark.anyio
async def test_a_watch_pass_leaves_its_question_in_the_panel_not_on_the_hud(assistant, model):
    rel = note(assistant)
    content = assistant.vault.read_note(rel)["content"]
    assert (await assistant.analyze(rel, content, force=False))["status"] == "started"
    assert assistant.status()["busy_quiet"] is True
    await settle(assistant)

    assert [n["kind"] for n in assistant.notes.open_questions(rel)] == ["platform"]
    assert assistant.queue == []                              # no card popped up
    assert [e["type"] for e in assistant.history.items] == ["question"]   # but it is in the panel
    assert all(t.get("phase") == "done" for t in assistant.broker.of("thinking"))


@pytest.mark.anyio
async def test_nothing_to_add_is_not_announced_every_pause(assistant, model):
    model.result = {"type": "net"}
    rel = note(assistant, IDEA)
    await assistant.analyze(rel, assistant.vault.read_note(rel)["content"], force=False)
    await settle(assistant)
    assert assistant.broker.of("flash") == []
    assert assistant.history.items == []


@pytest.mark.anyio
async def test_asking_still_puts_the_card_up(assistant, model):
    rel = note(assistant)
    await assistant.analyze(rel, assistant.vault.read_note(rel)["content"], force=True)
    await settle(assistant)
    assert [e["type"] for e in assistant.queue] == ["question"]


@pytest.mark.anyio
async def test_too_little_new_text_does_not_wake_the_model(assistant, model):
    rel = note(assistant)
    content = assistant.vault.read_note(rel)["content"]
    await assistant.analyze(rel, content, force=False)
    await settle(assistant)
    assert (await assistant.analyze(rel, content + "Bir de", force=False))["status"] == "skipped"
    assert len(model.seen) == 1


# ---------------------------------------------------------------- never interrupts
@pytest.mark.anyio
async def test_the_watch_does_not_cancel_a_pass_that_is_still_reading(assistant, model):
    """A 30-55 s pass cancelled at every new pause never finishes for a writer who pauses often."""
    rel = note(assistant)
    content = assistant.vault.read_note(rel)["content"]
    model.hold()
    await assistant.analyze(rel, content, force=False)
    await running(assistant)
    later = content + "Çevrimdışı da çalışsın, bağlantı gelince eşitlesin.\n"
    assert (await assistant.analyze(rel, later, force=False))["status"] == "busy"
    model.release()
    await settle(assistant)
    assert model.seen == [content]                              # not restarted
    assert assistant.notes.open_questions(rel)                  # and its answer was kept


@pytest.mark.anyio
async def test_a_conversation_takes_the_model_from_the_watch(assistant, model):
    rel = note(assistant)
    model.hold()
    await assistant.analyze(rel, assistant.vault.read_note(rel)["content"], force=False)
    await running(assistant)
    with assistant._conversing():
        model.release()
        await settle(assistant)
        assert assistant.notes.open_questions(rel) == []         # it gave way, applied nothing
        assert (await assistant.analyze(rel, SOFTWARE * 2, force=False))["status"] == "busy"
    assert assistant._chatting == 0


# ---------------------------------------------------------------- asking during a watch pass
@pytest.mark.anyio
async def test_asking_while_the_watch_reads_the_same_text_shows_that_pass(assistant, model):
    rel = note(assistant)
    content = assistant.vault.read_note(rel)["content"]
    model.hold()
    await assistant.analyze(rel, content, force=False)
    await running(assistant)
    assert (await assistant.analyze(rel, content, force=True))["status"] == "started"
    assert assistant.status()["busy_quiet"] is False
    model.release()
    await settle(assistant)
    assert len(model.seen) == 1                                 # one pass, not two
    assert [e["type"] for e in assistant.queue] == ["question"]   # and it came out loud


@pytest.mark.anyio
async def test_asking_about_newer_text_looks_again_once_the_old_pass_stops(assistant, model):
    rel = note(assistant)
    content = assistant.vault.read_note(rel)["content"]
    model.hold()
    await assistant.analyze(rel, content, force=False)
    await running(assistant)
    newer = content + "Çevrimdışı da çalışsın, bağlantı gelince eşitlesin.\n"
    assert (await assistant.analyze(rel, newer, force=True))["status"] == "started"
    model.release()
    await settle(assistant)
    assert model.seen == [content, newer]
    assert [e["type"] for e in assistant.queue] == ["question"]


# ---------------------------------------------------------------- the ladder
def test_a_finished_rung_is_quiet_but_the_product_phase_is_not(assistant):
    rel = note(assistant)
    assistant.set_decisions(rel, {d: True for d in ("amac", "kullanici", "platform", "calisma")},
                            by="not", quiet=True)
    assert assistant.broker.of("flash") == []
    assert assistant.broker.of("ladder")[-1]["transition"]["title"] == "Kapsam netleşti"

    assistant.set_decisions(rel, {d: True for d in DECISION_IDS}, by="not", quiet=True)
    assert [f["title"] for f in assistant.broker.of("flash")] == ["Ürün evresi"]
