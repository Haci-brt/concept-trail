"""Writing a note: the page itself, completion while writing, the assistant's
questions, and an answer that becomes text in the note only on approval."""


def test_the_app_opens_with_the_sample_notes_and_the_test_model(page):
    names = page.page.eval_on_selector_all(".sidebar .name", "els => els.map((e) => e.textContent.trim())")
    for sample in ("Bitki hatırlatıcı", "Kitap takası", "Büyük ağaç", "Uzun not"):
        assert any(n.startswith(sample) for n in names), names
    page.page.wait_for_function("document.querySelector('#llmPill')?.classList.contains('up')", timeout=15000)
    assert "Sahte model" in page.page.locator("#llmPill").inner_text()
    assert page.page.locator(".su-sheet").count() == 0                 # a model is there: no setup wizard


def test_completion_while_writing_is_taken_with_keys_and_undone_in_one_step(page, app):
    page.open_note(app.note("# Kulüp\n\n"))
    keys = page.page.keyboard
    keys.type("Herkes okuduğu kitabı", delay=15)
    page.page.wait_for_function("document.querySelector('.md-mirror .ghost')", timeout=5000)
    assert page.ghost() == " ve bunu olabildiğince sade tutar."
    assert page.value().endswith("kitabı")                              # shown, not written

    keys.type(" ve", delay=30)                                          # its own letters: it stays
    assert page.ghost() == " bunu olabildiğince sade tutar."
    keys.press("Control+ArrowRight")                                    # one word
    assert page.value().endswith("kitabı ve bunu") and page.ghost() == " olabildiğince sade tutar."
    keys.press("Tab")                                                   # the rest
    assert page.value().endswith("kitabı ve bunu olabildiğince sade tutar.") and page.ghost() is None
    keys.press("Control+z")                                             # one step back
    assert page.value().endswith("kitabı ve bunu")

    keys.press("End")
    keys.press("Enter")
    keys.type("Ayda bir buluşma", delay=15)
    page.page.wait_for_function("document.querySelector('.md-mirror .ghost')", timeout=5000)
    keys.press("Escape")
    assert page.ghost() is None and page.value().endswith("Ayda bir buluşma")
    keys.press("Control+Space")                                         # asked at once
    page.page.wait_for_function("document.querySelector('.md-mirror .ghost')", timeout=5000)
    keys.type("x")                                                      # anything else: it goes
    assert page.ghost() is None

    page.page.locator("#stComplete").click()                            # switched off
    page.editor().click()                                               # (a space on the button would press it)
    keys.press("Control+End")
    keys.type(" yine", delay=15)
    page.page.wait_for_timeout(1500)
    assert page.ghost() is None
    assert "kapalı" in page.page.locator("#stComplete .lbl").inner_text()
    page.page.locator("#stComplete").click()


def test_the_assistant_asks_and_an_answer_goes_into_the_note_only_when_approved(page, app):
    page.open_note(app.note("# Bitki sulama\n\nBitkilerimi sulamayı unutuyorum, bana hatırlatan bir şey istiyorum.\n"))
    page.page.keyboard.press("Control+Enter")                          # ask now
    card = page.page.locator(".h-item:not(.settled)").filter(has=page.page.locator("textarea")).first
    card.wait_for(timeout=15000)
    assert "?" in card.inner_text()

    answer = "Bunu evde yalnız ben kullanacağım"
    card.locator("textarea").fill(answer)
    card.locator("textarea").press("Enter")
    approve = page.page.locator('[data-act="approve"]:visible').first
    approve.wait_for(timeout=15000)
    assert answer not in page.value()                                   # not before approval
    approve.click()
    page.page.wait_for_function("(a) => document.querySelector('.md-input:not([hidden])') && "
                                "[...document.querySelectorAll('.md-input')].some((t) => t.value.includes(a))",
                                arg=answer, timeout=15000)
