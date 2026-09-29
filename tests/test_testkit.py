"""The stand-in model answers every job in the shape the app's parsers take.
If a prompt changes and the stand-in no longer recognises its job, this says
so here, before the browser tests fail somewhere less obvious."""
import pytest

from core import llm_client
from server import ladder
from server.providers import Provider
from testkit.fake_model import FakeModel
from testkit.seed import NOTES, seed_vault

NOTE = ("# Harcama takibi\n\nFişleri fotoğrafla çeken bir telefon uygulaması yapmak istiyorum. Ailem de kullanacak.\n"
        "İnternet yokken de çalışmalı, veriler telefonda dursun.\n")


@pytest.fixture(scope="module")
def provider():
    model = FakeModel().start()
    yield Provider(id="sahte", label="Sahte", base_url=model.base_url, model="sahte-model", kind="local",
                   health="models")
    model.stop()


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
