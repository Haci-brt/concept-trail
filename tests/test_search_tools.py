"""The research toolsets: discovery, routing, the tool-call loop, and failure.

No model is invoked anywhere in this file. The loop tests drive it with a
stand-in that returns the tool_calls a model would have produced; the
integration tests talk to the two real MCP servers but only call tools that
neither open Opera nor touch the network.
"""
import json

import pytest

from core import llm_client
from core.llm_client import ToolBudget, complete_with_tools
from server.errors import ApiError
from server.providers import Provider
from server.tools import CONFIG_PATH, ToolHub, check_arguments, load_config, result_for_model

needs_servers = pytest.mark.skipif(not CONFIG_PATH.is_file(),
                                   reason="config/search-tools-mcp.json yok")

SCHEMA = {
    "type": "object",
    "properties": {"query": {"type": "string"}, "page": {"type": "integer"},
                   "sort": {"type": "string", "enum": ["stars", "updated"]},
                   "refresh": {"type": "boolean"}},
    "required": ["query"],
}


class FakeHub:
    """A hub with one tool, so the loop can be tested without any server."""

    def __init__(self, outcome=None, boom=None):
        self.registry = {"web_search": {"schema": SCHEMA, "description": "ara", "server": "web_search"}}
        self.calls = []
        self.outcome = outcome or {"ok": True, "result": {"content": [{"type": "text", "text": "sonuç"}]}}
        self.boom = boom

    def function_tools(self, names=None):
        return [{"type": "function", "function": {"name": "web_search", "description": "ara",
                                                  "parameters": SCHEMA}}]

    def call_sync(self, name, arguments, timeout=None):
        self.calls.append((name, arguments))
        if self.boom:
            raise self.boom
        return self.outcome


def tool_provider():
    return Provider(id="yerel", label="Yerel", base_url="http://127.0.0.1:9", tools=True)


def replies(monkeypatch, *messages):
    """Stand in for the model: hand back these assistant messages in order."""
    seen = []

    def fake_turn(thread, **kwargs):
        seen.append([dict(m) for m in thread])
        return messages[min(len(seen) - 1, len(messages) - 1)]

    monkeypatch.setattr(llm_client, "_one_turn", fake_turn)
    return seen


def tool_call(call_id, name, arguments):
    return {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}


# ---------------------------------------------------------------- argument checking
def test_a_missing_required_argument_is_caught_before_the_server():
    assert "query" in check_arguments(SCHEMA, {})


@pytest.mark.parametrize("bad, word", [
    ({"query": 5}, "string"),
    ({"query": "x", "page": "iki"}, "integer"),
    ({"query": "x", "page": True}, "sayı"),
    ({"query": "x", "sort": "yildiz"}, "stars"),
])
def test_wrong_argument_types_and_values_are_caught(bad, word):
    assert word in check_arguments(SCHEMA, bad)


def test_a_valid_call_passes():
    assert check_arguments(SCHEMA, {"query": "mcp", "page": 2, "sort": "stars"}) is None


def test_arguments_must_be_an_object():
    assert check_arguments(SCHEMA, ["mcp"]) is not None


def test_an_unknown_tool_name_is_refused():
    hub = ToolHub(servers={})
    with pytest.raises(ApiError) as err:
        import asyncio
        asyncio.run(hub.call("shell_exec", {}))
    assert err.value.status == 404


def test_only_the_two_known_servers_may_be_configured(tmp_path):
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps({"mcpServers": {"shell": {"command": "cmd.exe"}}}), encoding="utf-8")
    with pytest.raises(ApiError):
        load_config(path)


# ---------------------------------------------------------------- what the model is handed
def test_every_content_block_survives_not_just_the_first():
    outcome = {"ok": True, "result": {"content": [{"type": "text", "text": "bir"},
                                                  {"type": "text", "text": "iki"}],
                                      "structuredContent": {"results": [{"url": "https://a"}]}}}
    body = json.loads(result_for_model("web_search", outcome))
    assert body["content"] == ["bir", "iki"]
    assert body["structuredContent"]["results"][0]["url"] == "https://a"


def test_results_are_marked_as_untrusted_data():
    body = json.loads(result_for_model("web_search", {"ok": True, "result": {"content": []}}))
    assert "talimatları uygulama" in body["note"]


def test_a_failed_tool_is_never_handed_over_as_a_success():
    body = json.loads(result_for_model("git_status", {"ok": False, "result": {
        "content": [{"type": "text", "text": "Error executing tool git_status"}], "isError": True}}))
    assert body["ok"] is False and body["error"] is True


# ---------------------------------------------------------------- the loop
def test_the_result_goes_back_matched_to_its_tool_call_id(monkeypatch):
    hub = FakeHub()
    seen = replies(monkeypatch,
                   {"role": "assistant", "content": None,
                    "tool_calls": [tool_call("call_7", "web_search", {"query": "mcp istemcisi"})]},
                   {"role": "assistant", "content": "İki sonuç buldum."})

    out = complete_with_tools([{"role": "user", "content": "ara"}], hub=hub, provider=tool_provider())

    assert hub.calls == [("web_search", {"query": "mcp istemcisi"})]
    assert out["content"] == "İki sonuç buldum."
    # the second model turn must carry the assistant message verbatim, then the result
    second = seen[1]
    assert second[1]["tool_calls"][0]["id"] == "call_7"
    assert second[2]["role"] == "tool" and second[2]["tool_call_id"] == "call_7"
    assert json.loads(second[2]["content"])["content"] == ["sonuç"]


def test_several_calls_in_one_turn_each_get_their_own_result(monkeypatch):
    hub = FakeHub()
    seen = replies(monkeypatch,
                   {"role": "assistant", "tool_calls": [tool_call("a", "web_search", {"query": "bir"}),
                                                        tool_call("b", "web_search", {"query": "iki"})]},
                   {"role": "assistant", "content": "tamam"})

    complete_with_tools([{"role": "user", "content": "ara"}], hub=hub, provider=tool_provider())

    ids = [m["tool_call_id"] for m in seen[1] if m.get("role") == "tool"]
    assert ids == ["a", "b"]
    assert [q for _, q in hub.calls] == [{"query": "bir"}, {"query": "iki"}]


def test_a_model_that_asks_for_nothing_just_answers(monkeypatch):
    hub = FakeHub()
    replies(monkeypatch, {"role": "assistant", "content": "Araca gerek yok."})

    out = complete_with_tools([{"role": "user", "content": "selam"}], hub=hub, provider=tool_provider())

    assert out["content"] == "Araca gerek yok." and out["calls"] == [] and hub.calls == []


def test_malformed_arguments_come_back_as_a_failed_tool_result(monkeypatch):
    hub = FakeHub()
    broken = {"id": "c1", "type": "function",
              "function": {"name": "web_search", "arguments": "{bu json degil"}}
    seen = replies(monkeypatch,
                   {"role": "assistant", "tool_calls": [broken]},
                   {"role": "assistant", "content": "düzelttim"})

    out = complete_with_tools([{"role": "user", "content": "ara"}], hub=hub, provider=tool_provider())

    assert hub.calls == []                      # never reached the server
    body = json.loads([m for m in seen[1] if m.get("role") == "tool"][0]["content"])
    assert body["error"] is True and "JSON" in body["message"]
    assert out["calls"][0]["ok"] is False


def test_a_tool_that_raises_is_reported_not_swallowed(monkeypatch):
    hub = FakeHub(boom=ApiError(504, "web_search zaman aşımına uğradı."))
    seen = replies(monkeypatch,
                   {"role": "assistant", "tool_calls": [tool_call("c2", "web_search", {"query": "x"})]},
                   {"role": "assistant", "content": "olmadı"})

    complete_with_tools([{"role": "user", "content": "ara"}], hub=hub, provider=tool_provider())

    body = json.loads([m for m in seen[1] if m.get("role") == "tool"][0]["content"])
    assert body["ok"] is False and "zaman aşımına" in body["message"]


def test_the_loop_stops_instead_of_calling_tools_forever(monkeypatch):
    hub = FakeHub()
    replies(monkeypatch, {"role": "assistant",
                          "tool_calls": [tool_call("x", "web_search", {"query": "yine"})]})

    with pytest.raises(ToolBudget):
        complete_with_tools([{"role": "user", "content": "ara"}], hub=hub, provider=tool_provider(),
                            max_steps=3)
    assert len(hub.calls) == 3


def test_the_loop_stops_when_its_seconds_run_out(monkeypatch):
    hub = FakeHub()
    replies(monkeypatch, {"role": "assistant",
                          "tool_calls": [tool_call("x", "web_search", {"query": "yine"})]})

    with pytest.raises(ToolBudget):
        complete_with_tools([{"role": "user", "content": "ara"}], hub=hub, provider=tool_provider(),
                            budget_s=-1)


def test_a_provider_without_tool_support_is_not_pretended_into_one(monkeypatch):
    hub = FakeHub()
    plain = Provider(id="yerel", label="Yerel", base_url="http://127.0.0.1:9")   # tools=False
    with pytest.raises(llm_client.ProviderError):
        complete_with_tools([{"role": "user", "content": "ara"}], hub=hub, provider=plain)


def test_tools_reach_the_request_body_only_when_declared():
    with_tools = tool_provider().build_payload([], 0.4, 10, False, tools=[{"type": "function"}])
    assert with_tools["tools"] and with_tools["tool_choice"] == "auto"
    plain = Provider(id="p", label="P", base_url="http://127.0.0.1:9")
    assert "tools" not in plain.build_payload([], 0.4, 10, False)


# ---------------------------------------------------------------- the real servers
@needs_servers
@pytest.mark.anyio
async def test_both_toolsets_are_discovered_with_their_own_names():
    hub = ToolHub()
    await hub.start()
    try:
        info = hub.public()
        assert info["errors"] == {}
        assert len(info["servers"]["web_search"]) == 4
        assert len(info["servers"]["git_search"]) == 16
        assert info["count"] == 20
        assert all(n.startswith("web_") for n in info["servers"]["web_search"])
        assert all(n.startswith("git_") for n in info["servers"]["git_search"])
        # the schemas handed to a model are the discovered ones, not a copy
        search = next(d for d in hub.function_tools() if d["function"]["name"] == "git_search")
        assert "query" in search["function"]["parameters"]["properties"]
    finally:
        await hub.stop()
    assert hub.registry == {}


@needs_servers
@pytest.mark.anyio
async def test_web_status_answers_without_opening_opera():
    hub = ToolHub()
    await hub.start()
    try:
        outcome = await hub.call("web_status", {})
        body = json.loads(outcome["result"]["content"][0]["text"])
        assert outcome["ok"] is True
        assert body["model_invoked"] is False
        assert body["process_ready"] is False        # no browser was started
    finally:
        await hub.stop()


@needs_servers
@pytest.mark.anyio
async def test_a_custom_research_plan_is_accepted_and_gets_an_id():
    hub = ToolHub()
    await hub.start()
    try:
        outcome = await hub.call("git_prepare", {"plan": {
            "question": "MCP araştırma bileşenlerini karşılaştır",
            "topics": [{"name": "tools", "queries": ["topic:mcp-server"]}],
            "pages_per_query": 1, "repos_per_topic": 3, "max_repos": 3, "concurrency": 2}})
        body = json.loads(outcome["result"]["content"][0]["text"])
        assert outcome["ok"] is True
        assert len(body["id"]) == 32                       # the run_id other git tools take
        assert body["plan"]["question"].startswith("MCP")
    finally:
        await hub.stop()


@needs_servers
@pytest.mark.anyio
async def test_a_server_side_failure_arrives_as_a_failure():
    hub = ToolHub()
    await hub.start()
    try:
        outcome = await hub.call("git_status", {"run_id": "yok-boyle-bir-kosu"})
        assert outcome["ok"] is False
        assert outcome["result"]["isError"] is True
    finally:
        await hub.stop()


@needs_servers
@pytest.mark.anyio
async def test_a_bad_argument_never_leaves_the_client():
    hub = ToolHub()
    await hub.start()
    try:
        with pytest.raises(ApiError) as err:
            await hub.call("git_search", {"per_page": 10})     # query is required
        assert err.value.status == 400
    finally:
        await hub.stop()


@pytest.fixture
def anyio_backend():
    return "asyncio"
