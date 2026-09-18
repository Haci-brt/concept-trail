"""The assistant argues with an answer instead of filing it away.

An answer that decides nothing must not end up in the note: the thread stays
open and the assistant says why it is not convinced. Only a real decision —
one that is not already written down — becomes a proposal.
"""
import asyncio

import pytest

from core import llm_client
from server.assistant import Assistant, note_domain, stage_for
from server.providers import ProviderRegistry
from server.store import HistoryStore, NoteStore
from server.vault import Vault

SHORT = "# Bisiklet Rotası\n\nGüvenli rotaları toplayan bir uygulama düşünüyorum.\n"
LONG = "# Bisiklet Rotası\n\n" + ("Uzun uzun anlattığım tek parça bir fikir. " * 30)
SECTIONED = SHORT + "\n## Paylaşım\n\nRotaları sadece tanıdıklarımla paylaşmak isterim.\n"


class FakeBroker:
    def __init__(self):
        self.sent = []

    def publish(self, kind, payload=None):
        self.sent.append((kind, payload))

    def of(self, kind):
        return [p for k, p in self.sent if k == kind]


@pytest.fixture
def app(tmp_path):
    vault = Vault(tmp_path / "notes")
    (vault.root / "rota.md").write_text(SECTIONED, encoding="utf-8")
    broker = FakeBroker()
    assistant = Assistant(vault, NoteStore(vault), HistoryStore(vault), broker,
                          ProviderRegistry(tmp_path / "providers.json"))
    return assistant, broker, vault


def ask(assistant, text="Rotaları kimlerle paylaşacaksın?"):
    return assistant.notes.add_node("rota.md", "question", text, status="open", kind="kapsam", section="")


def answer(assistant, question, message, reply):
    """Run one chat turn with the model's reply stubbed out."""
    async def drive():
        return [u async for u in assistant.chat_stream("rota.md", question["id"], message)]

    return asyncio.run(_with_reply(assistant, drive, reply))


async def _with_reply(assistant, drive, reply):
    original = llm_client.chat_reply
    llm_client.chat_reply = lambda *a, **k: reply
    try:
        updates = await drive()
    finally:
        llm_client.chat_reply = original
    for _ in range(40):                       # the write happens in a spawned task
        if any(u["type"] == "done" for u in updates):
            break
        await asyncio.sleep(0.05)
    return updates


def done_of(updates):
    return next(u for u in updates if u["type"] == "done")


# ---------------------------------------------------------------- staging
def test_a_short_note_gets_questions_about_the_whole_idea():
    assert "BÜTÜNÜNÜ" in stage_for(SHORT, "")


def test_a_long_note_with_no_headings_is_pushed_to_name_its_parts():
    assert "parçalarına ayırmaya" in stage_for(LONG, "")


def test_a_note_with_headings_is_asked_section_by_section():
    stage = stage_for(SECTIONED, "Paylaşım")
    assert "Paylaşım" in stage and "BÖLÜMDEN" in stage


def test_the_section_stage_falls_back_to_the_first_heading():
    assert "Paylaşım" in stage_for(SECTIONED, "")


def test_frontmatter_does_not_count_as_note_length():
    front = "---\ngizli: true\netiketler: [a, b]\n---\n" + SHORT
    assert stage_for(front, "") == stage_for(SHORT, "")


# ---------------------------------------------------------------- what kind of note
def test_architecture_is_the_default_not_a_mode(app):
    # this is a notebook for people designing software; every note is one
    assert note_domain("# Not defteri\n\nSenkronizasyonu modül modül ayıracağım.\n") == "kod"
    assert note_domain("# Boş\n\nHenüz bir şey yazmadım.") == "kod"


@pytest.mark.parametrize("declared", ["fikir", "genel", "not", "gunluk"])
def test_a_note_can_opt_out_in_its_frontmatter(declared):
    assert note_domain(f"---\ntur: {declared}\n---\n# Kafe\n\nKöşede masa olsun.") == "fikir"


@pytest.mark.parametrize("declared", ["kod", "mimari", "teknik", "yazilim"])
def test_declaring_a_software_note_changes_nothing(declared):
    assert note_domain(f"---\ntur: {declared}\n---\n# Plan\n\nBir şey.") == "kod"


def test_software_notes_get_asked_about_state_failures_and_seams():
    prompt = llm_client.DOMAIN_PROMPTS["kod"]
    for topic in ("veri:", "risk:", "sinir:", "kapsam:"):
        assert topic in prompt
    assert "hangi dil/framework" in prompt      # and not about the tech stack


# ---------------------------------------------------------------- pushing back
def test_an_answer_that_decides_nothing_is_argued_with_not_written_down(app):
    assistant, broker, vault = app
    question = ask(assistant)

    updates = answer(assistant, question, "Bakarız, belki güzel olur.",
                     "KARSI: Bu cevap kimin göreceğini söylemiyor. Tanıdık dediğin çember nerede biter?")

    done = done_of(updates)
    assert done["challenge"] is True
    assert done["understood"] is False
    assert done.get("proposal") is None
    assert broker.of("append_note") == []
    assert vault.read_note("rota.md")["content"] == SECTIONED
    assert assistant.notes.find_node("rota.md", question["id"])["status"] == "open"


def test_a_challenge_is_kept_in_the_thread_as_one(app):
    assistant, _, _ = app
    question = ask(assistant)

    answer(assistant, question, "Olabilir.", "KARSI: Bu bir karar değil. Kaç kişiye kadar açarsın?")

    reply = assistant.notes.thread("rota.md", question["id"])[-1]
    assert reply["type"] == "chat-assistant" and reply["challenge"] is True
    assert reply["mode"] == "question"          # the thread is still waiting on you


def test_a_real_decision_becomes_a_proposal(app):
    assistant, broker, vault = app
    question = ask(assistant)

    updates = answer(assistant, question, "Sadece bisiklet grubumdaki 12 kişi görecek.",
                     "ANLADIM\nNOT: Rotaları yalnızca bisiklet grubumdaki 12 kişiyle paylaşacağım.")

    done = done_of(updates)
    assert done["understood"] is True
    assert done["proposal"]["status"] == "pending"
    assert vault.read_note("rota.md")["content"] == SECTIONED      # still only a proposal
    assert broker.of("append_note") == []


def test_understanding_without_anything_new_writes_nothing(app):
    assistant, broker, vault = app
    question = ask(assistant)

    updates = answer(assistant, question, "Zaten notta yazdığım gibi, tanıdıklarımla.", "ANLADIM")

    done = done_of(updates)
    assert done["understood"] is True
    assert done["proposal"] is None
    assert broker.of("append_note") == []
    assert vault.read_note("rota.md")["content"] == SECTIONED
    assert assistant.notes.find_node("rota.md", question["id"])["status"] == "resolved"


def test_the_thread_is_never_written_up_behind_your_back(app, monkeypatch):
    # the old behaviour: once the assistant stopped asking it summarised the
    # whole thread and proposed that. Nothing may reach the note unasked now.
    assistant, broker, _ = app
    question = ask(assistant)
    called = []
    monkeypatch.setattr(llm_client, "summarize_for_note",
                        lambda *a, **k: called.append(1) or "uydurulmuş özet")

    for i in range(4):
        answer(assistant, question, f"{i}. cevabım", "KARSI: Hâlâ bir karar yok. Sınırı nerede çizersin?")

    assert called == []
    assert broker.of("append_note") == []


def test_after_enough_rounds_the_assistant_is_told_to_settle(app):
    assistant, _, _ = app
    question = ask(assistant)
    seen = []

    async def drive():
        return [u async for u in assistant.chat_stream("rota.md", question["id"], "cevap")]

    async def run():
        original = llm_client.chat_reply

        def spy(*args, settle=False, **kwargs):
            seen.append(settle)
            return "KARSI: Yetmedi. Neden?"

        llm_client.chat_reply = spy
        try:
            for _ in range(5):
                await drive()
                await asyncio.sleep(0.05)
        finally:
            llm_client.chat_reply = original

    asyncio.run(run())
    assert seen[0] is False           # the first rounds are a real discussion
    assert seen[-1] is True           # but it is not allowed to go on forever
