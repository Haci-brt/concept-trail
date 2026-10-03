"""First start with no model: the wizard opens by itself, can be put aside,
says what went wrong in words, and connects a model running on this computer."""
import pytest

from harness import App, Page


@pytest.fixture
def fresh(tmp_path, browser):
    running = App(tmp_path, model=None)                    # nothing connected, as after installing
    context = browser.new_context(viewport={"width": 1400, "height": 880})
    page = Page(context.new_page(), running).open()
    yield page
    context.close()
    running.stop()
    assert not page.errors, f"sayfada hata: {page.errors}"


def test_the_wizard_leads_from_nothing_to_a_connected_model(fresh, fake_model):
    p = fresh.page
    sheet = p.locator(".su-sheet")
    sheet.wait_for(timeout=15000)
    assert "Asistanı bir modele bağla" in sheet.inner_text()
    assert sheet.locator(".su-card").count() == 4

    sheet.locator('[data-act="later"]').click()                    # put aside ...
    p.wait_for_selector(".su-sheet", state="detached")
    p.reload()
    p.wait_for_selector(".sidebar .name", state="attached")
    p.wait_for_timeout(1500)
    assert p.locator(".su-sheet").count() == 0                    # ... it does not come back by itself
    pill = p.locator("#llmPill")
    assert "Modeli bağla" in pill.inner_text()

    pill.click()                                                   # but waits behind the model button
    sheet.wait_for()
    sheet.locator('[data-go="local"]').click()
    sheet.locator('[data-pick="manual"]').click()
    sheet.locator('[data-kind="llamacpp"]').click()
    sheet.locator('[data-f="localUrl"]').fill("http://127.0.0.1:9")          # nothing listens there
    sheet.locator('[data-act="connect"]').click()
    error = sheet.locator(".su-error")
    error.wait_for(timeout=20000)
    assert "ulaşılamadı" in error.inner_text()                     # said in words, nothing saved
    assert fresh.app.api.get("/api/setup").json()["needed"] is True

    sheet.locator('[data-f="localUrl"]').fill(fake_model.base_url)
    sheet.locator('[data-f="localModel"]').fill("sahte-model")
    sheet.locator('[data-act="connect"]').click()
    sheet.locator(".su-done").wait_for(timeout=20000)
    assert "Hazır" in sheet.inner_text()
    sheet.locator('.su-foot [data-act="close"]').click()
    p.wait_for_function("document.querySelector('#llmPill').classList.contains('up')", timeout=15000)
    roles = fresh.app.api.get("/api/providers").json()["roles"]
    assert all(chain[0] == "llamacpp" for chain in roles.values()), roles
