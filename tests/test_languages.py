"""Languages: the assistant writes in the writer's language when asked to,
the parsers' protocol stays, and the choice is kept."""
import json
import re
from pathlib import Path

import pytest

from core import llm_client
from server import ladder
from server.app import FINDING_WORDS, ResearchChoice, _research_proposal_text
from server.errors import ApiError
from server.preferences import LANGUAGES, Preferences

LOCALES = Path(__file__).resolve().parent.parent / "web" / "locales"


@pytest.fixture(autouse=True)
def turkish_again():
    yield
    llm_client.set_output_language("tr")


def captured(monkeypatch, name):
    seen = {}

    def fake(messages, **kwargs):
        seen["system"] = messages[0]["content"]
        return "SORU [amac]: Hangi sorunu çözüyor?"
    monkeypatch.setattr(llm_client, name, fake)
    return seen


def test_turkish_changes_nothing_in_the_prompts(monkeypatch):
    seen = captured(monkeypatch, "_complete")
    llm_client.chat_reply([{"role": "user", "content": "merhaba"}], "not")
    assert "[DİL]" not in seen["system"]
    assert llm_client.language_rule() == ""


@pytest.mark.parametrize("code,name", [("en", "English"), ("de", "Deutsch"), ("es", "Español"), ("fr", "Français")])
def test_every_prompt_the_writer_reads_carries_the_language(monkeypatch, code, name):
    llm_client.set_output_language(code)
    seen = captured(monkeypatch, "_complete")
    llm_client.chat_reply([{"role": "user", "content": "hi"}], "not")
    assert f"— {name} yaz" in seen["system"] and "Protokol etiketlerini" in seen["system"]
    llm_client.summarize_for_note([{"role": "user", "content": "hi"}])
    assert name in seen["system"]
    seen = captured(monkeypatch, "_complete_thinking_capped")
    llm_client.ask_about_note("# Not\nmetin", "metin", [], mode="yazilim")
    assert name in seen["system"]
    llm_client.offer_extras("# Not\nmetin")
    assert name in seen["system"]


def test_search_terms_are_not_forced_into_the_writers_language(monkeypatch):
    llm_client.set_output_language("de")
    seen = captured(monkeypatch, "_complete")
    llm_client.extract_search_terms("# Rezeptbuch")
    assert "[DİL]" not in seen["system"]


def test_an_unknown_language_falls_back_to_turkish():
    llm_client.set_output_language("xx")
    assert llm_client.output_language() == "tr"


def test_the_ladders_own_questions_exist_in_every_language():
    for code in ("en", "de", "es", "fr"):
        assert set(ladder.ASK_IN[code]) == set(ladder.ASK)
        assert all(q.rstrip().endswith("?") for q in ladder.ASK_IN[code].values())
    assert ladder.ask("hata", "de").startswith("Was passiert")
    assert ladder.ask("hata", "tr") == ladder.ASK["hata"]


def test_research_findings_go_into_the_note_in_the_assistants_language():
    result = {"status": "done", "candidates": [{"repo": "mealie-recipes/mealie", "description": "Recipe manager"}]}
    llm_client.set_output_language("fr")
    text = _research_proposal_text(result, [ResearchChoice(type="project", id="mealie-recipes/mealie")])
    assert text.splitlines()[0] == "## Résultats de la recherche"
    assert "**Projet similaire: mealie-recipes/mealie**" in text
    assert all(set(words) == set(FINDING_WORDS["en"]) for words in FINDING_WORDS.values())


def test_the_choice_is_kept_and_checked(tmp_path):
    prefs = Preferences(tmp_path / "preferences.json")
    assert prefs.public()["assistant_language"] == "tr"
    prefs.update({"ui_language": "en", "assistant_language": "de"})
    again = Preferences(tmp_path / "preferences.json")
    assert again.data == {"ui_language": "en", "assistant_language": "de"}
    with pytest.raises(ApiError):
        prefs.update({"ui_language": "xx"})
    with pytest.raises(ApiError):
        prefs.update({"theme": "dark"})


def test_master_prompt_speaks_every_language():
    assert set(llm_client.MASTER_LANGUAGES) == set(LANGUAGES)


# ---------------------------------------------------------------- the interface dictionaries
def locale(code):
    return json.loads((LOCALES / f"{code}.json").read_text(encoding="utf-8"))


def test_every_interface_language_has_the_same_entries():
    keys = set(locale("en"))
    assert len(keys) > 500
    for code in ("de", "es", "fr"):
        assert set(locale(code)) == keys, code


@pytest.mark.parametrize("code", ["en", "de", "es", "fr"])
def test_every_entry_is_translated_and_keeps_its_holes(code):
    for tr, out in locale(code).items():
        assert out.strip(), (code, tr)
        assert sorted(re.findall(r"\{\d+\}", tr)) == sorted(re.findall(r"\{\d+\}", out)), (code, tr, out)
