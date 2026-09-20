"""Reading a page: the address guard, the tiers, and what the model gets back.

Nothing here touches the network. The tier order and the size cap were chosen
from measurements on this machine — raw source 0.8s, plain HTTP 2.7s, a real
browser 4.2s, and a single docs page running to 75,000 characters — and the
tests below pin the parts that protect the app rather than the timings.
"""
import pytest

from server.errors import ApiError
from server.fetch import MAX_CHARS, extract, source_form, trim, validate_public_url


# ---------------------------------------------------------------- the guard
@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8765/api/state",       # this app's own API
    "http://localhost/admin",
    "http://192.168.1.1/",
    "http://10.0.0.5/",
    "http://169.254.169.254/latest/meta-data/",   # cloud metadata
    "http://[::1]/",
    "file:///etc/passwd",
    "ftp://example.com/x",
    "http://user:secret@example.com/",
    "",
])
def test_an_address_that_is_not_public_is_refused(url):
    """The model picks this URL and its input is untrusted page text, so a
    fetched page must never be able to aim the fetcher at the local machine."""
    with pytest.raises(ApiError):
        validate_public_url(url, resolve=False)


def test_a_public_address_passes():
    assert validate_public_url("https://example.com/a?b=1", resolve=False).startswith("https://")


def test_a_name_that_resolves_to_a_private_address_is_refused(monkeypatch):
    """Blocking literals is not enough: a hostname can point anywhere."""
    import server.fetch as fetch
    monkeypatch.setattr(fetch.socket, "getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 80))])
    with pytest.raises(ApiError):
        validate_public_url("http://kotu.example.com/", resolve=True)


# ---------------------------------------------------------------- source form
def test_a_github_file_is_read_from_its_raw_source():
    """A file view is 400 KB of HTML around a text file that is also served
    raw; git_read_file cut the same README off at 12,000 characters."""
    assert source_form("https://github.com/microsoft/playwright-mcp/blob/main/README.md") == \
        "https://raw.githubusercontent.com/microsoft/playwright-mcp/main/README.md"


def test_a_repository_root_tries_its_readme():
    assert source_form("https://github.com/ggml-org/llama.cpp") == \
        "https://raw.githubusercontent.com/ggml-org/llama.cpp/HEAD/README.md"


@pytest.mark.parametrize("url", ["https://example.com/a",
                                 "https://github.com/topics/mcp",
                                 "https://gist.github.com/o/abc"])
def test_anything_else_has_no_source_form(url):
    assert source_form(url) is None


# ---------------------------------------------------------------- trimming
def test_a_short_page_is_left_alone():
    assert trim("kisa metin", None, 100) == ("kisa metin", False)


def test_a_long_page_is_cut_and_says_so():
    text, truncated = trim("a" * 5000, None, 100)
    assert truncated is True and len(text) == 100


def test_the_kept_window_is_the_one_that_answers_the_question():
    """Cutting from the top throws away the answer when it is halfway down."""
    page = "giris " * 400 + " HEDEF KELIME burada anlatiliyor " + "son " * 400
    text, truncated = trim(page, "hedef kelime", 200)
    assert truncated is True and "HEDEF KELIME" in text


def test_without_a_query_the_start_of_the_page_is_kept():
    text, _ = trim("bas " + "x" * 5000, None, 50)
    assert text.startswith("bas")


def test_the_default_cap_is_what_a_model_can_actually_use():
    assert 2000 <= MAX_CHARS <= 20000


# ---------------------------------------------------------------- extraction
def test_headings_survive_extraction():
    html = "<html><body><article><h1>Baslik</h1><p>Bir paragraf metni burada duruyor.</p>" \
           "<script>kotu()</script></article></body></html>"
    text = extract(html, "https://example.com/a")
    assert "Baslik" in text and "Bir paragraf" in text and "kotu()" not in text


def test_nothing_readable_is_empty_not_a_crash():
    assert extract("", "https://example.com") == ""
