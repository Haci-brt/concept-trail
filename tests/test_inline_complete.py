"""The rest of the line while writing: what the model's words become, which
model does it, and a feature that stays quiet when it cannot help."""
import pytest
from fastapi.testclient import TestClient

from core import llm_client
from core.llm_client import clean_completion
from server.providers import ROLE_FALLBACK, ROLES, ProviderRegistry


@pytest.mark.parametrize("raw,before,after,want", [
    # it writes the words before the cursor out again and finishes them
    ("Herkes okuduğu kitabı rafa bırakır.", "Herkes okuduğu kitabı", "", " rafa bırakır."),
    ("It must work smoothly and accurately.", "# Notes\nIt must work", "", " smoothly and accurately."),
    ("Kitaplar rafa konur", "Kitap", "", "lar rafa konur"),                                 # mid-word goes on
    ("Harcamayı kimin yaptığı", "- Harcamayı kimin", "", " yaptığı"),                      # left out the "- "
    ("Herkes  okuduğu kitabı rafa", "Herkes okuduğu kitabı", "", " rafa"),                 # its own spacing
    # or only the continuation after all
    (" rafa bırakır, istediğini alır.", "Herkes okuduğu kitabı", "", " rafa bırakır, istediğini alır."),
    ("smoothly", "It must work", "", " smoothly"),                                         # a word needs a space
    ("...önceki kitaplar", "kitabı ", "", "önceki kitaplar"),                              # no filler
    (" rafa bırakır. Sonra eve gider.", "kitabı", "", " rafa bırakır."),                   # one sentence
    ('"rafa bırakır"', "Herkes okuduğu kitabı ", "", "rafa bırakır"),                      # quotes off
    (" rafa bırakır.\nİkinci satır", "kitabı", "", " rafa bırakır."),                      # one line only
    ("<cursor/> rafa koyar", "kitabı", "", " rafa koyar"),                                 # the prompt's tags
    ("\n rafa koyar", "kitabı", "", " rafa koyar"),
    ("   rafa", "kitabı ", "", "rafa"),                                                    # no double space
    (" rafa", "kitabı", " rafa bırakır", ""),                                              # already written
    ("...", "kitabı", "", ""),
    ("", "kitabı", "", ""),
])
def test_what_the_model_wrote_becomes_the_rest_of_the_line(raw, before, after, want):
    assert clean_completion(raw, before, after) == want


def test_a_long_answer_is_cut_at_a_word():
    text = clean_completion(" " + "kelime " * 60, "Bir", "")
    assert len(text) <= llm_client.INLINE_MAX_CHARS and text.endswith("kelime")


def test_one_short_call_that_is_never_retried(monkeypatch):
    seen = {}

    def once(messages, **kwargs):
        seen.update(messages=messages, **kwargs)
        return " rafa koyar"

    monkeypatch.setattr(llm_client, "_complete_once", once)
    monkeypatch.setattr(llm_client, "_complete", lambda *a, **k: pytest.fail("retried path used"))
    assert llm_client.inline_completion("Herkes kitabı", "", provider=object()) == " rafa koyar"
    assert seen["max_tokens"] == llm_client.INLINE_MAX_TOKENS and seen["timeout"] == llm_client.INLINE_TIMEOUT_S
    user = seen["messages"][1]["content"]
    assert user == "<before>Herkes kitabı</before><cursor/><after></after>\n\nWords before the cursor: Herkes kitabı"
    assert "never translate" in seen["messages"][0]["content"]


def test_a_long_line_is_written_out_again_only_from_its_last_sentence():
    line = "Bu uygulama " + "çok uzun bir paragrafın ortasında " * 6 + "duruyor. Son cümle burada"
    assert llm_client.words_before_cursor("# Başlık\n" + line) == "Son cümle burada"
    assert llm_client.words_before_cursor("# Başlık\nKısa satır") == "Kısa satır"


def test_until_a_model_is_chosen_it_runs_on_the_note_watch_model(tmp_path):
    assert "complete" in ROLES and ROLE_FALLBACK["complete"] == "analysis"
    registry = ProviderRegistry(path=tmp_path / "providers.json")
    assert [p.id for p in registry.chain("complete")] == [p.id for p in registry.chain("analysis")]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FIKIR_CONFIG_DIR", str(tmp_path / "config"))
    from server.app import create_app
    from server.settings import Settings
    return TestClient(create_app(Settings(vault=tmp_path / "vault", port=8765)), base_url="http://127.0.0.1:8765",
                      headers={"X-Fikir": "1"})


def test_the_endpoint_answers_with_the_rest_or_with_nothing(client, monkeypatch):
    monkeypatch.setattr(llm_client, "inline_completion", lambda before, after, provider, on_usage: " rafa koyar")
    assert client.post("/api/complete", json={"path": "a.md", "before": "kitabı", "after": ""}).json() == \
        {"text": " rafa koyar"}

    def down(*args, **kwargs):
        raise llm_client.ProviderError("Model ya da adres bulunamadı.", status=404)

    monkeypatch.setattr(llm_client, "inline_completion", down)
    reply = client.post("/api/complete", json={"path": "a.md", "before": "kitabı"})
    assert reply.status_code == 200 and reply.json() == {"text": ""}        # quiet, never an error
