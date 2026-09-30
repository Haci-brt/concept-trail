"""GitHub research, inside the app.

It used to be the git_search MCP server of the separate llm-stack project;
this is the part of it Concept Trail uses, with its safety rules kept and its
limits widened:

- only GET requests to api.github.com, never a redirect, only public repos,
  responses capped at 3 MiB, the token never in an error message;
- GitHub's own rate limit respected (a 403/429 with a reset blocks further
  calls until then, and says until when);
- searches spaced 2.1 s apart with a token — GitHub allows 30 a minute — and
  6.1 s without one (10 a minute); llm-stack spaced every search 6.1 s;
- a disk cache (an hour for searches and repositories), so a research run
  again, or a query two stages ask, costs nothing;
- beyond what llm-stack allowed: topic search (/search/topics — GitHub's own
  topic names; the model's "recipe-management" is not what Mealie carries),
  a repository's README straight from the API, the homepage / forks / open
  issues of a repository, and issues sorted by how much they were discussed.
"""
import base64
import hashlib
import json
import re
import threading
import time
from pathlib import Path

import httpx

from server.errors import ApiError
from server.settings import REPO_URL, VERSION

API = "https://api.github.com"
MAX_BYTES = 3 * 1024 * 1024
SEARCH_SPACING_TOKEN = 2.1        # GitHub: 30 searches a minute with a token
SEARCH_SPACING_ANON = 6.1         # 10 a minute without
CACHE_TTL = {"search": 3600, "topics": 86400, "repo": 3600, "issues": 1800, "readme": 3600}
MAX_README_CHARS = 60_000
VALID_REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9_.-]{1,100}$")
PATHS = (re.compile(r"^/search/(repositories|topics)$"),
         re.compile(r"^/repos/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9_.-]{1,100}(/issues|/readme)?$"))


class GitHubLimited(ApiError):
    def __init__(self, until: float):
        self.until = until
        wait = max(1, round(until - time.time()))
        super().__init__(429, f"GitHub hız sınırı: {wait} sn sonra yeniden denenebilir.")


class GitHubResearch:
    """What the research asks GitHub, as plain synchronous calls (the tool
    hub runs them on worker threads)."""

    def __init__(self, token=lambda: "", cache_dir: Path | None = None, transport=None,
                 clock=time.monotonic, sleep=time.sleep):
        self.token = token
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.transport = transport
        self.clock, self.sleep = clock, sleep
        self.search_lock = threading.Lock()
        self.slots = threading.Semaphore(4)
        self.next_search = 0.0
        self.blocked_until = 0.0

    # ---- the one way out ----
    def _get(self, kind: str, path: str, params: dict | None = None, accept: str | None = None):
        if not any(pattern.fullmatch(path) for pattern in PATHS) or ".." in path:
            raise ApiError(400, "Desteklenmeyen GitHub yolu.")
        key = hashlib.sha256(json.dumps([path, params or {}, accept], sort_keys=True).encode()).hexdigest()
        cached = self._cached(kind, key)
        if cached is not None:
            return cached
        if time.time() < self.blocked_until:
            raise GitHubLimited(self.blocked_until)
        token = (self.token() or "").strip()
        if path.startswith("/search/"):
            with self.search_lock:
                wait = self.next_search - self.clock()
                if wait > 0:
                    self.sleep(wait)
                self.next_search = self.clock() + (SEARCH_SPACING_TOKEN if token else SEARCH_SPACING_ANON)
        headers = {"Accept": accept or "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": f"ConceptTrail/{VERSION} (+{REPO_URL})"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        with self.slots, httpx.Client(base_url=API, headers=headers, timeout=20, follow_redirects=False,
                                      trust_env=False, transport=self.transport) as http:
            try:
                with http.stream("GET", path, params=params) as reply:
                    self._check(reply, token)
                    raw = bytearray()
                    for chunk in reply.iter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_BYTES:
                            raise ApiError(502, "GitHub yanıtı 3 MB'ı aştı; aramayı daralt.")
            except httpx.HTTPError as exc:
                message = str(exc).replace(token, "[gizli]") if token else str(exc)
                raise ApiError(502, f"GitHub'a ulaşılamadı: {type(exc).__name__}: {message[:200]}")
        try:
            body = json.loads(bytes(raw))
        except ValueError:
            raise ApiError(502, "GitHub geçersiz JSON döndürdü.")
        self._store(kind, key, body)
        return body

    def _check(self, reply, token: str):
        if reply.status_code in (403, 429) and (reply.status_code == 429 or
                                                reply.headers.get("x-ratelimit-remaining") == "0" or
                                                reply.headers.get("retry-after")):
            try:
                until = max(float(reply.headers.get("x-ratelimit-reset") or 0),
                            time.time() + float(reply.headers.get("retry-after") or 60))
            except ValueError:
                until = time.time() + 60
            self.blocked_until = until
            raise GitHubLimited(until)
        if reply.status_code == 422:
            raise ApiError(422, "GitHub bu aramayı kabul etmedi (ör. etiketler arasında OR desteklenmiyor).")
        if reply.status_code == 404:
            raise ApiError(404, "GitHub'da bulunamadı.")
        if reply.status_code != 200:
            raise ApiError(502, f"GitHub HTTP {reply.status_code}.")

    def _cached(self, kind, key):
        if self.cache_dir is None:
            return None
        path = self.cache_dir / f"{kind}-{key}.json"
        try:
            if time.time() - path.stat().st_mtime < CACHE_TTL.get(kind, 3600):
                return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        return None

    def _store(self, kind, key, body):
        if self.cache_dir is None:
            return
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_dir / f"{kind}-{key}.tmp"
            tmp.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.cache_dir / f"{kind}-{key}.json")
        except OSError:
            pass

    # ---- what the research asks ----
    @staticmethod
    def metadata(body: dict) -> dict:
        if body.get("private") is not False or body.get("visibility", "public") != "public":
            raise ApiError(403, "Yalnız herkese açık depolar araştırılır.")
        return {"repo": body["full_name"], "url": body["html_url"], "description": body.get("description"),
                "stars": body.get("stargazers_count"), "forks": body.get("forks_count"),
                "open_issues": body.get("open_issues_count"), "pushed_at": body.get("pushed_at"),
                "archived": body.get("archived"), "fork": body.get("fork"), "topics": body.get("topics") or [],
                "language": body.get("language"), "homepage": body.get("homepage") or None,
                "license_spdx": (body.get("license") or {}).get("spdx_id") or "UNKNOWN"}

    def search(self, query: str, per_page: int = 30, page: int = 1, sort: str = "stars") -> dict:
        query = " ".join(str(query).split())
        if not query:
            raise ApiError(400, "Arama boş olamaz.")
        params = {"q": f"{query} is:public", "per_page": per_page, "page": page, "order": "desc"}
        if sort != "best-match":
            params["sort"] = sort
        body = self._get("search", "/search/repositories", params)
        items = []
        for item in body.get("items") or []:
            try:
                items.append(self.metadata(item))
            except (ApiError, KeyError):
                continue
        total = int(body.get("total_count") or 0)
        return {"query": query, "page": page, "total_count": total,
                "incomplete_results": bool(body.get("incomplete_results")), "items": items,
                "has_next": page * per_page < min(1000, total)}

    def repo(self, repo: str) -> dict:
        self._valid(repo)
        return self.metadata(self._get("repo", f"/repos/{repo}"))

    def issues(self, repo: str, per_page: int = 10, sort: str = "updated", state: str = "all") -> dict:
        """The repository's issues, pull requests left out. sort=comments puts
        the most discussed first: what its users run into most."""
        self._valid(repo)
        body = self._get("issues", f"/repos/{repo}/issues",
                         {"state": state, "sort": sort, "direction": "desc", "per_page": per_page})
        rows = [{"number": item.get("number"), "title": item.get("title") or "", "url": item.get("html_url"),
                 "state": item.get("state"), "comments": item.get("comments"),
                 "reactions": (item.get("reactions") or {}).get("total_count"),
                 "body": (item.get("body") or "")[:2000]}
                for item in body if isinstance(item, dict) and "pull_request" not in item]
        return {"repo": repo, "items": rows}

    def readme(self, repo: str) -> dict:
        self._valid(repo)
        body = self._get("readme", f"/repos/{repo}/readme")
        if body.get("encoding") != "base64":
            raise ApiError(502, "README okunamadı.")
        text = base64.b64decode(body.get("content") or "").decode("utf-8", errors="replace")
        return {"repo": repo, "url": body.get("html_url"), "text": text[:MAX_README_CHARS],
                "truncated": len(text) > MAX_README_CHARS}

    def topics(self, query: str, per_page: int = 20) -> dict:
        """GitHub's own topic names for some words: which of "recipe-manager",
        "recipe-management", "recipes" projects actually use."""
        query = " ".join(str(query).split())
        if not query:
            raise ApiError(400, "Arama boş olamaz.")
        body = self._get("topics", "/search/topics", {"q": query, "per_page": per_page})
        return {"query": query, "items": [
            {"name": item.get("name"), "display_name": item.get("display_name"),
             "short_description": item.get("short_description"), "featured": item.get("featured"),
             "curated": item.get("curated")} for item in body.get("items") or [] if item.get("name")]}

    @staticmethod
    def _valid(repo: str):
        if not VALID_REPO.fullmatch(str(repo or "")) or any(p in {".", ".."} for p in str(repo).split("/")):
            raise ApiError(400, "Geçersiz depo adı.")
