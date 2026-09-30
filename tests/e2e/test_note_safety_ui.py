"""The page never loses what is in the editor when a save is refused: a note
changed elsewhere asks, a locked file is tried again, a gone note's text is
rescued into a note of its own."""
import time


def typed(page, text):
    page.editor().click()
    page.page.keyboard.press("Control+End")
    page.page.keyboard.type(text)


def disk(app, rel):
    return (app.vault / rel).read_text(encoding="utf-8")


def wait_for(page, check, seconds=10):
    # waits through the page, so its route handlers and timers keep running
    deadline = time.monotonic() + seconds
    while not check():
        assert time.monotonic() < deadline
        page.page.wait_for_timeout(200)


def test_a_note_changed_elsewhere_asks_and_keeps_both(page, app):
    rel = app.note("# Çakışma\n\nİlk hali.\n")
    page.open_note(rel)
    time.sleep(0.05)
    (app.vault / rel).write_text("# Çakışma\n\nObsidian'da değişti.\n", encoding="utf-8")
    typed(page, " Benim cümlem.")
    dialog = page.page.locator(".choice-dialog")
    dialog.wait_for(timeout=10000)
    dialog.locator('[data-choice="mine"]').click()
    wait_for(page, lambda: "Benim cümlem." in disk(app, rel))
    versions = app.api.get("/api/notes/versions", params={"path": rel}).json()
    kept = app.api.get("/api/notes/version", params={"path": rel, "id": versions[0]["id"]}).json()["content"]
    assert "Obsidian" in kept


def test_choosing_the_other_version_saves_mine_as_its_own_note(page, app):
    rel = app.note("# Diğeri\n\nİlk hali.\n", name="Diğeri")
    page.open_note(rel)
    time.sleep(0.05)
    (app.vault / rel).write_text("# Diğeri\n\nTelefondan değişti.\n", encoding="utf-8")
    typed(page, " Masaüstünde yazdım.")
    page.page.locator('.choice-dialog [data-choice="theirs"]').click(timeout=10000)
    page.page.wait_for_function("() => [...document.querySelectorAll('.md-input')].some((t) => t.value.includes('Telefondan'))",
                                timeout=10000)
    wait_for(page, lambda: (app.vault / "Diğeri (senin sürümün).md").exists())
    assert "Masaüstünde yazdım." in disk(app, "Diğeri (senin sürümün).md")
    assert "Masaüstünde" not in disk(app, rel)


def test_a_locked_file_keeps_the_tab_and_saves_once_free(page, app):
    rel = app.note("# Kilit\n\nİlk hali.\n")
    page.open_note(rel)
    refused = []

    def locked(route):
        if route.request.method == "PUT" and not refused:
            refused.append(1)
            return route.fulfill(status=423, content_type="application/json",
                                 body='{"detail": "Dosya başka bir program tarafından kilitli."}')
        return route.continue_()

    page.page.route("**/api/notes", locked)
    typed(page, " Kilitliyken yazdım.")
    wait_for(page, lambda: refused)
    assert page.page.locator(".md-editor.active").count() == 1          # the tab is still there
    wait_for(page, lambda: "Kilitliyken yazdım." in disk(app, rel), seconds=15)


def test_a_note_gone_elsewhere_rescues_what_was_typed(page, app):
    rel = app.note("# Silinecek\n\nİlk hali.\n", name="Silinecek")
    page.open_note(rel)
    (app.vault / rel).unlink()
    typed(page, " Kaybolmasın.")
    wait_for(page, lambda: (app.vault / "Silinecek (kurtarılan).md").exists())
    assert "Kaybolmasın." in disk(app, "Silinecek (kurtarılan).md")
