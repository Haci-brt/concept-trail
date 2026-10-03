"""A flow only the stand-in model's choice handling makes possible: the writer
does not know, the assistant offers options, the writer takes one, and the
decision comes back as a proposal for the note."""

NOTE = "# Bitki sulama\n\nBitkilerimi sulamayı unutuyorum, bana hatırlatan bir şey istiyorum.\n"


def send(page, text: str) -> None:
    box = page.page.locator(".chat textarea")
    box.fill(text)
    box.press("Enter")


def test_not_knowing_gets_options_and_choosing_one_gets_a_proposal(page, app):
    path = app.note(NOTE)
    page.open_note(path)
    page.page.keyboard.press("Control+Enter")
    page.page.locator(".h-item.open").first.wait_for(timeout=15000)
    item = page.page.locator(".h-item.open").first
    item.locator('[data-act="chat"]').dispatch_event("click")
    page.page.wait_for_selector(".chat.open .chat-log > *", timeout=10000)
    log = page.page.locator(".chat-log")

    send(page, "bilmiyorum")
    page.page.wait_for_function("(t) => document.querySelector('.chat-log')?.textContent.includes(t)",
                                arg="Ortak bir klasör", timeout=15000)
    assert "Bir görev listesi" in log.inner_text()
    assert page.page.locator(".chat .msg.proposal").count() == 0         # nothing offered for the note yet

    send(page, "ilkini yapalım")
    card = page.page.locator('.chat .msg.proposal')
    card.locator('[data-act="approve"]').wait_for(timeout=15000)
    assert card.locator(".p-text").inner_text().startswith("Karar: Ortak bir klasör")
