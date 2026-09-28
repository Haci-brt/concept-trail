"""Web search inside the app: which browser, which windows are hidden, which
results are kept — and a search with no browser at all."""
import asyncio

import pytest

from server import websearch as W
from server.errors import ApiError


class FakeWindows:
    def __init__(self, windows, table=None):
        self.windows_ = windows            # hwnd -> (pid, visible)
        self.table = table or {}
        self.hidden = []

    def windows(self):
        return list(self.windows_)

    def pid_of(self, hwnd):
        return self.windows_[hwnd][0]

    def visible(self, hwnd):
        return self.windows_[hwnd][1]

    def hide(self, hwnd):
        self.hidden.append(hwnd)

    def children(self):
        return self.table


def test_only_our_browsers_are_found():
    """The app -> Playwright's driver -> opera.exe: ours. The writer's own
    Opera does not descend from the app, so it is never touched."""
    table = {10: (1, "pythonw.exe"), 20: (10, "node.exe"), 30: (20, "opera.exe"), 31: (30, "opera.exe"),
             40: (5, "opera.exe"), 41: (40, "opera.exe"), 50: (10, "qtwebengineprocess.exe"),
             60: (20, "msedge.exe"), 70: (3, "msedge.exe")}
    assert W.our_browsers(10, table) == {30, 31}
    assert W.our_browsers(10, table, "msedge.exe") == {60}         # the writer's own Edge (70) is not ours


def test_only_the_visible_windows_of_those_processes_are_hidden():
    api = FakeWindows({1: (30, True), 2: (30, False), 3: (40, True), 4: (31, True)})
    assert W.hide_windows({30, 31}, api) == 2 and api.hidden == [1, 4]


def test_a_process_is_worked_out_once():
    api = FakeWindows({}, {10: (1, "python.exe"), 20: (10, "node.exe"), 30: (20, "opera.exe"),
                           40: (5, "opera.exe")})
    hider = W.WindowHider(api=api, root=10)
    assert hider.ours(30) and not hider.ours(40)
    api.table = {}                                  # not read again
    assert hider.ours(30) and not hider.ours(40)


def test_results_are_public_new_and_meaningful():
    raw = [{"href": "https://mealie.io/", "title": "Mealie", "snippet": "Self-hosted recipe manager"},
           {"href": "https://mealie.io/#top", "title": "Mealie again"},
           {"href": "https://search.yahoo.com/more", "title": "More results"},
           {"href": "http://192.168.1.2/admin", "title": "Router admin"},
           {"href": "https://docs.mealie.io/", "title": "Doc"},
           {"href": "javascript:void(0)", "title": "Script link"},
           {"href": "https://github.com/mealie-recipes/mealie", "title": "GitHub - mealie"}]
    rows = W.pick_results(raw)
    assert [r["url"] for r in rows] == ["https://mealie.io/", "https://github.com/mealie-recipes/mealie"]
    assert rows[0]["rank"] == 1 and rows[1]["rank"] == 2


def test_starting_the_app_starts_no_browser(monkeypatch):
    monkeypatch.setattr(W, "find_browser", lambda configured=None: None)
    search = W.HiddenBrowserSearch()
    assert search.status() == {"running": False, "pid": None, "hidden": True, "browser": None}


# ---------------------------------------------------------------- which browser
def test_the_first_installed_browser_is_driven(tmp_path, monkeypatch):
    opera, edge, chrome = (tmp_path / "opera.exe", tmp_path / "msedge.exe", tmp_path / "chrome.exe")
    for env in ("CT_BROWSER", "OPERA_EXECUTABLE"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr(W, "browser_candidates", lambda platform=None: [opera, edge, chrome])
    assert W.find_browser() is None                                  # none installed
    edge.write_text("")
    chrome.write_text("")
    assert W.find_browser() == edge.resolve()                        # no Opera: Edge, which every Windows has
    opera.write_text("")
    assert W.find_browser() == opera.resolve()
    monkeypatch.setenv("CT_BROWSER", str(chrome))
    assert W.find_browser() == chrome.resolve()                      # the writer's choice comes first


def test_every_system_has_places_to_look():
    for platform in ("win32", "darwin"):
        names = [p.name for p in W.browser_candidates(platform)]
        assert names and all(names)
    assert [W.browser_name(W.Path(p)) for p in (r"C:\x\Edge\Application\msedge.exe", "/usr/bin/chromium",
                                                "/opt/google/chrome/google-chrome", "/usr/bin/opera")] == \
        ["Edge", "Chromium", "Chrome", "Opera"]


# ---------------------------------------------------------------- without a browser
DDG_HTML = """
<div class="result results_links"><h2 class="result__title">
<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fgithub.com%2Fsomeone%2Fplant%2Dreminder&amp;rut=1">someone/plant-reminder - GitHub</a></h2>
<a class="result__url" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fgithub.com%2Fsomeone%2Fplant%2Dreminder&amp;rut=1">github.com/someone/plant-reminder</a>
<a class="result__snippet" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fgithub.com%2Fsomeone%2Fplant%2Dreminder&amp;rut=1">Reminds you to <b>water</b> each plant &amp; shares the list.</a></div>
<div class="result results_links_deep result--ad"><a class="result__a" href="https://duckduckgo.com/y.js?ad_domain=shop.example">Buy pots</a></div>
<div class="result results_links"><h2 class="result__title">
<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwaterme.example.org%2F&amp;rut=2">Water Me - a watering app</a></h2>
<a class="result__snippet" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwaterme.example.org%2F&amp;rut=2">A PWA with push reminders.</a></div>
"""
DDG_LITE = """<tr><td>1.&nbsp;</td><td>
<a rel="nofollow" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fgithub.com%2Ffrancis%2Fplant%2Dwatering&amp;rut=3" class='result-link'>francis/plant-watering - GitHub</a>
</td></tr><tr><td>&nbsp;</td><td class='result-snippet'>
Soil sensor and a <b>reminder</b> on your phone.</td></tr>"""


def test_duckduckgo_pages_are_read_without_a_browser():
    rows = W.pick_results(W.parse_duckduckgo(DDG_HTML))
    assert [(r["url"], r["title"]) for r in rows] == [
        ("https://github.com/someone/plant-reminder", "someone/plant-reminder - GitHub"),
        ("https://waterme.example.org/", "Water Me - a watering app")]          # the ad is not a result
    assert rows[0]["snippet"] == "Reminds you to water each plant & shares the list."
    lite = W.pick_results(W.parse_duckduckgo(DDG_LITE))
    assert lite[0]["url"] == "https://github.com/francis/plant-watering"
    assert lite[0]["snippet"] == "Soil sensor and a reminder on your phone."


def test_a_search_without_a_browser_tries_the_lighter_page_next(monkeypatch):
    monkeypatch.setattr(W, "HTTP_GAP_S", 0)
    asked = []

    def get(url):
        asked.append(url)
        return (202, "<html>please wait</html>") if "html.duckduckgo" in url else (200, DDG_LITE)

    result = W.http_search("plant watering reminder", get=get)
    assert result["provider"] == "duckduckgo-lite" and result["browser"] is None
    assert "q=plant+watering+reminder" in asked[0] and len(asked) == 2
    with pytest.raises(ApiError):
        W.http_search("x", get=lambda url: (200, "<html>nothing</html>"))


def test_no_browser_means_a_search_without_one_and_no_retry_each_time(monkeypatch):
    search = W.HiddenBrowserSearch()
    tries = []

    async def no_browser(query):
        tries.append(query)
        raise W.NoBrowser("tarayıcı yok")

    monkeypatch.setattr(search, "_browser_search", no_browser)
    monkeypatch.setattr(W, "http_search", lambda query: {"query": query, "provider": "duckduckgo", "results": []})
    first = asyncio.run(search._search("bir"))
    second = asyncio.run(search._search("iki"))
    assert first["provider"] == second["provider"] == "duckduckgo"
    assert tries == ["bir"]                           # a missing browser is not looked for before every search


def test_a_browser_that_finds_nothing_hands_over_but_is_kept(monkeypatch):
    search = W.HiddenBrowserSearch()
    tries = []

    async def engines_failed(query):
        tries.append(query)
        raise ApiError(502, "Arama sayfalarından sonuç okunamadı.")

    monkeypatch.setattr(search, "_browser_search", engines_failed)
    monkeypatch.setattr(W, "http_search", lambda query: {"query": query, "provider": "duckduckgo", "results": []})
    asyncio.run(search._search("bir"))
    asyncio.run(search._search("iki"))
    assert tries == ["bir", "iki"]                    # it ran; next time it is asked again
