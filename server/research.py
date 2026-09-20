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
import json
import re
from dataclasses import dataclass, field

from core import llm_client
from server.errors import ApiError
from server.store import now_iso

MAX_KEYWORDS = 6
MAX_TOPICS = 4
MAX_GITHUB_QUERIES = 6      # each costs ~6s: the server throttles searches
PER_PAGE = 20
STAR_GATES = (5000, 20000)  # big projects hide behind generic words without these


def _clean(items, limit: int) -> list[str]:
    seen: list[str] = []
    for raw in items or []:
        word = str(raw).strip().lower()
        if word and word not in seen:
            seen.append(word)
    return seen[:limit]


def build_queries(keywords, topics) -> list[dict]:
    """One query per proven style, built from what the model extracted.

    Returns [{"style", "query"}] in the order they should run; the caller cuts
    the list at MAX_GITHUB_QUERIES.
    """
    words = _clean(keywords, MAX_KEYWORDS)
    tags = _clean(topics, MAX_TOPICS)
    queries: list[dict] = []

    def add(style: str, query: str):
        query = query.strip()
        if query and not any(q["query"] == query for q in queries):
            queries.append({"style": style, "query": query})

    # the single most effective style in the trial: a specific topic on its own
    for tag in tags[:3]:
        add("topic", f"topic:{tag.replace(' ', '-')}")
    if len(tags) >= 2:
        add("topic-pair", f"topic:{tags[0].replace(' ', '-')} topic:{tags[1].replace(' ', '-')}")
    if words:
        add("kisa", " ".join(words[:3]))
        for gate in STAR_GATES:
            add("populer", f"{' '.join(words[:2])} stars:>{gate}")
    return queries


def web_query(summary: str) -> str:
    """Web search ranks 'what are the popular X' far better than GitHub does —
    it found projects GitHub search missed, and missed ones GitHub found."""
    summary = " ".join(str(summary or "").split())[:180]
    return f"best open source {summary} github" if summary else ""


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

    def public(self) -> dict:
        return {"repo": self.repo, "stars": self.stars, "language": self.language,
                "license": self.license, "description": self.description, "url": self.url,
                "pushed_at": self.pushed_at, "topics": self.topics,
                "found_by": sorted(set(self.found_by))}


def merge(candidates: dict, style: str, items: list[dict]) -> None:
    """Fold one search's results into the running set, remembering provenance.
    A repo found by several styles is a stronger signal than a lone hit."""
    for item in items or []:
        repo = str(item.get("repo") or "").strip()
        if not repo:
            continue
        current = candidates.get(repo)
        if current is None:
            current = candidates[repo] = Candidate(
                repo=repo, stars=int(item.get("stars") or 0),
                language=item.get("language"), license=item.get("license_spdx"),
                description=str(item.get("description") or ""), url=str(item.get("url") or ""),
                pushed_at=str(item.get("pushed_at") or ""), topics=list(item.get("topics") or []),
            )
        current.found_by.append(style)


def rank(candidates: dict, limit: int = 12) -> list[Candidate]:
    """Most corroborated first, then most popular. Stars alone would bury a
    small project that every single query style agreed on."""
    return sorted(candidates.values(),
                  key=lambda c: (-len(set(c.found_by)), -c.stars, c.repo))[:limit]


# gist.github.com/<user>/<hash> looks exactly like a repo path but is not one:
# a live run turned a gist id into a 404 lookup.
REPO_URL_RE = re.compile(r"(?<!gist\.)github\.com/([A-Za-z0-9][\w.-]*/[\w.-]+)", re.IGNORECASE)
SKIP_OWNERS = {"topics", "search", "features", "about", "pricing", "orgs", "sponsors", "collections"}


def repos_in_web_results(results, limit=5):
    """GitHub links the web search turned up.

    In the trial the web search found leaders GitHub's own search had missed
    (and vice versa), but it answers with pages, not repositories, so the repo
    names have to be lifted out of the links it returns.
    """
    found = []
    for item in results or []:
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
    return body.get("data", body)


def items_of(outcome):
    return payload_of(outcome).get("items") or []


class ResearchRunner:
    """One prior-art run per note, in the background.

    A run is about six GitHub searches (the server throttles them to one per
    six seconds), one web search and two model calls, so roughly a minute. That
    is far past what a chat turn can hold: it reports progress over the broker
    and keeps its result on the note.
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

    async def start(self, rel, content):
        if self.busy(rel):
            return {"status": "busy"}
        if self.is_private(rel):
            raise ApiError(403, "Bu not gizli: fikri aratmak onu disari gonderir. "
                                "Arastirmak icin notun basindaki 'gizli' satirini kaldir.")
        if self.tool_hub is None or not self.tool_hub.available:
            raise ApiError(503, "Arastirma sunuculari calismiyor.")
        started = self._save(rel, status="running", started=now_iso(), candidates=[],
                             verdict=None, error=None)
        task = asyncio.create_task(self._run(rel, content))
        self.running[rel] = task
        task.add_done_callback(lambda _t: self.running.pop(rel, None))
        return {"status": "started", **started}

    async def _run(self, rel, content):
        try:
            terms = await self._terms(rel, content)
            candidates = await self._search(rel, terms)
            await self._web(rel, terms, candidates)
            await self._judge(rel, content, rank(candidates), terms)
        except ApiError as exc:
            self._save(rel, status="error", error=exc.message)
            self._progress(rel, "hata", exc.message)
        except asyncio.CancelledError:
            self._save(rel, status="cancelled")
            raise
        except Exception as exc:
            self._save(rel, status="error", error=type(exc).__name__ + ": " + str(exc))
            self._progress(rel, "hata", str(exc)[:200])

    async def _terms(self, rel, content):
        self._progress(rel, "terimler", "Fikirden arama terimleri cikariliyor")
        provider = self.provider_for("analysis", rel)
        terms = await asyncio.to_thread(llm_client.extract_search_terms, content, provider,
                                        self.record_usage)
        if not terms.get("keywords") and not terms.get("topics"):
            raise ApiError(422, "Fikirden arama terimi cikarilamadi; notu biraz daha yaz.")
        self._save(rel, terms=terms)
        self._progress(rel, "terimler", "Terimler hazir.", terms=terms)
        return terms

    async def _search(self, rel, terms):
        queries = build_queries(terms.get("keywords"), terms.get("topics"))[:MAX_GITHUB_QUERIES]
        candidates = {}
        for index, entry in enumerate(queries, start=1):
            label = "GitHub " + str(index) + "/" + str(len(queries)) + ": " + entry["query"]
            self._progress(rel, "arama", label, done=index - 1, total=len(queries))
            try:
                outcome = await self.tool_hub.call(
                    "git_search", {"query": entry["query"], "per_page": PER_PAGE, "sort": "stars"})
            except ApiError:
                continue
            if not outcome.get("ok"):
                continue
            merge(candidates, entry["style"], items_of(outcome))
            self._save(rel, candidates=[c.public() for c in rank(candidates)])
        self._progress(rel, "arama", str(len(candidates)) + " aday bulundu.",
                       done=len(queries), total=len(queries))
        return candidates

    async def _web(self, rel, terms, candidates):
        """A rescue net, never the backbone: it opens a browser window and
        costs about twelve seconds, so one search and a handful of lookups."""
        query = web_query(terms.get("summary") or " ".join(terms.get("keywords") or []))
        if not query or "web_search" not in getattr(self.tool_hub, "registry", {}):
            return
        self._progress(rel, "web", "Webde capraz kontrol, tarayici acilir")
        try:
            outcome = await self.tool_hub.call("web_search", {"query": query})
        except ApiError:
            return
        if not outcome.get("ok"):
            return
        repos = repos_in_web_results(payload_of(outcome).get("results") or [])
        for repo in repos:
            if repo in candidates:
                candidates[repo].found_by.append("web")
                continue
            try:
                detail = await self.tool_hub.call("git_repo", {"repo": repo})
            except ApiError:
                continue
            if detail.get("ok"):
                merge(candidates, "web", [payload_of(detail)])
        self._progress(rel, "web", "Web " + str(len(repos)) + " depo onerdi.")

    async def _judge(self, rel, content, ranked, terms):
        self._progress(rel, "degerlendirme", "Bulunanlar fikirle karsilastiriliyor")
        listed = [c.public() for c in ranked]
        provider = self.provider_for("chat", rel)
        result = await asyncio.to_thread(llm_client.judge_prior_art, content, listed, provider,
                                         self.record_usage)
        saved = self._save(rel, status="done", finished=now_iso(), candidates=listed,
                           verdict=result, terms=terms)
        self._progress(rel, "bitti", result.get("verdict", ""), result=saved)
