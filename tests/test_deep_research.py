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
def test_the_comparison_keeps_only_given_projects_and_components():
    raw = ('{"projeler": [{"repo": "foambubble/foam", "ozet": "VS Code içinde not ağı", '
           '"zayif": ["büyük kasada yavaş"], "ders": "Graf görünümü eklenti olarak başlayabilir."}, '
           '{"repo": "uydurma/proje", "ozet": "x"}], '
           '"anahtarlar": {"Graph visualization": ["graph view", "x"], "Uydurma bileşen": ["y y y"]}, '
           '"oneriler": [{"repo": "foambubble/foam", "kanit": "graph visualization of your notes", '
           '"karar": "graph visualization", "oneri": "Graf ilk sürümde salt okunur olmalı, düzenleme sonra; '
           'rakip de böyle başlamış."}, {"repo": "uydurma/proje", "kanit": "a b c", "karar": "veri", '
           '"oneri": "Bir şey yap."}]}')
    result = llm_client.parse_comparison(raw, ["foambubble/foam"], ["graph visualization", "backlinks"])
    assert [p["repo"] for p in result["projects"]] == ["foambubble/foam"]
    assert result["projects"][0]["weak"] == ["büyük kasada yavaş"]
    assert result["keywords"] == {"graph visualization": ["graph view"]}
    assert [a["repo"] for a in result["arguments"]] == ["foambubble/foam"]


def test_a_flat_absence_claim_is_dropped():
    """Measured: "Logseq has no graph view", "none of them offer full-text search"."""
    raw = ('{"projeler": [{"repo": "a/b", "ozet": "Not uygulaması; tam metin arama sunmuyor.", '
           '"ders": "Hiçbiri çevrimdışı çalışmıyor, bu fırsat."}], '
           '"oneriler": [{"repo": "a/b", "kanit": "local first notes", "karar": "veri", '
           '"oneri": "Projelerin hiçbiri yerel arama desteklemiyor, sen de yerel aramayı ekle çünkü fark olur."}]}')
    result = llm_client.parse_comparison(raw, ["a/b"], [])
    assert result["projects"][0]["summary"] == ""
    assert result["arguments"] == []
    # said about what was read, it may stand
    assert not llm_client.overclaims("Okunan README'lerde tam metin aramadan söz edilmiyor.")


def test_components_get_turkish_names_for_the_reader():
    raw = ('{"projeler": [], '
           '"adlar": {"Full text search": "tam metin arama", "uydurma": "x y", "backlinks": "backlinks"}}')
    result = llm_client.parse_comparison(raw, ["a/b"], ["full text search", "backlinks"])
    assert result["labels"] == {"full text search": "tam metin arama"}


# ---------------------------------------------------------------- what the evidence supports
LOGSEQ = {"repo": "logseq/logseq", "evidence": "A privacy-first platform. Graph view of your pages, "
                                               "bidirectional links and block references."}
REVIEWDOG = {"repo": "reviewdog/reviewdog", "evidence": "reviewdog posts review comments to code hosting "
                                                        "services from the output of any lint tool."}


def test_the_matrix_comes_from_the_evidence_and_never_says_no():
    parsed = {"keywords": {"graph visualization": ["graph view"], "full-text search": ["full-text", "search"]},
              "labels": {"full-text search": "tam metin arama"}}
    result = R.ground_comparison(parsed, [LOGSEQ, REVIEWDOG], ["graph visualization", "full-text search"])
    assert result["matrix"] == {"graph visualization": {"logseq/logseq": "var"}}
    assert "Graph view of your pages" in result["quotes"]["graph visualization"]["logseq/logseq"]
    assert all(value == "var" for row in result["matrix"].values() for value in row.values())
    # Logseq's README never says "search": unknown, said as unknown
    assert result["differentiators"] == [
        "“tam metin arama”, incelenen 2 projenin okunan README ve sitelerinde geçmiyor; fikrini "
        "ayırabilecek bir nokta olabilir (yokluk kanıtı değil, doğrulamak gerekir)."]
    logseq = next(p for p in result["projects"] if p["repo"] == "logseq/logseq")
    assert logseq["shared"] == ["graph visualization"] and logseq["unseen"] == ["tam metin arama"]


def test_reviewdog_is_not_said_to_lack_line_comments():
    parsed = {"keywords": {"comment on lines": ["review comments", "inline comment"],
                           "run static analysis": ["lint", "linter"]}}
    result = R.ground_comparison(parsed, [REVIEWDOG, LOGSEQ], ["comment on lines", "run static analysis"])
    assert result["matrix"]["comment on lines"] == {"reviewdog/reviewdog": "var"}
    assert result["matrix"]["run static analysis"] == {"reviewdog/reviewdog": "var"}
    assert result["differentiators"] == []


def test_a_component_said_another_way_is_still_found():
    """The idea says "report warnings"; reviewdog's README says "reports lint warnings"."""
    text = "It reports lint warnings as review comments on the changed lines."
    assert R._near(text, "report warnings") >= 0 and R._near(text, "comment on lines") >= 0
    assert R._near("reports are generated. " + "x" * 80 + " warnings", "report warnings") == -1
    result = R.ground_comparison({}, [{"repo": "r/d", "evidence": text}], ["report warnings"])
    assert result["matrix"] == {"report warnings": {"r/d": "var"}}


def test_silence_is_claimed_only_where_nothing_hints_at_it():
    """reviewdog says "reporter", not "report warnings": no "none of them mentions it"."""
    reviewdog = {"repo": "r/d", "evidence": "Reporter: GitHub PullRequest review comment (-reporter=github-pr-review)"}
    other = {"repo": "o/x", "evidence": "An AI bot."}
    result = R.ground_comparison({}, [reviewdog, other], ["report warnings", "offline sync"])
    assert "report warnings" not in result["matrix"]
    assert [d.split("”")[0] for d in result["differentiators"]] == ["“offline sync"]
    assert next(p for p in result["projects"] if p["repo"] == "r/d")["unseen"] == ["offline sync"]


def test_an_argument_needs_its_quote_in_that_projects_evidence():
    parsed = {"arguments": [
        {"repo": "reviewdog/reviewdog", "quote": "from the output of any lint tool", "decision": "parcalar",
         "idea": "Bot kendi analizini yazmak yerine mevcut linter çıktısını okuyabilir."},
        {"repo": "reviewdog/reviewdog", "quote": "supports forty languages out of the box", "decision": "dis",
         "idea": "Kırk dili desteklemeli."}]}
    result = R.ground_comparison(parsed, [REVIEWDOG], [])
    assert result["arguments"] == ["Ana parçalar: Bot kendi analizini yazmak yerine mevcut linter çıktısını "
                                   "okuyabilir. (reviewdog/reviewdog: “from the output of any lint tool”)"]


def test_a_competitors_issue_becomes_the_first_suggestion():
    reviewdog = {**REVIEWDOG, "issues": ["Reviewdog fails on GitHub PRs with more than 300 files"]}
    parsed = {"arguments": [
        {"repo": "reviewdog/reviewdog", "quote": "from the output of any lint tool", "decision": "parcalar",
         "idea": "Bot kendi analizini yazmak yerine mevcut linter çıktısını okuyabilir."},
        {"repo": "reviewdog/reviewdog", "quote": "Reviewdog fails on GitHub PRs with more than 300 files",
         "decision": "kenar", "idea": "Büyük PR'lerde bot yalnız değişen satırlara bakmalı; rakip 300 dosyada çöküyor."}]}
    result = R.ground_comparison(parsed, [reviewdog], [])
    assert result["arguments"][0].startswith("Uç durumlar: Büyük PR'lerde")
    assert "issue'su: “Reviewdog fails on GitHub PRs with more than 300 files”" in result["arguments"][0]


def test_a_suggestion_that_only_names_a_feature_is_too_shallow():
    assert not llm_client.deep_enough("Python kod stil denetimi otomatikleştirilmeli.")
    assert not llm_client.deep_enough("Satır yorumları inceleme sürecini daha etkili hale getirebilir, bu önemli.")
    assert llm_client.deep_enough("Bot kendi analizini yazmak yerine ekibin zaten kullandığı linter çıktısını okumalı.")


def test_a_suggestion_must_name_the_decision_it_changes():
    raw = ('{"oneriler": [{"repo": "a/b", "kanit": "x y z", "karar": "platform", '
           '"oneri": "Web yerine masaüstü olmalı, çünkü rakibin kullanıcıları çevrimdışı çalışıyor."}, '
           '{"repo": "a/b", "kanit": "x y z", "karar": "uydurma", '
           '"oneri": "Web yerine masaüstü olmalı, çünkü rakibin kullanıcıları çevrimdışı çalışıyor."}]}')
    assert [a["decision"] for a in llm_client.parse_comparison(raw, ["a/b"], [])["arguments"]] == ["platform"]


def test_no_evidence_is_not_a_weakness():
    raw = '{"projeler": [{"repo": "a/b", "zayif": ["Son issue başlıkları okunamadı.", "Büyük PR\'lerde yavaş"]}]}'
    assert llm_client.parse_comparison(raw, ["a/b"], [])["projects"][0]["weak"] == ["Büyük PR'lerde yavaş"]


@pytest.mark.anyio
async def test_the_best_known_projects_are_looked_at_too(runner, monkeypatch):
    """Live: only 0-1 star repos the verdict named were analysed, never Logseq or Joplin."""
    looked = []
    monkeypatch.setattr(llm_client, "compare_projects",
                        lambda note, comps, projects, *a, **k: looked.extend(p["repo"] for p in projects)
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
                        lambda note, comps, projects, *a, **k: looked.extend(p["repo"] for p in projects)
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


def test_the_research_profile_keeps_only_what_is_safe_to_apply():
    raw = ('{"alan": "aile tarif defteri", "urun_turu": "Recipe Manager", "cekirdek": ["recipe", "app", "tracking"], '
           '"etiketler": ["Recipe Management", "meal-planning"], '
           '"karisan": [{"alan": "aile yemek planı", "isaretler": ["meal planning", "blog", "calorie tracking"]}], '
           '"esanlamlilar": {"Recipe Import": ["recipe scraper"], "uydurma": ["x y z"]}, '
           '"belirsiz": ["recipe import", "uydurma"], '
           '"kutuphane_aramasi": {"recipe import": "recipe scraper library"}, "rakip_turu": "uygulama"}')
    profile = llm_client.parse_research_profile(raw, ["recipe import"], "tarif defteri",
                                                ["family recipe book", "meal planning"])
    assert profile["anchors"] == ["recipe"]                       # no function or generic words
    assert profile["topics"] == ["recipe-management", "meal-planning"]
    # "meal planning" is the idea itself; "blog" is too short a word to be a signal
    assert profile["confusions"] == [{"area": "aile yemek planı", "signals": ["calorie tracking"]}]
    assert profile["synonyms"] == {"recipe import": ["recipe scraper"]}
    assert profile["ambiguous"] == ["recipe import"] and profile["rival_kind"] == "app"
    assert llm_client.parse_research_profile("anlamadım", ["x"]) == {}


def test_a_neighbour_field_only_goes_back_when_the_idea_is_not_named():
    terms = {"profile": {"anchors": ["recipe"], "confusions": [{"area": "beslenme", "signals": ["nutrition"]}]}}
    assert R.off_topic("Calorie and nutrition tracker", terms)
    # Mealie mentions nutrition too, but it is a recipe manager
    assert not R.off_topic("Self-hosted recipe manager with meal planning and nutrition", terms)
    ranked = R.rank({"a/diet": R.Candidate(repo="a/diet", url="u", stars=900, description="Nutrition tracker",
                                          found_by=["topic", "kisa"]),
                     "b/recipes": R.Candidate(repo="b/recipes", url="u", stars=5, description="Recipe manager",
                                             found_by=["kisa"])}, keywords=["family recipe book"], terms=terms)
    assert [c.repo for c in ranked] == ["b/recipes", "a/diet"]       # last, but still there


@pytest.mark.anyio
async def test_the_profile_is_asked_after_the_terms_and_kept_with_them(runner, monkeypatch):
    monkeypatch.setattr(llm_client, "extract_search_terms",
                        lambda note, *a: {"keywords": ["recipe manager"], "components": ["recipe import"]})
    monkeypatch.setattr(llm_client, "research_profile", lambda note, terms, *a: {"anchors": ["recipe"]})
    runner.provider_for = lambda role, rel: object()
    rel = runner.vault.create_note("", "fikir", "tarif")
    terms = await runner._terms(rel, "tarif")
    assert terms["profile"] == {"anchors": ["recipe"]} and runner.state(rel)["terms"]["profile"]
    monkeypatch.setattr(llm_client, "research_profile", lambda *a: (_ for _ in ()).throw(RuntimeError("429")))
    assert "profile" not in await runner._terms(rel, "tarif")    # no rules rather than old ones


@pytest.mark.anyio
async def test_a_thin_topic_gives_its_place_to_the_next(runner, monkeypatch):
    """family-recipes found 3 projects where grocery-list would have found 50."""
    asked = []

    class TopicHub:
        registry = {"git_search": {}}

        async def call(self, name, arguments):
            asked.append(arguments["query"])
            size = 3 if arguments["query"] == "topic:family-recipes" else 20
            return envelope({"items": [{"repo": f"{arguments['query']}/r{i}", "stars": i} for i in range(size)]})

    monkeypatch.setattr(R, "MAX_GITHUB_QUERIES", 2)
    runner.tool_hub = TopicHub()
    rel = runner.vault.create_note("", "fikir", "tarif")
    terms = {"keywords": ["recipe manager"], "topics": ["grocery-list"],
             "profile": {"anchors": ["recipe"], "topics": ["family-recipes", "recipe-management"]}}
    await runner._search(rel, terms, "tarif", [])
    assert asked == ["topic:family-recipes", "topic:grocery-list", "topic:recipe-management"]


def test_a_query_inside_a_whole_earlier_result_is_known_to_add_nothing():
    assert R.wider_queries("topic:recipe-management topic:meal-planning") == [
        "topic:recipe-management", "topic:meal-planning"]
    assert R.wider_queries("family recipe stars:>20000") == ["family recipe stars:>5000"]
    assert R.wider_queries("family recipe stars:>5000") == [] and R.wider_queries("topic:recipes") == []


def test_topics_are_learned_from_what_was_found():
    """Mealie carries recipe-manager, Tandoor meal-planner; the model guessed recipe-management."""
    found = {
        "mealie-recipes/mealie": R.Candidate(repo="mealie-recipes/mealie", url="u", stars=13000, description="",
                                             topics=["recipe-manager", "meal-plans", "self-hosted"]),
        "TandoorRecipes/recipes": R.Candidate(repo="TandoorRecipes/recipes", url="u", stars=8600, description="",
                                              topics=["meal-planner", "recipes", "docker", "self-hosted"]),
        "small/one": R.Candidate(repo="small/one", url="u", stars=3, description="", topics=["recipe-manager"]),
    }
    terms = {"keywords": ["family recipe book"], "profile": {"anchors": ["recipe", "meal plan"]}}
    learned = R.learned_topics(found, terms, {"topic:recipes"}, 3)
    assert learned[:2] == ["recipe-manager", "meal-planner"] and "self-hosted" not in learned


@pytest.mark.anyio
async def test_skipped_searches_pay_for_learned_topics(runner, monkeypatch):
    asked = []

    class Hub2:
        registry = {"git_search": {}}

        async def call(self, name, arguments):
            asked.append(arguments["query"])
            if arguments["query"] == "topic:recipe-management":      # the whole result: 3 of 3
                return envelope({"total_count": 3, "items": [
                    {"repo": "mealie-recipes/mealie", "stars": 13000, "topics": ["recipe-manager", "meal-plans"]},
                    {"repo": "TomBursch/kitchenowl", "stars": 3700, "topics": ["recipe-manager"]},
                    {"repo": "a/b", "stars": 1, "topics": []}]})
            return envelope({"total_count": 500, "items": [{"repo": f"x/{len(asked)}", "stars": 1}]})

    monkeypatch.setattr(R, "build_queries", lambda *a, **k: [
        {"style": "topic", "query": "topic:recipe-management"},
        {"style": "topic-pair", "query": "topic:recipe-management topic:meal-planning"}])
    runner.tool_hub = Hub2()
    rel = runner.vault.create_note("", "fikir", "tarif")
    log = []
    await runner._search(rel, {"keywords": ["recipe manager"], "profile": {"anchors": ["recipe"]}}, "tarif", log)
    assert "topic:recipe-management topic:meal-planning" not in asked        # inside a whole result
    assert [q for q in log if q.get("skipped")][0]["query"] == "topic:recipe-management topic:meal-planning"
    assert "topic:recipe-manager" in asked                                      # learned from what was found


def test_the_kind_of_each_candidate_is_read_from_its_line():
    raw = ("getlago/lago: komşu — şirketler için kullanım bazlı faturalama\n"
           "- **ellite/Wallos**: aynı — aileler için abonelik takibi\n"
           "uydurma/proje: ayni — x\nimgbot/Imgbot: belki")
    assert llm_client.parse_competitor_kinds(raw, ["getlago/lago", "ellite/Wallos", "imgbot/Imgbot"]) == {
        "getlago/lago": ("komsu", "şirketler için kullanım bazlı faturalama"),
        "ellite/Wallos": ("ayni", "aileler için abonelik takibi")}


def subscription_candidates():
    return [R.Candidate(repo="ellite/Wallos", url="u", stars=8587, description="Personal subscription tracker",
                        topics=["subscription-tracker"], found_by=["topic"]),
            R.Candidate(repo="small/subs", url="u", stars=3, description="Track your subscriptions",
                        topics=[], found_by=["kisa"]),
            R.Candidate(repo="getlago/lago", url="u", stars=8000, found_by=["topic"],
                        description="Usage based billing, subscription management for SaaS",
                        topics=["subscription-management", "billing"])]


@pytest.mark.anyio
async def test_a_neighbour_is_named_but_not_compared(runner, monkeypatch):
    """Lago — billing for SaaS companies — was compared with a family subscription tracker."""
    looked = []
    monkeypatch.setattr(llm_client, "compare_projects",
                        lambda note, comps, projects, *a, **k: looked.extend(p["repo"] for p in projects) or {})
    monkeypatch.setattr(llm_client, "classify_competitors", lambda note, rows, *a: {
        "ellite/Wallos": ("ayni", "aileler için abonelik takibi"), "getlago/lago": ("komsu", "şirketler için faturalama"),
        "small/subs": ("ayni", "")})
    runner.provider_for = lambda role, rel: object()
    rel = runner.vault.create_note("", "fikir", "Ailece abonelik takibi")
    deep = await runner._deep(rel, "Ailece abonelik takibi", subscription_candidates(),
                              {"same": [], "adjacent": ["small/subs"]}, [],
                              {"keywords": ["subscription tracking"], "components": ["renewal reminders"]})
    assert looked == ["ellite/Wallos", "small/subs"]     # the model's order, not the verdict's
    assert deep["neighbours"] == [{"repo": "getlago/lago", "stars": 8000, "why": "şirketler için faturalama"}]


@pytest.mark.anyio
async def test_when_every_candidate_is_a_neighbour_none_is_compared(runner, monkeypatch):
    monkeypatch.setattr(llm_client, "compare_projects", lambda *a, **k: pytest.fail("nothing to compare"))
    monkeypatch.setattr(llm_client, "classify_competitors",
                        lambda note, rows, *a: {row["repo"]: ("komsu", "başka iş") for row in rows})
    runner.provider_for = lambda role, rel: object()
    rel = runner.vault.create_note("", "fikir", "x")
    deep = await runner._deep(rel, "x", subscription_candidates(), {}, [], {"keywords": ["subscription tracking"]})
    assert deep["projects"] == [] and sorted(n["repo"] for n in deep["neighbours"]) == [
        "ellite/Wallos", "getlago/lago", "small/subs"]


@pytest.mark.anyio
async def test_how_many_competitors_is_the_models_call_up_to_a_ceiling(runner, monkeypatch):
    looked = []
    monkeypatch.setattr(llm_client, "compare_projects",
                        lambda note, comps, projects, *a, **k: looked.extend(p["repo"] for p in projects) or {})
    many = [R.Candidate(repo=f"o/r{i}", url="u", stars=i, description="subscription tracker", topics=[],
                        found_by=["topic"]) for i in range(12)]
    # the model names the eleventh candidate first and ten of them in all
    monkeypatch.setattr(llm_client, "classify_competitors", lambda note, rows, *a: {
        f"o/r{i}": ("ayni", "") for i in [11, *range(9)]})
    runner.provider_for = lambda role, rel: object()
    rel = runner.vault.create_note("", "fikir", "x")
    await runner._deep(rel, "x", many, {}, [], {"keywords": ["subscription tracking"]})
    assert looked[0] == "o/r11" and len(looked) == R.DEEP_PROJECTS


@pytest.mark.anyio
async def test_without_an_answer_the_choice_stays_as_it_was(runner, monkeypatch):
    looked = []
    monkeypatch.setattr(llm_client, "compare_projects",
                        lambda note, comps, projects, *a, **k: looked.extend(p["repo"] for p in projects) or {})
    monkeypatch.setattr(llm_client, "classify_competitors", lambda *a: (_ for _ in ()).throw(RuntimeError("429")))
    runner.provider_for = lambda role, rel: object()
    rel = runner.vault.create_note("", "fikir", "x")
    await runner._deep(rel, "x", subscription_candidates(), {"adjacent": ["small/subs"]}, [],
                       {"keywords": ["subscription tracking"]})
    assert "getlago/lago" in looked


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

    def compare(note, components, projects, provider, on_usage, decisions=""):
        seen["projects"] = projects
        seen["decisions"] = decisions
        return {"projects": [{"repo": "org/notes", "summary": "Not ağı", "weak": ["çevrimdışı eşitleme"],
                              "lesson": ""}],
                "keywords": {"backlinks": ["backlink"]}, "labels": {"backlinks": "geri bağlantılar"},
                "arguments": [{"repo": "org/notes", "quote": "Page text about graphs", "decision": "veri",
                               "idea": "Graf görünümü sayfa metninden üretilebilir."}]}

    monkeypatch.setattr(llm_client, "compare_projects", compare)
    rel = runner.vault.create_note("", "fikir", "Markdown not ağı")
    candidate = R.Candidate(repo="org/notes", url="https://github.com/org/notes", stars=10,
                            description="notes", topics=[], found_by=["topic"])
    deep = await runner._deep(rel, "Markdown not ağı", [candidate], {"same": ["org/notes"], "adjacent": []}, [],
                              {"components": ["backlinks"], "keywords": ["markdown"]})
    gathered = seen["projects"][0]
    assert gathered["issues"] == ["Sync loses notes offline"] and gathered["site"].startswith("Page text")
    assert deep["projects"][0]["stars"] == 900 and deep["projects"][0]["weak"] == ["çevrimdışı eşitleme"]
    assert deep["matrix"] == {"backlinks": {"org/notes": "var"}} and "evidence" not in deep["projects"][0]
    assert deep["arguments"][0]["text"].startswith("Veri: Graf görünümü sayfa metninden üretilebilir.")
    assert "Açık: amac (Amaç" in seen["decisions"]
    assert deep["arguments"][0]["id"].startswith("arg-")


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
