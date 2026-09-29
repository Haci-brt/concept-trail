"""The chat drawer: a half-typed answer stays with the question it was typed
for, and a proposal left waiting is still there when the thread is reopened."""
import time

NOTE = "# Bitki sulama\n\nBitkilerimi sulamayı unutuyorum, bana hatırlatan bir şey istiyorum.\n"


def ask(page, app) -> tuple[str, list[str]]:
    """A note of its own, asked about at once: its path and the questions waiting."""
    path = app.note(NOTE)
    page.open_note(path)
    page.page.keyboard.press("Control+Enter")
    page.page.locator(".h-item.open").first.wait_for(timeout=15000)
    return path, page.page.eval_on_selector_all(".h-item.open", "els => els.map((e) => e.dataset.id)")


def open_chat(page, event_id: str) -> None:
    """The question's chat, opened from its card in the panel."""
    item = page.page.locator(f'.h-item[data-id="{event_id}"]')
    question = item.locator(".h-text").inner_text()
    # an open drawer lies over the panel; the click still goes to the card's button
    item.locator('[data-act="chat"]').dispatch_event("click")
    page.page.wait_for_function("(q) => document.querySelector('.chat.open .q')?.textContent === q",
                                arg=question, timeout=10000)
    page.page.wait_for_selector(".chat.open .chat-log > *", timeout=10000)


def answer_in_chat(page, text: str) -> None:
    page.page.locator(".chat textarea").fill(text)
    page.page.locator(".chat textarea").press("Enter")
    page.page.locator('.chat .msg.proposal [data-act="approve"]').wait_for(timeout=15000)


def close_chat(page) -> None:
    page.page.locator('.chat [data-act="close"]').click()


def test_a_half_typed_answer_stays_with_its_own_question(page, app):
    _, (first, second, *_) = ask(page, app)
    box = page.page.locator(".chat textarea")
    open_chat(page, first)
    box.fill("Yarım kalan cevabım")

    open_chat(page, second)                                             # switched while open
    assert box.input_value() == ""
    box.fill("Başka bir taslak")

    open_chat(page, first)
    assert box.input_value() == "Yarım kalan cevabım"
    close_chat(page)
    open_chat(page, second)                                             # closed in between
    assert box.input_value() == "Başka bir taslak"


def test_a_waiting_proposal_is_there_when_the_chat_is_reopened(page, app):
    path, (first, second, *_) = ask(page, app)
    answer = "Bunu evde yalnız ben kullanacağım"
    open_chat(page, first)
    answer_in_chat(page, answer)
    close_chat(page)                                                    # left without deciding

    open_chat(page, first)
    order = page.page.eval_on_selector_all(".chat-log > .msg", "els => els.map((e) => e.classList[1])")
    assert order == ["user", "assistant", "proposal"]
    card = page.page.locator(".chat .msg.proposal")
    assert answer in card.locator(".p-text").inner_text()
    assert "done" not in card.get_attribute("class")
    card.locator('[data-act="approve"]').click()
    page.page.wait_for_function("document.querySelector('.chat .msg.proposal.done')", timeout=10000)
    assert card.locator(".p-actions").inner_text() == "Nota eklendi."
    deadline = time.monotonic() + 15
    while answer not in app.api.get("/api/notes", params={"path": path}).json()["content"]:
        assert time.monotonic() < deadline, "onaylanan metin nota girmedi"
        time.sleep(0.3)
    close_chat(page)

    # one turned down comes back as it was left, with nothing left to click
    open_chat(page, second)
    answer_in_chat(page, "Telefonda çalışan bir uygulama olacak")
    page.page.locator('.chat .msg.proposal [data-act="reject"]').click()
    page.page.wait_for_function("document.querySelector('.chat .msg.proposal.dropped')", timeout=10000)
    close_chat(page)
    open_chat(page, second)
    card = page.page.locator(".chat .msg.proposal")
    assert "dropped" in card.get_attribute("class") and card.locator("button").count() == 0
    assert card.locator(".p-actions").inner_text() == "Nota eklenmedi."
    assert "Telefonda çalışan" not in app.api.get("/api/notes", params={"path": path}).json()["content"]
