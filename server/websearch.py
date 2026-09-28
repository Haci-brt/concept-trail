"""Web search, inside the app — with no browser window on the screen.

It used to be the web_search MCP server of the separate llm-stack project,
which drove a visible Opera: a window opened on the writer's screen for every
search. This is the same search — a real, headed browser, because search
engines answer a real browser, and nothing here disguises it — but its
window is placed off the screen and hidden (Windows ShowWindow SW_HIDE) as
soon as it exists. Only the windows of the browser process this app started
are touched: its id comes from the browser itself over CDP, never from a
name, so the writer's own browser windows are left alone.

Any Chromium-family browser will do: Opera, Edge, Chrome, Brave or Chromium,
the first one installed (Edge comes with every Windows). Elsewhere a window
cannot be hidden like that, so there the browser runs headless. And with no
browser at all — or one that will not start — the search still runs, without
one: DuckDuckGo keeps a page for browsers without JavaScript, and a plain
HTTP request reads it (measured: ten relevant results where Bing, asked the
same way, answered with unrelated pages).

The browser runs one fresh, empty context — no profile, no history, deleted
when the browser closes — with a few tabs opened once at launch and reused;
each search clears the cookies first, so it starts as clean as a new context
did. Measured: a new context opened a new window and every new tab showed
the window again, each visible for a moment before it could be hidden.
Images, media and fonts are not loaded; every request must go to a public
address. The browser starts on the first search and closes after
IDLE_CLOSE_S without one.
"""
import asyncio
import os
import re
import shutil
import sys
import threading
import time
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlsplit

from server.errors import ApiError

SEARCH_PROVIDERS = (
    ("yahoo", "https://search.yahoo.com/search?p={query}"),
    ("brave", "https://search.brave.com/search?q={query}&source=web"),
    ("google", "https://www.google.com/search?q={query}"),
    ("bing", "https://www.bing.com/search?q={query}"),
)
SEARCH_HOSTS = {"search.yahoo.com", "search.brave.com", "www.google.com", "www.bing.com", "duckduckgo.com"}
SELECTORS = {"yahoo": "#web a[href], main a[href]", "brave": "#results a[href], main a[href]",
             "google": "a:has(h3)", "bing": "li.b_algo h2 a"}
MAX_RESULTS = 5
CONCURRENCY = 3
SEARCH_TIMEOUT_S = 70
IDLE_CLOSE_S = 180
LAUNCH_ARGS = [
    "--no-first-run", "--no-default-browser-check", "--disable-session-crashed-bubble", "--disable-sync",
    # off the screen from the first frame, before it can be hidden
    "--window-position=-32000,-32000", "--window-size=1365,900",
    # a hidden window must not be put to sleep: Chromium throttles windows it
    # thinks nobody sees, and the search would wait on its own timers
    "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
    "--disable-background-timer-throttling",
]


# without a browser: DuckDuckGo's page for browsers without JavaScript, then its lighter one
HTTP_ENGINES = (("duckduckgo", "https://html.duckduckgo.com/html/?q={query}"),
                ("duckduckgo-lite", "https://lite.duckduckgo.com/lite/?q={query}"))
HTTP_GAP_S = 1.5             # between two searches without a browser, to stay a polite visitor
NO_BROWSER_RETRY_S = 600     # a browser that is missing or would not start is tried again after this
HTTP_TIMEOUT_S = 15


def browser_candidates(platform: str | None = None) -> list[Path]:
    """Where Opera, Edge, Chrome, Brave and Chromium live, in that order."""
    platform = platform or sys.platform
    if platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        pf, pf86 = Path(os.environ.get("PROGRAMFILES", "")), Path(os.environ.get("PROGRAMFILES(X86)", ""))
        return [local / "Programs" / "Opera" / "opera.exe", local / "Programs" / "Opera GX" / "opera.exe",
                pf / "Opera" / "opera.exe", pf86 / "Opera" / "opera.exe",
                pf86 / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                pf / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                pf / "Google" / "Chrome" / "Application" / "chrome.exe",
                pf86 / "Google" / "Chrome" / "Application" / "chrome.exe",
                local / "Google" / "Chrome" / "Application" / "chrome.exe",
                pf / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
                local / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
                local / "Chromium" / "Application" / "chrome.exe"]
    if platform == "darwin":
        apps = ("Opera", "Microsoft Edge", "Google Chrome", "Brave Browser", "Chromium")
        return [root / f"{app}.app" / "Contents" / "MacOS" / app
                for app in apps for root in (Path("/Applications"), Path.home() / "Applications")]
    found = []
    for name in ("opera", "microsoft-edge", "microsoft-edge-stable", "google-chrome", "google-chrome-stable",
                 "brave-browser", "chromium", "chromium-browser"):
        path = shutil.which(name)
        if path:
            found.append(Path(path))
    return found


def find_browser(configured: str | None = None) -> Path | None:
    """The browser the search drives: one named in the settings or by
    CT_BROWSER (OPERA_EXECUTABLE, its old name, still works), else the first
    one installed. None when there is none — the search then goes without."""
    named = [configured, os.environ.get("CT_BROWSER", ""), os.environ.get("OPERA_EXECUTABLE", "")]
    for candidate in [Path(n.strip()).expanduser() for n in named if n and n.strip()] + browser_candidates():
        if candidate.is_file():
            return candidate.resolve()
    return None


def browser_name(path: Path | None) -> str | None:
    if path is None:
        return None
    text = str(path).lower()
    for key, name in (("opera", "Opera"), ("edge", "Edge"), ("brave", "Brave"), ("chromium", "Chromium"),
                      ("chrome", "Chrome")):
        if key in text:
            return name
    return path.stem


# ---------------------------------------------------------------- the window
class _Win32:
    """The four calls hide_windows needs, so a test can stand in for them."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self._ctypes, self._wintypes = ctypes, wintypes
        self.user32 = ctypes.windll.user32

    def windows(self):
        found = []
        proc = self._ctypes.WINFUNCTYPE(self._wintypes.BOOL, self._wintypes.HWND, self._wintypes.LPARAM)
        self.user32.EnumWindows(proc(lambda hwnd, _: found.append(hwnd) or True), 0)
        return found

    def pid_of(self, hwnd) -> int:
        owner = self._wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, self._ctypes.byref(owner))
        return owner.value

    def visible(self, hwnd) -> bool:
        return bool(self.user32.IsWindowVisible(hwnd))

    def hide(self, hwnd) -> None:
        self.user32.ShowWindow(hwnd, 0)          # SW_HIDE: gone from the screen and the taskbar


    def children(self) -> dict[int, tuple[int, str]]:
        """pid -> (parent pid, executable name) for every running process."""
        ctypes, wintypes = self._ctypes, self._wintypes

        class Entry(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                        ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]
        kernel32 = ctypes.windll.kernel32
        snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)          # TH32CS_SNAPPROCESS
        table = {}
        try:
            entry = Entry()
            entry.dwSize = ctypes.sizeof(Entry)
            ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while ok:
                table[entry.th32ProcessID] = (entry.th32ParentProcessID, entry.szExeFile.lower())
                ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)
        return table


def our_browsers(root: int, table: dict[int, tuple[int, str]], exe: str = "opera.exe") -> set[int]:
    """The browser processes (opera.exe, msedge.exe, …) that descend from this
    app's own process (by way of Playwright's driver) — never the writer's own
    browser of the same name, which does not."""
    ours, frontier = set(), {root}
    while frontier:
        frontier = {pid for pid, (parent, _) in table.items() if parent in frontier and pid not in ours}
        ours |= frontier
    return {pid for pid in ours if table[pid][1] == exe.lower()}


def hide_windows(pids, api=None) -> int:
    """Hide every visible top-level window of these processes; return how many."""
    pids = {pids} if isinstance(pids, int) else set(pids or ())
    if not pids or (api is None and os.name != "nt"):
        return 0
    api = api or _Win32()
    hidden = 0
    for hwnd in api.windows():
        if api.pid_of(hwnd) in pids and api.visible(hwnd):
            api.hide(hwnd)
            hidden += 1
    return hidden


class WindowHider:
    """While our browser lives, hides each of its windows the moment Windows
    shows it. It listens for the system's "window shown" event instead of
    looking: looking every 15 ms took 70 ms a turn (the process list is long)
    and a launching Opera's window stayed up for half a second (measured).
    Whose window it is — one of our browser's processes or not — is worked
    out once per process and remembered."""

    def __init__(self, api=None, root: int | None = None, exe: str = "opera.exe"):
        self.api = api
        self.root = root or os.getpid()
        self.exe = exe
        self.hidden = 0
        self.thread = None
        self._thread_id = None
        self._known: dict[int, bool] = {}
        self._ready = threading.Event()

    def ours(self, pid: int) -> bool:
        # every window shown on the system comes through here: whether a
        # process is ours is worked out once and remembered, either way
        if pid not in self._known:
            api = self.api or _Win32()
            mine = our_browsers(self.root, api.children(), self.exe)
            for child in mine:
                self._known[child] = True
            self._known.setdefault(pid, pid in mine)
        return self._known[pid]

    def start(self, exe: str | None = None):
        if exe and exe.lower() != self.exe.lower():
            self.exe = exe
            self._known.clear()
        if os.name != "nt" or self.api is not None:
            return
        if self.thread is None or not self.thread.is_alive():
            self._known.clear()
            self._ready.clear()
            self.thread = threading.Thread(target=self._run, name="gizli-tarayici-pencere", daemon=True)
            self.thread.start()
            self._ready.wait(2)
        # our browser's processes start seconds before its first window: know
        # them by then, so the window is hidden without first reading the
        # whole process list (70 ms, during which it stayed on — measured)
        threading.Thread(target=self._learn, args=(30.0,), name="gizli-tarayici-surec", daemon=True).start()

    def _learn(self, seconds: float):
        api = self.api or _Win32()
        until = time.monotonic() + seconds
        while time.monotonic() < until and self.thread is not None and self.thread.is_alive():
            for pid in our_browsers(self.root, api.children(), self.exe):
                self._known[pid] = True
            time.sleep(0.1)

    def stop(self):
        if self.thread is not None and self.thread.is_alive() and self._thread_id:
            import ctypes
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)     # WM_QUIT
            self.thread.join(2)

    def _run(self):
        import ctypes
        from ctypes import wintypes
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        api = _Win32()
        self._thread_id = kernel32.GetCurrentThreadId()
        EVENT_OBJECT_SHOW, OBJID_WINDOW, GA_ROOT = 0x8002, 0, 2
        callback_type = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
                                           wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD)

        def on_show(hook, event, hwnd, id_object, id_child, thread, when):
            try:
                if id_object != OBJID_WINDOW or not hwnd or user32.GetAncestor(hwnd, GA_ROOT) != hwnd:
                    return
                if self.ours(api.pid_of(hwnd)):
                    user32.ShowWindow(hwnd, 0)                  # SW_HIDE
                    self.hidden += 1
            except Exception:
                pass

        callback = callback_type(on_show)
        hook = user32.SetWinEventHook(EVENT_OBJECT_SHOW, EVENT_OBJECT_SHOW, 0, callback, 0, 0,
                                      0x0000 | 0x0002)                  # out of context, skip own process
        # a window shown before the hook was in place
        self.hidden += hide_windows(our_browsers(self.root, api.children(), self.exe), api)
        self._ready.set()
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            user32.UnhookWinEvent(hook)


# ---------------------------------------------------------------- the results
def pick_results(raw: list[dict], limit: int = MAX_RESULTS) -> list[dict]:
    """Anchors read off a result page -> at most five public results: no link
    back into the search engine, no duplicate, no title too short to mean
    anything. The addresses are checked here; DNS is checked when a page is
    actually read."""
    from server.fetch import validate_public_url
    rows, seen = [], set()
    for item in raw or []:
        href = str(item.get("href") or "").strip()
        title = " ".join(str(item.get("title") or "").split())
        try:
            target = validate_public_url(href, resolve=False)
        except ApiError:
            continue
        host = (urlsplit(target).hostname or "").lower()
        if any(host == h or host.endswith("." + h) for h in SEARCH_HOSTS) or len(title) < 4:
            continue
        canonical = target.split("#", 1)[0]
        if canonical in seen:
            continue
        seen.add(canonical)
        rows.append({"rank": len(rows) + 1, "title": title[:500], "url": canonical,
                     "snippet": " ".join(str(item.get("snippet") or "").split())[:800]})
        if len(rows) == limit:
            break
    return rows


# ---------------------------------------------------------------- without a browser
_ANCHOR = re.compile(r"""<a\b[^>]*href=["']([^"']*uddg=[^"']*)["'][^>]*>(.*?)</a>""", re.S | re.I)
_SNIPPET = re.compile(r"""class=["']result[_-]+snippet["'][^>]*>(.*?)</(?:a|td)>""", re.S | re.I)
_http_lock = threading.Lock()
_http_last = [0.0]


def _text(fragment: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def parse_duckduckgo(page: str) -> list[dict]:
    """The results on DuckDuckGo's pages for browsers without JavaScript. Every
    link of a result — its title, its address, its snippet — goes through
    duckduckgo.com/l/?uddg=<the real address>; ads go through y.js and are
    not links of this kind. The first link of a result gives the title, the
    snippet is the one marked so, or else the text up to the next result."""
    found, order = {}, []
    matches = list(_ANCHOR.finditer(page))
    for m in matches:
        href = unescape(m.group(1))
        query = urlsplit(href if "://" in href else "https:" + href).query
        target = (parse_qs(query).get("uddg") or [""])[0]
        if not target:
            continue
        if target not in found:
            found[target] = {"href": target, "title": _text(m.group(2)), "start": m.end()}
            order.append(target)
    rows = []
    for i, target in enumerate(order):
        item = found[target]
        end = found[order[i + 1]]["start"] if i + 1 < len(order) else min(len(page), item["start"] + 4000)
        segment = page[item["start"]:end]
        marked = _SNIPPET.search(segment)
        rows.append({"href": target, "title": item["title"],
                     "snippet": _text(marked.group(1) if marked else segment)[:800]})
    return rows


def http_search(query: str, get=None) -> dict:
    """A search with no browser at all: one plain request to DuckDuckGo."""
    from server.fetch import USER_AGENT
    started = time.monotonic()
    if get is None:
        import httpx

        def get(url):
            reply = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT_S,
                              follow_redirects=True)
            return reply.status_code, reply.text
    errors = []
    for provider, template in HTTP_ENGINES:
        url = template.format(query=quote_plus(query))
        with _http_lock:
            wait = HTTP_GAP_S - (time.monotonic() - _http_last[0])
            if wait > 0:
                time.sleep(wait)
            _http_last[0] = time.monotonic()
        try:
            status, page = get(url)
        except Exception as exc:
            errors.append(f"{provider}: {type(exc).__name__}: {str(exc)[:120]}")
            continue
        if status >= 400:
            errors.append(f"{provider}: HTTP {status}")
            continue
        rows = pick_results(parse_duckduckgo(page))
        if rows:
            return {"query": query, "provider": provider, "search_url": url,
                    "duration_ms": round((time.monotonic() - started) * 1000),
                    "browser": None, "results": rows}
        errors.append(f"{provider}: sonuç yok")
    raise ApiError(502, "Arama sayfalarından sonuç okunamadı. " + " | ".join(errors))


# ---------------------------------------------------------------- the browser
class NoBrowser(Exception):
    """No Chromium-family browser here, or none that would start."""


class HiddenBrowserSearch:
    """One browser for the whole app, on its own thread and event loop;
    search() is a plain blocking call for the tool hub's worker threads.
    Without a browser it searches without one."""

    def __init__(self, executable: str | None = None):
        self.executable = executable
        self._name = None
        self._skip_browser_until = 0.0
        self._lock = threading.Lock()
        self._loop = None
        self._browser = None
        self._playwright = None
        self._pid = None
        self._slots = None
        self._start_lock = None
        self._context = None
        self._tabs = None
        self._last_used = 0.0
        self.hider = WindowHider()

    # ---- the thread ----
    def _ensure_loop(self):
        with self._lock:
            if self._loop is None:
                loop = asyncio.new_event_loop()
                threading.Thread(target=loop.run_forever, name="gizli-opera", daemon=True).start()
                self._loop = loop
                asyncio.run_coroutine_threadsafe(self._idle_watch(), loop)
            return self._loop

    def search(self, query: str) -> dict:
        query = " ".join(str(query or "").split())
        if not 1 <= len(query) <= 500:
            raise ApiError(400, "Arama sorgusu 1 ile 500 karakter arasında olmalı.")
        future = asyncio.run_coroutine_threadsafe(self._search(query), self._ensure_loop())
        try:
            return future.result(timeout=SEARCH_TIMEOUT_S)
        except TimeoutError:
            future.cancel()
            raise ApiError(504, f"Web araması {SEARCH_TIMEOUT_S} sn içinde bitmedi.")

    def close(self) -> None:
        if self._loop is not None:
            try:
                asyncio.run_coroutine_threadsafe(self._close(), self._loop).result(timeout=15)
            except Exception:
                pass

    def status(self) -> dict:
        return {"running": self._browser is not None, "pid": self._pid, "hidden": True,
                "browser": self._name or browser_name(find_browser(self.executable))}

    # ---- on the loop ----
    async def _idle_watch(self):
        while True:
            await asyncio.sleep(30)
            if self._browser is not None and time.monotonic() - self._last_used > IDLE_CLOSE_S:
                await self._close()

    async def _ensure_browser(self):
        if self._start_lock is None:
            self._start_lock, self._slots = asyncio.Lock(), asyncio.Semaphore(CONCURRENCY)
        async with self._start_lock:
            if self._browser is not None and self._browser.is_connected():
                return self._browser
            await self._close()
            try:
                from playwright.async_api import async_playwright
            except ImportError:
                raise NoBrowser("Playwright kurulu değil")
            executable = find_browser(self.executable)
            if executable is None:
                raise NoBrowser("tarayıcı yok")
            # Windows can hide a real window; elsewhere it would be on the
            # screen, so there the browser has none
            headless = os.name != "nt"
            if not headless:
                self.hider.start(executable.name)    # before the first window exists
            playwright = await async_playwright().start()
            try:
                browser = await playwright.chromium.launch(executable_path=str(executable), headless=headless,
                                                           args=LAUNCH_ARGS)
            except Exception as exc:
                await playwright.stop()
                self.hider.stop()
                raise NoBrowser(f"{browser_name(executable)} başlatılamadı: {type(exc).__name__}: {str(exc)[:160]}")
            self._playwright, self._browser = playwright, browser
            self._name = browser_name(executable)
            self._pid = await self._browser_pid(browser)
            self._context = await browser.new_context(viewport={"width": 1365, "height": 900},
                                                      accept_downloads=False, service_workers="block",
                                                      user_agent=self._true_agent(browser) if headless else None)
            await self._context.route("**/*", self._guard)
            self._tabs = asyncio.Queue()
            for _ in range(CONCURRENCY):
                self._tabs.put_nowait(await self._context.new_page())
            return browser

    @staticmethod
    async def _guard(route, request):
        from server.fetch import validate_public_url
        if request.resource_type in {"image", "media", "font"}:
            await route.abort("blockedbyclient")
            return
        if urlsplit(request.url).scheme in {"data", "blob", "about"}:
            await route.continue_()
            return
        try:
            await asyncio.to_thread(validate_public_url, request.url)
        except ApiError:
            await route.abort("blockedbyclient")
            return
        await route.continue_()

    @staticmethod
    def _true_agent(browser) -> str:
        """A headless browser calls itself HeadlessChrome, which is what crude
        filters key on. This says what it is — this browser, at this version,
        on this system — and who is asking, as server/fetch.py does."""
        system = "Macintosh; Intel Mac OS X 10_15_7" if sys.platform == "darwin" else "X11; Linux x86_64"
        return (f"Mozilla/5.0 ({system}) AppleWebKit/537.36 (KHTML, like Gecko) "
                f"Chrome/{browser.version} Safari/537.36 ConceptTrail/0.3")

    @staticmethod
    async def _browser_pid(browser) -> int | None:
        """The browser process id, from the browser itself — the only safe way
        to tell our browser from the writer's own."""
        try:
            session = await browser.new_browser_cdp_session()
            info = await session.send("SystemInfo.getProcessInfo")
            return next((int(p["id"]) for p in info.get("processInfo") or [] if p.get("type") == "browser"), None)
        except Exception:
            return None

    async def _close(self):
        browser, playwright = self._browser, self._playwright
        self._browser = self._playwright = self._pid = self._context = self._tabs = None
        for step in ((browser.close,) if browser else ()) + ((playwright.stop,) if playwright else ()):
            try:
                await step()
            except Exception:
                pass
        # only once it is gone: a closing Opera showed its window again (measured)
        self.hider.stop()

    async def _search(self, query: str) -> dict:
        """With the browser if there is one and it finds something; else
        without one."""
        if time.monotonic() >= self._skip_browser_until:
            try:
                return await self._browser_search(query)
            except asyncio.CancelledError:
                raise
            except NoBrowser:
                # a research runs a dozen searches: do not try to start a
                # missing or broken browser before every one of them
                self._skip_browser_until = time.monotonic() + NO_BROWSER_RETRY_S
            except ApiError:
                pass            # the browser ran but no engine answered it
        return await asyncio.to_thread(http_search, query)

    async def _browser_search(self, query: str) -> dict:
        await self._ensure_browser()
        self._last_used = time.monotonic()
        tabs = self._tabs
        page = await tabs.get()                          # a tab opened at launch
        try:
            started = time.monotonic()
            # every search starts clean, as a new context did — without the new
            # window a new context opens: in a trial a second search in the
            # same cookies got an error page from Yahoo
            await self._context.clear_cookies()
            if True:
                errors = []
                for provider, template in SEARCH_PROVIDERS:
                    try:
                        reply = await page.goto(template.format(query=quote_plus(query)),
                                                wait_until="domcontentloaded", timeout=12_000)
                        if reply is not None and reply.status >= 400:
                            raise ApiError(502, f"HTTP {reply.status}")
                        await page.wait_for_timeout(400)
                        raw = await page.eval_on_selector_all(SELECTORS[provider], """els => els.slice(0, 24).map(a => {
                            const box = a.closest('div, li');
                            return {href: a.href, title: a.innerText, snippet: box ? box.innerText.slice(0, 900) : ''};
                        })""")
                        rows = pick_results(raw)
                        if rows:
                            return {"query": query, "provider": provider, "search_url": page.url,
                                    "duration_ms": round((time.monotonic() - started) * 1000),
                                    "browser": self._name, "results": rows}
                        errors.append(f"{provider}: sonuç yok")
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        errors.append(f"{provider}: {type(exc).__name__}: {str(exc)[:120]}")
                        # a failed page may still be navigating ("interrupted by
                        # another navigation" for every engine after it): the
                        # next engine gets a clean tab
                        try:
                            await page.goto("about:blank", timeout=5_000)
                        except Exception:
                            try:
                                await page.close()
                            except Exception:
                                pass
                            page = await self._context.new_page()
                raise ApiError(502, "Arama sayfalarından sonuç okunamadı. " + " | ".join(errors))
        finally:
            if tabs is self._tabs and not page.is_closed():
                tabs.put_nowait(page)
            elif tabs is self._tabs and self._context is not None:
                tabs.put_nowait(await self._context.new_page())
            self._last_used = time.monotonic()
