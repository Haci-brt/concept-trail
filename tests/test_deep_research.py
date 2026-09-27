"""Competitor analysis: the closest projects looked at closely and compared with the idea."""
import asyncio

import pytest

from core import llm_client
from server import research as R
from server.app import ResearchChoice, _research_proposal_text
from server.store import NoteStore
from server.vault import Vault


def envelope(payload):
    """The tool reply as the MCP servers send it: JSON text, rows under `data`."""
    import json
    return {"ok": True, "result": {"content": [{"type": "text", "text": json.dumps({"data": payload})}]}}


# ---------------------------------------------------------------- reading the model
def test_the_comparison_keeps_only_given_projects_components_and_values():
    raw = ('{"projeler": [{"repo": "foambubble/foam", "ozet": "VS Code içinde not ağı", '
           '"ortak": ["backlink"], "eksik": ["çevrimdışı mobil"], "zayif": ["büyük kasada yavaş"], '
           '"ders": "graf görünümü eklenti olabilir"}, {"repo": "uydurma/proje", "ozet": "x"}], '
           '"tablo": {"Graph visualization": {"foambubble/foam": "kısmen", "uydurma/proje": "var"}, '
           '"Uydurma bileşen": {"foambubble/foam": "var"}, "backlinks": {"foambubble/foam": "belki"}}, '
           '"ayrisma": ["Hiçbiri soru soran bir asistan içermiyor."], "argumanlar": []}')
    result = llm_client.parse_comparison(raw, ["foambubble/foam"], ["graph visualization", "backlinks"])
    assert [p["repo"] for p in result["projects"]] == ["foambubble/foam"]
    assert result["projects"][0]["weak"] == ["büyük kasada yavaş"]
    assert result["matrix"] == {"graph visualization": {"foambubble/foam": "kismen"}}
    assert result["differentiators"] == ["Hiçbiri soru soran bir asistan içermiyor."]


def test_components_get_turkish_names_for_the_reader():
    raw = ('{"projeler": [], "tablo": {"full text search": {"a/b": "var"}}, '
           '"adlar": {"Full text search": "tam metin arama", "uydurma": "x y", "backlinks": "backlinks"}}')
    result = llm_client.parse_comparison(raw, ["a/b"], ["full text search", "backlinks"])
    assert result["matrix"] == {"full text search": {"a/b": "var"}}
    assert result["labels"] == {"full text search": "tam metin arama"}


def test_no_evidence_is_not_a_weakness():
    raw = '{"projeler": [{"repo": "a/b", "zayif": ["Son issue başlıkları okunamadı.", "Büyük PR\'lerde yavaş"]}]}'
    assert llm_client.parse_comparison(raw, ["a/b"], [])["projects"][0]["weak"] == ["Büyük PR'lerde yavaş"]


@pytest.mark.anyio
async def test_the_best_known_projects_are_looked_at_too(runner, monkeypatch):
    """Live: only 0-1 star repos the verdict named were analysed, never Logseq or Joplin."""
    looked = []
    monkeypatch.setattr(llm_client, "compare_projects",
                        lambda note, comps, projects, *a: looked.extend(p["repo"] for p in projects)
                        or {"projects": [], "matrix": {}, "differentiators": [], "arguments": []})
    rel = runner.vault.create_note("", "fikir", "x")
    ranked = [R.Candidate(repo=f"small/r{i}", url="u", stars=i, description="d", topics=[], found_by=["topic"])
              for i in range(6)] + [R.Candidate(repo="logseq/logseq", url="u", stars=45000, description="d",
                                                topics=[], found_by=["topic"])]
    await runner._deep(rel, "x", ranked, {"same": ["small/r0"], "adjacent": ["small/r1"]}, [], {})
    assert looked == ["small/r0", "small/r1", "logseq/logseq"]


@pytest.mark.anyio
async def test_a_famous_list_is_not_a_competitor(runner, monkeypatch):
    looked = []
    monkeypatch.setattr(llm_client, "compare_projects",
                        lambda note, comps, projects, *a: looked.extend(p["repo"] for p in projects)
                        or {"projects": [], "matrix": {}, "differentiators": [], "arguments": []})
    rel = runner.vault.create_note("", "fikir", "x")
    ranked = [
        R.Candidate(repo="trimstray/the-book-of-secret-knowledge", url="u", stars=246000,
                    description="A collection of inspiring lists, manuals, cheatsheets", topics=["knowledge"],
                    found_by=["readme"]),
        R.Candidate(repo="logseq/logseq", url="u", stars=45000, topics=["markdown", "knowledge-graph"],
                    description="Privacy-first knowledge management with Markdown notes, backlinks and graph",
                    found_by=["topic"]),
        R.Candidate(repo="small/notes", url="u", stars=3, topics=[], found_by=["topic"],
                    description="Local-first Markdown notes with backlinks and a knowledge graph")]
    terms = {"keywords": ["Markdown", "knowledge graph", "backlinks"], "components": ["backlinks"]}
    await runner._deep(rel, "x", ranked, {"same": [], "adjacent": []}, [], terms)
    assert "logseq/logseq" in looked and "trimstray/the-book-of-secret-knowledge" not in looked


def test_the_site_comes_from_the_readme():
    """git_repo has no homepage field: no competitor's site had ever been read."""
    text = ("[![Download](https://img.shields.io/badge/x.svg)](https://github.com/logseq/logseq/releases) "
            "Chat: https://discord.gg/KpN4eHY Docs https://docs.example.org and https://logseq.com")
    assert R.readme_homepage(text, "logseq/logseq") == "https://logseq.com"
    assert R.readme_homepage("see https://docs.example.org.", "a/b") == "https://docs.example.org"
    assert R.readme_homepage("![s](https://example.org/shot.png) https://github.com/a/b", "a/b") is None
    assert R.readme_homepage("npm run dev, then open `http://localhost:5173` or http://127.0.0.1:8080", "a/b") is None


def test_a_reply_that_is_no_comparison_leaves_it_empty():
    assert llm_client.parse_comparison("anlaşılmadı", ["a/b"], ["x"])["projects"] == []


def test_repository_facts_and_issue_titles_are_read_whatever_the_names():
    facts = R.repo_facts({"stargazers_count": 16000, "license": {"spdx_id": "MIT"},
                          "pushed_at": "2026-09-01T10:00:00Z", "homepage": "https://foambubble.github.io"})
    assert facts == {"stars": 16000, "license": "MIT", "updated": "2026-09-01",
                     "homepage": "https://foambubble.github.io", "archived": False}
    assert R.issue_titles({"items": [{"title": "Graph is slow"}, {"title": "Graph is slow"}, {"x": 1}]}) == ["Graph is slow"]


# ---------------------------------------------------------------- the stage
class Hub:
    registry = {"git_repo": {}, "git_issues": {}, "web_fetch": {}}

    def __init__(self, slow=()):
        self.calls, self.slow = [], set(slow)

    async def call(self, name, arguments):
        self.calls.append((name, arguments))
        if name in self.slow:
            await asyncio.sleep(5)
        if name == "git_repo":
            return envelope({"stars": 900, "pushed_at": "2026-08-30", "homepage": "https://example.org"})
        if name == "git_issues":
            return envelope({"items": [{"title": "Sync loses notes offline"}]})
        return envelope({"text": "Page text about graphs and backlinks."})


@pytest.fixture
def runner(tmp_path):
    vault = Vault(tmp_path / "vault")

    class Broker:
        def publish(self, *a):
            pass

    return R.ResearchRunner(vault, NoteStore(vault), Broker(), Hub(), lambda role, rel: None)


@pytest.mark.anyio
async def test_the_closest_projects_are_looked_at_and_compared(runner, monkeypatch):
    seen = {}

    def compare(note, components, projects, provider, on_usage):
        seen["projects"] = projects
        return {"projects": [{"repo": "org/notes", "summary": "Not ağı", "shared": [], "missing": [],
                              "weak": ["çevrimdışı eşitleme"], "lesson": ""}],
                "matrix": {"backlinks": {"org/notes": "var"}},
                "differentiators": ["Soru soran asistan yok."], "arguments": ["Önce çevrimdışı."]}

    monkeypatch.setattr(llm_client, "compare_projects", compare)
    rel = runner.vault.create_note("", "fikir", "Markdown not ağı")
    candidate = R.Candidate(repo="org/notes", url="https://github.com/org/notes", stars=10,
                            description="notes", topics=[], found_by=["topic"])
    deep = await runner._deep(rel, "Markdown not ağı", [candidate], {"same": ["org/notes"], "adjacent": []}, [],
                              {"components": ["backlinks"], "keywords": ["markdown"]})
    gathered = seen["projects"][0]
    assert gathered["issues"] == ["Sync loses notes offline"] and gathered["site"].startswith("Page text")
    assert deep["projects"][0]["stars"] == 900 and deep["projects"][0]["weak"] == ["çevrimdışı eşitleme"]
    assert deep["differentiators"][0]["text"] == "Soru soran asistan yok."
    assert deep["differentiators"][0]["id"].startswith("ayr-")


@pytest.mark.anyio
async def test_a_slow_tool_is_skipped_not_waited_on(runner, monkeypatch):
    monkeypatch.setattr(R, "DEEP_CALL_TIMEOUT", 0.05)
    runner.tool_hub = Hub(slow={"git_issues"})
    monkeypatch.setattr(llm_client, "compare_projects",
                        lambda *a, **k: {"projects": [], "matrix": {}, "differentiators": [], "arguments": []})
    rel = runner.vault.create_note("", "fikir", "x")
    candidate = R.Candidate(repo="org/notes", url="https://github.com/org/notes", stars=1,
                            description="d", topics=[], found_by=["topic"])
    deep = await runner._deep(rel, "x", [candidate], {"same": ["org/notes"]}, [], {"components": ["a b"]})
    assert deep["projects"][0]["issues"] == [] and deep["projects"][0]["stars"] == 900


# ---------------------------------------------------------------- into the note
def test_an_insight_can_be_proposed_into_the_note():
    result = {"status": "done", "candidates": [], "tools": [], "opportunities": [], "sources": [],
              "deep": {"differentiators": [{"id": "ayr-1", "kind": "ayrisma", "text": "Hiçbiri çevrimdışı değil."}],
                       "arguments": [{"id": "arg-1", "kind": "arguman", "text": "Önce yerel çalış."}]}}
    text = _research_proposal_text(result, [ResearchChoice(type="insight", id="ayr-1"),
                                            ResearchChoice(type="insight", id="arg-1")])
    assert "- **Ayrışma:** Hiçbiri çevrimdışı değil." in text
    assert "- **Argüman:** Önce yerel çalış." in text


# ---------------------------------------------------------------- web search switched off
class WebHub(Hub):
    registry = {"web_search": {}, "git_search": {}}


@pytest.mark.anyio
async def test_web_search_off_opens_no_browser_window(runner):
    """Every web_search opens a visible Opera window; switched off, none is called."""
    runner.tool_hub = WebHub()
    rel = runner.vault.create_note("", "fikir", "Markdown not ağı")
    runner.web_off.add(rel)
    terms = {"summary": "markdown not ağı", "keywords": ["markdown", "notes"], "components": ["backlinks"]}
    assert await runner._web(rel, terms, [], "Markdown not ağı", []) == []
    await runner._adjacent(rel, terms, "Markdown not ağı", [], [])
    assert [name for name, _ in runner.tool_hub.calls if name == "web_search"] == []


@pytest.mark.anyio
async def test_without_web_search_github_has_to_be_there(runner):
    from server.errors import ApiError
    runner.tool_hub = type("OnlyWeb", (Hub,), {"registry": {"web_search": {}}})()
    rel = runner.vault.create_note("", "fikir", "x")
    with pytest.raises(ApiError):
        await runner.start(rel, "x", web=False)
