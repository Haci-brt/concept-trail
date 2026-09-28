"""A dropped connection or a busy provider is tried again; a wrong key is not."""
import pytest
import requests

from core import llm_client
from server.providers import Provider

REMOTE = Provider(id="or", label="OpenRouter", base_url="https://openrouter.ai/api", model="m", api_key="k",
                  kind="remote", health="models")
LOCAL = Provider(id="local", label="Yerel", base_url="http://127.0.0.1:8899", kind="local", health="llama")


class Reply:
    def __init__(self, status=200, content="tamam", headers=None):
        self.status_code, self.ok, self.headers = status, status < 400, headers or {}
        self.text = ""
        self._content = content

    def json(self):
        if not self.ok:
            return {"error": {"message": "sınır"}}
        return {"choices": [{"message": {"content": self._content}}], "usage": {}}


@pytest.fixture
def calls(monkeypatch):
    log = {"posts": [], "waits": [], "plan": []}

    def post(url, **kwargs):
        log["posts"].append(url)
        step = log["plan"].pop(0) if log["plan"] else Reply()
        if isinstance(step, Exception):
            raise step
        return step

    monkeypatch.setattr(llm_client.requests, "post", post)
    monkeypatch.setattr(llm_client.time, "sleep", lambda s: log["waits"].append(s))
    return log


def ask(provider):
    return llm_client._complete([{"role": "user", "content": "x"}], temperature=0, max_tokens=5, provider=provider)


def test_a_reset_connection_is_tried_again(calls):
    """Measured: ("Connection aborted.", ConnectionResetError) ended a whole research."""
    calls["plan"] = [requests.ConnectionError("Connection aborted."), requests.ConnectionError("again")]
    assert ask(REMOTE) == "tamam"
    assert len(calls["posts"]) == 3 and calls["waits"] == list(llm_client.RETRY_WAITS)


def test_a_busy_provider_is_waited_for_as_long_as_it_says(calls):
    calls["plan"] = [Reply(429, headers={"retry-after": "12"})]
    assert ask(REMOTE) == "tamam" and calls["waits"] == [12.0]
    calls["plan"], calls["waits"] = [Reply(503, headers={"retry-after": "600"})], []
    assert ask(REMOTE) == "tamam" and calls["waits"] == [llm_client.MAX_RETRY_AFTER]


def test_a_wrong_key_fails_at_once(calls):
    calls["plan"] = [Reply(401)]
    with pytest.raises(llm_client.ProviderError):
        ask(REMOTE)
    assert len(calls["posts"]) == 1 and calls["waits"] == []


def test_a_local_server_that_is_down_is_not_waited_on(calls):
    calls["plan"] = [requests.ConnectionError("refused")]
    with pytest.raises(requests.ConnectionError):
        ask(LOCAL)
    assert calls["waits"] == []


def test_it_gives_up_after_the_last_try(calls):
    calls["plan"] = [requests.Timeout()] * 3
    with pytest.raises(requests.Timeout):
        ask(REMOTE)
    assert len(calls["posts"]) == 3


def test_an_answer_already_shown_is_not_asked_again(monkeypatch, calls):
    def once(messages, **kwargs):
        kwargs["on_chunk"]("yarım cev")
        raise requests.exceptions.ChunkedEncodingError("kesildi")
    monkeypatch.setattr(llm_client, "_complete_once", once)
    with pytest.raises(requests.exceptions.ChunkedEncodingError):
        llm_client._complete([], temperature=0, max_tokens=5, provider=REMOTE, on_chunk=lambda t: None)
    assert calls["waits"] == []
