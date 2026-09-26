"""Prior-art research: the query fan-out, the merge, and the verdict.

No model and no network here. The strategy under test was chosen by measurement,
not taste: five ideas whose answer was known up front were run through four
query styles, and a single model-style sentence found nothing at all while the
union of the styles found a known project for every idea. The tests below pin
that finding down so it cannot be quietly undone.
"""
import pytest
import json

from core import llm_client
from server.research import (Candidate, MAX_GITHUB_QUERIES, MAX_WEB_READS, build_queries,
                             build_support_queries, support_web_queries, diverse_helpers,
                             adjacent_web_query, relevance_score, evidence_excerpt,
                             select_sources_for_fetch, source_prefetch_score,
                             candidate_fit_score, evidence_fallback, calibrate_prior_art,
                             route_helper_products,
                             apply_page_read,
                             sources_in_web_results, prioritized_sources,
                             items_of, merge, payload_of,
                             rank, repos_in_web_results, web_query)


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


def test_both_star_gates_fit_in_actual_six_query_budget():
    queries = build_queries(["note", "taking", "markdown"],
                            ["note-taking", "markdown", "pkm"])[:MAX_GITHUB_QUERIES]
    assert len(queries) <= MAX_GITHUB_QUERIES
    assert any("stars:>5000" in q["query"] for q in queries)
    assert any("stars:>20000" in q["query"] for q in queries)


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


def test_support_searches_cover_reusable_parts_with_bounded_short_queries():
    queries = build_support_queries(["markdown", "editor", "local"], ["note-taking"])
    assert {q["style"] for q in queries} == {"topic-library", "sdk", "library", "toolkit"}
    assert all(len(q["query"].split()) <= 3 for q in queries)
    assert support_web_queries(["markdown", "editor"], []) == [
        "markdown editor open source libraries tools",
        "markdown editor implementation architecture examples"]


def test_note_components_drive_distinct_tool_and_architecture_searches():
    queries = build_support_queries(["note", "taking"], ["note-taking"],
                                    ["syntax highlighting", "graph visualization"])
    assert "syntax highlighting" in [q["query"] for q in queries]
    assert "graph visualization" in [q["query"] for q in queries]
    assert support_web_queries(["note", "taking"], ["note-taking"],
                               ["syntax highlighting", "graph visualization"]) == [
        "javascript network graph nodes edges interactive library",
        "syntax highlighting parser library"]


def test_adjacent_query_explores_approaches_instead_of_more_product_names():
    assert adjacent_web_query(["notes"], ["graph visualization"]) == \
        "graph visualization alternative approaches use cases"


def test_all_four_named_components_fit_in_support_search_budget():
    parts = ["question linking", "memory retrieval", "graph visualization", "research sourcing"]
    queries = build_support_queries(["local markdown", "idea tree"], ["note-taking"], parts)
    assert all(any(query["query"].startswith(part) for query in queries) for part in parts)
    assert "memory retrieval markdown notes" in {q["query"] for q in queries}
    assert len(queries) <= 6


def test_helper_shortlist_represents_each_searched_component():
    found = {}
    for i in range(12):
        merge(found, "component-2", [row(f"memory/r{i}", 10000 - i)])
    merge(found, "component-1", [row("links/tool", 1)])
    merge(found, "component-3", [row("graph/tool", 1)])
    shortlist = diverse_helpers(found, ["question linking", "memory retrieval", "graph visualization"],
                                limit=10)
    assert {"links/tool", "graph/tool"} <= {candidate.repo for candidate in shortlist}
    assert len(shortlist) == 10


def test_helper_shortlist_excludes_seo_profile_excel_and_hacker_noise():
    note_terms = {"summary": "A local Markdown notebook with backlinks and graph views",
                  "keywords": ["markdown", "backlinks", "graph visualization"],
                  "components": ["backlinking", "graph visualization"]}
    note_rows = {
        "didi/LogicFlow": Candidate("didi/LogicFlow", description="Flow chart editing framework",
                                     found_by=["component-2"]),
        "noise/seo": Candidate("noise/seo", description="SEO backlinks and rank tracking",
                               found_by=["component-1"]),
        "api-evangelist/logseq": Candidate("api-evangelist/logseq",
            description="Independent third-party profile of a public API surface",
            found_by=["component-2"]),
    }
    selected = diverse_helpers(note_rows, note_terms["components"], note_terms["keywords"],
                               terms=note_terms)
    assert [row.repo for row in selected] == ["didi/LogicFlow"]
    assert candidate_fit_score(note_rows["noise/seo"], note_terms) < 0

    web_terms = {"summary": "Web research assistant with page extraction and robots rules",
                 "keywords": ["web research", "page extraction"],
                 "components": ["text extraction", "robots.txt respect"]}
    web_rows = {
        "adbar/trafilatura": Candidate("adbar/trafilatura",
            description="Crawling, scraping and text extraction on the Web",
            found_by=["component-1"]),
        "noise/scraper-to-excel": Candidate("noise/scraper-to-excel",
            description="Web scraper that exports Excel files", found_by=["component-1"]),
        "noise/Xsearch4Hacker": Candidate("noise/Xsearch4Hacker",
            description="Search webpages by keyword", found_by=["component-1"]),
    }
    assert [row.repo for row in diverse_helpers(web_rows, web_terms["components"],
        web_terms["keywords"], terms=web_terms)] == ["adbar/trafilatura"]


def test_whole_note_apps_move_to_comparable_projects_but_plugins_stay_tools():
    terms = {"summary": "Local Markdown notes with backlinks and graph view",
             "components": ["backlinking", "graph visualization", "full-text search"]}
    prior = {"other/notebook": Candidate("other/notebook", description="Markdown notes app")}
    helpers = {
        "paragon-ux/trellis": Candidate("paragon-ux/trellis",
            description="Knowledge garden: Markdown notes, backlinks, search and graph view",
            found_by=["component-1"]),
        "iwe-org/vscode-iwe": Candidate("iwe-org/vscode-iwe",
            description="VS Code extension for Markdown notes with backlinks",
            found_by=["component-1"]),
        "graph/lib": Candidate("graph/lib", description="Graph visualization JavaScript library",
            found_by=["component-2"]),
    }
    route_helper_products(prior, helpers, terms)
    assert "paragon-ux/trellis" in prior
    assert "paragon-ux/trellis" not in helpers
    assert {"iwe-org/vscode-iwe", "graph/lib"} <= set(helpers)


def test_model_terms_cannot_inject_search_qualifiers():
    queries = build_support_queries(["markdown stars:>999999", "editor"], ["note-taking stars:>1"])
    assert all("stars:" not in q["query"] for q in queries)


def test_multiword_keywords_search_as_words_not_literal_hyphenated_terms():
    queries = build_queries(["local markdown", "idea tree", "ai memory"], ["note-taking"])
    short = next(q["query"] for q in queries if q["style"] == "kisa")
    assert short == "local markdown idea"
    assert len(short.split()) == 3


def test_markdown_backlinks_do_not_search_seo_backlinking():
    terms = {"keywords": ["local-first", "markdown", "knowledge graph", "backlinks",
                          "full-text search", "graph visualization"],
             "topics": ["local-first", "markdown-notebook", "knowledge-graph", "full-text-search"],
             "components": ["backlinking", "graph visualization", "full-text search", "markdown editing"],
             "summary": "A local Markdown notebook with backlinks, graph views, and full-text search."}
    prior = build_queries(terms["keywords"], terms["topics"], terms["summary"])
    support = build_support_queries(terms["keywords"], terms["topics"],
                                    terms["components"], terms["summary"])
    assert prior[0]["query"] == "topic:markdown-notebook"
    assert prior[1]["query"] == "topic:knowledge-graph"
    assert {q["query"] for q in support} >= {
        "backlinking markdown notes", "full-text search markdown notes"}
    assert support_web_queries(terms["keywords"], terms["topics"], terms["components"],
                               terms["summary"]) == [
        "javascript network graph nodes edges interactive library",
        "full-text search local library engine"]
    assert adjacent_web_query(terms["keywords"], terms["components"], terms["topics"],
                              terms["summary"]).startswith("backlinking markdown notes")
    assert len(prior) + len(support) + 4 == 14  # prior web, two support web, adjacent web


def test_web_research_searches_pages_instead_of_generic_extraction():
    terms = {"keywords": ["evidence-based", "web research", "page extraction", "crawler",
                          "citation", "safe fetching"],
             "topics": ["web research", "local workspace", "page extraction", "robot compliance"],
             "components": ["text extraction", "citation generation", "robots.txt respect", "SSRF blocking"],
             "summary": "A local research assistant that extracts and cites web page content."}
    prior = build_queries(terms["keywords"], terms["topics"], terms["summary"])
    support = build_support_queries(terms["keywords"], terms["topics"],
                                    terms["components"], terms["summary"])
    assert [q["query"] for q in prior[:2]] == ["topic:web-research", "topic:page-extraction"]
    assert support[0]["query"] == "text extraction web pages"
    assert support[1]["query"] == "citation generation web pages"
    assert len(support) == 4


@pytest.mark.anyio
async def test_helper_readme_becomes_verified_source(runner):
    from server.research import Candidate

    rel = runner.vault.create_note("", "readme", "# Fikir\nGrafik gösterimi")
    candidate = Candidate(repo="org/graph", description="Interactive graph visualization",
                          url="https://github.com/org/graph", found_by=["component-1"])
    runner.tool_hub = StubHub({"web_fetch": envelope({"data": {"text": "Interactive graph API"}})},
                              registry=("web_fetch",))
    sources = []
    await runner._fetch_helper_docs(rel, "# Fikir\nGrafik gösterimi", {candidate.repo: candidate},
                                    sources, {"components": ["graph visualization"]})
    assert sources[0]["url"] == candidate.url
    assert sources[0]["verified"] is True
    assert "Interactive graph API" in sources[0]["excerpt"]


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


def test_relevance_breaks_a_corroboration_tie_before_stars():
    found = {}
    merge(found, "sdk", [row("a/other", 10000, description="generic"),
                         row("b/markdown", 5, description="markdown editor")])
    assert rank(found, keywords=["markdown"])[0].repo == "b/markdown"


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


def test_sources_drop_private_urls_and_mark_snippets_unverified():
    sources = sources_in_web_results([web("http://127.0.0.1/admin"),
                                      web("https://docs.example.org/editor", "Docs", "Has APIs")],
                                     "editor library", "support")
    assert len(sources) == 1
    assert sources[0]["url"] == "https://docs.example.org/editor"
    assert sources[0]["verified"] is False and sources[0]["read_error"] is None


def test_serp_title_breadcrumb_is_removed_without_changing_source_url():
    url = "https://codelit.io/blog/search-engine-architecture"
    raw = "codelit.io https://codelit.io › blog › " \
          "search-engine-architecture Search Engine Architecture: How Search Works"
    source = sources_in_web_results([web(url, raw, raw)],
        "search architecture", "support")[0]
    assert source["url"] == url
    assert source["title"] == "Search Engine Architecture: How Search Works"
    assert source["snippet"] == ""


def test_note_graph_prefetch_rejects_seo_and_generic_search_architecture():
    terms = {"summary": "Markdown notebook with backlinks and full-text search",
             "keywords": ["markdown", "backlinks", "full-text search"],
             "components": ["backlinking", "full-text search"]}
    sources = [
        {"url": "https://abun.com/backlinking-strategies", "title": "Backlink Strategies for SEO",
         "kind": "adjacent", "query": "backlinks", "snippet": "organic traffic"},
        {"url": "https://sysdesign.wiki/guides/full-text-search/",
         "title": "Full-Text Search - Practical System Design Guide", "kind": "support",
         "query": "search", "snippet": "sysdesign.wiki https://sysdesign.wiki › guides › full-text-search"},
        {"url": "https://notes.example.org/docs/backlinks",
         "title": "Markdown note backlinks API", "kind": "support",
         "query": "backlinks", "snippet": "Links between notes and graph view"},
    ]
    assert [s["url"] for s in select_sources_for_fetch(sources, terms)] == [
        "https://notes.example.org/docs/backlinks"]


def test_primary_graph_library_page_can_be_read_without_markdown_words():
    terms = {"summary": "Markdown notebook with a graph view",
             "keywords": ["markdown", "graph visualization"],
             "components": ["graph visualization"]}
    source = {"url": "https://graph.example.org/docs/api", "title": "Graph visualization library API",
              "snippet": "Render interactive node diagrams", "kind": "support",
              "query": "javascript network graph nodes edges interactive library"}
    assert source_prefetch_score(source, terms) >= 2
    assert select_sources_for_fetch([source], terms) == [source]


def test_page_research_prefetch_favors_implementation_docs_over_definition_pages():
    terms = {"summary": "Web research assistant that extracts and cites page content",
             "keywords": ["web research", "page extraction", "citation"],
             "components": ["text extraction", "robots.txt respect"]}
    rows = [
        {"url": "https://parseur.com/blog/text-extraction", "title": "What is text extraction?",
         "kind": "adjacent", "query": "extraction", "snippet": "Text extraction use cases"},
        {"url": "https://crawlee.dev/python/docs/examples/respect-robots-txt-file",
         "title": "Respect robots.txt file | Crawlee for Python", "kind": "support",
         "query": "robots", "snippet": "Crawler API example"},
        {"url": "https://zenodo.org/robots-study.pdf", "title": "Robots.txt standard",
         "kind": "support", "query": "robots", "snippet": "Web crawling study"},
    ]
    assert source_prefetch_score(rows[1], terms) > source_prefetch_score(rows[0], terms)
    assert [s["url"] for s in select_sources_for_fetch(rows, terms)] == [rows[1]["url"]]
    assert MAX_WEB_READS == 4


def test_verified_support_sources_survive_a_full_source_budget():
    sources = [{"url": f"https://example.org/{i}", "kind": "prior", "verified": False}
               for i in range(10)]
    sources.append({"url": "https://docs.example.org/tool", "kind": "support", "verified": True})
    kept = prioritized_sources(sources, limit=10)
    assert len(kept) == 10
    assert kept[0]["url"] == "https://docs.example.org/tool"


def test_synthetic_retrieval_prefers_relevant_lower_result_across_intents():
    """A first-result preview misses the mechanism page; diversified reads find it."""
    terms = {"keywords": ["markdown", "editor"],
             "components": ["syntax highlighting", "graph visualization"]}
    rows = [
        {"url": "https://example.org/general", "title": "Best software", "snippet": "List",
         "query": "tools", "kind": "support"},
        {"url": "https://example.org/syntax", "title": "Syntax highlighting library",
         "snippet": "Markdown editor parser", "query": "tools", "kind": "support"},
        {"url": "https://example.net/graph", "title": "Graph visualization architecture",
         "snippet": "Node layout for markdown editor", "query": "architecture", "kind": "support"},
        {"url": "https://example.com/adjacent", "title": "Knowledge graph alternative",
         "snippet": "Graph visualization use case", "query": "alternatives", "kind": "adjacent"},
    ]
    selected = select_sources_for_fetch(rows, terms, limit=3)
    assert {row["url"] for row in selected} == {
        "https://example.org/syntax", "https://example.net/graph",
        "https://example.com/adjacent"}
    assert "https://example.org/general" not in {row["url"] for row in selected}


def test_page_body_produces_full_content_and_relevant_evidence_window():
    terms = {"keywords": ["markdown"], "components": ["syntax highlighting"]}
    page = "Intro and navigation.\n" * 300 + \
           "\nSyntax highlighting for markdown with token scopes and extension hooks.\n" + \
           "Footer link.\n" * 300
    source = {"url": "https://docs.example.org/highlight", "title": "Docs",
              "verified": False, "read_error": None}
    apply_page_read(source, envelope({"text": page}), terms)
    assert source["verified"] is True
    assert "Syntax highlighting" in source["excerpt"]
    assert len(source["content"]) == 8000
    assert source["relevance"] == relevance_score(source["content"] + " Docs", terms)


def test_failed_page_read_is_not_marked_as_verified():
    source = {"url": "https://docs.example.org/missing", "verified": False}
    apply_page_read(source, {"ok": False}, {"keywords": ["markdown"]})
    assert source["verified"] is False
    assert source["read_error"] and "content" not in source


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


def test_search_terms_include_functional_components_when_present():
    terms = llm_client.parse_search_terms(
        "ANAHTAR: notes, graph\nKONU: note-taking\n"
        "BILESEN: graph visualization, syntax highlighting\nOZET: notes app")
    assert terms["components"] == ["graph visualization", "syntax highlighting"]


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


@pytest.mark.parametrize("claim", [
    "Bu fikir özgün.", "Bu orijinal bir proje.", "Bunu kimse yapmamış.",
    "İlk sensin.", "Böyle bir uygulama daha önce yapılmamış.",
])
def test_model_originality_claim_is_neutralized_even_if_prompt_is_ignored(claim):
    result = llm_client.parse_prior_art(f"AYNI:\nKOMSU:\nKARAR: {claim}", known=[])
    assert result["verdict"] == "Bu aramada eşleşme bulunamadı; sonuçlar sınırlı."


def test_originality_filter_does_not_deny_a_real_match():
    result = llm_client.parse_prior_art(
        "AYNI: real/editor\nKOMSU:\nKARAR: Bu fikir özgün.", known=["real/editor"])
    assert result["same"] == ["real/editor"]
    assert result["verdict"] == "Bulunan projelerle benzerlikler var; sonuçlar sınırlı."


def test_empty_model_verdict_falls_back_only_to_supported_feature_overlap():
    terms = {"summary": "Markdown notebook with backlinks and full-text search",
             "components": ["backlinking", "graph visualization", "full-text search", "markdown editing"]}
    candidates = [Candidate("noise/markdown-list", description="Curated Markdown links"),
                  Candidate("quick-open/note-nest",
                      description="Local Markdown knowledge base with backlinks, tags and full-text search")]
    result = evidence_fallback(candidates, [], terms)
    assert result["same"] == []
    assert result["adjacent"] == ["quick-open/note-nest"]
    assert "noise/markdown-list" not in result["verdict"]
    assert "özgün" not in result["verdict"].lower()
    assert evidence_fallback(candidates[:1] * 15, [], terms)["adjacent"] == []


def test_exact_match_claim_needs_readme_evidence_for_every_component():
    terms = {"summary": "Markdown notebook with backlinks, graph, search and questions",
             "components": ["backlink tracking", "graph visualization", "full-text search",
                            "threaded questions"]}
    candidate = Candidate("real/notes", description="Markdown notes with backlinks, graph view and full-text search",
                          url="https://github.com/real/notes")
    result = calibrate_prior_art(
        {"same": ["real/notes"], "adjacent": [], "verdict": "Bu fikir daha önce yapılmıştır."},
        [candidate], [{"url": candidate.url, "verified": True,
                       "content": "Markdown notes with backlinks, graph view, and full-text search."}],
        terms)
    assert result["same"] == []
    assert result["adjacent"] == ["real/notes"]
    assert "daha önce yapılmıştır" not in result["verdict"]


def test_the_prompt_forbids_calling_an_idea_original():
    """Recall was 2-3 of 5 known projects even at its best, so 'nobody has done
    this' is a claim this feature is never allowed to make."""
    assert "özgün" in llm_client.PRIOR_ART_PROMPT
    assert "KANITLAMAZ" in llm_client.PRIOR_ART_PROMPT
    assert "uydurma" in llm_client.PRIOR_ART_PROMPT


def test_prior_art_model_receives_readme_evidence_but_not_unread_snippets(monkeypatch):
    seen = {}
    def complete(messages, **_kwargs):
        seen["prompt"] = messages[-1]["content"]
        return "AYNI: real/editor\nKOMSU:\nKARAR: Yakın bir örnek var."
    monkeypatch.setattr(llm_client, "_complete", complete)
    llm_client.judge_prior_art("Bir markdown editörü", [{"repo": "real/editor"}],
                              sources=[{"url": "https://github.com/real/editor", "verified": True,
                                        "excerpt": "README: markdown AST ve eklenti arayüzü"},
                                       {"url": "https://example.org/unread", "verified": False,
                                        "excerpt": "UNREAD CLAIM"}])
    assert "markdown AST" in seen["prompt"]
    assert "UNREAD CLAIM" not in seen["prompt"]


def test_recommendations_require_discovered_repos_and_verified_source_urls():
    raw = json.dumps({"tools": [{"repo": "real/library", "why": "Renderer provides parsing"},
                                {"repo": "invented/library", "why": "Magic"}],
                      "opportunities": [
                          {"title": "Use parser", "detail": "Integrate its AST", "source_urls":
                           ["https://github.com/real/library"]},
                          {"title": "Unproved", "detail": "Unknown", "source_urls":
                           ["https://example.org/unread"]}]})
    result = llm_client.parse_research_recommendations(
        raw, [{"repo": "real/library"}],
        [{"url": "https://example.org/unread", "verified": False}])
    assert result["tools"] == [{"repo": "real/library", "why": "Renderer provides parsing"}]
    assert [o["title"] for o in result["opportunities"]] == ["Use parser"]


def test_malformed_recommendation_fields_cannot_crash_parser():
    raw = '{"tools":"fake", "opportunities":[{"title":"X","detail":"Y",' \
          '"source_urls":[{}, [], "https://github.com/o/r"]}]}'
    result = llm_client.parse_research_recommendations(raw, [{"repo": "o/r"}], [])
    assert result["tools"] == []
    assert result["opportunities"][0]["source_urls"] == ["https://github.com/o/r"]


def test_related_question_parent_id_is_parsed_without_breaking_old_format():
    result = llm_client.parse_response("SORU[derinlestirme][q7]: Bunun ikinci adımı ne?\n"
                                       "SORU[alternatif]: Başka yol var mı?")
    assert result["questions"][0]["parent_id"] == "q7"
    assert "parent_id" not in result["questions"][1]


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
async def test_unsaved_private_frontmatter_is_never_researched(runner):
    from server.errors import ApiError
    rel = runner.vault.create_note("", "taslak", "Herkese acik taslak")
    with pytest.raises(ApiError) as err:
        await runner.start(rel, "---\ngizli: true\n---\n\nYeni gizli fikir")
    assert err.value.status == 403
    assert runner.hub.calls == []


@pytest.mark.anyio
async def test_user_focus_is_capped_persisted_and_passed_to_research(runner, monkeypatch):
    rel = runner.vault.create_note("", "taslak", "# Not\nBir fikir")
    seen = []
    async def run(_rel, _content, focus):
        seen.append(focus)
    monkeypatch.setattr(runner, "_run", run)
    result = await runner.start(rel, "# Not\nBir fikir", focus="graph visualization " * 30)
    await runner.running[rel]
    assert result["status"] == "started"
    assert len(result["focus"]) <= 400
    assert seen == [result["focus"]]


@pytest.mark.anyio
async def test_no_tool_servers_means_no_run(runner):
    from server.errors import ApiError
    runner.tool_hub = StubHub(registry=())
    with pytest.raises(ApiError) as err:
        await runner.start("a.md", "fikir")
    assert err.value.status == 503


@pytest.mark.anyio
async def test_builtin_fetch_alone_is_not_a_search_server(runner):
    from server.errors import ApiError
    runner.tool_hub = StubHub(registry=("web_fetch",))
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


@pytest.mark.anyio
async def test_failed_searches_never_become_a_no_match_verdict(runner, monkeypatch):
    rel = runner.vault.create_note("", "fikir", "bir fikir")
    runner.hub = StubHub({"git_search": {"ok": False}, "web_search": {"ok": False}})
    runner.tool_hub = runner.hub
    monkeypatch.setattr(llm_client, "extract_search_terms", lambda *a, **k:
                        {"keywords": ["notes"], "topics": ["note-taking"],
                         "summary": "notes app"})
    await runner._run(rel, "bir fikir")
    state = runner.state(rel)
    assert state["status"] == "error"
    assert "eslesme yok sonucu cikarilamaz" in state["error"]
    assert state.get("verdict") is None


@pytest.mark.anyio
async def test_research_run_collects_tool_evidence_and_stable_opportunity_ids(runner, monkeypatch):
    rel = runner.vault.create_note("", "fikir", "Markdown fikri")
    runner.hub = StubHub({
        "git_search": envelope({"data": {"items": [row("real/editor", 42,
            description="Markdown editor parsing library") ]}}),
        "web_search": envelope({"data": {"results": [
            web("https://docs.example.org/editor", "Markdown editor documentation", "Markdown AST API example"),
            web("https://github.com/real/editor") ]}}),
        "web_fetch": envelope({"text": "Editor parsing API supports Markdown AST."}),
    }, registry=("git_search", "web_search", "git_repo", "web_fetch"))
    runner.tool_hub = runner.hub
    seen_note = []
    def terms_for(note, *_args):
        seen_note.append(note)
        return {"keywords": ["markdown", "editor"], "topics": ["markdown"],
                "summary": "markdown editor"}
    monkeypatch.setattr(llm_client, "extract_search_terms", terms_for)
    monkeypatch.setattr(llm_client, "judge_prior_art", lambda *a, **k:
                        {"same": [], "adjacent": ["real/editor"],
                         "verdict": "Kismi eslesme bulundu."})

    def recommend(_content, helpers, sources, *_args):
        assert helpers and any(source.get("verified") for source in sources)
        return {"tools": [{"repo": "real/editor", "why": "Markdown AST icin aday."}],
                "opportunities": [{"title": "AST dene", "detail": "Editorde AST prototipi kur.",
                                   "source_urls": ["https://docs.example.org/editor"]}]}

    monkeypatch.setattr(llm_client, "recommend_research", recommend)
    await runner._run(rel, "Markdown fikri", focus="graph visualization")
    state = runner.state(rel)
    assert state["status"] == "done", state.get("error")
    assert state["tools"][0]["id"] == "real/editor"
    assert state["opportunities"][0]["id"].startswith("opp-")
    assert any(s["verified"] and s["kind"] == "support" for s in state["sources"])
    assert {q["purpose"] for q in state["queries"]} == {"prior", "support", "adjacent"}
    assert all(q["ok"] for q in state["queries"])
    assert any(name == "web_fetch" for name, _ in runner.hub.calls)
    assert "[ARAŞTIRMA ODAĞI]\ngraph visualization" in seen_note[0]
    assert {"terms", "prior_git", "prior_web", "support", "adjacent", "web_reads",
            "readmes", "prior_judge", "recommendations", "judge", "total"} <= set(state["timings"])
    assert state["timings"]["total"] >= 0


@pytest.mark.anyio
async def test_fetch_reads_distinct_tool_and_architecture_queries(runner):
    rel = runner.vault.create_note("", "fikir", "Bir fikir")
    runner.hub = StubHub({"web_fetch": envelope({"text": "Documented Markdown editor implementation"})},
                         registry=("web_fetch",))
    runner.tool_hub = runner.hub
    sources = [
        {"url": "https://example.org/a", "title": "Markdown editor parser", "query": "tools", "kind": "support", "verified": False},
        {"url": "https://example.org/b", "title": "Markdown editor library", "query": "tools", "kind": "support", "verified": False},
        {"url": "https://example.org/c", "title": "Markdown editor architecture", "query": "architecture", "kind": "support", "verified": False},
    ]
    await runner._fetch_sources(rel, "Bir fikir", sources,
                                {"keywords": ["markdown", "editor"], "summary": "markdown editor"})
    fetched = [args["url"] for name, args in runner.hub.calls if name == "web_fetch"]
    assert fetched[:2] == ["https://example.org/a", "https://example.org/c"]
    assert len(fetched) == 2  # at most two reads from one host
    assert sum(source["verified"] for source in sources) == 2


@pytest.mark.anyio
async def test_verified_branded_graph_library_resolves_one_github_repo(runner):
    rel = runner.vault.create_note("", "graf", "# Markdown notes graph view")
    runner.hub = StubHub({
        "web_fetch": envelope({"text": "Sigma.js is a JavaScript library for graph visualization of nodes and edges."}),
        "git_search": envelope({"data": {"items": [
            row("jacomyal/sigma.js", 12000,
                description="A JavaScript library aimed at visualizing graphs of nodes and edges"),
            row("noise/sigma-docs", 200, description="Unrelated docs"),
        ]}}),
    }, registry=("web_fetch", "git_search"))
    runner.tool_hub = runner.hub
    sources = [{"url": "https://www.sigmajs.org/", "title": "Sigma.js", "snippet": "",
                "query": "javascript network graph nodes edges interactive library",
                "search_rank": 1, "kind": "support", "verified": False}]
    helpers, queries = {}, []
    terms = {"summary": "Markdown notebook with a graph view",
             "keywords": ["markdown", "graph visualization"],
             "components": ["graph visualization"]}
    await runner._fetch_sources(rel, "# Markdown notes graph view", sources, terms,
                                helpers=helpers, query_log=queries)
    assert sources[0]["verified"] and sources[0]["relevance"] >= 2
    assert set(helpers) == {"jacomyal/sigma.js"}
    assert helpers["jacomyal/sigma.js"].evidence_url == "https://www.sigmajs.org/"
    assert [name for name, _ in runner.hub.calls] == ["web_fetch", "git_search"]
    assert queries == [{"purpose": "support", "style": "verified-library",
                        "query": "Sigma.js", "ok": True}]


def test_a_gist_link_is_not_a_repository():
    """A live run turned gist.github.com/<user>/<hash> into a 404 repo lookup."""
    assert repos_in_web_results([web("https://gist.github.com/paulrobello/ddee910edcbc4d69f38ff57d19a44030")]) == []
    assert repos_in_web_results([web("https://github.com/o/ddee910edcbc4d69f38ff57d19a44030")]) == []
    assert repos_in_web_results([web("https://github.com/o/real-repo")]) == ["o/real-repo"]
