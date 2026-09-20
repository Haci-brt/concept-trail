"""Prior-art research: the query fan-out, the merge, and the verdict.

No model and no network here. The strategy under test was chosen by measurement,
not taste: five ideas whose answer was known up front were run through four
query styles, and a single model-style sentence found nothing at all while the
union of the styles found a known project for every idea. The tests below pin
that finding down so it cannot be quietly undone.
"""
import pytest

from core import llm_client
from server.research import (Candidate, MAX_GITHUB_QUERIES, build_queries, items_of, merge,
                             payload_of, rank, repos_in_web_results, web_query)


# ---------------------------------------------------------------- the queries
def test_every_proven_style_is_represented():
    styles = {q["style"] for q in build_queries(["html", "markdown", "converter"],
                                                ["html-to-markdown", "markdown"])}
    assert {"topic", "topic-pair", "kisa", "populer"} <= styles


def test_the_style_that_found_nothing_is_never_produced():
    """A long descriptive sentence scored 0/5 in the trial. Nothing may emit one."""
    queries = build_queries(["note", "taking", "markdown", "backlinks", "app", "local"],
                            ["note-taking", "markdown"])
    for entry in queries:
        assert len(entry["query"].split()) <= 4, entry


def test_star_gates_are_there_because_big_projects_hide_without_them():
    queries = [q["query"] for q in build_queries(["llm", "inference"], [])]
    assert any("stars:>5000" in q for q in queries)
    assert any("stars:>20000" in q for q in queries)


def test_topics_become_real_github_qualifiers():
    queries = [q["query"] for q in build_queries([], ["note taking"])]
    assert "topic:note-taking" in queries          # spaces are not valid in a topic


def test_queries_are_unique_and_bounded():
    queries = build_queries(["a", "a", "b"], ["t", "t", "u", "v", "w", "x"])
    assert len(queries) == len({q["query"] for q in queries})
    assert len(queries[:MAX_GITHUB_QUERIES]) <= MAX_GITHUB_QUERIES


def test_nothing_to_go_on_produces_nothing():
    assert build_queries([], []) == []
    assert build_queries(None, None) == []


def test_the_web_query_asks_the_way_a_person_would():
    assert web_query("note taking app") == "best open source note taking app github"
    assert web_query("") == ""


# ---------------------------------------------------------------- the merge
def row(repo, stars=0, **extra):
    return {"repo": repo, "stars": stars, "description": "d", "url": "u", **extra}


def test_a_repo_found_by_several_styles_remembers_all_of_them():
    found = {}
    merge(found, "topic", [row("a/b", 10)])
    merge(found, "populer", [row("a/b", 10)])
    assert found["a/b"].public()["found_by"] == ["populer", "topic"]


def test_corroboration_outranks_popularity():
    """A small project every style agreed on beats a big one seen once: in the
    trial the leaders showed up under several styles at a time."""
    found = {}
    merge(found, "topic", [row("small/one", 50)])
    merge(found, "kisa", [row("small/one", 50)])
    merge(found, "populer", [row("huge/two", 90000)])
    assert [c.repo for c in rank(found)] == ["small/one", "huge/two"]


def test_rows_without_a_name_are_dropped():
    found = {}
    merge(found, "topic", [{"stars": 5}, row("")])
    assert found == {}


def test_ranking_is_capped():
    found = {}
    merge(found, "topic", [row(f"o/r{i}", i) for i in range(30)])
    assert len(rank(found, limit=12)) == 12


# ------------------------------------------------- repos hidden in web results
def web(url, title="t", snippet="s"):
    return {"url": url, "title": title, "snippet": snippet}


def test_repositories_are_lifted_out_of_the_links():
    found = repos_in_web_results([web("https://github.com/Aider-AI/aider"),
                                  web("https://github.com/logseq/logseq/issues/42")])
    assert found == ["Aider-AI/aider", "logseq/logseq"]


def test_githubs_own_pages_are_not_repositories():
    assert repos_in_web_results([web("https://github.com/topics/mcp-server"),
                                 web("https://github.com/search?q=mcp"),
                                 web("https://github.com/features/copilot")]) == []


def test_the_same_repo_twice_is_listed_once_and_the_list_is_capped():
    rows = [web(f"https://github.com/o/r{i}") for i in range(10)] * 2
    assert len(repos_in_web_results(rows, limit=3)) == 3


def test_a_dot_git_suffix_is_not_part_of_the_name():
    assert repos_in_web_results([web("https://github.com/ggml-org/llama.cpp.git")]) == \
        ["ggml-org/llama.cpp"]


def test_nothing_in_the_results_is_not_an_error():
    assert repos_in_web_results([]) == [] and repos_in_web_results(None) == []


# ---------------------------------------------------------------- tool payloads
def envelope(data):
    import json
    return {"ok": True, "result": {"content": [{"type": "text", "text": json.dumps(data)}]}}


def test_the_rows_are_read_from_under_data():
    assert items_of(envelope({"data": {"items": [row("a/b")]}}))[0]["repo"] == "a/b"


def test_a_payload_that_makes_no_sense_is_empty_not_a_crash():
    assert payload_of({"result": {"content": [{"text": "duz metin"}]}}) == {}
    assert payload_of({}) == {} and items_of({}) == []


# ---------------------------------------------------------------- the verdict
def test_search_terms_are_read_off_the_three_lines():
    terms = llm_client.parse_search_terms(
        "ANAHTAR: html, markdown, converter\nKONU: html-to-markdown, markdown\nOZET: convert html")
    assert terms["keywords"] == ["html", "markdown", "converter"]
    assert terms["topics"] == ["html-to-markdown", "markdown"]
    assert terms["summary"] == "convert html"


def test_a_project_the_model_remembered_is_not_a_finding():
    """The whole point is evidence: only repos the search actually returned may
    appear in the verdict, never one the model produced from memory."""
    result = llm_client.parse_prior_art(
        "AYNI: microsoft/markitdown, uydurma/proje\nKOMSU: \nKARAR: Benzer bir is yapiliyor.",
        known=["microsoft/markitdown", "adbar/trafilatura"])
    assert result["same"] == ["microsoft/markitdown"]
    assert result["verdict"] == "Benzer bir is yapiliyor."


def test_a_bare_repo_name_still_matches_the_candidate():
    result = llm_client.parse_prior_art("AYNI: markitdown\nKARAR: var.",
                                        known=["microsoft/markitdown"])
    assert result["same"] == ["microsoft/markitdown"]


def test_an_empty_verdict_is_read_as_nothing_found():
    result = llm_client.parse_prior_art("AYNI:\nKOMSU:\nKARAR: Arama bir eslesme bulamadi.",
                                        known=["a/b"])
    assert result["same"] == [] and result["adjacent"] == []


def test_the_prompt_forbids_calling_an_idea_original():
    """Recall was 2-3 of 5 known projects even at its best, so 'nobody has done
    this' is a claim this feature is never allowed to make."""
    assert "özgün" in llm_client.PRIOR_ART_PROMPT
    assert "KANITLAMAZ" in llm_client.PRIOR_ART_PROMPT
    assert "uydurma" in llm_client.PRIOR_ART_PROMPT


# ---------------------------------------------------------------- the runner
class StubHub:
    def __init__(self, replies=None, registry=("git_search", "web_search", "git_repo")):
        self.registry = {name: {} for name in registry}
        self.replies = replies or {}
        self.calls = []

    @property
    def available(self):
        return bool(self.registry)

    async def call(self, name, arguments):
        self.calls.append((name, arguments))
        return self.replies.get(name, envelope({"data": {"items": []}}))


class StubBroker:
    def __init__(self):
        self.published = []

    def publish(self, kind, data):
        self.published.append((kind, data))


@pytest.fixture
def runner(tmp_path):
    from server.research import ResearchRunner
    from server.store import NoteStore
    from server.vault import Vault
    vault = Vault(tmp_path / "notes")
    notes = NoteStore(vault)
    hub = StubHub()
    run = ResearchRunner(vault, notes, StubBroker(), hub, lambda role, rel=None: object())
    run.hub = hub
    return run


@pytest.mark.anyio
async def test_a_private_note_is_never_researched(runner):
    """Searching publishes the idea to GitHub and to a search engine, so the
    rule that keeps a private note off remote models has to hold here too."""
    from server.errors import ApiError
    runner.is_private = lambda _rel: True
    rel = runner.vault.create_note("", "gizli", "---\ngizli: true\n---\n\nfikir")
    with pytest.raises(ApiError) as err:
        await runner.start(rel, "fikir")
    assert err.value.status == 403
    assert runner.hub.calls == []          # nothing left the machine


@pytest.mark.anyio
async def test_no_tool_servers_means_no_run(runner):
    from server.errors import ApiError
    runner.tool_hub = StubHub(registry=())
    with pytest.raises(ApiError) as err:
        await runner.start("a.md", "fikir")
    assert err.value.status == 503


@pytest.mark.anyio
async def test_a_second_start_while_one_runs_is_refused(runner):
    import asyncio
    rel = runner.vault.create_note("", "fikir", "bir fikir")
    runner.running[rel] = asyncio.create_task(asyncio.sleep(5))
    try:
        assert (await runner.start(rel, "fikir"))["status"] == "busy"
    finally:
        runner.running[rel].cancel()


@pytest.mark.anyio
async def test_a_failing_step_is_recorded_not_swallowed(runner, monkeypatch):
    rel = runner.vault.create_note("", "fikir", "bir fikir")
    monkeypatch.setattr(llm_client, "extract_search_terms",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("model yok")))
    await runner._run(rel, "bir fikir")
    state = runner.state(rel)
    assert state["status"] == "error" and "model yok" in state["error"]
    assert any(kind == "research" and data["step"] == "hata"
               for kind, data in runner.broker.published)


@pytest.mark.anyio
async def test_terms_the_model_could_not_produce_stop_the_run(runner, monkeypatch):
    rel = runner.vault.create_note("", "fikir", "bir fikir")
    monkeypatch.setattr(llm_client, "extract_search_terms",
                        lambda *a, **k: {"keywords": [], "topics": [], "summary": ""})
    await runner._run(rel, "bir fikir")
    assert runner.state(rel)["status"] == "error"
    assert runner.hub.calls == []


def test_a_gist_link_is_not_a_repository():
    """A live run turned gist.github.com/<user>/<hash> into a 404 repo lookup."""
    assert repos_in_web_results([web("https://gist.github.com/paulrobello/ddee910edcbc4d69f38ff57d19a44030")]) == []
    assert repos_in_web_results([web("https://github.com/o/ddee910edcbc4d69f38ff57d19a44030")]) == []
    assert repos_in_web_results([web("https://github.com/o/real-repo")]) == ["o/real-repo"]
