"""Prior-art research for a note's idea: has someone already built this?

The search strategy here is not a guess. Five ideas whose answer was known in
advance were run through four query styles, and only the union of several
styles found anything:

    tek uzun cumle (bir modelin dogal yazacagi sorgu)  0/5 fikir
    kisa anahtar kelimeler                             2/5
    topic: nitelemesi                                  2/5
    stars:>N filtresi                                  3/5
    hepsinin + web aramasinin birlesimi                5/5

So the model is never asked to write *the* query. It is asked for keywords and
topics — a much easier job — and the queries are built from those mechanically,
one per style. Even then the recall of the full known set was 2-3 out of 5, so
nothing here may ever report that an idea is original: absence of a result is
not evidence of absence.
"""
import asyncio
import hashlib
import ipaddress
import json
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from core import llm_client
from server.errors import ApiError
from server import ladder
from server.store import now_iso
from server.vault import split_frontmatter

MAX_KEYWORDS = 6
# Widened 2026-09-27: one big model now does the research and there is no
# rush, so it asks more ways, reads more pages and keeps more of what it finds.
MAX_TOPICS = 5
MAX_GITHUB_QUERIES = 10     # each costs ~6s: the server throttles searches
MAX_SUPPORT_QUERIES = 10
MAX_WEB_SOURCES = 30
MAX_WEB_READS = 8
MAX_REPO_READS = 8
PRIOR_WEB_SOURCES = 5       # pages kept from each prior-art web search
WEB_REPOS = 8               # GitHub links lifted from each web search
RANK_LIMIT = 20             # similar projects shown and judged
READ_CONCURRENCY = 3
# How many competitors, which ones and in what order is the model's call
# (classify_competitors); this is only a ceiling on time and cost — each
# project looked at is three or four tool calls of up to 30 s.
DEEP_PROJECTS = 8
DEEP_CALL_TIMEOUT = 30      # seconds per tool call there; a slow one is skipped, not waited on
KNOWN_STARS = 500           # "best known": a project people actually use
COMPETITOR_POOL = RANK_LIMIT  # every ranked candidate is put to the model, not a top slice
# A topic search that finds a handful of projects spent a place the idea's
# other topics could use: the model's niche "family-recipes" (3 results) took
# the place of grocery-list (50), and Tandoor and KitchenOwl were not found.
THIN_TOPIC = 10
MAX_TOPIC_SWAPS = 2
# Topics learned from the projects found: GitHub's own words for the idea.
# The model said recipe-management and meal-planning; Mealie carries
# recipe-manager, Tandoor meal-planner — and topic:recipe-manager, already
# sorted by stars, puts Mealie and KitchenOwl first.
LEARNED_TOPICS = 2
MAX_FOCUS_CHARS = 400
MAX_SOURCE_CONTENT = 8000
PER_PAGE = 50
STAR_GATES = (5000, 20000)  # big projects hide behind generic words without these


def _clean(items, limit: int) -> list[str]:
    seen: list[str] = []
    for raw in items or []:
        # Model output is data, never GitHub search syntax. In particular a
        # stray qualifier must not broaden the search or spend our budget.
        word = re.sub(r"[^a-z0-9.+-]+", "-", str(raw).strip().lower()).strip("-.")
        if word and word not in seen:
            seen.append(word)
    return seen[:limit]


def _keywords(items, limit: int) -> list[str]:
    """Keep keyword phrases as free-text tokens, unlike hyphenated topics."""
    seen = []
    for raw in items or []:
        for token in re.findall(r"[a-z0-9]+(?:[.+-][a-z0-9]+)*", str(raw).lower()):
            if token in {"stars", "topic", "sort", "fork"} or token.isdigit():
                continue
            if token not in seen:
                seen.append(token)
            if len(seen) >= limit:
                return seen
    return seen


def _profile(terms) -> dict:
    """The idea's own search rules (llm_client.research_profile); {} without one."""
    return (terms or {}).get("profile") or {}


def _tags(topics, profile=None) -> list[str]:
    """The topics to search: the ones the model says projects like this carry
    first, then the ones it read off the idea. (The ranking of notes, wiki
    and markdown topics above all others that stood here came from the first
    test idea, a notes app, and did nothing for any other idea.)"""
    return _clean([*((profile or {}).get("topics") or []), *(topics or [])], MAX_TOPICS)


def _idea_words(keywords, summary="", profile=None):
    """The words that say what the idea is, from its keywords. (The profile's
    anchors are for ranking, not for queries: put first here they made the
    popular-project query "code review pull request review stars:>5000",
    which found nothing, and reviewdog and danger were never found — measured.)"""
    words = _keywords([str(item).lower().strip() for item in (keywords or [])], MAX_KEYWORDS)
    selected = []
    for word in words:
        if word not in selected and word not in {"local-first", "open-source"}:
            selected.append(word)
    return selected[:MAX_KEYWORDS] or words


def _is_component_topic(tag, components):
    """"graph-visualization" is a part of the idea, not the idea: asked as a
    prior-art topic it filled the similar-projects list with chart libraries."""
    words = tag.replace("-", " ")
    parts = [part.replace("-", " ") for part in _components(components)]
    return any(words in part or part in words for part in parts)


# GitHub names these tools by what they are, not by what they do
AGENT_NOUNS = {"tracking": "tracker", "management": "manager", "monitoring": "monitor",
               "scheduling": "scheduler", "planning": "planner", "logging": "logger",
               "reminders": "reminder", "budgeting": "budget", "reading": "reader"}
# words that say nothing about which idea this is
PLAIN_WORDS = {"simple", "family", "personal", "open", "source", "self", "hosted", "local", "first",
               "mobile", "desktop", "app", "application", "tool", "tools", "smart", "easy", "free",
               "based", "online", "offline", "private", "small", "tiny",
               # on GitHub nearly every repository is "code": as the telling
               # word of "code review" it learned the topics codex and
               # claude-code, and AI-agent tooling filled the list (measured)
               "code", "automated", "automatic", "automation"}


def _agent_topics(keywords) -> list[str]:
    """"subscription tracking" -> subscription-tracker: the topic GitHub's
    projects actually carry (expense-tracker, password-manager). The model
    chose subscription-management for it — the topic of billing platforms."""
    topics = []
    for phrase in keywords or []:
        words = re.findall(r"[a-z0-9]+", str(phrase).lower())
        if len(words) == 2 and words[1] in AGENT_NOUNS and words[0] not in PLAIN_WORDS:
            topic = f"{words[0]}-{AGENT_NOUNS[words[1]]}"
            if topic not in topics:
                topics.append(topic)
    return topics[:2]


def _anchor_word(keywords) -> str:
    """The idea's own noun: the first telling word of its first keyword
    ("subscription" in "subscription tracking")."""
    for phrase in keywords or []:
        for word in re.findall(r"[a-z0-9]+", str(phrase).lower()):
            if len(word) >= 4 and word not in PLAIN_WORDS:
                return word
        break
    return ""


def build_queries(keywords, topics, summary="", components=(), profile=None) -> list[dict]:
    """One query per proven style, built from what the model extracted.

    Returns [{"style", "query"}] in the order they should run; the caller cuts
    the list at MAX_GITHUB_QUERIES.
    """
    words = _idea_words(keywords, summary, profile)
    tags = _tags(topics, profile)
    queries: list[dict] = []

    def add(style: str, query: str):
        query = query.strip()
        if query and not any(q["query"] == query for q in queries):
            queries.append({"style": style, "query": query})

    # the single most effective style in the trial: a specific topic on its own
    # The six measured styles run first, both star gates among them; the
    # widening only adds after them, so a cut never costs a proven query.
    # A one-word topic ("markdown") is a whole category: alone it returned the
    # most starred Markdown tools (rich, pandoc), not note apps. It still
    # narrows a pair, so it only stands alone when nothing specific is left.
    specific = [tag for tag in tags if "-" in tag] + [tag for tag in tags if "-" not in tag]
    # GitHub's naming, from the keywords, ahead of the model's own topics too:
    # "meal planning" -> topic:meal-planner found Mealie, Tandoor and
    # KitchenOwl; without it the model's recipe-management and family-recipes
    # found neither Tandoor nor KitchenOwl in four runs (measured)
    agent = _agent_topics(keywords)
    specific = [*agent[:1], *[tag for tag in specific if tag not in agent[:1]]]
    for tag in specific[:2]:
        add("topic", f"topic:{tag.replace(' ', '-')}")
    if len(tags) >= 2:
        add("topic-pair", f"topic:{tags[0].replace(' ', '-')} topic:{tags[1].replace(' ', '-')}")
    if words:
        add("kisa", " ".join(words[:3]))
        for gate in STAR_GATES:
            add("populer", f"{' '.join(words[:2])} stars:>{gate}")
    # the widening: the idea's third topic, another pair, other words, and
    # projects that only describe the idea in their README
    extra = [tag for tag in specific[2:] if "-" in tag and not _is_component_topic(tag, components)]
    if extra:
        add("topic", f"topic:{extra[0].replace(' ', '-')}")
        if tags:
            add("topic-pair", f"topic:{tags[0].replace(' ', '-')} topic:{extra[0].replace(' ', '-')}")
    if len(words) > 3:
        add("kisa", " ".join(words[1:4]))
    if words:
        add("readme", f"{' '.join(words[:2])} in:readme stars:>100")
    return queries


def web_query(summary: str) -> str:
    """Web search ranks 'what are the popular X' far better than GitHub does —
    it found projects GitHub search missed, and missed ones GitHub found."""
    summary = " ".join(str(summary or "").split())[:180]
    return f"best open source {summary} github" if summary else ""


def prior_web_queries(summary: str, keywords=()) -> list[str]:
    """Three ways of asking the web who already built this: the open-source
    leaders, the products people compare (closed ones included, which GitHub
    never shows), and small projects their makers announced themselves."""
    summary = " ".join(str(summary or "").split())[:180]
    words = " ".join(_keywords(keywords, 3))
    queries = [web_query(summary)]
    if summary:
        queries.append(f"{summary} alternatives")
    if words:
        queries.append(f"Show HN {words}")
    return [query for query in queries if query]


def _components(items):
    seen = []
    for raw in items or []:
        tokens = [token for token in re.findall(r"[a-z0-9]+(?:[.+-][a-z0-9]+)*", str(raw).lower())
                  if token not in {"stars", "topic", "sort", "fork"}]
        phrase = " ".join(tokens[:3])
        if phrase and phrase not in seen:
            seen.append(phrase)
    return seen[:6]


def _context_phrase(profile) -> str:
    """What this kind of product is called ("recipe manager")."""
    return " ".join(str((profile or {}).get("product") or "").split())[:40]


def _ambiguous(phrase, profile) -> bool:
    """A component whose name alone means something else — the model says
    which ("search" alone is web search engines, not searching one's notes)."""
    return phrase.casefold() in {str(p).casefold() for p in ((profile or {}).get("ambiguous") or [])}


def _focused_component(phrase, profile=None):
    context = _context_phrase(profile)
    return f"{phrase} {context}" if context and _ambiguous(phrase, profile) else phrase


def build_support_queries(keywords, topics, components=(), summary="", profile=None) -> list[dict]:
    """Find reusable pieces of an idea, not only whole products like it.

    The model supplies concepts; query wording is mechanical and short. Repo
    search handles qualifiers differently from web search, so these avoid long
    natural-language questions and are capped separately from prior-art.
    """
    words = _idea_words(keywords, summary, profile)
    tags = _tags(topics, profile)
    parts = _components(components)
    focus = " ".join(words[:2])
    queries = []
    if parts:
        # Every feature named in the note gets a search. A generic "library"
        # suffix excluded real graph and editor libraries in a live trial.
        for index, part in enumerate(parts, start=1):
            queries.append({"style": f"component-{index}",
                            "query": _focused_component(part, profile)})
        # The same features as GitHub topics, most starred first: that is
        # where the libraries themselves are (a notes-anchored query returned
        # note apps; "graph visualization" alone returned a charting library).
        for index, part in enumerate(parts[:4], start=1):
            # a topic is lowercase letters, digits and hyphens: "robots.txt
            # respect" can never be one, so it would only cost a search
            if len(part.split()) <= 3 and re.fullmatch(r"[a-z0-9 -]+", part):
                queries.append({"style": f"component-topic-{index}",
                                "query": "topic:" + part.replace(" ", "-")})
        if tags and len(parts) < 3:
            queries.append({"style": "topic-library", "query": f"topic:{tags[0]} library"})
        if focus and len(parts) < 3:
            queries.append({"style": "sdk", "query": f"{focus} sdk"})
    else:
        if tags:
            queries.append({"style": "topic-library", "query": f"topic:{tags[0]} library"})
        if focus:
            queries.extend([
                {"style": "sdk", "query": f"{focus} sdk"},
                {"style": "library", "query": f"{focus} library"},
                {"style": "toolkit", "query": f"{focus} toolkit"},
            ])
        if len(tags) > 1:
            queries.append({"style": "adjacent-topic", "query": f"topic:{tags[1]} library"})
    return queries[:MAX_SUPPORT_QUERIES]


def support_web_queries(keywords, topics, components=(), summary="", profile=None) -> list[str]:
    words = _idea_words(keywords, summary, profile)
    tags = _tags(topics, profile)
    parts = _components(components)
    libraries = {str(k).casefold(): str(v) for k, v in ((profile or {}).get("library_queries") or {}).items()}
    focus = " ".join(words[:3]) or " ".join(tags[:2]).replace("-", " ")
    if not focus and not parts:
        return []
    focus = focus or parts[0]
    if parts:
        def libraries_for(part):
            # the model's words for finding a library for this part: "graph
            # visualization" alone found bar charts, a phrase naming network
            # graphs found the graph libraries (live trial, notes idea)
            return (libraries.get(part.casefold()) or
                    f"{_focused_component(part, profile)} open source libraries tools")
        second = parts[2] if len(parts) > 2 else parts[1] if len(parts) > 1 else focus
        queries = [libraries_for(parts[0]),
                   f"{_focused_component(second, profile)} implementation architecture examples"]
        if len(parts) > 2:
            # the component the first two left out
            queries.append(libraries_for(parts[1]))
        return queries
    return [f"{focus} open source libraries tools", f"{focus} implementation architecture examples"]


def adjacent_web_query(keywords, components=(), topics=(), summary="", profile=None) -> str:
    """Explore alternate mechanisms and use cases, not another product list."""
    parts = _components(components)
    words = _keywords(keywords, 3)
    focus = parts[0] if parts else " ".join(words)
    focus = _focused_component(focus, profile)
    return f"{focus} alternative approaches use cases" if focus else ""


@dataclass
class Candidate:
    repo: str
    stars: int = 0
    language: str | None = None
    license: str | None = None
    description: str = ""
    url: str = ""
    pushed_at: str = ""
    topics: list[str] = field(default_factory=list)
    found_by: list[str] = field(default_factory=list)   # which styles surfaced it
    evidence_url: str = ""

    def public(self) -> dict:
        return {"repo": self.repo, "stars": self.stars, "language": self.language,
                "license": self.license, "description": self.description, "url": self.url,
                "pushed_at": self.pushed_at, "topics": self.topics,
                "found_by": sorted(set(self.found_by)), "evidence_url": self.evidence_url}


VALID_REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_.-]+$")


def merge(candidates: dict, style: str, items: list[dict]) -> None:
    """Fold one search's results into the running set, remembering provenance.
    A repo found by several styles is a stronger signal than a lone hit."""
    for item in items or []:
        if not isinstance(item, dict):
            continue
        repo = str(item.get("repo") or "").strip()
        if not VALID_REPO.fullmatch(repo):
            continue
        key = next((name for name in candidates if name.casefold() == repo.casefold()), repo)
        current = candidates.get(key)
        if current is None:
            try:
                stars = max(0, int(item.get("stars") or 0))
            except (TypeError, ValueError):
                stars = 0
            current = candidates[key] = Candidate(
                repo=repo, stars=stars,
                language=str(item.get("language"))[:60] if item.get("language") else None,
                license=str(item.get("license_spdx"))[:60] if item.get("license_spdx") else None,
                description=str(item.get("description") or "")[:500],
                url=f"https://github.com/{repo}",
                pushed_at=str(item.get("pushed_at") or ""),
                topics=[str(topic)[:80] for topic in (item.get("topics") or [])[:20]]
                if isinstance(item.get("topics"), list) else [],
            )
        else:
            try:
                current.stars = max(current.stars, max(0, int(item.get("stars") or 0)))
            except (TypeError, ValueError):
                pass
        current.found_by.append(style)


# The styles whose agreement was measured to mean something: different ways
# of asking GitHub (and the web) "who already built this idea?".
PRIOR_STYLES = ("topic", "topic-pair", "topic-duz", "kisa", "populer", "readme", "web")
# Styles that ask the same thing count once: "topic:a topic:b" only ever
# returns repos that "topic:a" already returns, so a small repo carrying both
# topics was counted as confirmed three times for one property. With the
# widened searches that pushed pr-agent and danger out of the top 20.
STYLE_FAMILY = {"topic": "topic", "topic-pair": "topic", "topic-duz": "words", "kisa": "words",
                "populer": "popular", "readme": "readme", "web": "web"}


def prior_families(candidate) -> set[str]:
    """Independent prior-art strategies that surfaced this repo.

    Component searches are not in here. They ask for one feature each with
    near-identical words ("backlinking markdown notes", "full-text search
    markdown notes"), so a repo matching two of them has been found twice by
    the same question, not confirmed by two. Counting them as corroboration
    put 0-star repos above 11k-star prior art in the live evaluation.
    """
    return {STYLE_FAMILY[style] for style in candidate.found_by if style in STYLE_FAMILY}


def rank(candidates: dict, limit: int = RANK_LIMIT, keywords=(), terms=None) -> list[Candidate]:
    """Most corroborated by independent prior-art styles first; a product that
    only a component search surfaced comes after everything a prior-art query
    found. Within a tier relevance, then popularity. Stars alone would bury a
    small project that every single query style agreed on."""
    words = set(_keywords(keywords, 12))
    anchors = [a for a in (_profile(terms).get("anchors") or [_anchor_word(keywords)]) if a]
    # any telling word of the concept, for pushing back what is about something
    # else: the model named "personal wiki" and "knowledge graph" for a notes
    # idea, and SiYuan ("personal knowledge management") fell off the list
    # while only the whole phrases counted (measured, before/after run)
    touch = {_anchor_stem(w) for a in anchors for w in re.findall(r"[a-z0-9]+", a.lower())
             if len(w) >= 4 and w not in PLAIN_WORDS}

    def haystack(candidate):
        return " ".join((candidate.repo, candidate.description, " ".join(candidate.topics))).lower()

    def about_it(candidate):
        """Touches the idea's own concept: medicine reminders that three queries
        agreed on outranked every subscription tracker without this."""
        return not touch or any(_mentions(haystack(candidate), stem) >= 0 for stem in touch)

    def names_it(candidate):
        """Names the concept itself, the whole phrase: for the best-known
        places, which by a word alone went to lists and code-graph engines."""
        return not anchors or any(_mentions(haystack(candidate), _anchor_stem(a)) >= 0 for a in anchors)

    def relevance(candidate):
        haystack = " ".join((candidate.repo, candidate.description, " ".join(candidate.topics))).lower()
        return sum(word in haystack for word in words)

    def key(c):
        prior = prior_families(c)
        support = any(style not in STYLE_FAMILY for style in c.found_by)
        # a field the model named as a confusion goes last, but stays: a
        # wrong rule costs a place in the list, never the project
        return (off_topic(haystack(c), terms), not about_it(c), -len(prior), -support, -relevance(c),
                -c.stars, c.repo.casefold())

    ordered = sorted(candidates.values(), key=key)
    # A fifth of the list goes to the best known prior art the corroboration
    # order left out: with ten searches, small repos that several narrow
    # queries all matched pushed a 16k-star project like Foam off the list.
    popular = limit // 4
    head = ordered[:limit - popular]
    tail = ordered[limit - popular:]
    # ...but only prior art that says so itself: an "in:readme" search also
    # returns awesome-lists and interview guides whose READMEs mention
    # everything, and by stars alone they took every one of these places
    enough = min(2, len(words))
    known = sorted((c for c in tail if prior_families(c) and relevance(c) >= enough and names_it(c)
                    and not off_topic(haystack(c), terms)),
                   key=lambda c: (-c.stars, c.repo.casefold()))
    others = [c for c in tail if c not in known]     # in their own order, after the known ones
    return head + (known + others)[:limit - len(head)]


def _synonyms(component, terms) -> list[str]:
    table = {str(k).casefold(): v for k, v in (_profile(terms).get("synonyms") or {}).items()}
    return [str(s).lower() for s in table.get(str(component).casefold(), [])]


def _component_match(component, text, terms=None):
    """Does the text speak of this part of the idea: in one of the phrases the
    model gave for it, or failing those, in most of its own words. (A table
    of aliases for backlinks, graphs, full-text search, citations, robots.txt
    and SSRF stood here — the parts of the first two test ideas.)"""
    if any(phrase and phrase in text for phrase in _synonyms(component, terms)):
        return True
    tokens = [token[:5] for token in _keywords([component], 4) if len(token) >= 4]
    return bool(tokens) and sum(token in text for token in tokens) >= min(2, len(tokens))


def _explicit_component_match(component, text, terms=None):
    """A concrete mention before a nearby project is classified: the
    component or one of the model's phrases for it, as words."""
    synonyms = _synonyms(component, terms)
    if any(_mentions(text, phrase) >= 0 for phrase in [component, *synonyms]):
        return True
    return False if synonyms else _component_match(component, text)


def candidate_fit_score(candidate, terms):
    text = " ".join((candidate.repo, candidate.description, " ".join(candidate.topics))).lower()
    if off_topic(text, terms):
        return -100
    anchor = _has_anchor(text, terms)
    components = _components(terms.get("components"))
    hits = sum(_component_match(component, text, terms) for component in components)
    if components and not hits:
        return -100
    keywords = set(_keywords(terms.get("keywords"), 12))
    overlap = sum(word in text for word in keywords if len(word) >= 4)
    provenance = len(set(candidate.found_by))
    component_search = any(style.startswith("component-") for style in candidate.found_by)
    return ((3 if anchor else 0) + 2 * hits + min(overlap, 3) +
            min(provenance, 2) + (2 if component_search and hits else 0) +
            (3 if candidate.evidence_url and hits else 0))


def diverse_helpers(candidates: dict, components=(), keywords=(), limit: int = 20,
                    terms=None) -> list[Candidate]:
    """Keep a representative from each searched feature in the model context."""
    ordered = rank(candidates, limit=len(candidates), keywords=[*components, *keywords], terms=terms)
    if terms is not None:
        ordered = [candidate for candidate in ordered if candidate_fit_score(candidate, terms) >= 4]
        ordered.sort(key=lambda candidate: (-candidate_fit_score(candidate, terms),
                                            -len(set(candidate.found_by)), -candidate.stars))
    chosen = []
    count = len(_components(components))
    styles = [f"component-{index}" for index in range(1, count + 1)]
    styles += [f"component-topic-{index}" for index in range(1, min(count, 4) + 1)]
    for style in styles:
        hit = next((candidate for candidate in ordered
                    if style in candidate.found_by and candidate not in chosen), None)
        if hit is not None:
            chosen.append(hit)
        if len(chosen) >= limit:
            return chosen
    # The libraries themselves: the most starred results of each topic search.
    # Scored by fit alone they lost to small note apps that merely say
    # "markdown" (the recommender then saw plotly and a 4-star search repo).
    for index in range(1, min(count, 4) + 1):
        style = f"component-topic-{index}"
        known = sorted((candidate for candidate in ordered
                        if style in candidate.found_by and candidate not in chosen),
                       key=lambda candidate: -candidate.stars)
        for candidate in known[:2]:
            chosen.append(candidate)
            if len(chosen) >= limit:
                return chosen
    chosen.extend(candidate for candidate in ordered if candidate not in chosen)
    return chosen[:limit]


def route_helper_products(prior: dict, helpers: dict, terms) -> None:
    """Whole applications of the idea's kind belong with comparable projects,
    not libraries.

    Search overlap is useful here: a component query can surface a relevant
    application which the prior-art query missed. Keep its provenance so the
    candidate ranking and verdict can still use that evidence. Only when the
    model's profile says rivals are applications, and only what names the
    idea's own concept.
    """
    profile = _profile(terms)
    if not profile or profile.get("rival_kind") == "library":
        return
    components = _components(terms.get("components"))
    product_words = [w for w in re.findall(r"[a-z]+", str(profile.get("product") or "")) if len(w) >= 4]
    for repo, candidate in list(helpers.items()):
        text = " ".join((candidate.repo, candidate.description, " ".join(candidate.topics))).lower()
        if off_topic(text, terms) or not _has_anchor(text, terms):
            continue
        if re.search(r"\b(library|sdk|framework|plugin|extension|parser|database|cli)\b", text):
            continue
        feature_hits = sum(_explicit_component_match(component, text, terms) for component in components)
        product_label = bool(re.search(r"\b(app|application|workspace|self-hosted)\b", text) or
                             any(_mentions(text, word) >= 0 for word in product_words))
        if feature_hits < 2 and not (product_label and feature_hits):
            continue
        duplicate = next((name for name in prior if name.casefold() == repo.casefold()), None)
        if duplicate:
            existing = prior[duplicate]
            existing.found_by.extend(candidate.found_by)
            if len(candidate.description) > len(existing.description):
                existing.description = candidate.description
            existing.stars = max(existing.stars, candidate.stars)
        else:
            prior[repo] = candidate
        del helpers[repo]


def _source_url(raw):
    """Keep only plausible public web links before handing them to the UI.

    Actual page reads still go through web_fetch's DNS and robots checks.
    """
    try:
        parts = urlsplit(str(raw or "").strip())
        host = (parts.hostname or "").rstrip(".").lower()
        if parts.scheme not in {"https", "http"} or not host or parts.username or parts.password:
            return ""
        if host == "localhost" or host.endswith(".localhost"):
            return ""
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            if not address.is_global:
                return ""
        return parts.geturl()
    except ValueError:
        return ""


def sources_in_web_results(results, query, kind, limit=MAX_WEB_SOURCES):
    sources = []
    seen = set()
    for index, item in enumerate(results or [], start=1):
        if not isinstance(item, dict):
            continue
        url = _source_url(item.get("url"))
        if not url or url in seen:
            continue
        seen.add(url)
        raw_title = str(item.get("title") or "")
        snippet = str(item.get("snippet") or item.get("text") or "")
        if " ".join(snippet.split()) == " ".join(raw_title.split()):
            snippet = ""
        try:
            search_rank = max(1, int(item.get("rank") or index))
        except (TypeError, ValueError):
            search_rank = index
        sources.append({"url": url, "title": clean_search_title(item.get("title"), url),
                        "snippet": snippet[:500],
                        "query": query, "kind": kind, "verified": False,
                        "read_error": None, "relevance": 0, "search_rank": search_rank})
        if len(sources) >= limit:
            break
    return sources


def clean_search_title(raw, url):
    """Remove SERP breadcrumbs while retaining the publisher's actual title."""
    title = " ".join(str(raw or "").split())
    if "›" in title or "�" in title:
        title = re.split(r"[›�]", title)[-1].strip()
        title = re.sub(r"^[a-z0-9_./-]+\s+(?=[A-Z0-9])", "", title)
    else:
        title = re.sub(r"^\S+\s+https?://\S+\s+", "", title)
    return (title or urlsplit(url).hostname or url)[:180]


def _anchor_stem(anchor: str) -> str:
    anchor = " ".join(str(anchor).lower().split())
    return anchor if " " in anchor or len(anchor) <= 5 else anchor[:5]


def _has_anchor(text, terms):
    """Does the text name the idea's own concept (the profile's anchors, e.g.
    "subscription", "code review")? Without a profile nothing is required —
    the notes and web-research words that stood here fit two ideas only."""
    anchors = _profile(terms).get("anchors") or []
    if not anchors:
        return True
    return any(_mentions(str(text), _anchor_stem(anchor)) >= 0 for anchor in anchors)


def off_topic(text, terms):
    """Another field that shares the idea's words, as the model named them
    for this idea ("newsletter", "mailing list" for a subscription tracker),
    in a text that does not name the idea's own concept at all. The hand
    list that stood here (SEO for notes; hacker, excel, academic for web
    research) knew two ideas."""
    body = str(text or "")
    for area in _profile(terms).get("confusions") or []:
        if any(_mentions(body, signal) >= 0 for signal in area.get("signals") or []):
            return not _has_anchor(body, terms)
    return False


def relevance_score(text, terms, require_context=False) -> int:
    """Score topic coverage; generic component pages need domain context."""
    body = str(text or "").lower()
    if not body:
        return 0
    tokens = [word for word in _keywords(
        [*(terms.get("components") or []), *(terms.get("keywords") or [])], 14)
        if len(word) >= 3]
    phrases = [phrase for phrase in _components(terms.get("components"))
               if " " in phrase]
    token_hits = sum(bool(re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", body))
                     for word in set(tokens))
    phrase_hits = sum(phrase in body for phrase in phrases)
    score = min(30, 2 * token_hits + 4 * phrase_hits)
    if require_context and not _has_anchor(body, terms):
        return min(score, 1)
    return score


def _library_queries(terms) -> set[str]:
    return {str(q) for q in (_profile(terms).get("library_queries") or {}).values()}


def source_prefetch_score(source, terms):
    url = str(source.get("url") or "")
    snippet = str(source.get("snippet") or "")
    # Some search providers return the SERP breadcrumb as the snippet too. Its
    # hostname (e.g. sysdesign.wiki) is not evidence of note-related content.
    if "http" in snippet and ("›" in snippet or "�" in snippet):
        snippet = ""
    metadata = " ".join((str(source.get("title") or ""), snippet,
                         urlsplit(url).path.replace("-", " ")))
    if off_topic(metadata, terms):
        return 0
    score = relevance_score(metadata, terms, require_context=True)
    if score < 2 and source.get("kind") == "support" and "library" in str(source.get("query") or "").lower():
        # A reusable graph or search library may not mention Markdown notes.
        # Its own API/library description is enough to read the primary page.
        if re.search(r"\b(library|framework|package|sdk|api)\b", metadata.lower()) and any(
                _component_match(part, metadata.lower(), terms) for part in
                _components(terms.get("components"))):
            score = relevance_score(metadata, terms)
    if score < 2 and source.get("kind") == "support" and str(
            source.get("query") or "") in _library_queries(terms) and int(source.get("search_rank") or 99) <= 2:
        # A project homepage can have only a brand name in the SERP. Read the
        # best result once, then require actual library evidence in the body.
        score = 2
    if score < 2:
        return 0
    # A specific implementation page is usually more useful than a broad
    # explainer with the same keywords. The model still sees every read page.
    title = str(source.get("title") or "").lower()
    url = url.lower()
    if re.search(r"/(docs?|examples?|api|reference)/", url):
        score += 3
    if source.get("kind") in {"support", "adjacent"}:
        if re.search(r"\b(what is|use cases|beginner|best|top \d+)\b", title):
            score = max(0, score - 3)
        elif "/blog/" in url and not re.search(r"architecture|implement|library|tool|code|example", title):
            score = max(0, score - 2)
    return score


def evidence_excerpt(content, terms, limit=1800) -> str:
    """Show the most relevant page window while preserving the full body too."""
    body = str(content or "").strip()
    if len(body) <= limit:
        return body
    best_start, best_score = 0, -1
    step = max(200, limit // 4)
    for start in range(0, len(body) - limit + 1, step):
        score = relevance_score(body[start:start + limit], terms)
        if score > best_score:
            best_start, best_score = start, score
    if best_start:
        newline = body.rfind("\n", max(0, best_start - 100), best_start + 1)
        if newline >= 0:
            best_start = newline + 1
    excerpt = body[best_start:best_start + limit].strip()
    return ("[…]\n" if best_start else "") + excerpt + (
        "\n[…]" if best_start + limit < len(body) else "")


def select_sources_for_fetch(sources, terms, limit=MAX_WEB_READS):
    """Read promising links across search intents instead of the first two."""
    eligible = [source for source in sources if source.get("kind") in {
        "prior", "support", "adjacent"} and
        urlsplit(source.get("url") or "").hostname not in {"github.com", "www.github.com"} and
        not urlsplit(source.get("url") or "").path.lower().endswith(".pdf") and
        source_prefetch_score(source, terms) >= 2]
    ordered = sorted(eligible, key=lambda source: (-source_prefetch_score(source, terms),
        source.get("url") or ""))
    selected = []
    used_groups = set()
    hosts = {}

    def add(source):
        host = urlsplit(source["url"]).hostname or ""
        if source in selected or hosts.get(host, 0) >= 2:
            return False
        selected.append(source)
        hosts[host] = hosts.get(host, 0) + 1
        used_groups.add((source.get("kind"), source.get("query")))
        return True

    for source in ordered:
        group = (source.get("kind"), source.get("query"))
        if group not in used_groups:
            add(source)
        if len(selected) >= limit:
            return selected
    for source in ordered:
        add(source)
        if len(selected) >= limit:
            break
    return selected


def prioritized_sources(sources, limit=MAX_WEB_SOURCES):
    """Keep fetched support evidence visible when search returns many links."""
    return sorted(sources, key=lambda s: (not s.get("verified"),
                                          -int(s.get("relevance") or 0),
                                          s.get("kind") not in {"support", "adjacent"}))[:limit]


# gist.github.com/<user>/<hash> looks exactly like a repo path but is not one:
# a live run turned a gist id into a 404 lookup.
REPO_URL_RE = re.compile(r"(?<!gist\.)github\.com/([A-Za-z0-9][\w.-]*/[\w.-]+)", re.IGNORECASE)
SKIP_OWNERS = {"topics", "search", "features", "about", "pricing", "orgs", "sponsors", "collections"}


def repos_in_web_results(results, limit=WEB_REPOS):
    """GitHub links the web search turned up.

    In the trial the web search found leaders GitHub's own search had missed
    (and vice versa), but it answers with pages, not repositories, so the repo
    names have to be lifted out of the links it returns.
    """
    found = []
    for item in results or []:
        if not isinstance(item, dict):
            continue
        blob = " ".join(str(item.get(k) or "") for k in ("url", "title", "snippet", "text"))
        for match in REPO_URL_RE.finditer(blob):
            repo = match.group(1).rstrip("/.")
            if repo.lower().endswith(".git"):
                repo = repo[:-4]
            owner, _, name = repo.partition("/")
            if owner.lower() in SKIP_OWNERS or not name or "/" in name:
                continue
            if len(name) >= 20 and re.fullmatch(r"[0-9a-f]+", name):
                continue                  # a gist id, not a repository name
            if repo not in found:
                found.append(repo)
            if len(found) >= limit:
                return found
    return found


def payload_of(outcome):
    """The tool envelope carries evidence ids and the source url; the rows we
    want are under `data`."""
    try:
        body = json.loads(outcome["result"]["content"][0]["text"])
    except (KeyError, IndexError, TypeError, ValueError):
        return {}
    if not isinstance(body, dict):
        return {}
    data = body.get("data", body)
    return data if isinstance(data, dict) else {}


def items_of(outcome):
    return payload_of(outcome).get("items") or []


def repo_facts(payload: dict) -> dict:
    """What a repository's metadata says about how alive the project is."""
    if not isinstance(payload, dict):
        return {}
    first = lambda *keys: next((payload[k] for k in keys if payload.get(k) not in (None, "")), None)
    license_ = first("license_spdx", "license")
    if isinstance(license_, dict):
        license_ = license_.get("spdx_id") or license_.get("name")
    facts = {"stars": first("stars", "stargazers_count", "stargazers"),
             "forks": first("forks", "forks_count"),
             "license": license_,
             "updated": str(first("pushed_at", "updated_at", "last_push", "pushed") or "")[:10] or None,
             "open_issues": first("open_issues", "open_issues_count"),
             "homepage": first("homepage", "homepage_url"),
             "archived": bool(payload.get("archived"))}
    return {key: value for key, value in facts.items() if value not in (None, "")}


# Links in a README that are not the project's own site: badges, chat,
# stores, sponsors, the repository itself.
NOT_A_SITE = ("github.com", "githubusercontent.com", "shields.io", "badgen.net", "codecov.io",
              "travis-ci.org", "travis-ci.com", "discord.gg", "discord.com", "twitter.com", "x.com", "t.me",
              "reddit.com", "youtube.com", "youtu.be", "npmjs.com", "pypi.org", "crates.io",
              "opencollective.com", "patreon.com", "ko-fi.com", "buymeacoffee.com", "liberapay.com",
              "gitter.im", "matrix.to", "apps.apple.com", "play.google.com", "flathub.org", "snapcraft.io",
              "linkedin.com", "wikipedia.org", "creativecommons.org", "opensource.org", "gitpod.io",
              "star-history.com", "trendshift.io", "producthunt.com", "vercel.com", "netlify.com")
LINK_RE = re.compile(r"https?://[^\s)\]>\"'<`]+")


def readme_homepage(text: str, repo: str) -> str | None:
    """The project's own site as its README links it — git_repo carries no
    homepage field, so without this no competitor's site was ever read.
    A host that carries the project's or owner's name wins ("logseq.com")."""
    owner, _, name = str(repo or "").lower().partition("/")
    names = {"".join(ch for ch in part if ch.isalnum()) for part in (owner, name)} - {""}
    sites = []
    for link in LINK_RE.findall(str(text or "")):
        link = link.rstrip(".,;:")
        host = (urlsplit(link).hostname or "").lower()
        if not host or any(host == skip or host.endswith("." + skip) for skip in NOT_A_SITE):
            continue
        # "run it and open http://localhost:5173": a README's setup step
        if "." not in host or re.fullmatch(r"[\d.]+", host) or host.endswith((".localhost", ".local")):
            continue
        if re.search(r"\.(png|jpe?g|gif|svg|webp|ico|mp4)(\?|$)", link, re.IGNORECASE):
            continue
        sites.append((host, link))
    for host, link in sites:
        bare = "".join(ch for ch in host if ch.isalnum())
        if any(len(n) >= 3 and n in bare for n in names):
            return link
    return sites[0][1] if sites else None


def _mentions(text: str, phrase: str) -> int:
    """Where `phrase` starts a word in `text`, in any case, or -1.
    "search" finds "Search" and "searching", not "research"."""
    phrase = " ".join(phrase.split())
    if len(phrase) < 3:
        return -1
    found = re.search(r"(?<![a-z0-9])" + re.escape(phrase).replace(r"\ ", r"[\s-]+"), text, re.IGNORECASE)
    return found.start() if found else -1


NEAR_STOP = {"with", "from", "into", "that", "this", "your", "their", "them", "have", "when", "each"}


def _near(text: str, component: str, window: int = 60) -> int:
    """Where every word of a multi-word component appears within `window`
    characters of the first, as a word start ("report warnings" finds
    "reports lint warnings"), or -1. The phrases the model offers follow the
    idea's own wording; READMEs say it their way (measured: 22 misses)."""
    stems = [w[:4] for w in re.findall(r"[a-z0-9]+", component.lower()) if len(w) >= 4 and w not in NEAR_STOP]
    if len(stems) < 2:
        return -1
    for first in re.finditer(r"(?<![a-z0-9])" + re.escape(stems[0]), text, re.IGNORECASE):
        around = text[max(0, first.start() - window):first.start() + window]
        if all(re.search(r"(?<![a-z0-9])" + re.escape(stem), around, re.IGNORECASE) for stem in stems[1:]):
            return first.start()
    return -1


# words too common in READMEs to say anything about a feature
LOOSE_STOP = NEAR_STOP | {"code", "user", "users", "data", "file", "files", "note", "notes", "tool", "tools",
                          "support", "based", "open", "source", "using", "make", "more", "like", "allow",
                          "feature", "features", "system", "project", "application", "easy", "simple"}


def _hinted(text: str, phrases: list[str]) -> bool:
    """Any word of the component or its phrases at a word start, however
    far from the others: "reporter" for "report warnings", "DB graphs" for
    "graph visualization". Not enough to say a project has it; enough that
    saying the README is silent about it would mislead."""
    words = {w for phrase in phrases for w in re.findall(r"[a-z0-9]+", phrase.lower())
             if len(w) >= 4 and w not in LOOSE_STOP}
    stems = {w[:4] if len(w) <= 5 else w[:5] for w in words}
    return any(re.search(r"(?<![a-z0-9])" + re.escape(stem), text, re.IGNORECASE) for stem in stems)


def _snippet(text: str, at: int, width: int = 90) -> str:
    start = max(0, at - width // 3)
    return ("…" if start else "") + " ".join(text[start:start + width].split()) + "…"


def _quoted(quote: str, text: str) -> bool:
    """Is a model's "quote" really in the evidence? Word for word, or nearly:
    four in five of its words, in a text the model saw."""
    words = re.findall(r"[a-z0-9]{3,}", quote.lower())
    if len(words) < 3:
        return False
    if " ".join(quote.lower().split()) in " ".join(text.lower().split()):
        return True
    return sum(_mentions(text, word) >= 0 for word in words) >= 0.8 * len(words)


def _an_issue(quote: str, titles: list[str]) -> str | None:
    """The issue title a quote stands for: the same, or nearly (four in five
    of its words)."""
    words = re.findall(r"[a-z0-9]{3,}", quote.lower())
    for title in titles:
        if " ".join(quote.lower().split()) == " ".join(title.lower().split()):
            return title
        if len(words) >= 3 and sum(_mentions(title, w) >= 0 for w in words) >= 0.8 * len(words):
            return title
    return None


def ground_comparison(parsed: dict, gathered: list[dict], components: list[str]) -> dict:
    """The comparison as the evidence supports it.

    A cell is "var" only where the project's README, site or description
    mentions the component (its name or a phrase the model offered), with
    the passage kept to show; everywhere else it stays unknown, never "yok" —
    a README that does not mention search is no proof Logseq has none. A
    differentiator is a component no project's evidence mentions, said as
    exactly that. An argument survives only if its quote is in that
    project's evidence."""
    evidence = {facts["repo"]: " ".join(str(facts.get(key) or "") for key in
                                        ("evidence", "readme", "site", "description"))
                for facts in gathered}
    labels = dict(parsed.get("labels") or {})
    matrix, quotes, hinted = {}, {}, {}
    for component in components:
        phrases = list(dict.fromkeys([component, *(parsed.get("keywords") or {}).get(component, [])]))
        for repo, text in evidence.items():
            if _hinted(text, phrases):
                hinted.setdefault(component, set()).add(repo)
            at = next((pos for pos in (_mentions(text, phrase) for phrase in phrases) if pos >= 0), -1)
            if at < 0:
                at = _near(text, component)
            if at >= 0:
                matrix.setdefault(component, {})[repo] = "var"
                quotes.setdefault(component, {})[repo] = _snippet(text, at)
    analysed = {item["repo"]: item for item in parsed.get("projects") or []}
    projects = []
    for repo in evidence:
        seen = [c for c in components if repo in matrix.get(c, {})]
        # "not in what was read" only where not even a word of it is: the
        # rest is neither shown as there nor as missing
        silent = [c for c in components if c not in seen and repo not in hinted.get(c, set())]
        projects.append({**analysed.get(repo, {"repo": repo}), "repo": repo,
                         "shared": [labels.get(c, c) for c in seen],
                         "unseen": [labels.get(c, c) for c in silent]})
    differentiators = []
    if len(evidence) >= 2:
        for component in components:
            if component not in matrix and not hinted.get(component):
                differentiators.append(
                    f"“{labels.get(component, component)}”, incelenen {len(evidence)} projenin okunan README "
                    "ve sitelerinde geçmiyor; fikrini ayırabilecek bir nokta olabilir (yokluk kanıtı değil, "
                    "doğrulamak gerekir).")
    issues = {facts["repo"]: facts.get("issues") or [] for facts in gathered}
    arguments, from_issues = [], []
    for item in parsed.get("arguments") or []:
        repo = item.get("repo")
        if repo not in evidence:
            continue
        decision = item.get("decision") or ""
        target = (ladder.DECISIONS[decision][1] if decision in ladder.DECISIONS
                  else labels.get(decision, decision))
        title = _an_issue(item.get("quote", ""), issues.get(repo, []))
        if title:                           # what its users run into: the most telling
            from_issues.append(f"{target}: {item['idea']} ({repo} issue'su: “{title}”)")
        elif _quoted(item.get("quote", ""), evidence[repo]):
            arguments.append(f"{target}: {item['idea']} ({repo}: “{item['quote']}”)")
    arguments = from_issues + arguments
    return {"projects": projects, "matrix": matrix, "quotes": quotes, "labels": labels,
            "differentiators": differentiators[:4], "arguments": arguments[:5]}


def issue_titles(payload: dict, limit: int = 8) -> list[str]:
    rows = []
    if isinstance(payload, dict):
        rows = payload.get("items") or payload.get("issues") or []
    elif isinstance(payload, list):
        rows = payload
    titles = []
    for row in rows:
        title = " ".join(str((row or {}).get("title") or "").split())[:140] if isinstance(row, dict) else ""
        if title and title not in titles:
            titles.append(title)
        if len(titles) >= limit:
            break
    return titles


def log_result(record: dict, outcome: dict, rows: list) -> None:
    """A search that answered is not a search that found something. `ok` is
    the transport; `count` is what came back. Counting both as success made
    three empty prior-art queries out of six look like a full run."""
    record["ok"] = bool(outcome.get("ok"))
    record["count"] = len(rows or [])
    total = payload_of(outcome).get("total_count")
    if isinstance(total, int):
        record["total"] = total
    record["empty"] = record["ok"] and record["count"] == 0


def wider_queries(query: str) -> list[str]:
    """The earlier queries whose results contain everything this one could
    return: each topic of a topic pair, the lower star gate of a star gate."""
    query = " ".join(query.split())
    topics = re.findall(r"topic:([A-Za-z0-9][A-Za-z0-9-]*)", query)
    if len(topics) >= 2 and len(topics) == len(query.split()):
        return [f"topic:{topic}" for topic in topics]
    gate = re.fullmatch(r"(.+) stars:>(\d+)", query)
    if gate:
        return [f"{gate.group(1)} stars:>{lower}" for lower in STAR_GATES if lower < int(gate.group(2))]
    return []


def learned_topics(candidates: dict, terms, asked, limit: int = LEARNED_TOPICS) -> list[str]:
    """The topics the projects found actually carry, where they contain one of
    the idea's own words: "recipe-manager" and "meal-planner" from Mealie and
    Tandoor, which the model's "recipe-management" missed. A topic counts when
    two projects carry it, or one well-known project does."""
    profile = _profile(terms)
    phrases = profile.get("anchors") or terms.get("keywords") or []
    # five letters: "auto" of "automated" learned autonomous-agent
    stems = {w[:5] for phrase in phrases for w in re.findall(r"[a-z0-9]+", str(phrase).lower())
             if len(w) >= 4 and w not in PLAIN_WORDS}
    score = {}
    for candidate in candidates.values():
        text = " ".join((candidate.repo, candidate.description, " ".join(candidate.topics))).lower()
        if off_topic(text, terms):
            continue
        weight = 1 + ((candidate.stars or 0) >= KNOWN_STARS) + ((candidate.stars or 0) >= 5000)
        for topic in set(candidate.topics or []):
            topic = str(topic).lower()
            if f"topic:{topic}" in asked or not any(part.startswith(stem) for part in topic.split("-")
                                                    for stem in stems):
                continue
            score[topic] = score.get(topic, 0) + weight
    ranked = sorted(score.items(), key=lambda item: (-item[1], item[0]))
    return [topic for topic, points in ranked if points >= 2][:limit]


def plain_topic(query: str) -> str:
    """`topic:markdown-notebook` -> `markdown notebook`: the words the model
    meant, for when the topic itself does not exist on GitHub."""
    match = re.fullmatch(r"topic:([A-Za-z0-9][A-Za-z0-9-]*)", query.strip())
    return match.group(1).replace("-", " ") if match else ""


def apply_page_read(source, outcome, terms):
    """Attach actual page evidence, keeping a failed read distinct from a hit."""
    if not outcome.get("ok"):
        source["read_error"] = "Kaynak sayfası okunamadı."
        return
    payload = payload_of(outcome)
    page = str(payload.get("text") or "").strip()[:MAX_SOURCE_CONTENT]
    if not page:
        source["read_error"] = "Kaynak sayfası boş döndü."
        return
    query = str(source.get("query") or "").lower()
    library_page = (source.get("kind") == "support" and "library" in query and
                    re.search(r"\b(library|framework|package|sdk|api)\b", page.lower()) and
                    any(_component_match(part, page.lower(), terms) for part in
                        _components(terms.get("components"))))
    source.update({"verified": True, "read_error": None, "content": page,
                   "excerpt": evidence_excerpt(page, terms),
                   "relevance": relevance_score(page + " " + str(source.get("title") or ""),
                                                terms, require_context=(
                                                    source.get("query") != "GitHub README" and
                                                    not library_page)),
                   "final_url": str(payload.get("final_url") or source["url"])[:2000],
                   "fetched_at": payload.get("fetched_at")})


def evidence_fallback(candidates, sources, terms):
    """A bounded factual summary when the local judge returns no verdict.

    The number of search hits is not evidence of similarity. A candidate only
    becomes an adjacent example when its own description or fetched README
    covers at least two of the note's distinct implementation components.
    """
    components = _components(terms.get("components"))
    by_url = {source.get("url"): source for source in sources if source.get("verified")}
    supported = []
    for candidate in candidates:
        row = candidate.public() if isinstance(candidate, Candidate) else candidate
        text = " ".join((str(row.get("repo") or ""), str(row.get("description") or ""),
                         " ".join(row.get("topics") or [])))
        source = by_url.get(row.get("url"))
        if source:
            text += " " + str(source.get("content") or "")[:3500]
        if off_topic(text[:700], terms) or not _has_anchor(text, terms):
            continue
        hits = sum(_explicit_component_match(component, text.lower(), terms) for component in components)
        if hits >= 2:
            supported.append((hits, row.get("repo")))
    supported.sort(key=lambda item: -item[0])
    nearby = [repo for _, repo in supported[:3] if repo]
    if nearby:
        return {"same": [], "adjacent": nearby,
                "verdict": "Bazı özellikler şu projelerde görülüyor: " + ", ".join(nearby) +
                           ". Kapsam ve uygulama farkları ayrıca incelenmeli."}
    return {"same": [], "adjacent": [],
            "verdict": "Bu tarama yakın bir uygulamayı doğrulamadı; sonuçlar sınırlı."}


def calibrate_prior_art(result, candidates, sources, terms):
    """Turn the model's labels into claims supported by returned evidence.

    Search descriptions can establish overlap. An exact match needs a read
    README and explicit evidence for every listed component; a short model
    verdict alone cannot establish that two products have identical scope.
    """
    components = _components(terms.get("components"))
    rows = {c.repo: c for c in candidates}
    readmes = {s.get("url"): s for s in sources if s.get("verified") and
               urlsplit(s.get("url") or "").hostname == "github.com"}
    same, adjacent = [], []
    for label, destination in (("same", same), ("adjacent", adjacent)):
        for repo in result.get(label) or []:
            candidate = rows.get(repo)
            if not candidate or repo in same or repo in adjacent:
                continue
            text = " ".join((candidate.repo, candidate.description,
                             " ".join(candidate.topics))).lower()
            readme = readmes.get(candidate.url)
            if readme:
                text += " " + str(readme.get("content") or "")[:3500].lower()
            if off_topic(text[:700], terms) or not _has_anchor(text, terms):
                continue
            hits = sum(_explicit_component_match(part, text, terms) for part in components)
            if components and not hits:
                continue
            confirmed = (label == "same" and len(components) >= 3 and
                         hits == len(components) and readme is not None)
            (same if confirmed else adjacent).append(repo)
    if not components:
        same = [repo for repo in result.get("same") or [] if repo in rows]
        adjacent = [repo for repo in result.get("adjacent") or [] if repo in rows and repo not in same]
    if same:
        verdict = ("Okunan depo belgeleri şu projelerde nottaki temel işlevleri gösteriyor: " +
                   ", ".join(same[:3]) + ". Kapsam ve deneyim farkları ayrıca incelenmeli.")
    elif adjacent:
        verdict = ("Notta geçen bazı işlevler şu projelerde görülüyor: " +
                   ", ".join(adjacent[:3]) + ". Kapsamın aynı olduğu doğrulanmadı.")
    else:
        verdict = evidence_fallback(candidates, sources, terms)["verdict"]
    return {"same": same[:5], "adjacent": adjacent[:5], "verdict": verdict}


class ResearchRunner:
    """One user-started research run per note, with progress over the broker.

    Similar projects and reusable components use separate, bounded GitHub and
    web searches. The result and its sources live in per-note assistant state.
    """

    def __init__(self, vault, notes, broker, tool_hub, provider_for, record_usage=None,
                 is_private=None):
        self.vault = vault
        self.notes = notes
        self.broker = broker
        self.tool_hub = tool_hub
        self.provider_for = provider_for
        self.record_usage = record_usage
        # a search puts the idea itself on someone else's server, so the same
        # rule that keeps a private note off remote models applies here too
        self.is_private = is_private or (lambda _rel: False)
        self.running = {}
        # notes whose current run skips web_search: every web search opens a
        # visible browser window, and the writer may not want that
        self.web_off = set()

    def state(self, rel):
        return dict(self.notes.load(rel).get("research") or {})

    def _save(self, rel, **fields):
        with self.notes.lock:
            state = self.notes.load(rel)
            current = dict(state.get("research") or {})
            current.update(fields)
            state["research"] = current
            self.notes.save(rel)
        return current

    def _progress(self, rel, step, note="", **extra):
        self.broker.publish("research", {"path": rel, "step": step, "note": note, **extra})

    def busy(self, rel):
        task = self.running.get(rel)
        return task is not None and not task.done()

    def _assert_public(self, rel, content):
        # The editor sends unsaved text. Checking only the on-disk note would
        # leak an unsaved `gizli: true` note to both search servers.
        meta, _, _ = split_frontmatter(content)
        private_value = meta.get("gizli", meta.get("private", ""))
        if self.is_private(rel) or str(private_value).strip().lower() in {"true", "evet", "yes", "1"}:
            raise ApiError(403, "Bu not gizli: fikri aratmak onu disari gonderir. "
                                "Arastirmak icin notun basindaki 'gizli' satirini kaldir.")

    async def start(self, rel, content, focus=None, web=True):
        if self.busy(rel):
            return {"status": "busy"}
        self._assert_public(rel, content)
        registry = getattr(self.tool_hub, "registry", {}) if self.tool_hub else {}
        if not registry or not ({"git_search", "web_search"} & set(registry)):
            raise ApiError(503, "Arastirma sunuculari calismiyor.")
        if not web and "git_search" not in registry:
            raise ApiError(503, "GitHub araması çalışmıyor; web araması kapalıyken aranacak yer kalmadı.")
        (self.web_off.discard if web else self.web_off.add)(rel)
        focus = " ".join(str(focus or "").split())[:MAX_FOCUS_CHARS]
        started = self._save(rel, status="running", started=now_iso(), focus=focus, web=bool(web),
                             candidates=[],
                             tools=[], opportunities=[], sources=[], queries=[],
                             verdict=None, error=None, timings={})
        task = asyncio.create_task(self._run(rel, content, focus))
        self.running[rel] = task
        task.add_done_callback(lambda _t: self.running.pop(rel, None))
        return {**started, "status": "started"}

    async def _run(self, rel, content, focus=""):
        started = time.perf_counter()
        timings = {}

        async def timed(stage, step):
            stage_started = time.perf_counter()
            try:
                return await step
            finally:
                timings[stage] = round(time.perf_counter() - stage_started, 2)
                self._save(rel, timings=dict(timings))

        try:
            self._assert_public(rel, content)
            research_text = (f"[ARAŞTIRMA ODAĞI]\n{focus}\n\n[NOT]\n{content}"
                             if focus else content)
            terms = await timed("terms", self._terms(rel, research_text))
            self._assert_public(rel, content)
            queries = []
            candidates = await timed("prior_git", self._search(rel, terms, content, queries))
            sources = await timed("prior_web", self._web(rel, terms, candidates, content, queries))
            helpers = await timed("support", self._support(rel, terms, content, queries, sources))
            route_helper_products(candidates, helpers, terms)
            self._save(rel, candidates=[c.public() for c in
                       rank(candidates, keywords=terms.get("keywords"), terms=terms)])
            await timed("adjacent", self._adjacent(rel, terms, content, queries, sources))
            if not any(entry.get("ok") for entry in queries):
                raise ApiError(502, "Arastirma kaynaklari yanit vermedi; eslesme yok sonucu cikarilamaz.")
            await timed("web_reads", self._fetch_sources(rel, content, sources, terms,
                                                        helpers=helpers, query_log=queries))
            await timed("readmes", self._fetch_helper_docs(rel, content, helpers, sources,
                                                           terms, candidates))
            ranked = rank(candidates, keywords=terms.get("keywords"), terms=terms)
            results = await timed("judge", self._judge(
                rel, research_text, ranked,
                diverse_helpers(helpers, terms.get("components") or [],
                                terms.get("keywords") or [], terms=terms),
                sources, terms, queries, timings))
            deep = await timed("rakipler", self._deep(rel, research_text, ranked,
                                                      results["verdict"], sources, terms))
            if deep:
                results["deep"] = deep
            timings["total"] = round(time.perf_counter() - started, 2)
            saved = self._save(rel, status="done", finished=now_iso(), timings=dict(timings),
                               **results)
            self._progress(rel, "bitti", results["verdict"].get("verdict", ""), result=saved)
        except ApiError as exc:
            timings["total"] = round(time.perf_counter() - started, 2)
            self._save(rel, status="error", error=exc.message, timings=dict(timings))
            self._progress(rel, "hata", exc.message)
        except asyncio.CancelledError:
            timings["total"] = round(time.perf_counter() - started, 2)
            self._save(rel, status="cancelled", timings=dict(timings))
            raise
        except Exception as exc:
            timings["total"] = round(time.perf_counter() - started, 2)
            self._save(rel, status="error", error=type(exc).__name__ + ": " + str(exc),
                       timings=dict(timings))
            self._progress(rel, "hata", str(exc)[:200])

    async def _terms(self, rel, content):
        self._progress(rel, "terimler", "Fikirden arama terimleri cikariliyor")
        provider = self.provider_for("analysis", rel)
        terms = await asyncio.to_thread(llm_client.extract_search_terms, content, provider,
                                        self.record_usage)
        if not any(terms.get(key) for key in ("keywords", "topics", "components")):
            raise ApiError(422, "Fikirden arama terimi cikarilamadi; notu biraz daha yaz.")
        profile = await self._research_profile(rel, content, terms)
        if profile:
            terms = {**terms, "profile": profile}
        self._save(rel, terms=terms)
        self._progress(rel, "terimler", "Terimler hazir.", terms=terms)
        return terms

    async def _search(self, rel, terms, content, query_log):
        if "git_search" not in getattr(self.tool_hub, "registry", {}):
            return {}
        queries = build_queries(terms.get("keywords"), terms.get("topics"),
                                terms.get("summary"), terms.get("components"),
                                _profile(terms))[:MAX_GITHUB_QUERIES]
        candidates = {}
        spare = [f"topic:{tag}" for tag in _tags(terms.get("topics"), _profile(terms))]
        complete = set()        # queries whose every result came back
        swaps, skipped, index = 0, 0, 0

        def asked():
            return {q["query"] for q in queries} | {str(q.get("query")) for q in query_log}

        async def run(entry, number, total):
            self._assert_public(rel, content)
            self._progress(rel, "arama", f"GitHub {number}/{total}: {entry['query']}", done=number - 1, total=total)
            record = {"purpose": "prior", **entry, "ok": False}
            query_log.append(record)
            try:
                outcome = await self.tool_hub.call(
                    "git_search", {"query": entry["query"], "per_page": PER_PAGE, "sort": "stars"})
            except ApiError:
                return None
            rows = items_of(outcome) if outcome.get("ok") else []
            log_result(record, outcome, rows)
            if not outcome.get("ok"):
                return None
            if isinstance(record.get("total"), int) and record["total"] <= record["count"]:
                complete.add(entry["query"])
            merge(candidates, entry["style"], rows)
            words = plain_topic(entry["query"]) if not rows and entry["style"] == "topic" else ""
            if words and not any(q.get("query") == words for q in query_log):
                # the model named a topic GitHub has never heard of; its words
                # still describe the idea, so ask for them once as plain text
                retry = {"purpose": "prior", "style": "topic-duz", "query": words, "ok": False}
                query_log.append(retry)
                try:
                    again = await self.tool_hub.call(
                        "git_search", {"query": words, "per_page": PER_PAGE, "sort": "stars"})
                except ApiError:
                    again = {}
                again_rows = items_of(again) if again.get("ok") else []
                log_result(retry, again, again_rows)
                merge(candidates, "topic-duz", again_rows)
            self._save(rel, candidates=[c.public() for c in rank(candidates, keywords=terms.get("keywords"),
                                                                  terms=terms)],
                       queries=query_log)
            return rows

        while index < len(queries):
            entry = queries[index]
            index += 1
            if any(wider in complete for wider in wider_queries(entry["query"])):
                # a topic pair inside a topic that came back whole, a higher
                # star gate inside a lower one: nothing new can come of it
                query_log.append({"purpose": "prior", **entry, "ok": True, "skipped": True, "count": 0})
                skipped += 1
                continue
            rows = await run(entry, index, len(queries))
            if (rows is not None and entry["style"] == "topic" and 0 < len(rows) < THIN_TOPIC
                    and swaps < MAX_TOPIC_SWAPS):
                better = next((topic for topic in spare if topic not in asked()), None)
                if better:
                    queries.insert(index, {"style": "topic", "query": better})
                    swaps += 1
        # the calls saved above go to the topics the found projects carry
        learned = learned_topics(candidates, terms, asked(), LEARNED_TOPICS + skipped)
        for number, topic in enumerate(learned, start=1):
            await run({"style": "topic", "query": f"topic:{topic}", "learned": True},
                      len(queries) + number, len(queries) + len(learned))
        self._progress(rel, "arama", str(len(candidates)) + " aday bulundu.",
                       done=len(queries) + len(learned), total=len(queries) + len(learned))
        return candidates

    def _web_ok(self, rel):
        return "web_search" in getattr(self.tool_hub, "registry", {}) and rel not in self.web_off

    async def _web(self, rel, terms, candidates, content, query_log):
        """Asks the web the same question three ways (see prior_web_queries).
        Each search opens a browser window and costs about twelve seconds."""
        if not self._web_ok(rel):
            return []
        queries = prior_web_queries(terms.get("summary") or " ".join(terms.get("keywords") or []),
                                    terms.get("keywords"))
        sources, repos = [], []
        for index, query in enumerate(queries, start=1):
            self._assert_public(rel, content)
            record = {"purpose": "prior", "style": "web", "query": query, "ok": False}
            query_log.append(record)
            self._progress(rel, "web", f"Webde capraz kontrol {index}/{len(queries)} (arka planda)")
            try:
                outcome = await self.tool_hub.call("web_search", {"query": query})
            except ApiError:
                continue
            results = payload_of(outcome).get("results") or [] if outcome.get("ok") else []
            log_result(record, outcome, results)
            if not outcome.get("ok"):
                continue
            seen = {source["url"] for source in sources}
            sources.extend(source for source in sources_in_web_results(results, query, "prior",
                                                                        limit=PRIOR_WEB_SOURCES)
                           if source["url"] not in seen and not off_topic(
                               " ".join(str(source.get(key) or "") for key in ("url", "title", "snippet")),
                               terms))
            repos.extend(repo for repo in repos_in_web_results(results) if repo not in repos)
        for repo in repos:
            self._assert_public(rel, content)
            key = next((name for name in candidates if name.casefold() == repo.casefold()), None)
            if key:
                candidates[key].found_by.append("web")
                continue
            try:
                detail = await self.tool_hub.call("git_repo", {"repo": repo})
            except ApiError:
                continue
            if detail.get("ok"):
                merge(candidates, "web", [payload_of(detail)])
        self._progress(rel, "web", "Web " + str(len(repos)) + " depo onerdi.")
        self._save(rel, candidates=[c.public() for c in rank(candidates, keywords=terms.get("keywords"), terms=terms)],
                   sources=sources, queries=query_log)
        return sources

    async def _support(self, rel, terms, content, query_log, sources):
        helpers = {}
        if "git_search" in getattr(self.tool_hub, "registry", {}):
            queries = build_support_queries(terms.get("keywords"), terms.get("topics"),
                                            terms.get("components"), terms.get("summary"), _profile(terms))
            for index, entry in enumerate(queries, start=1):
                self._assert_public(rel, content)
                self._progress(rel, "araclar", f"GitHub {index}/{len(queries)}: {entry['query']}",
                               done=index - 1, total=len(queries))
                record = {"purpose": "support", **entry, "ok": False}
                query_log.append(record)
                try:
                    outcome = await self.tool_hub.call("git_search", {
                        "query": entry["query"], "per_page": PER_PAGE, "sort": "stars"})
                except ApiError:
                    continue
                rows = items_of(outcome) if outcome.get("ok") else []
                log_result(record, outcome, rows)
                if outcome.get("ok"):
                    merge(helpers, entry["style"], rows)
        if self._web_ok(rel):
            for query in support_web_queries(terms.get("keywords"), terms.get("topics"),
                                             terms.get("components"), terms.get("summary"),
                                             _profile(terms)):
                self._assert_public(rel, content)
                self._progress(rel, "kaynaklar", "Yardimci araclar ve uygulama ornekleri araniyor")
                record = {"purpose": "support", "style": "web", "query": query, "ok": False}
                query_log.append(record)
                try:
                    outcome = await self.tool_hub.call("web_search", {"query": query})
                except ApiError:
                    continue
                results = payload_of(outcome).get("results") or [] if outcome.get("ok") else []
                log_result(record, outcome, results)
                if not outcome.get("ok"):
                    continue
                existing = {source["url"]: source for source in sources}
                for source in sources_in_web_results(results, query, "support", limit=4):
                    if source_prefetch_score(source, terms) < 2:
                        continue
                    if source["url"] in existing:
                        # A source surfaced independently in the tool search;
                        # retain it as support evidence so it can be fetched.
                        if existing[source["url"]]["kind"] != "support":
                            existing[source["url"]]["kind"] = "support"
                            existing[source["url"]]["query"] = query
                    else:
                        sources.append(source)
                        existing[source["url"]] = source
                plausible = [row for row in results if isinstance(row, dict) and not off_topic(
                    " ".join(str(row.get(key) or "") for key in ("url", "title", "snippet")), terms)]
                for repo in repos_in_web_results(plausible, limit=3):
                    self._assert_public(rel, content)
                    # "support-web", not "web": this search asked for a
                    # component, so it must not vote as a prior-art strategy
                    key = next((name for name in helpers if name.casefold() == repo.casefold()), None)
                    if key:
                        helpers[key].found_by.append("support-web")
                        continue
                    try:
                        detail = await self.tool_hub.call("git_repo", {"repo": repo})
                    except ApiError:
                        continue
                    if detail.get("ok"):
                        merge(helpers, "support-web", [payload_of(detail)])
        sources[:] = prioritized_sources(sources)
        self._save(rel, sources=sources, queries=query_log)
        return helpers

    async def _adjacent(self, rel, terms, content, query_log, sources):
        if not self._web_ok(rel):
            return
        query = adjacent_web_query(terms.get("keywords"), terms.get("components"),
                                   terms.get("topics"), terms.get("summary"), _profile(terms))
        if not query:
            return
        self._assert_public(rel, content)
        self._progress(rel, "kaynaklar", "Alternatif yaklaşımlar ve komşu fikirler aranıyor")
        record = {"purpose": "adjacent", "style": "web", "query": query, "ok": False}
        query_log.append(record)
        try:
            outcome = await self.tool_hub.call("web_search", {"query": query})
        except ApiError:
            return
        results = payload_of(outcome).get("results") or [] if outcome.get("ok") else []
        log_result(record, outcome, results)
        if not outcome.get("ok"):
            return
        existing = {source["url"]: source for source in sources}
        for source in sources_in_web_results(results, query, "adjacent", limit=6):
            if source_prefetch_score(source, terms) < 2:
                continue
            old = existing.get(source["url"])
            if old is None:
                sources.append(source)
                existing[source["url"]] = source
            elif old["kind"] == "prior":
                old["kind"] = "adjacent"
                old["query"] = query
        sources[:] = prioritized_sources(sources)
        self._save(rel, sources=sources, queries=query_log)

    async def _fetch_sources(self, rel, content, sources, terms, helpers=None, query_log=None):
        if "web_fetch" not in getattr(self.tool_hub, "registry", {}):
            return
        chosen = select_sources_for_fetch(sources, terms)
        gate = asyncio.Semaphore(READ_CONCURRENCY)

        async def read(source):
            async with gate:
                self._assert_public(rel, content)
                self._progress(rel, "kaynaklar", "Kaynak sayfasi okunuyor: " + source["title"][:80])
                query = source.get("query") or " ".join(_keywords(terms.get("keywords"), 3))
                try:
                    outcome = await self.tool_hub.call("web_fetch", {
                        "url": source["url"], "query": str(query)[:200]})
                except ApiError as exc:
                    source["read_error"] = exc.message[:200]
                    return
                except Exception as exc:
                    source["read_error"] = type(exc).__name__
                    return
                apply_page_read(source, outcome, terms)

        await asyncio.gather(*(read(source) for source in chosen))
        if helpers is not None and "git_search" in getattr(self.tool_hub, "registry", {}):
            # A component library's homepage often has only its brand in the
            # search snippet (Sigma.js was one live example). Once the page
            # itself confirms the graph library, resolve its repository with
            # one bounded GitHub query so it can be proposed as a tool.
            for source in chosen:
                if (not source.get("verified") or int(source.get("relevance") or 0) < 2 or
                        str(source.get("query") or "") not in _library_queries(terms)):
                    continue
                brand = str(source.get("title") or "").split(" | ", 1)[0].strip()
                if not re.fullmatch(r"[A-Za-z][A-Za-z0-9.+-]{2,40}", brand):
                    continue
                self._assert_public(rel, content)
                record = {"purpose": "support", "style": "verified-library", "query": brand,
                          "ok": False}
                if query_log is not None:
                    query_log.append(record)
                try:
                    outcome = await self.tool_hub.call("git_search", {
                        "query": brand, "per_page": 10, "sort": "stars"})
                except ApiError:
                    break
                log_result(record, outcome, items_of(outcome) if outcome.get("ok") else [])
                if outcome.get("ok"):
                    canonical = re.sub(r"[^a-z0-9]", "", brand.lower())
                    for item in items_of(outcome):
                        if not isinstance(item, dict):
                            continue
                        repo = str(item.get("repo") or "")
                        repo_name = re.sub(r"[^a-z0-9]", "", repo.rsplit("/", 1)[-1].lower())
                        if repo_name != canonical or not any(_component_match(
                                part, str(item.get("description") or "").lower(), terms)
                                for part in _components(terms.get("components"))):
                            continue
                        merge(helpers, "verified-library", [item])
                        key = next((name for name in helpers if name.casefold() == repo.casefold()), None)
                        if key:
                            helpers[key].evidence_url = source["url"]
                        break
                break
        sources[:] = prioritized_sources(sources)
        fields = {"sources": sources}
        if query_log is not None:
            fields["queries"] = query_log
        self._save(rel, **fields)

    async def _fetch_helper_docs(self, rel, content, helpers, sources, terms, prior=None):
        """Read both comparable products and reusable components at the source."""
        if "web_fetch" not in getattr(self.tool_hub, "registry", {}):
            return
        components = terms.get("components") or []
        keywords = terms.get("keywords") or []
        prior_rows = rank(prior or {}, limit=4, keywords=keywords, terms=terms)
        helper_rows = diverse_helpers(helpers, components, keywords, limit=6, terms=terms)
        desired = [(candidate, "support") for candidate in helper_rows[:3]] + [
            (candidate, "prior") for candidate in prior_rows] + [
            (candidate, "support") for candidate in helper_rows[3:]]
        chosen = []
        seen = set()
        for candidate, kind in desired:
            if candidate.repo.casefold() in seen:
                continue
            seen.add(candidate.repo.casefold())
            chosen.append((candidate, kind))
            if len(chosen) >= MAX_REPO_READS:
                break
        gate = asyncio.Semaphore(READ_CONCURRENCY)

        async def read(candidate, kind):
            async with gate:
                self._assert_public(rel, content)
                self._progress(rel, "kaynaklar", "Depo açıklaması okunuyor: " + candidate.repo)
                existing = next((source for source in sources if source["url"] == candidate.url), None)
                row = existing if existing is not None else {
                    "url": candidate.url, "title": candidate.repo + " README",
                    "snippet": candidate.description[:300], "query": "GitHub README",
                    "kind": kind, "verified": False, "read_error": None, "relevance": 0}
                if existing is None:
                    sources.append(row)
                try:
                    outcome = await self.tool_hub.call("web_fetch", {
                        "url": candidate.url,
                        "query": " ".join(_keywords([*components, *keywords], 6))[:200]})
                except ApiError as exc:
                    row["read_error"] = exc.message[:200]
                    return
                except Exception as exc:
                    row["read_error"] = type(exc).__name__
                    return
                apply_page_read(row, outcome, terms)

        await asyncio.gather(*(read(candidate, kind) for candidate, kind in chosen))
        sources[:] = prioritized_sources(sources)
        self._save(rel, sources=sources)

    async def _deep(self, rel, content, ranked, verdict, sources, terms):
        """The closest projects, looked at closely: their activity, their recent
        issues (what their users complain about), their README and their site —
        read through web_fetch, whose browser tier renders script-built pages —
        then one model call compares them with the idea (compare_projects)."""
        # the closest by the verdict, then the best known on the list: a live
        # run looked only at 0-1 star repos the verdict named, and never at
        # Logseq, Joplin or Foam, the ones a writer is actually up against
        by_repo = {c.repo: c for c in ranked}
        picked = [repo for repo in dict.fromkeys([*(verdict.get("same") or []), *(verdict.get("adjacent") or [])])
                  if repo in by_repo]
        closest = picked[:3]
        # ...the most relevant of the well-known ones, not the most starred:
        # by stars alone a 246k-star "collection of lists" and a code-graph
        # engine took two of the five places while Logseq waited (live run).
        # A threshold relative to the best score did not hold either — the
        # best was a 0-star repo, and Logseq fell under it on the next run.
        def fit(c):
            return relevance_score(" ".join((c.repo, c.description or "", " ".join(c.topics or []))).lower(),
                                   terms)
        famous = [c for c in ranked if c.repo not in closest and (c.stars or 0) >= KNOWN_STARS]
        floor = max((fit(c) for c in famous), default=0) / 2
        known = [c.repo for c in sorted(famous, key=lambda c: (-fit(c), -(c.stars or 0))) if fit(c) >= floor]
        # ...and only those doing the idea's job for the idea's users: Lago,
        # billing for SaaS companies, came in as "best known" for a family
        # subscription tracker. The model sorts the pool; without an answer
        # the choice stays as it was.
        pool = list(dict.fromkeys([*picked, *known, *(c.repo for c in ranked)]))[:COMPETITOR_POOL]
        kinds = await self._competitor_kinds(rel, content, [by_repo[repo] for repo in pool])
        neighbours = []
        if kinds:
            # the model's competitors in the model's order: which and how many
            # is its judgement; the closest-three-then-stars rule is only the
            # fallback for when it gave none
            order = [repo for repo, (kind, _) in kinds.items() if kind == "ayni"]
            neighbours = [{"repo": repo, "stars": by_repo[repo].stars, "why": why}
                          for repo, (kind, why) in kinds.items() if kind == "komsu"][:6]
        else:
            order = [*closest, *known]
        chosen = [by_repo[repo] for repo in dict.fromkeys(order)][:DEEP_PROJECTS]
        if not chosen:
            return {"components": [], "projects": [], "matrix": {}, "quotes": {}, "labels": {},
                    "differentiators": [], "arguments": [], "neighbours": neighbours} if neighbours else None
        self._progress(rel, "rakipler", f"{len(chosen)} benzer proje yakından inceleniyor")
        registry = getattr(self.tool_hub, "registry", {})
        query = " ".join(_keywords([*(terms.get("components") or []), *(terms.get("keywords") or [])], 6))[:200]
        gate = asyncio.Semaphore(READ_CONCURRENCY)

        async def call(name, arguments):
            if name not in registry:
                return None
            try:
                outcome = await asyncio.wait_for(self.tool_hub.call(name, arguments), DEEP_CALL_TIMEOUT)
            except Exception:
                return None
            return payload_of(outcome) if isinstance(outcome, dict) and outcome.get("ok") else None

        async def look(candidate):
            async with gate:
                self._assert_public(rel, content)
                self._progress(rel, "rakipler", "İnceleniyor: " + candidate.repo)
                facts = {"repo": candidate.repo, "url": candidate.url, "description": candidate.description,
                         "stars": candidate.stars, "license": candidate.license}
                facts.update(repo_facts(await call("git_repo", {"repo": candidate.repo}) or {}))
                # the most discussed issues: what its users run into most, not
                # the latest dependency bump
                facts["issues"] = issue_titles(await call("git_issues", {"repo": candidate.repo,
                                                                         "sort": "comments"}) or {})
                read = next((s for s in sources if s.get("url") == candidate.url and s.get("verified")), None)
                readme = str((read or {}).get("content") or (read or {}).get("excerpt") or "")
                if not readme:
                    # the README itself from GitHub, links and all, before the page
                    readme = str((await call("git_readme", {"repo": candidate.repo}) or {}).get("text") or "")
                homepage = str(facts.get("homepage") or "")
                if not readme or not (homepage or readme_homepage(readme, candidate.repo)):
                    # an excerpt keeps no links; the page itself does
                    page = await call("web_fetch", {"url": candidate.url, "query": query})
                    readme = str((page or {}).get("text") or "") or readme
                facts["readme"] = readme[:1500]
                facts["evidence"] = readme          # all of it, for ground_comparison; not stored
                if not homepage.startswith("http"):
                    homepage = readme_homepage(readme, candidate.repo) or ""
                    if homepage:
                        facts["homepage"] = homepage
                if homepage.startswith("http") and "github.com" not in homepage:
                    site = await call("web_fetch", {"url": homepage, "query": query})
                    facts["site"] = str((site or {}).get("text") or "")[:900]
                return facts

        gathered = await asyncio.gather(*(look(candidate) for candidate in chosen))
        components = _components(terms.get("components")) or _keywords(terms.get("keywords"), 4)
        self._progress(rel, "rakipler", "Benzer projeler fikirle karşılaştırılıyor")
        try:
            decisions = ladder.brief(ladder.state(self.notes.load(rel).get("decisions")))
            parsed = await asyncio.to_thread(
                llm_client.compare_projects, content, components, gathered,
                self.provider_for("compare", rel), self.record_usage, decisions=decisions)
        except Exception:
            parsed = {}                         # the matrix still comes from the evidence
        comparison = ground_comparison(parsed, gathered, components)
        analysed = {item["repo"]: item for item in comparison["projects"]}
        projects = []
        for facts in gathered:
            keep = {key: facts.get(key) for key in ("repo", "url", "description", "stars", "forks", "license",
                                                    "updated", "open_issues", "homepage", "archived")}
            keep["issues"] = facts.get("issues") or []
            keep["read"] = {"readme": bool(facts.get("readme")), "site": bool(facts.get("site")),
                            "issues": bool(facts.get("issues"))}
            projects.append({**keep, **analysed.get(facts["repo"], {})})

        def ids(texts, kind):
            return [{"id": kind[:3] + "-" + hashlib.sha256(text.encode()).hexdigest()[:10], "kind": kind,
                     "text": text} for text in texts]

        return {"components": components, "projects": projects, "matrix": comparison["matrix"],
                "quotes": comparison["quotes"], "labels": comparison["labels"], "neighbours": neighbours,
                "differentiators": ids(comparison["differentiators"], "ayrisma"),
                "arguments": ids(comparison["arguments"], "arguman")}

    async def _research_profile(self, rel, content, terms) -> dict:
        """This idea's own search rules from the model; {} when there is no
        model or no answer — then no field-specific rule applies at all."""
        try:
            provider = self.provider_for("compare", rel)
        except ApiError:
            return {}
        if provider is None:
            return {}
        self._progress(rel, "terimler", "Bu fikre özel arama kuralları çıkarılıyor")
        try:
            return await asyncio.to_thread(llm_client.research_profile, content, terms, provider,
                                           self.record_usage)
        except Exception:
            return {}

    async def _competitor_kinds(self, rel, content, candidates) -> dict:
        """repo -> (ayni | komsu | alakasiz, why); {} when there is no model or
        it did not answer — the caller then keeps its old choice."""
        try:                                # no model, or the day's budget spent
            provider = self.provider_for("compare", rel)
        except ApiError:
            return {}
        if provider is None or not candidates:
            return {}
        self._progress(rel, "rakipler", "Adaylar ayıklanıyor: aynı işi mi yapıyor, komşu alan mı")
        # by stars, not by the order the search produced: the model echoed
        # the order it was given, and the 41k-star competitor sat ninth behind
        # small projects and fell under the ceiling (measured)
        rows = [{"repo": c.repo, "description": c.description, "topics": c.topics, "stars": c.stars}
                for c in sorted(candidates, key=lambda c: -(c.stars or 0))]
        try:
            return await asyncio.to_thread(llm_client.classify_competitors, content, rows, provider,
                                           self.record_usage)
        except Exception:
            return {}

    async def _judge(self, rel, content, ranked, helpers, sources, terms, queries,
                     timings=None):
        self._progress(rel, "degerlendirme", "Bulunanlar fikirle karsilastiriliyor")
        listed = [c.public() for c in ranked]
        prior_provider = self.provider_for("analysis", rel)
        recommend_provider = self.provider_for("chat", rel)
        prior_started = time.perf_counter()
        if any(q.get("purpose") == "prior" and q.get("ok") for q in queries):
            result = await asyncio.to_thread(llm_client.judge_prior_art, content, listed, prior_provider,
                                             self.record_usage, sources=sources)
        else:
            result = {"same": [], "adjacent": [],
                      "verdict": "Benzer proje aramasi tamamlanamadi; eslesme yok sonucu cikarilamaz."}
        if timings is not None:
            timings["prior_judge"] = round(time.perf_counter() - prior_started, 2)
            self._save(rel, timings=dict(timings))
        result = calibrate_prior_art(result, ranked, sources, terms)
        self._progress(rel, "oneriler", "Yardimci araclar ve gelistirme firsatlari degerlendiriliyor")
        helper_rows = [c.public() for c in helpers]
        grounded_sources = [source for source in sources if source.get("verified") and
                            int(source.get("relevance") or 0) >= 2]
        recommendations_started = time.perf_counter()
        recommendations = await asyncio.to_thread(
            llm_client.recommend_research, content, helper_rows, grounded_sources,
            recommend_provider, self.record_usage)
        if timings is not None:
            timings["recommendations"] = round(time.perf_counter() - recommendations_started, 2)
            self._save(rel, timings=dict(timings))
        selected = {item["repo"]: item for item in recommendations["tools"]}
        tools = []
        for candidate in helpers:
            recommendation = selected.get(candidate.repo)
            if not recommendation or not recommendation.get("why") or not candidate.description:
                continue
            evidence = next((source for source in sources if source.get("url") == candidate.url), None)
            tools.append({"id": candidate.repo, "repo": candidate.repo, "name": candidate.repo,
                          "url": candidate.url, "description": candidate.description,
                          "stars": candidate.stars, "language": candidate.language,
                          "license": candidate.license,
                          "why": recommendation["why"],
                          "recommended": True,
                          "relevance": int((evidence or {}).get("relevance") or 0),
                          "source_urls": [url for url in (candidate.url, candidate.evidence_url) if url],
                          "found_by": sorted(set(candidate.found_by))})
        tools.sort(key=lambda item: not item["recommended"])
        opportunities = []
        for item in recommendations["opportunities"]:
            digest = hashlib.sha256((item["title"] + "\0" + item["detail"]).encode()).hexdigest()[:12]
            opportunities.append({"id": "opp-" + digest, **item})
        return {"candidates": listed, "verdict": result, "terms": terms, "tools": tools,
                "opportunities": opportunities, "sources": sources, "queries": queries}
