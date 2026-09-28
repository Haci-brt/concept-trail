"""Web search inside the app: which windows are hidden, which results are kept."""
from server import websearch as W


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


def test_only_our_operas_are_found():
    """The app -> Playwright's driver -> opera.exe: ours. The writer's own
    Opera does not descend from the app, so it is never touched."""
    table = {10: (1, "pythonw.exe"), 20: (10, "node.exe"), 30: (20, "opera.exe"), 31: (30, "opera.exe"),
             40: (5, "opera.exe"), 41: (40, "opera.exe"), 50: (10, "qtwebengineprocess.exe")}
    assert W.our_operas(10, table) == {30, 31}


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


def test_starting_the_app_starts_no_browser():
    search = W.HiddenOperaSearch()
    assert search.status() == {"running": False, "pid": None, "hidden": True}
