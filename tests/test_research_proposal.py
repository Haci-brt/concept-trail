"""Selected research findings enter the note only as an approval proposal."""

import pytest

from server.app import ResearchChoice, _research_proposal_text
from server.errors import ApiError


def result():
    return {
        "status": "done",
        "candidates": [{"repo": "org/related", "description": "Benzer bir not ağı.",
                        "url": "https://github.com/org/related"}],
        "tools": [{"id": "org/tool", "name": "org/tool",
                   "why": "Soru dallarını görselleştirmek için kullanılabilir.",
                   "source_urls": ["https://github.com/org/tool"]}],
        "opportunities": [{"id": "opp-123", "title": "Dal bağlamı",
                           "detail": "İlişkili sorulara önceki cevapları aktar.",
                           "source_urls": ["https://example.org/evidence"]}],
        "sources": [{"url": "https://example.org/guide", "title": "Teknik kılavuz",
                     "excerpt": "Uygulama için doğrulanmış yöntem.", "verified": True},
                    {"url": "https://example.org/unread", "title": "Okunmayan sayfa",
                     "snippet": "Arama özeti.", "verified": False}],
    }


def test_selected_findings_include_traceable_sources():
    text = _research_proposal_text(result(), [
        ResearchChoice(type="tool", id="org/tool"),
        ResearchChoice(type="opportunity", id="opp-123"),
    ])
    assert "org/tool" in text and "Dal bağlamı" in text
    assert "https://github.com/org/tool" in text
    assert "https://example.org/evidence" in text


def test_client_cannot_inject_unsaved_research_into_proposal():
    with pytest.raises(ApiError) as exc:
        _research_proposal_text(result(), [ResearchChoice(type="tool", id="uydurma")])
    assert exc.value.status == 404


def test_project_and_read_web_page_can_be_proposed_with_sources():
    text = _research_proposal_text(result(), [
        ResearchChoice(type="project", id="org/related"),
        ResearchChoice(type="source", id="https://example.org/guide"),
    ])
    assert "Benzer proje: org/related" in text
    assert "Okunan kaynak: Teknik kılavuz" in text
    assert "https://github.com/org/related" in text
    assert "https://example.org/guide" in text


def test_unread_web_result_cannot_be_added_as_read_evidence():
    with pytest.raises(ApiError) as exc:
        _research_proposal_text(result(), [ResearchChoice(type="source", id="https://example.org/unread")])
    assert exc.value.status == 404


def test_page_excerpt_stays_one_readable_markdown_item():
    report = result()
    report["sources"][0]["excerpt"] = "# Başlık\n\n<em>Gerçek yöntem</em> ve ikinci satır."
    text = _research_proposal_text(report, [ResearchChoice(type="source", id="https://example.org/guide")])
    assert "# Başlık Gerçek yöntem ve ikinci satır." in text
    assert "<em>" not in text
    assert len([row for row in text.splitlines() if row.startswith("- ")]) == 1


def test_only_finished_research_can_be_proposed():
    with pytest.raises(ApiError) as exc:
        _research_proposal_text({"status": "running"}, [ResearchChoice(type="tool", id="org/tool")])
    assert exc.value.status == 409


def test_proposal_does_not_write_note_until_approval(tmp_path):
    from server.assistant import Assistant
    from server.store import HistoryStore, NoteStore
    from server.vault import Vault

    class Broker:
        def __init__(self):
            self.events = []

        def publish(self, kind, data):
            self.events.append((kind, data))

    vault = Vault(tmp_path / "vault")
    path = vault.create_note("", "Fikir", "Benim fikrim.\n")
    broker = Broker()
    assistant = Assistant(vault, NoteStore(vault), HistoryStore(vault), broker, providers=object())
    text = _research_proposal_text(result(), [ResearchChoice(type="tool", id="org/tool")])
    proposal = assistant.propose_text(path, text)["proposal"]

    assert vault.read_note(path)["content"] == "Benim fikrim.\n"
    assert proposal["status"] == "pending"
    assert not any(kind == "append_note" for kind, _ in broker.events)

    assistant.hud_action(proposal["id"], "reject")
    assert vault.read_note(path)["content"] == "Benim fikrim.\n"
    assert not any(kind == "append_note" for kind, _ in broker.events)
