"""Narrow windows, the keyboard, the roadmap chips, the "Rotayı düzelt" dialog,
the toolbar, the English interface and the small things around them."""
import re
import time

import pytest

from harness import PENDING_EN, Page, merge_pending_en
from test_card_next import clear_card

NOTE = "# Bitki sulama\n\nBitkilerimi sulamayı unutuyorum, bana hatırlatan bir şey istiyorum.\n"
ANSWER = "Bunu evde yalnız ben kullanacağım. Sabah sulama hatırlatması gelsin."

TURKISH = re.compile(r"[çğıöşüÇĞİÖŞÜ]|\b(gerekmez|gerekli|bekliyor|için|bir|yok|ekle|kapat)\b")
SWEEP = """() => {
  const skip = ".md-mirror, .preview-body, .md, .mp-raw, .tn-body, .tab .name, .sidebar .name, .crumbs, .msg, "
    + ".p-text, .h-text, .h-reply, .note-heading h1, [translate=no], code, pre, kbd, .vt-row, .hud-title, .hud-sub, "
    + ".hud-note, .hud-thought, .tn-section-name, .direction-context, .direction-current, .direction-said, "
    + ".md-chapter-picker option:not([value=start])";
  const out = new Set();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const p = n.parentElement;
    if (!p || p.closest(skip) || ["SCRIPT", "STYLE", "TEXTAREA"].includes(p.tagName)) continue;
    const text = n.data.trim();
    if (text) out.add(text);
  }
  for (const el of document.querySelectorAll("*")) {
    if (el.closest(skip)) continue;
    for (const a of ["title", "placeholder", "aria-label"]) {
      const v = el.getAttribute(a);
      if (v && !el.closest(".tab")) out.add(`[${a}] ${v}`);
    }
  }
  return [...out];
}"""


@pytest.fixture
def at(browser, app):
    """Pages at a width of the test's choosing; their errors are checked at the end."""
    made = []

    def open_at(width, height=880):
        context = browser.new_context(viewport={"width": width, "height": height})
        made.append((context, Page(context.new_page(), app).open()))
        return made[-1][1]

    yield open_at
    for context, page in made:
        context.close()
        assert not page.errors, f"sayfada hata: {page.errors}"


def own_note(page, app, text=NOTE):
    page.open_note(app.note(text))
    return page


def ask(page, app, text=NOTE):
    clear_card(app)
    own_note(page, app, text)
    page.page.keyboard.press("Control+Enter")
    page.page.locator(".h-item.open").first.wait_for(state="attached", timeout=20000)
    deadline = time.monotonic() + 20
    while app.api.get("/api/state").json()["status"]["busy"]:
        assert time.monotonic() < deadline, "asistan bitirmedi"
        time.sleep(0.2)


def box(page, selector):
    return page.page.evaluate("""(s) => { const e = document.querySelector(s); if (!e) return null;
      const r = e.getBoundingClientRect(), c = getComputedStyle(e);
      return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width,
               shown: c.display !== "none" && c.visibility !== "hidden" && r.width > 0 }; }""", selector)


# ---------------------------------------------------------------- 1. narrow windows
@pytest.mark.parametrize("width", [900, 1280, 1400, 1920])
def test_each_width_keeps_what_it_has_room_for_and_nothing_is_cut_off(at, app, width):
    page = own_note(at(width), app)
    page.page.wait_for_timeout(300)
    assert page.page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "sayfa yana kayıyor"
    assert box(page, "#sidebar")["shown"], "not listesi görünmeli"
    assert box(page, ".editor-card")["shown"]
    assert bool(box(page, ".preview-card")["shown"]) == (width >= 1500)      # the preview gives way first
    assert bool(box(page, "#rightpanel")["shown"]) == (width >= 1180)
    card, direction = box(page, ".editor-card"), box(page, "#directionBtn")
    assert card["left"] <= direction["left"] and direction["right"] <= card["right"], (card, direction)


def test_the_preview_collapses_before_the_sidebar_and_comes_back_with_room(at, app):
    page = own_note(at(1400), app)
    assert box(page, "#sidebar")["shown"] and not box(page, ".preview-card")["shown"]
    page.page.set_viewport_size({"width": 1920, "height": 880})
    page.page.wait_for_function("document.querySelector('.preview-card').getBoundingClientRect().width > 0")
    page.page.set_viewport_size({"width": 1400, "height": 880})
    page.page.wait_for_function("document.querySelector('.preview-card').getBoundingClientRect().width === 0")
    assert box(page, "#sidebar")["shown"]
    page.page.locator("#previewToggle").click()                              # asked for in so many words
    page.page.wait_for_function("document.querySelector('.preview-card').getBoundingClientRect().width > 0")


def test_a_hidden_panel_shows_what_waits_in_it_and_opens_over_the_note(at, app):
    page = at(900)
    ask(page, app)
    toggle = page.page.locator("#togglePanel")
    toggle.and_(page.page.locator(".has-badge")).wait_for(timeout=10000)
    assert int(toggle.get_attribute("data-badge")) >= 2
    page.page.wait_for_selector(".toast >> text=/sorusu var/", timeout=10000)
    assert page.page.locator(".toast >> text=/sorusu var/").count() == 1       # once, not for every question

    toggle.click()
    assert "panel-overlay" in page.page.get_attribute("#app", "class")
    panel = box(page, "#rightpanel")
    assert panel["shown"] and panel["left"] >= 0 and panel["right"] <= 900
    assert not toggle.get_attribute("data-badge")                              # seen now
    page.page.locator("#editorHost, .editor-card").first.click(position={"x": 30, "y": 30})
    page.page.wait_for_function("!document.querySelector('#app').classList.contains('panel-overlay')")


# ---------------------------------------------------------------- 2. keyboard
def region_with_focus(page):
    return page.page.evaluate("""() => { const a = document.activeElement;
      return a.closest('#sidebar') ? 'sidebar' : a.closest('#rightpanel') ? 'panel' : a.closest('.editor-card') ? 'editor' : 'other'; }""")


def test_f6_goes_round_the_list_the_note_and_the_panel_with_a_visible_ring(at, app):
    page = at(1400)
    ask(page, app)
    page.editor().click()
    order = []
    for _ in range(3):
        page.page.keyboard.press("F6")
        order.append(region_with_focus(page))
    assert order == ["panel", "sidebar", "editor"], order
    ring = page.page.evaluate("getComputedStyle(document.querySelector('.f6-ring')).outlineStyle")
    assert ring == "solid"
    page.page.keyboard.press("Shift+F6")
    assert region_with_focus(page) == "sidebar"
    page.editor().click()                                                      # clicking away takes the ring
    assert page.page.locator(".f6-ring").count() == 0


def test_tab_in_the_editor_still_indents(at, app):
    page = own_note(at(1400), app, "# Not\n\n")
    page.page.keyboard.type("madde")
    page.page.keyboard.press("Tab")
    assert page.value().endswith(("madde  ", "madde\t")), repr(page.value())          # an indent, not a jump to the next control
    assert region_with_focus(page) == "editor"


def test_the_palette_answers_the_next_question_and_corrects_the_course(at, app):
    page = at(1400)
    ask(page, app)
    page.page.keyboard.press("Control+p")
    page.page.keyboard.type(">Sıradaki soruyu")
    page.page.keyboard.press("Enter")
    page.page.wait_for_function("document.activeElement?.matches('.h-item.open textarea')", timeout=5000)
    first = page.page.locator(".h-item.open").first.get_attribute("data-id")
    assert page.page.evaluate("document.activeElement.closest('.h-item').dataset.id") == first

    page.page.keyboard.press("Control+p")
    page.page.keyboard.type(">Rotayı düzelt")
    page.page.keyboard.press("Enter")
    page.page.locator(".direction-dialog").wait_for(timeout=5000)
    page.page.keyboard.press("Escape")
    page.page.locator("#stKeys").click()
    shortcuts = page.page.locator(".shortcut-grid").inner_text()
    for row in ("Sıradaki soruyu cevapla", "Rotayı düzelt"):
        assert row in shortcuts, shortcuts


# ---------------------------------------------------------------- 3. roadmap chips
def chip(page, index=0):
    return page.page.locator(".lg-chip").nth(index)


def test_a_roadmap_chip_opens_a_popover_and_every_change_can_be_taken_back(at, app):
    page = own_note(at(1400), app)
    page.page.locator(".lg-chip").first.wait_for(timeout=15000)
    first = chip(page)
    assert "y" not in (first.get_attribute("class") or "").split()
    first.click()
    pop = page.page.locator(".lg-pop")
    assert pop.locator(".lg-pop-state").inner_text() == "Henüz karar verilmedi"
    pop.locator(".lg-pop-value").fill("yalnız ben")
    pop.get_by_role("button", name="Karar verildi").click()
    page.page.wait_for_function("document.querySelector('.lg-chip').classList.contains('y')")
    assert page.page.locator(".lg-pop").count() == 0
    toast = page.page.locator(".toast", has_text="karar verildi")
    toast.get_by_role("button", name="Geri al").click()                       # back to undecided
    page.page.wait_for_function("!document.querySelector('.lg-chip').classList.contains('y')")

    first.click()                                                              # decide again, then reopen it
    page.page.locator(".lg-pop-value").fill("yalnız ben")
    page.page.locator(".lg-pop").get_by_role("button", name="Karar verildi").click()
    page.page.wait_for_function("document.querySelector('.lg-chip').classList.contains('y')")
    first.click()
    facts = page.page.locator(".lg-pop-facts").inner_text()
    assert "yalnız ben" in facts and "sen işaretledin" in facts                # the value, and who set it
    page.page.locator(".lg-pop").get_by_role("button", name="Yeniden sor").click()
    page.page.wait_for_function("!document.querySelector('.lg-chip').classList.contains('y')")
    page.page.locator(".toast", has_text="yeniden sorulacak").get_by_role("button", name="Geri al").click()
    page.page.wait_for_function("document.querySelector('.lg-chip').classList.contains('y')")
    first.click()
    assert "yalnız ben" in page.page.locator(".lg-pop-facts").inner_text()     # the value came back too
    page.page.keyboard.press("Escape")


# ---------------------------------------------------------------- 4. "Rotayı düzelt"
PLAN = {"summary": "Bekleyen her şey kapanır.", "items": {}, "update": {}, "reopen": [],
        "drop_questions": [], "drop_proposals": [], "ask": [], "fallback": True}


def open_direction(page, text):
    page.page.locator("#directionBtn").click()
    page.page.locator(".direction-dialog").wait_for()
    page.page.locator('[data-category="kapsam"]').click()
    page.page.locator("#directionText").fill(text)


def test_closing_the_correction_while_its_effect_is_read_does_not_throw(at, app):
    page = own_note(at(1400), app)

    def slow(route):
        page.page.wait_for_timeout(700)
        route.fulfill(json={**PLAN, "fallback": False, "summary": "Yeni yön."})

    page.page.route("**/api/assistant/direction/preview", slow)
    open_direction(page, "Sadece ben kullanacağım.")
    page.page.locator(".direction-dialog [data-act=next]").click()
    page.page.wait_for_selector(".direction-dialog [data-act=next]:disabled")
    page.page.keyboard.press("Escape")
    page.page.wait_for_timeout(1200)
    assert page.page.locator(".direction-dialog").count() == 0


def test_a_click_beside_the_correction_keeps_what_was_typed(at, app):
    page = own_note(at(1400), app)
    open_direction(page, "Sadece ben kullanacağım.")
    page.page.mouse.click(8, 400)
    page.page.wait_for_timeout(200)
    assert page.page.locator("#directionText").input_value() == "Sadece ben kullanacağım."
    page.page.locator('[data-act="cancel"]').click()
    page.page.locator("#directionBtn").click()                                 # nothing typed this time: it just closes
    page.page.locator(".direction-dialog").wait_for()
    page.page.mouse.click(8, 400)
    page.page.wait_for_function("!document.querySelector('.direction-dialog')")


def test_without_a_model_the_review_does_not_promise_both_things(at, app):
    page = own_note(at(1400), app)
    page.page.route("**/api/assistant/direction/preview", lambda route: route.fulfill(json=PLAN))
    open_direction(page, "Sadece ben kullanacağım.")
    page.page.locator(".direction-dialog [data-act=next]").click()
    review = page.page.locator(".direction-review")
    review.wait_for()
    text = review.inner_text()
    assert "Bekleyen her şey kapanır" not in text                              # the server's blanket rule is not shown
    assert not ("kapanmayacak" in text and "korunacak" in text), text
    assert "çelişmiyor" not in text, text


# ---------------------------------------------------------------- 5. toolbar
def test_the_toolbar_keeps_the_assistants_buttons_and_folds_the_rest_into_a_menu(at, app):
    page = own_note(at(1280), app)
    page.page.locator("#previewToggle").click()                                # two columns on a laptop
    page.page.wait_for_function("document.querySelector('.preview-card').getBoundingClientRect().width > 0")
    page.page.wait_for_function("!document.querySelector('#toolbarMore').hidden", timeout=5000)
    page.page.wait_for_timeout(600)                                            # the columns have settled
    card = box(page, ".editor-card")
    for selector in ("#directionBtn", "#askBtn", "#previewToggle", "#toolbarMore"):
        b = box(page, selector)
        assert b["shown"] and card["left"] <= b["left"] and b["right"] <= card["right"], (selector, b, card)
    hidden = page.page.eval_on_selector_all("#toolbar [data-tool]", "els => els.filter((e) => e.hidden).length")
    page.page.locator("#toolbarMore").click()
    assert page.page.locator(".menu .menu-item").count() == hidden >= 1
    page.page.keyboard.press("Escape")
    page.page.set_viewport_size({"width": 1920, "height": 880})                # room again: nothing folded
    page.page.wait_for_function("document.querySelector('#toolbarMore').hidden", timeout=5000)


# ---------------------------------------------------------------- 6. English interface
def english(page, app):
    app.api.put("/api/preferences", json={"ui_language": "en"})
    merge_pending_en(page.page)
    page.page.reload()
    page.page.wait_for_selector(".sidebar .name", state="attached")
    page.page.wait_for_timeout(1200)


def turkish_left(page):
    return [i for i in page.page.evaluate(SWEEP) if TURKISH.search(i)]


def test_the_english_interface_has_no_turkish_in_the_editor_or_its_dialogs(at, app):
    page = at(1400)
    try:
        english(page, app)
        page.open_note("Bitki hatırlatıcı")
        page.page.keyboard.press("Control+Enter")
        page.page.locator(".h-item.open").first.wait_for(state="attached", timeout=20000)
        page.page.wait_for_timeout(800)
        assert page.page.locator(".md-chapter-kicker").inner_text().upper() == "SECTION"
        assert page.page.locator('.md-chapter-picker option[value="start"]').inner_text() != "Başlangıç"
        assert page.page.get_attribute(".md-chapter-picker select", "aria-label") == "Go to section"
        assert page.page.get_attribute(".md-input", "aria-label") == "Note text"
        assert "Bitki hatırlatıcı" in page.page.locator(".md-chapter-picker").inner_text()   # the note's own heading stays
        found = {"main": turkish_left(page)}
        for name, open_it, close_it in [
            ("settings", lambda: page.page.click("#settingsBtn"), lambda: page.page.keyboard.press("Escape")),
            ("palette", lambda: page.page.keyboard.press("Control+p"), lambda: page.page.keyboard.press("Escape")),
            ("shortcuts", lambda: page.page.click("#stKeys"), lambda: page.page.keyboard.press("Escape")),
            ("direction", lambda: page.page.click("#directionBtn"), lambda: page.page.keyboard.press("Escape")),
            ("chip", lambda: page.page.locator(".lg-chip").first.click(), lambda: page.page.keyboard.press("Escape")),
        ]:
            open_it()
            page.page.wait_for_timeout(500)
            found[name] = turkish_left(page)
            close_it()
        # a provider's key field says "not needed" / "required", not "gerekmez" / "gerekli"
        page.page.click("#settingsBtn")
        page.page.wait_for_timeout(500)
        holders = page.page.eval_on_selector_all("[data-f=api_key]", "els => els.map((e) => e.placeholder)")
        assert holders and all(h in ("not needed", "required") for h in holders), holders
        page.page.keyboard.press("Escape")
        # the roadmap chips' tooltips are the server's words, translated on this side
        chips = page.page.eval_on_selector_all(".lg-chip", "els => els.map((e) => e.title)")
        assert chips and not [c for c in chips if TURKISH.search(c)], chips
        assert not any(found.values()), found
        missing = page.page.evaluate("window.__i18nMissing()")
        assert not [m for m in missing if TURKISH.search(m) and m not in PENDING_EN and not m.endswith(".md")], missing[:10]   # a note's own path is not the interface
    finally:
        app.api.put("/api/preferences", json={"ui_language": "tr"})


# ---------------------------------------------------------------- 7. polish
def test_the_answer_box_shows_its_whole_prompt_and_the_tabs_have_no_extension(at, app):
    page = at(1400)
    ask(page, app)
    fits = page.page.evaluate("""() => { const t = document.querySelector('.h-item.open textarea');
      const c = getComputedStyle(t), p = getComputedStyle(t, '::placeholder'), probe = document.createElement('canvas').getContext('2d');
      probe.font = `${p.fontSize} ${c.fontFamily}`;
      const room = t.clientWidth - parseFloat(c.paddingLeft) - parseFloat(c.paddingRight);
      return { text: probe.measureText(t.placeholder).width, room }; }""")
    assert fits["text"] <= fits["room"], fits
    names = page.page.eval_on_selector_all("#tabs .tab .name", "els => els.map((e) => e.textContent.trim())")
    assert names and not [n for n in names if n.lower().endswith(".md")], names


def test_the_card_and_the_panel_list_the_questions_in_the_same_order(at, app):
    page = at(1400)
    ask(page, app)
    panel = page.page.eval_on_selector_all(".h-item.open", "els => els.map((e) => e.dataset.id)")
    seen = []
    for _ in range(min(len(panel), 3)):
        seen.append(page.page.locator("#hudSlot .hud-card").get_attribute("data-id"))
        if len(seen) < min(len(panel), 3):
            page.page.locator('#hudSlot [data-act="next"]').click()
            page.page.wait_for_function("(id) => document.querySelector('#hudSlot .hud-card')?.dataset.id !== id",
                                        arg=seen[-1])
    assert seen == panel[:len(seen)], (seen, panel)


def test_every_approval_button_says_nota_ekle_and_vazgec(at, app):
    page = at(1400)
    ask(page, app)
    first = page.page.locator(".h-item.open").first
    first.locator("textarea").fill(ANSWER)
    first.locator("textarea").press("Enter")
    page.page.wait_for_selector("#hudSlot .hud-card.kind-summary", timeout=20000)
    card = page.page.locator("#hudSlot .hud-card.kind-summary")
    assert card.locator('[data-act="approve"]').inner_text().strip() == "Nota ekle"
    assert card.locator('[data-act="reject"]').inner_text().strip() == "Vazgeç"
    panel = page.page.locator('.h-item [data-act="approve"]').first
    assert panel.inner_text().strip() == "Nota ekle"
    assert page.page.locator('.h-item [data-act="reject"]').first.inner_text().strip() == "Vazgeç"


def test_approving_from_another_note_names_the_note_in_the_toast(at, app):
    page = at(1400)
    ask(page, app)
    name = page.page.locator("#tabs .tab.active .name").inner_text().strip()
    first = page.page.locator(".h-item.open").first
    first.locator("textarea").fill(ANSWER)
    first.locator("textarea").press("Enter")
    page.page.wait_for_selector("#hudSlot .hud-card.kind-summary", timeout=20000)
    page.page.evaluate("[...document.querySelectorAll('.sidebar .name')].find((e) => e.textContent.trim().startsWith('Beni oku')).click()")
    page.page.wait_for_function("document.querySelector('#tabs .tab.active .name').textContent.startsWith('Beni oku')")
    page.page.locator('#hudSlot [data-act="approve"]').click()
    page.page.locator(".toast", has_text=name).wait_for(timeout=10000)


def test_chat_bubbles_show_lists_and_bold_and_never_raw_html(at, app):
    page = at(1400)
    ask(page, app)
    first = page.page.locator(".h-item.open").first
    first.locator('[data-act="chat"]').dispatch_event("click")
    page.page.wait_for_selector(".chat.open .chat-log > *", timeout=10000)
    page.page.locator(".chat textarea").fill("Bilmiyorum, fikrin var mı?")
    page.page.locator(".chat textarea").press("Enter")
    page.page.wait_for_function("document.querySelectorAll('.chat .msg.assistant.rich li').length >= 2", timeout=20000)
    html = page.page.evaluate("""async () => {
      const { miniMarkdown } = await import('/static/js/util.js');
      return miniMarkdown('**kalın** <img src=x onerror=alert(1)>\\n- bir\\n- iki');
    }""")
    assert "<strong>kalın</strong>" in html and "<li>bir</li>" in html
    assert "<img" not in html and "&lt;img" in html


def test_the_master_prompt_toast_does_not_cover_the_sheets_footer(at, app):
    page = at(1400)
    page.open_note("Harcama takibi")
    page.page.keyboard.press("Control+Shift+M")
    page.page.locator(".mp-sheet").wait_for(timeout=10000)
    page.page.locator(".mp-go").click()
    page.page.locator(".toast", has_text="Master prompt hazır").wait_for(timeout=40000)
    foot, toast = box(page, ".mp-foot"), box(page, ".toast")
    assert toast["top"] >= foot["bottom"] or toast["bottom"] <= foot["top"] or toast["right"] <= foot["left"] \
        or toast["left"] >= foot["right"], (foot, toast)
