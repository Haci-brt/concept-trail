"""The assistant card: "Sonrakini Göster" goes round everything waiting
without losing any of it, an answered question gives way to its proposal, a
long proposal can be read to the end with its buttons in reach, and the idea
tree's "Sıradaki soru" never sits there doing nothing."""
import time

NOTE = "# Bitki sulama\n\nBitkilerimi sulamayı unutuyorum, bana hatırlatan bir şey istiyorum.\n"
# a write-up in bullets, long enough to overflow a small card
ANSWER = ("Bunu evde yalnız ben kullanacağım.\n- Sabah sulama hatırlatması gelsin\n"
          "- Haftada bir gübre hatırlatması\n- Tatildeyken komşuya haber versin")
LONG = ANSWER + "\n- Ayrıntı: " + "bitkilerin her biri kendi takvimiyle sulanır, " * 40

# the desktop bridge, as the Qt shell gives it to the card's own window
BRIDGE = """window.__hud = [];
window.desktop = { setHudState: (v, h) => window.__hud.push([v, h]), startMove() {}, focusMain() {} };"""


def clear_card(app) -> None:
    """Earlier tests' passes may still be landing on the shared card: wait for
    them, then close it, so each test starts with an empty line."""
    deadline = time.monotonic() + 20
    while app.api.get("/api/state").json()["status"]["busy"] and time.monotonic() < deadline:
        time.sleep(0.2)
    # "Kapat" closes one note's items at a time
    for _ in range(50):
        event = app.api.get("/api/state").json()["hud"]["event"]
        if not event:
            break
        app.api.post("/api/assistant/hud", json={"event_id": event["id"], "action": "dismiss"})


def ask(page, app) -> str:
    clear_card(app)
    path = app.note(NOTE)
    page.open_note(path)
    page.page.keyboard.press("Control+Enter")
    page.page.wait_for_selector("#hudSlot .hud-card.kind-question", timeout=15000)
    deadline = time.monotonic() + 15
    while app.api.get("/api/state").json()["status"]["busy"]:
        assert time.monotonic() < deadline, "asistan bitirmedi"
        time.sleep(0.2)
    return path


def card_id(page) -> str:
    return page.page.locator("#hudSlot .hud-card").get_attribute("data-id")


def press_next(page) -> None:
    before = card_id(page)
    page.page.locator('#hudSlot [data-act="next"]').click()
    page.page.wait_for_function("(id) => document.querySelector('#hudSlot .hud-card')?.dataset.id !== id",
                                arg=before, timeout=10000)


def test_next_goes_round_everything_waiting_and_loses_nothing(page, app):
    ask(page, app)
    remaining = app.api.get("/api/state").json()["hud"]["remaining"]
    assert remaining >= 2
    seen = []
    for _ in range(remaining + 2):
        seen.append(page.page.locator("#hudSlot .hud-title").inner_text())
        assert page.page.locator("#hudSlot .hud-count").inner_text() == f"+{remaining}"
        press_next(page)
    total = remaining + 1
    assert len(set(seen[:total])) == total                          # each one, once
    assert seen[total] == seen[0]                                   # and round again


def test_an_answered_question_gives_way_to_its_proposal(page, app):
    path = ask(page, app)
    remaining = app.api.get("/api/state").json()["hud"]["remaining"]
    question = card_id(page)
    item = page.page.locator(f'.h-item[data-id="{question}"]')      # the same question in the panel
    item.locator("textarea").fill(ANSWER)
    item.locator("textarea").press("Enter")

    page.page.wait_for_selector("#hudSlot .hud-card.kind-summary", timeout=15000)
    card = page.page.locator("#hudSlot .hud-card")
    assert card.get_attribute("data-id") != question
    assert page.page.locator("#hudSlot .hud-count").inner_text() == f"+{remaining}"
    assert "\n- Haftada bir" in card.locator(".hud-sub").inner_text()   # its lines kept
    for _ in range(remaining):                                     # the answered question is gone
        press_next(page)
        assert card_id(page) != question

    # the proposal in the panel reads to its end, not three lines of it
    proposal = page.page.locator(".h-item").filter(has=page.page.locator('[data-act="approve"]')).first
    clipped = proposal.locator(".h-text").evaluate("(e) => e.scrollHeight - e.clientHeight")
    assert clipped <= 1, clipped
    assert "Tatildeyken" in proposal.locator(".h-text").inner_text()

    # approved there: it leaves the card, one fewer waits
    proposal.locator('[data-act="approve"]').click()
    page.page.wait_for_function(
        "(n) => (document.querySelector('#hudSlot .hud-count')?.textContent || '+0') === `+${n}`",
        arg=remaining - 1, timeout=10000)
    assert page.page.locator("#hudSlot .hud-card.kind-question").count() == 1
    deadline = time.monotonic() + 15
    while "Tatildeyken" not in app.api.get("/api/notes", params={"path": path}).json()["content"]:
        assert time.monotonic() < deadline, "onaylanan metin nota girmedi"
        time.sleep(0.3)


def test_the_desktop_card_keeps_a_long_proposal_readable_and_fits_the_next_one(browser, app):
    clear_card(app)
    path = app.note(NOTE)
    content = app.api.get("/api/notes", params={"path": path}).json()["content"]
    app.api.post("/api/assistant/analyze", json={"path": path, "content": content, "force": True})
    deadline = time.monotonic() + 15
    while not app.api.get("/api/state").json()["hud"]["event"] or \
            app.api.get("/api/state").json()["status"]["busy"]:
        assert time.monotonic() < deadline, "soru gelmedi"
        time.sleep(0.2)
    question = app.api.get("/api/state").json()["hud"]["event"]
    with app.api.stream("POST", "/api/assistant/chat",
                        json={"path": path, "node_id": question["node_id"], "message": LONG}) as reply:
        reply.read()

    context = browser.new_context(viewport={"width": 380, "height": 640})   # the window's widest and tallest
    try:
        hud = context.new_page()
        errors = []
        hud.on("pageerror", lambda error: errors.append(str(error)))
        hud.add_init_script(BRIDGE)
        hud.goto(f"{app.url}hud?desktop=1")
        hud.wait_for_selector(".hud-card.kind-summary", timeout=15000)
        hud.wait_for_function("window.__hud.length > 0")
        visible, height = hud.evaluate("window.__hud.at(-1)")
        assert visible and height <= 640
        sub = hud.locator(".hud-sub")
        assert sub.evaluate("(e) => e.scrollHeight > e.clientHeight")      # the rest scrolls into view
        for act in ("approve", "reject", "next"):
            box = hud.locator(f'[data-act="{act}"]').bounding_box()
            assert box and box["y"] + box["height"] <= height, act       # inside the window, not cut off

        hud.locator('[data-act="next"]').click()                         # a short question after it
        hud.wait_for_selector(".hud-card.kind-question", timeout=10000)
        hud.wait_for_function("(h) => window.__hud.at(-1)[1] < h", arg=height, timeout=5000)
        shorter = hud.evaluate("window.__hud.at(-1)[1]")
        bottom = hud.evaluate("document.querySelector('.hud-card').getBoundingClientRect().bottom")
        assert bottom <= shorter < height                                # the window shrinks to the card
        assert not errors, errors
    finally:
        context.close()


def test_the_trees_next_question_is_off_when_nothing_waits_and_goes_round_when_it_does(page, app):
    clear_card(app)
    path = app.note(NOTE)
    page.open_note(path)
    page.page.locator('[title^="Fikir ağacı"]').first.click()
    button = page.page.locator(".cv-next")
    page.page.wait_for_selector(".tv-empty:not([hidden])", timeout=10000)
    assert button.is_disabled()

    page.page.locator('.tv-empty [data-act="ask"]').click()
    page.page.wait_for_function("() => !document.querySelector('.cv-next').disabled", timeout=15000)
    deadline = time.monotonic() + 15
    while app.api.get("/api/state").json()["status"]["busy"]:
        assert time.monotonic() < deadline, "asistan bitirmedi"
        time.sleep(0.2)
    nodes = app.api.get("/api/assistant/nodes", params={"path": path}).json()["nodes"]
    waiting = sum(1 for n in nodes if n["type"] == "question" and n["status"] == "open")
    assert waiting >= 2
    opened = []
    for _ in range(waiting + 1):
        button.click()
        page.page.wait_for_selector(".cv-card.open", timeout=5000)
        opened.append(page.page.locator(".cv-card").get_attribute("data-id"))
    assert len(set(opened[:waiting])) == waiting and opened[waiting] == opened[0], opened

    page.page.locator('.seg [data-filter="done"]').click()               # none of them in view
    page.page.wait_for_function("() => document.querySelector('.cv-next').disabled", timeout=5000)
