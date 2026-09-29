"""An approved write-up lands in the note whatever the page is showing.

Seen by the writer: in the idea tree, with the chat box focused, approving a
proposal typed its text into the chat box — the editor hidden behind the tree
could not take focus, and the insert went to whatever had it."""
import json
import time


def a_proposal(app, rel, content):
    app.api.post("/api/assistant/analyze", json={"path": rel, "content": content, "force": True})
    for _ in range(60):
        nodes = app.api.get("/api/assistant/nodes", params={"path": rel}).json()["nodes"]
        waiting = [n for n in nodes if n["type"] == "question" and n["status"] == "open"]
        if waiting:
            break
        time.sleep(0.3)
    with app.api.stream("POST", "/api/assistant/chat", json={
            "path": rel, "node_id": waiting[0]["id"], "message": "Ailem de kullanacak, dört kişiyiz"}) as reply:
        for line in reply.iter_lines():
            if line.strip() and json.loads(line)["type"] == "done":
                return json.loads(line)["proposal"]


def test_approving_in_the_idea_tree_writes_the_note_not_the_chat_box(page, app):
    content = "# İki araç\n\nİki yapay zeka aracını aynı projede çalıştırmak istiyorum."
    rel = app.note(content)
    page.open_note(rel)
    page.page.locator('[title^="Fikir ağacı"]').first.click()
    page.page.wait_for_timeout(300)
    proposal = a_proposal(app, rel, content)
    page.page.evaluate("document.querySelector('.chat textarea').focus()")

    app.api.post("/api/assistant/hud", json={"event_id": proposal["id"], "action": "approve"})
    page.page.wait_for_function(
        "(t) => [...document.querySelectorAll('.md-input')].some((e) => e.value.includes(t))",
        arg=proposal["text"], timeout=10000)
    assert page.page.evaluate("document.querySelector('.chat textarea').value") == ""
    deadline = time.monotonic() + 10
    while proposal["text"] not in app.api.get("/api/notes", params={"path": rel}).json()["content"]:
        assert time.monotonic() < deadline, "not diske yazılmadı"
        time.sleep(0.2)
