"""The research toolsets: discovery, routing, the tool-call loop, and failure.

No model is invoked anywhere in this file. The loop tests drive it with a
stand-in that returns the tool_calls a model would have produced; the
integration tests talk to the two real MCP servers but only call tools that
neither open Opera nor touch the network.
"""
import json
import tempfile
from pathlib import Path

import pytest

from core import llm_client
from core.llm_client import ToolBudget, complete_with_tools
from server.errors import ApiError
from server.providers import KEY_MASK, Provider
from server.tools import (CONFIG_PATH, ToolHub, ToolSettings, check_arguments, check_bounds,
                          expand, load_config, result_for_model)


def isolated_settings() -> ToolSettings:
    """Never read or write the real config folder from a test."""
    return ToolSettings(path=Path(tempfile.mkdtemp()) / "tool-settings.json")


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
    hub = ToolHub(servers={}, settings=isolated_settings())
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


# ---------------------------------------------------------------- the built-in tools
# The two llm-stack MCP servers are now part of this app (server/github.py,
# server/websearch.py). Starting the hub starts nothing: no process, no Opera.
BUILTIN_TOOLS = ["git_issues", "git_readme", "git_repo", "git_search", "git_topics", "web_fetch", "web_search"]


@pytest.mark.anyio
async def test_the_research_tools_are_the_apps_own():
    hub = ToolHub(servers={}, settings=isolated_settings())
    await hub.start()
    try:
        info = hub.public()
        assert info["errors"] == {} and info["servers"] == {"builtin": BUILTIN_TOOLS}
        search = next(d for d in hub.function_tools() if d["function"]["name"] == "git_search")
        assert "query" in search["function"]["parameters"]["properties"]
        assert hub.web.status()["running"] is False             # no browser was started
    finally:
        await hub.stop()
    assert hub.registry == {}


@pytest.mark.anyio
async def test_a_failing_tool_arrives_as_a_failure(monkeypatch):
    hub = ToolHub(servers={}, settings=isolated_settings())
    await hub.start()
    try:
        def gone(repo):
            raise ApiError(404, "GitHub'da bulunamadı.")
        hub.registry["git_repo"]["handler"] = gone
        outcome = await hub.call("git_repo", {"repo": "yok/boyle"})
        assert outcome["ok"] is False and outcome["result"]["isError"] is True
    finally:
        await hub.stop()


@pytest.mark.anyio
async def test_a_bad_argument_never_leaves_the_client():
    hub = ToolHub(servers={}, settings=isolated_settings())
    await hub.start()
    try:
        with pytest.raises(ApiError) as err:
            await hub.call("git_search", {"per_page": 10})     # query is required
        assert err.value.status == 400
        with pytest.raises(ApiError):
            await hub.call("git_repo", {"repo": "../etc"})       # not owner/name
    finally:
        await hub.stop()


@pytest.mark.anyio
async def test_the_built_in_tools_publish_their_limits():
    hub = ToolHub(servers={}, settings=isolated_settings())
    await hub.start()
    try:
        search = hub.registry["git_search"]["schema"]["properties"]
        assert search["per_page"]["maximum"] == 100      # GitHub's own ceiling
        assert search["page"]["maximum"] == 10           # the 1000-result window
        assert search["query"]["maxLength"] == 256
        assert set(search["sort"]["enum"]) == {"stars", "updated", "best-match"}
        assert hub.registry["web_search"]["schema"]["properties"]["query"]["maxLength"] == 500
        assert len(hub.function_tools()) == len(BUILTIN_TOOLS)
    finally:
        await hub.stop()


@pytest.mark.anyio
async def test_a_configured_server_does_not_replace_the_apps_tools():
    hub = ToolHub(servers={}, settings=isolated_settings())
    hub.registry["git_search"] = {"session": object(), "server": "git_search", "description": "eski",
                                  "schema": {}, "handler": None}
    await hub.start()
    try:
        assert hub.registry["git_search"]["server"] == "builtin"
    finally:
        await hub.stop()


# ---------------------------------------------------------------- the bounds
# tools/list hands over types but not limits; the servers publish the limits
# separately and refuse anything outside them with a bare "Error executing
# tool X" whose reason never crosses the wire. So they are enforced here.
BOUNDED = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "query": {"type": "string", "minLength": 1, "maxLength": 256},
        "page": {"type": "integer", "minimum": 1, "maximum": 10},
        "repo": {"type": "string", "pattern": r"^[\w.-]+/[\w.-]+$"},
        "ids": {"type": "array", "minItems": 1, "maxItems": 20},
        "refresh": {"type": "boolean"},
    },
    "required": ["query"],
}


@pytest.mark.parametrize("arguments, word", [
    ({"query": "a" * 257}, "256"),
    ({"query": ""}, "en az 1"),
    ({"query": "q", "page": 11}, "10"),
    ({"query": "q", "page": 0}, "en az 1"),
    ({"query": "q", "repo": "sadece-isim"}, "biçimde"),
    ({"query": "q", "ids": []}, "en az 1"),
    ({"query": "q", "ids": list(range(21))}, "20"),
])
def test_calls_outside_the_published_bounds_never_reach_the_server(arguments, word):
    problem = check_arguments(BOUNDED, arguments)
    assert problem and word in problem


@pytest.mark.parametrize("arguments", [
    {"query": "a" * 256},
    {"query": "q", "page": 10},
    {"query": "q", "page": 1},
    {"query": "q", "repo": "anthropics/claude-code"},
    {"query": "q", "ids": list(range(20))},
])
def test_calls_at_the_very_edge_of_the_bounds_are_allowed(arguments):
    assert check_arguments(BOUNDED, arguments) is None


def test_a_boolean_is_never_range_checked_as_a_number():
    """True is 1 in Python; a bool must not satisfy a numeric bound."""
    assert check_bounds("refresh", {"minimum": 5}, True) is None
    assert check_arguments(BOUNDED, {"query": "q", "refresh": True}) is None


def test_a_pattern_that_will_not_compile_is_left_to_the_server():
    assert check_bounds("repo", {"pattern": "([unclosed"}, "ne olursa olsun") is None


# ---------------------------------------------------------- refined schemas
class FakeBlock:
    def __init__(self, text):
        self.text = text


class FakeResult:
    def __init__(self, texts, is_error=False):
        self.content = [FakeBlock(t) for t in texts]
        self.is_error = is_error


class FakeSession:
    def __init__(self, result):
        self.result = result

    async def call_tool(self, name, arguments):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


BARE = {"type": "object", "properties": {"per_page": {"type": "integer"}}}


def published(name, maximum=100, description="yeni"):
    return json.dumps({"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": {
            "per_page": {"type": "integer", "minimum": 1, "maximum": maximum}}}}})


def a_hub(**extra):
    hub = ToolHub(servers={}, settings=isolated_settings())
    hub.registry = {
        "git_search": {"session": None, "server": "git_search", "description": "eski", "schema": dict(BARE)},
        "git_tool_schemas": {"session": None, "server": "git_search", "description": "", "schema": {}},
        **extra,
    }
    return hub


@pytest.mark.anyio
async def test_the_servers_own_bounds_replace_the_schema_it_listed():
    hub = a_hub()
    await hub._refine_schemas("git_search", FakeSession(FakeResult([published("git_search")])))
    assert hub.registry["git_search"]["schema"]["properties"]["per_page"]["maximum"] == 100
    assert hub.registry["git_search"]["description"] == "yeni"
    # which is the whole point: the limit is now enforced before the call goes out
    assert check_arguments(hub.registry["git_search"]["schema"], {"per_page": 200})


@pytest.mark.anyio
async def test_one_server_may_not_rewrite_anothers_tool():
    hub = a_hub(web_search={"session": None, "server": "web_search", "description": "d",
                            "schema": dict(BARE)})
    await hub._refine_schemas("git_search", FakeSession(FakeResult([published("web_search")])))
    assert hub.registry["web_search"]["schema"] == BARE


@pytest.mark.anyio
@pytest.mark.parametrize("result", [
    RuntimeError("sunucu cevap vermedi"),
    FakeResult([published("git_search")], is_error=True),
    FakeResult(["düz metin, JSON değil"]),
    FakeResult(["[1, 2, 3]"]),                       # valid JSON, not a definition
    FakeResult([json.dumps({"function": {"name": "git_search", "parameters": "nesne değil"}})]),
])
async def test_schemas_that_do_not_arrive_cost_only_the_bounds(result):
    """Startup must survive it: the plain schema still works, just unbounded."""
    hub = a_hub()
    await hub._refine_schemas("git_search", FakeSession(result))
    assert hub.registry["git_search"]["schema"] == BARE


def test_the_adapter_schema_tools_are_not_offered_to_the_model():
    """They exist for adapters like this one and were read at startup; handing
    them to the model only costs it a step to discover that."""
    hub = a_hub()
    offered = [d["function"]["name"] for d in hub.function_tools()]
    assert offered == ["git_search"]
    # unless asked for by name
    assert [d["function"]["name"] for d in hub.function_tools(["git_tool_schemas"])] == ["git_tool_schemas"]


# ------------------------------------------------------- portable configuration
def test_a_variable_is_expanded_so_one_config_fits_more_than_one_machine(monkeypatch):
    monkeypatch.setenv("FIKIR_TOOLS_ROOT", "E:/araclar")
    assert expand("${FIKIR_TOOLS_ROOT}/.venv/python.exe") == "E:/araclar/.venv/python.exe"


def test_the_default_is_used_when_the_variable_is_not_set(monkeypatch):
    monkeypatch.delenv("FIKIR_TOOLS_ROOT", raising=False)
    assert expand("${FIKIR_TOOLS_ROOT:-D:/varsayilan}/bin") == "D:/varsayilan/bin"


def test_a_variable_with_no_value_and_no_default_disappears(monkeypatch):
    monkeypatch.delenv("YOK_BOYLE_BIR_DEGISKEN", raising=False)
    assert expand("${YOK_BOYLE_BIR_DEGISKEN}/bin") == "/bin"


def test_expansion_reaches_the_command_the_arguments_and_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("FIKIR_TOOLS_ROOT", "E:/araclar")
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps({"mcpServers": {"git_search": {
        "command": "${FIKIR_TOOLS_ROOT}/python.exe",
        "args": ["--root", "${FIKIR_TOOLS_ROOT}/runtime"],
        "env": {"PYTHONPATH": "${FIKIR_TOOLS_ROOT}"}}}}), encoding="utf-8")
    server = load_config(path)["git_search"]
    assert server["command"] == "E:/araclar/python.exe"
    assert server["args"] == ["--root", "E:/araclar/runtime"]
    assert server["env"]["PYTHONPATH"] == "E:/araclar"


@pytest.mark.anyio
async def test_a_command_that_is_not_there_says_how_to_point_at_it():
    """The toolset living somewhere else must not surface as a raw WinError."""
    hub = ToolHub(servers={"git_search": {"command": "D:/yok/boyle/python.exe", "args": []}},
                  settings=isolated_settings())
    await hub.start()
    try:
        assert "FIKIR_TOOLS_ROOT" in hub.errors["git_search"]
        # the app still runs: its own research tools do not depend on a server
        assert sorted(hub.registry) == BUILTIN_TOOLS
    finally:
        await hub.stop()


# ------------------------------------------------------------- the GitHub token
@pytest.fixture
def secrets(tmp_path):
    return ToolSettings(path=tmp_path / "tool-settings.json")


def test_a_saved_token_is_never_handed_back_in_the_clear(secrets):
    secrets.replace({"github_token": "ghp_gizli"})
    shown = secrets.public()["github_token"]
    assert shown["value"] == KEY_MASK and shown["has_token"] is True
    assert "ghp_gizli" not in json.dumps(secrets.public())


def test_the_mask_coming_back_means_leave_it_alone(secrets):
    secrets.replace({"github_token": "ghp_gizli"})
    secrets.replace({"github_token": KEY_MASK})
    assert secrets.get("github_token") == "ghp_gizli"


def test_an_empty_value_clears_the_token(secrets):
    secrets.replace({"github_token": "ghp_gizli"})
    secrets.replace({"github_token": ""})
    assert secrets.get("github_token") == ""
    assert secrets.public()["github_token"]["has_token"] is False


def test_a_token_already_in_the_environment_keeps_working(secrets, monkeypatch):
    monkeypatch.setenv("GITHUB_RESEARCH_TOKEN", "ghp_ortamdan")
    assert secrets.get("github_token") == "ghp_ortamdan"
    assert secrets.public()["github_token"]["from_env"] is True
    secrets.replace({"github_token": "ghp_ayarlardan"})     # an explicit one wins
    assert secrets.get("github_token") == "ghp_ayarlardan"
    assert secrets.public()["github_token"]["from_env"] is False


def test_the_token_survives_being_written_and_read_again(tmp_path):
    path = tmp_path / "tool-settings.json"
    ToolSettings(path=path).replace({"github_token": "ghp_kalici"})
    assert ToolSettings(path=path).get("github_token") == "ghp_kalici"


def test_the_token_reaches_only_the_server_that_reads_it(secrets):
    secrets.replace({"github_token": "ghp_gizli"})
    hub = ToolHub(servers={}, settings=secrets)
    git = hub._environment("git_search", {"env": {"PYTHONPATH": "/x"}})
    assert git == {"PYTHONPATH": "/x", "GITHUB_RESEARCH_TOKEN": "ghp_gizli"}
    assert "GITHUB_RESEARCH_TOKEN" not in hub._environment("web_search", {"env": {}})


def test_no_token_means_no_empty_variable_is_invented(secrets, monkeypatch):
    monkeypatch.delenv("GITHUB_RESEARCH_TOKEN", raising=False)
    hub = ToolHub(servers={}, settings=secrets)
    assert hub._environment("git_search", {"env": {}}) == {}


# ------------------------------------------------------- a failure that explains itself
def test_a_failed_web_search_explains_the_likeliest_cause():
    """Zero results is raised as an error by that server, and the reason never
    crosses the wire — so the model is told what it most likely means."""
    body = json.loads(result_for_model("web_search", {"ok": False, "result": {
        "content": [{"type": "text", "text": "Error executing tool web_search"}], "isError": True}}))
    assert body["ok"] is False and body["error"] is True
    assert "SIFIR sonucu" in body["hint"]
    assert "uydurma" in body["hint"]


def test_a_successful_search_is_never_given_a_failure_hint():
    body = json.loads(result_for_model("web_search", {"ok": True, "result": {"content": []}}))
    assert "hint" not in body


def test_a_tool_with_nothing_useful_to_add_gets_no_hint():
    body = json.loads(result_for_model("git_search", {"ok": False, "result": {"isError": True}}))
    assert "hint" not in body and body["error"] is True


# ------------------------------------------------------------------ restarting
@pytest.mark.anyio
async def test_restarting_picks_up_a_corrected_config(tmp_path, monkeypatch):
    """A path fixed while the app is running must not need an app restart."""
    path = tmp_path / "search-tools-mcp.json"
    path.write_text(json.dumps({"mcpServers": {"git_search": {
        "command": "D:/yok/boyle/python.exe", "args": []}}}), encoding="utf-8")
    monkeypatch.setattr("server.tools.USER_CONFIG_PATH", path)

    hub = ToolHub(settings=isolated_settings())          # read from disk, not passed in
    await hub.start()
    try:
        assert "git_search" in hub.errors
        path.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
        info = await hub.restart()
        assert info["errors"] == {} and info["configured"] == []
    finally:
        await hub.stop()


@pytest.mark.anyio
async def test_a_hub_given_its_servers_does_not_go_back_to_disk(monkeypatch):
    """Tests and callers that pass servers explicitly must stay in control."""
    monkeypatch.setattr("server.tools.load_config",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("disk okundu")))
    hub = ToolHub(servers={}, settings=isolated_settings())
    await hub.restart()
    assert hub.servers == {}


def test_the_token_state_travels_with_the_tool_status(secrets):
    secrets.replace({"github_token": "ghp_gizli"})
    hub = ToolHub(servers={}, settings=secrets)
    assert hub.public()["settings"]["github_token"]["has_token"] is True
    assert "ghp_gizli" not in json.dumps(hub.public())
