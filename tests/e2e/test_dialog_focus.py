"""Open dialogs keep the keyboard: Tab and Shift+Tab never leave the dialog,
and when it closes focus goes back to the button that opened it."""
import pytest

from harness import App, Page

INSIDE = "(sel) => { const d = document.querySelector(sel); return !!d && d.contains(document.activeElement); }"
FOCUSED = "document.activeElement?.id || document.activeElement?.tagName"


def cycle(p, dialog, key, steps=40):
    """Press `key` more times than the dialog has stops; focus must stay in it."""
    for i in range(steps):
        p.keyboard.press(key)
        assert p.evaluate(INSIDE, dialog), (
            f"{key} no. {i + 1} took focus out of {dialog}: "
            + p.evaluate("(document.activeElement.outerHTML || '').slice(0, 120)"))


def settled(p):
    """The search for local models repaints the wizard when it ends, focus with
    it: let it end first."""
    p.wait_for_function("!document.querySelector('.su-probe')?.textContent.includes('aranıyor')", timeout=30000)
    p.wait_for_timeout(400)


def check(page, opener, dialog, closed, close_key="Escape"):
    """Open `dialog` from `opener`, tab around it both ways, close it, and see
    that focus is back on the opener."""
    p = page.page
    p.locator(opener).focus()
    p.keyboard.press("Enter")                       # opened from the keyboard: the opener is what has focus
    p.wait_for_selector(dialog, timeout=10000)
    p.wait_for_timeout(300)                         # sheets fade in; their buttons settle
    cycle(p, dialog, "Tab")
    cycle(p, dialog, "Shift+Tab")
    p.keyboard.press(close_key)
    p.wait_for_selector(closed, state="detached", timeout=10000)
    assert p.evaluate(FOCUSED) == opener.lstrip("#"), "focus did not return to the opener"


def test_settings_and_palette_trap_focus_and_give_it_back(page):
    check(page, "#settingsBtn", ".settings", ".settings")
    check(page, "#globalSearch", ".palette", ".palette")


def test_the_new_note_prompt_traps_focus_and_gives_it_back(page):
    check(page, "#addTab", ".dialog", ".dialog")


def test_master_prompt_and_direction_trap_focus_and_give_it_back(page, app):
    page.open_note(app.note("# Odak\n\nBir not.\n"))
    check(page, "#masterLaunch", ".mp-sheet", ".mp-sheet")
    check(page, "#directionBtn", ".direction-dialog", ".direction-dialog")


def test_a_dialog_over_a_dialog_traps_only_the_newest(page):
    """A prompt opened over settings holds focus; closing it hands focus back
    to where it was in settings, and settings holds it again."""
    p = page.page
    p.locator("#settingsBtn").click()
    p.wait_for_selector(".settings")
    p.locator("#addTab").evaluate("(b) => b.click()")          # a second dialog over the first
    p.wait_for_selector(".dialog:not(.settings)")
    cycle(p, ".dialog:not(.settings)", "Tab", 12)
    p.locator('.dialog:not(.settings) [data-act="cancel"]').click()
    p.wait_for_selector(".dialog:not(.settings)", state="detached")
    cycle(p, ".settings", "Tab", 12)
    p.keyboard.press("Escape")
    p.wait_for_selector(".settings", state="detached")


@pytest.fixture
def fresh(tmp_path, browser):
    running = App(tmp_path, model=None)                    # nothing connected: the wizard opens by itself
    context = browser.new_context(viewport={"width": 1400, "height": 880})
    page = Page(context.new_page(), running).open()
    yield page
    context.close()
    running.stop()
    assert not page.errors, f"sayfada hata: {page.errors}"


def test_the_setup_wizard_traps_focus_and_gives_it_back(fresh):
    p = fresh.page
    p.wait_for_selector(".su-sheet", timeout=15000)
    settled(p)
    cycle(p, ".su-sheet", "Tab")
    cycle(p, ".su-sheet", "Shift+Tab")
    p.locator('.su-sheet [data-act="later"]').click()
    p.wait_for_selector(".su-sheet", state="detached")
    p.locator("#llmPill").click()                      # reopened from the model button
    p.wait_for_selector(".su-sheet")
    settled(p)
    cycle(p, ".su-sheet", "Tab")
    p.keyboard.press("Escape")
    p.wait_for_selector(".su-sheet", state="detached")
