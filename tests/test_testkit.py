"""The stand-in model answers every job in the shape the app's parsers take.
If a prompt changes and the stand-in no longer recognises its job, this says
so here, before the browser tests fail somewhere less obvious."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from core import llm_client
from server import ladder
from server.assistant import Assistant
from server.errors import ApiError
from server.providers import ROLES, Provider, ProviderRegistry
from server.store import HistoryStore, NoteStore
from server.vault import Vault
from testkit.__main__ import bind, parse_args
from testkit.fake_model import MODEL_ID, REMOTE_MODEL_ID, FakeModel
from testkit.seed import NOTES, seed_vault

NOTE = ("# Harcama takibi\n\nFişleri fotoğrafla çeken bir telefon uygulaması yapmak istiyorum. Ailem de kullanacak.\n"
        "İnternet yokken de çalışmalı, veriler telefonda dursun.\n")


@pytest.fixture(scope="module")
def provider():
    model = FakeModel().start()
    yield Provider(id="sahte", label="Sahte", base_url=model.base_url, model="sahte-model", kind="local",
                   health="models")
    model.stop()


@pytest.fixture
def offering():
    """The stand-in as the sandbox runs it: it also offers the model's own
    suggestion and a research proposal, once per note text."""
    model = FakeModel(extras=True).start()
    yield model, Provider(id="sahte", label="Sahte", base_url=model.base_url, model=MODEL_ID, kind="local",
                          health="models")
    model.stop()


class Broker:
    def __init__(self):
        self.events = []

    def publish(self, kind, data):
        self.events.append((kind, data))


def assistant_on(root, providers_file) -> Assistant:
    """The app's assistant on a vault of its own, every provider it was given up."""
    vault = Vault(root / "kasa")
    assistant = Assistant(vault, NoteStore(vault), HistoryStore(vault), Broker(),
                          ProviderRegistry(path=providers_file))
    for bound in assistant.providers.all():
        assistant.providers.set_health(bound.id, True)
    return assistant


async def settle(assistant):
    for _ in range(50):
        if not assistant._tasks:
            return
        await asyncio.gather(*list(assistant._tasks), return_exceptions=True)


def test_the_ladder_takes_what_the_note_says_and_asks_the_rest(provider):
    state = ladder.state({})
    said = llm_client.ask_about_note(NOTE, NOTE, [], None, provider, None, None, None, "", ladder.roadmap(state),
                                     "yazilim", state["open"])
    assert set(said["known"]) == {"amac", "kullanici", "platform", "calisma"}
    empty = llm_client.ask_about_note("# Bot\n\nBir şey.\n", "Bir şey.", [], None, provider, None, None, None, "",
                                      ladder.roadmap(state), "yazilim", state["open"])
    assert {q["kind"] for q in empty["questions"]} >= {"kullanici", "platform", "calisma"}


def test_an_idea_note_gets_curiosity_questions(provider):
    idea = "---\ntur: fikir\n---\n# Kitap\n\nApartmanın girişine bir raf koymak istiyorum.\n"
    kinds = [q["kind"] for q in llm_client.ask_about_note(idea, idea, [], None, provider)["questions"]]
    assert kinds == ["derinlestirme", "alternatif"]


def test_a_chat_understands_a_full_answer_and_asks_again_on_a_short_one(provider):
    ask = lambda answer: llm_client.parse_chat_reply(llm_client.chat_reply(
        [{"role": "assistant", "content": "Kim kullanacak?"}, {"role": "user", "content": answer}], NOTE, None, provider))
    assert ask("Ailem de kullanacak, dört kişiyiz") == {"type": "understood", "note": "Ailem de kullanacak, dört kişiyiz"}
    assert ask("bilmem")["type"] == "question"


def test_an_option_chosen_after_ideas_becomes_the_decision(provider):
    def chat(*turns, ideas=False):
        history = [{"role": "assistant", "content": "İki aracı nasıl haberleştireceksin?"}]
        history += [{"role": ("user", "assistant")[i % 2], "content": text} for i, text in enumerate(turns)]
        return llm_client.parse_chat_reply(llm_client.chat_reply(history, NOTE, None, provider, wants_ideas=ideas))

    offered = chat("bilmiyorum", ideas=True)
    assert offered["type"] == "ideas" and offered["text"].startswith("- Ortak bir klasör")
    options = offered["text"]                                   # as the app keeps them: the tag taken off
    assert chat("bilmiyorum", options, "ilkini yapalım") == {
        "type": "understood",
        "note": "Karar: Ortak bir klasör — kolay kurulur, ama aynı dosyaya iki araç birden yazabilir."}
    advised = chat("bilmiyorum", options, "önerdiğin olsun")     # the one it said it would choose
    assert advised["type"] == "understood" and advised["note"].startswith("Karar: Bir görev listesi — ")
    assert chat("bilmiyorum", options, "tamam") == chat("bilmiyorum", options, "ikincisi olsun") == advised
    assert chat("bilmiyorum", options, "hmm")["type"] == "question"             # no pick: asked again
    assert chat("Bilmem", "Kim kullanacak?", "tamam")["type"] == "question"      # nothing was offered


def test_each_lens_offers_a_suggestion_grounded_in_the_note_once_per_text(offering, provider):
    _, offers = offering
    roadmap = ladder.roadmap(ladder.state({}))
    said = {}
    for number, lens in enumerate(ladder.LENSES, start=1):
        note = f"{NOTE}\nSürüm {number}.\n"                      # a text of its own for each pass
        extras = llm_client.offer_extras(note, roadmap + ladder.lens_line(lens), offers)
        assert extras["basis"] == "Fişleri fotoğrafla + İnternet yokken"      # both found in the note
        said[lens[0]] = extras["suggestion"]
    assert len(set(said.values())) == len(ladder.LENSES)
    assert "şifreli" in said["guvenlik"] and "İlk sürüm" in said["urun"]
    again = llm_client.offer_extras(note, roadmap + ladder.lens_line(ladder.LENSES[0]), offers)
    assert again == {}                                           # the same text: nothing new
    assert llm_client.offer_extras(NOTE, roadmap, provider) == {}     # off unless asked for (the browser tests)


def test_the_research_proposal_names_a_capability_the_note_needs(offering):
    _, offers = offering
    roadmap = ladder.roadmap(ladder.state({})) + ladder.lens_line(ladder.LENSES[1])
    research = llm_client.offer_extras(NOTE, roadmap, offers)["research"]
    assert research["topic"] == "fiş fotoğrafından tutar okuma" and research["why"]
    plant = llm_client.offer_extras(NOTES["Bitki hatırlatıcı.md"], roadmap, offers)
    assert plant["research"]["topic"] == "zamanlanmış hatırlatma bildirimleri" and plant["suggestion"]


@pytest.mark.anyio
async def test_the_app_shows_the_suggestion_with_its_lens_and_the_research_offer(offering, tmp_path):
    model, _ = offering
    assistant = assistant_on(tmp_path, bind(tmp_path / "ayar", model.base_url, parse_args([])))
    rel = assistant.vault.create_note("", "Harcama", NOTE)
    offered = lambda: [n for n in assistant.notes.load(rel)["nodes"] if n.get("source") == "model"]
    await assistant.analyze(rel, NOTE, True)
    await settle(assistant)
    assert [(n["lens"], n["status"]) for n in offered()] == [("mimar", "pending")]
    research = [e for e in assistant.history.items if e["type"] == "research"]
    assert len(research) == 1 and research[0]["topic"] == "fiş fotoğrafından tutar okuma"

    await assistant.analyze(rel, NOTE, True)                     # asked again, nothing written since
    await settle(assistant)
    assert len(offered()) == 1


def test_the_remote_flag_binds_the_stand_in_as_a_remote_provider_first(tmp_path):
    url = "http://127.0.0.1:9"
    alone_local = ProviderRegistry(path=bind(tmp_path / "a", url, parse_args([])))
    assert [(p.id, p.kind) for p in alone_local.all()] == [("sahte", "local")]

    registry = ProviderRegistry(path=bind(tmp_path / "b", url, parse_args(["--uzak"])))
    far, near = registry.chain("analysis")
    assert (far.kind, far.model, far.base_url) == ("remote", REMOTE_MODEL_ID, url)
    assert (near.kind, near.model, near.base_url) == ("local", MODEL_ID, url)
    assert all([p.id for p in registry.chain(role)] == ["sahte-uzak", "sahte"] for role in ROLES)

    alone_remote = ProviderRegistry(path=bind(tmp_path / "c", url, parse_args(["--yalniz-uzak"])))
    assert [(p.id, p.kind) for p in alone_remote.all()] == [("sahte-uzak", "remote")]
    with pytest.raises(SystemExit):
        parse_args(["--uzak", "--gercek-model"])                # there is no stand-in to bind


@pytest.mark.anyio
async def test_a_private_note_never_reaches_the_remote_provider(tmp_path):
    model = FakeModel().start()
    try:
        assistant = assistant_on(tmp_path, bind(tmp_path / "ayar", model.base_url, parse_args(["--uzak"])))
        private = assistant.vault.create_note("", "Maaş planı", NOTES["Maaş planı.md"])
        public = assistant.vault.create_note("", "Harcama", NOTE)
        for role in ROLES:                                       # every job: master prompt, completion too
            assert assistant.provider_for(role, private).kind == "local"
            assert assistant.provider_for(role, public).kind == "remote"
        assistant.tool_hub = SimpleNamespace(available=True)     # research tools up, a provider that takes them
        with_tools = replace(assistant.provider_for("chat", public), tools=True)
        assert assistant.tools_allowed(with_tools, public) and not assistant.tools_allowed(with_tools, private)

        for rel in (private, public):                            # a pass, then an answer in its chat
            await assistant.analyze(rel, assistant.vault.read_note(rel)["content"], True)
            await settle(assistant)
            waiting = assistant.notes.open_questions(rel)[0]
            async for _ in assistant.chat_stream(rel, waiting["id"], "Ailem de kullanacak, dört kişiyiz"):
                pass
        about = {(call["note"], call["model"]) for call in model.calls}
        assert ("Maaş planı", MODEL_ID) in about and ("Maaş planı", REMOTE_MODEL_ID) not in about
        assert ("Harcama takibi", REMOTE_MODEL_ID) in about

        alone = assistant_on(tmp_path / "yalniz", bind(tmp_path / "ayar2", model.base_url,
                                                       parse_args(["--yalniz-uzak"])))
        private = alone.vault.create_note("", "Maaş planı", NOTES["Maaş planı.md"])
        with pytest.raises(ApiError) as refused:                 # no local model: no model at all
            alone.provider_for("analysis", private)
        assert refused.value.status == 503 and "gizli" in refused.value.message
        before = len(model.calls)
        await alone.analyze(private, NOTES["Maaş planı.md"], True)
        await settle(alone)
        assert len(model.calls) == before
    finally:
        model.stop()


def test_the_rest_of_the_line_follows_the_note_language(provider):
    assert llm_client.inline_completion("# X\n\nHerkes okuduğu kitabı", "", provider) == " ve bunu olabildiğince sade tutar."
    assert llm_client.inline_completion("# X\n\nIt must work", "", provider) == " and keeps it as simple as possible."


def test_the_master_prompt_has_every_section_and_nothing_left_open(provider):
    raw = llm_client._complete([{"role": "system", "content": llm_client.MASTER_PROMPT_SYSTEM},
                                {"role": "user", "content": NOTE}], temperature=0.2, max_tokens=4000,
                               provider=provider)
    headings = [line for line in raw.splitlines() if line.startswith("## ")]
    assert len(headings) == 19 and not llm_client.unresolved_lines(raw)
    assert len(llm_client.master_assumptions(raw)) >= 2


def test_the_connection_check_and_the_sample_vault(provider, tmp_path):
    assert llm_client.probe(provider) == "tamam"
    written = seed_vault(tmp_path)
    assert set(NOTES) <= set(written) and {"Uzun not.md", "Büyük ağaç.md"} <= set(written)
    assert len((tmp_path / "Uzun not.md").read_text(encoding="utf-8")) > 20000
    assert seed_vault(tmp_path) == []                        # what is there is never overwritten
