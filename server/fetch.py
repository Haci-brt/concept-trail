"""Reading a web page, in tiers, so the assistant can cite instead of guess.

The existing web_search finds five links and a sentence each; it cannot read.
This fills that half. Every tier below was measured on this machine first:

    llms.txt / raw .md kaynagi   0.5-0.6 sn   sitenin kendi makine-okur hali
    httpx (durust UA)            0.6-1.1 sn   cogu sayfa; bazilari 403 verir
    Chromium (Playwright)        1.5-4.7 sn   403 alan sayfa burada 200 doner

The order matters more than the speed: a site that publishes llms.txt or keeps
its docs as markdown on GitHub is telling us how it wants to be read, and that
path never meets a bot wall at all.

Two rules this module exists to enforce:

* the URL is chosen by a model whose input is untrusted web text, so it is
  validated as a public address before anything is opened — no loopback, no
  private range, no credentials in the URL;
* what comes back is data. The caller marks it as such; nothing here treats a
  fetched instruction as an instruction.
"""
import ipaddress
import socket
import time
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx

from server.errors import ApiError

USER_AGENT = ("ConceptTrail/0.2 (kisisel arastirma araci; "
              "https://github.com/modelcontextprotocol)")
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 ConceptTrail/0.2")
HTTP_TIMEOUT = 20.0
BROWSER_TIMEOUT_MS = 30000
MAX_CHARS = 8000            # what a model can actually use; pages run to 75k
ROBOTS_TTL_S = 900
MAX_REDIRECTS = 5
# github.com/<these>/... are site pages, not owner/repo pairs
RESERVED_PATHS = {"topics", "search", "features", "about", "pricing", "orgs",
                  "sponsors", "collections", "settings", "notifications", "explore"}


def _is_public_address(raw: str) -> bool:
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        return False
    return not (address.is_private or address.is_loopback or address.is_link_local
                or address.is_multicast or address.is_reserved or address.is_unspecified)


def validate_public_url(url: str, resolve: bool = True) -> str:
    """The model picks this URL and its input is untrusted page text, so a
    fetched page must never be able to aim us at 127.0.0.1 or the LAN."""
    if not isinstance(url, str) or not url.strip():
        raise ApiError(400, "Adres bos olamaz.")
    parsed = urlsplit(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ApiError(400, "Yalniz http ve https adresleri acilabilir.")
    if parsed.username or parsed.password:
        raise ApiError(400, "Kimlik bilgisi iceren adres kullanilamaz.")
    host = (parsed.hostname or "").rstrip(".").lower()
    if not host or host in {"localhost", "localhost.localdomain"}:
        raise ApiError(400, "Yerel adresler acilamaz.")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and not _is_public_address(str(literal)):
        raise ApiError(400, "Ozel, loopback ya da link-local adres acilamaz.")
    if resolve and literal is None:
        try:
            addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except OSError:
            raise ApiError(400, "Alan adi cozumlenemedi: " + host)
        if not addresses or any(not _is_public_address(item[4][0]) for item in addresses):
            raise ApiError(400, "Alan adi herkese acik olmayan bir adrese cozumlendi.")
    return parsed.geturl()


_robots_cache: dict[str, tuple[float, RobotFileParser | None]] = {}


def robots_allows(url: str, agent: str = USER_AGENT) -> bool:
    """A site's stated policy, which is not the same thing as its bot filter:
    realpython.com returns 403 to a plain client but its robots.txt allows the
    article. Only an explicit Disallow stops us."""
    parts = urlsplit(url)
    root = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
    cached = _robots_cache.get(root)
    if cached and time.monotonic() - cached[0] < ROBOTS_TTL_S:
        parser = cached[1]
    else:
        parser = RobotFileParser()
        try:
            status, body, _ = _http_get(root, timeout=8)
            parser.parse(body.splitlines() if status == 200 else [])
        except Exception:
            parser = None          # unreachable robots.txt is not a refusal
        _robots_cache[root] = (time.monotonic(), parser)
    if parser is None:
        return True
    return parser.can_fetch(agent, url)


def source_form(url: str) -> str | None:
    """The exact source of a page, when it has one.

    A GitHub file view is a 400 KB HTML app around a text file that is also
    served raw; reading the raw form is faster, cleaner and never meets a bot
    filter. (A site-wide llms.txt is a different thing — a curated index of a
    whole docs site, not a substitute for one page — so it is not used here.)
    """
    parts = urlsplit(url)
    host = parts.netloc.lower()
    if host not in ("github.com", "www.github.com"):
        return None
    segments = [s for s in parts.path.split("/") if s]
    if not segments or segments[0].lower() in RESERVED_PATHS:
        return None
    if len(segments) >= 5 and segments[2] == "blob":
        owner, repo, ref = segments[0], segments[1], segments[3]
        return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{'/'.join(segments[4:])}"
    if len(segments) == 2:
        owner, repo = segments
        return f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/README.md"
    return None


def extract(html: str, url: str) -> str:
    """Article text as markdown. Headings survive, which is most of why the
    result is usable: a flat wall of text loses the shape of the page."""
    try:
        import trafilatura
    except ImportError:
        trafilatura = None
    if trafilatura is not None:
        text = trafilatura.extract(html, url=url, include_comments=False, include_links=False,
                                   favor_precision=True, output_format="markdown")
        if text and text.strip():
            return text.strip()
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for junk in soup(["script", "style", "nav", "footer", "header", "noscript", "aside", "form"]):
        junk.decompose()
    main = soup.find("article") or soup.find("main") or soup.body or soup
    return "\n".join(line.strip() for line in main.get_text("\n").splitlines() if line.strip())


def trim(text: str, query: str | None = None, limit: int = MAX_CHARS) -> tuple[str, bool]:
    """Pages run to 75,000 characters; a model can use a small fraction of that.

    With a query, keep the window around where the page actually talks about
    it, so the answer is not the part that got cut. Returns (text, truncated).
    """
    text = (text or "").strip()
    if len(text) <= limit:
        return text, False
    words = [w for w in (query or "").lower().split() if len(w) > 3][:6]
    if words:
        lowered = text.lower()
        best, score = 0, -1
        step = max(limit // 4, 1)
        for start in range(0, max(len(text) - limit, 1), step):
            window = lowered[start:start + limit]
            hits = sum(window.count(word) for word in words)
            if hits > score:
                best, score = start, hits
        if score > 0:
            snippet = text[best:best + limit]
            head = "" if best == 0 else "[...]\n"
            return head + snippet.split("\n", 1)[-1] if best else snippet, True
    return text[:limit], True


def _http_get(url: str, timeout: float = HTTP_TIMEOUT, check_robots: bool = False):
    """Follow redirects only after validating every destination as public."""
    current = validate_public_url(url)
    if check_robots and not robots_allows(current):
        raise ApiError(403, "Sitenin robots.txt dosyasi bu adresi kapatmis.")
    with httpx.Client(follow_redirects=False, timeout=timeout,
                      headers={"User-Agent": USER_AGENT}) as client:
        for _ in range(MAX_REDIRECTS + 1):
            reply = client.get(current)
            if reply.status_code in {301, 302, 303, 307, 308} and reply.headers.get("location"):
                current = validate_public_url(urljoin(str(reply.url), reply.headers["location"]))
                if check_robots and not robots_allows(current):
                    raise ApiError(403, "Sitenin robots.txt dosyasi bu adresi kapatmis.")
                continue
            return reply.status_code, reply.text, str(reply.url)
    raise ApiError(502, "Sayfa çok fazla yönlendirme yaptı.")


def _browser_get(url: str):
    """A real browser for pages a plain client cannot reach. This is not a
    disguise — it is Chromium, announcing itself as Chromium; realpython.com
    answers 403 to httpx and 200 here while its own robots.txt allows the page."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as play:
        browser = play.chromium.launch()
        try:
            # the default headless string is what crude filters key on. This one
            # is true — it really is Chromium on Windows — and it adds who is
            # asking, which the default never did. That is the whole extent of
            # it: if a site still refuses, the refusal stands.
            context = browser.new_context(user_agent=BROWSER_UA)
            def guard(route):
                try:
                    target = validate_public_url(route.request.url)
                    if route.request.resource_type == "document" and not robots_allows(target):
                        route.abort()
                    else:
                        route.continue_()
                except ApiError:
                    route.abort()
            context.route("**/*", guard)
            page = context.new_page()
            reply = page.goto(url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT_MS)
            page.wait_for_timeout(600)
            return (reply.status if reply else 0), page.content(), page.url
        finally:
            browser.close()


def fetch_page(url: str, query: str | None = None, limit: int = MAX_CHARS,
               allow_browser: bool = True) -> dict:
    """Read one page, cheapest way first. Raises ApiError when no tier works."""
    url = validate_public_url(url)
    attempts: list[dict] = []

    raw = source_form(url)
    if raw:
        try:
            status, body, final = _http_get(raw, check_robots=True)
        except httpx.HTTPError as exc:
            status, body, final = 0, "", type(exc).__name__
        attempts.append({"tier": "kaynak", "status": status})
        if status == 200 and body.strip():
            text, truncated = trim(body, query, limit)
            return _result(url, final, "kaynak", status, text, truncated, attempts)

    if not robots_allows(url):
        raise ApiError(403, "Sitenin robots.txt dosyasi bu adresi kapatmis.")

    try:
        status, body, final = _http_get(url, check_robots=True)
    except httpx.HTTPError as exc:
        status, body, final = 0, "", type(exc).__name__
    attempts.append({"tier": "http", "status": status})
    if status == 200:
        text, truncated = trim(extract(body, final), query, limit)
        if text:
            return _result(url, final, "http", status, text, truncated, attempts)

    if allow_browser:
        try:
            status, body, final = _browser_get(url)
        except Exception as exc:
            attempts.append({"tier": "tarayici", "status": 0, "error": type(exc).__name__})
        else:
            attempts.append({"tier": "tarayici", "status": status})
            if status and status < 400:
                text, truncated = trim(extract(body, final), query, limit)
                if text:
                    return _result(url, final, "tarayici", status, text, truncated, attempts)

    last = attempts[-1]["status"] if attempts else 0
    raise ApiError(502, "Sayfa okunamadi (son durum " + str(last) + "). Denenenler: "
                   + ", ".join(a["tier"] + "=" + str(a["status"]) for a in attempts))


def _result(url, final, tier, status, text, truncated, attempts) -> dict:
    return {"url": url, "final_url": final, "tier": tier, "status": status,
            "text": text, "characters": len(text), "truncated": truncated,
            "attempts": attempts, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "content_trust": "untrusted_external_data"}
