"""The key binder's backend: what a provider is allowed to be, and which one
does a given job. Keys pass through the UI masked, so the round trip must not
lose them — that is the failure that would silently send a request with no key.
"""
import json

import pytest

from server.errors import ApiError
from server.providers import KEY_MASK, ProviderRegistry

REMOTE = {"id": "openai", "label": "OpenAI", "base_url": "https://api.openai.com",
          "model": "gpt-4o-mini", "api_key": "sk-test-anahtar", "kind": "remote",
          "health": "models", "token_field": "max_completion_tokens"}
LOCAL = {"id": "yerel", "label": "Yerel", "base_url": "http://127.0.0.1:8899", "kind": "local"}


@pytest.fixture
def registry(tmp_path):
    return ProviderRegistry(tmp_path / "providers.json")


def payload(*providers, **roles):
    return {"providers": [dict(p) for p in providers], "roles": roles}


# ---------------------------------------------------------------- defaults
def test_a_fresh_install_has_the_two_local_models_bound(registry):
    data = registry.public()
    assert [p["id"] for p in data["providers"]] == ["local-chat", "local-fast"]
    assert data["roles"]["analysis"][0] == "local-fast"   # the small model watches
    assert data["roles"]["chat"][0] == "local-chat"       # the big one talks


# ---------------------------------------------------------------- keys
def test_a_key_is_never_sent_to_the_browser(registry):
    registry.replace(payload(REMOTE, LOCAL, chat=["openai"]))
    shown = next(p for p in registry.public()["providers"] if p["id"] == "openai")
    assert shown["api_key"] == KEY_MASK and shown["has_key"] is True
    assert "sk-test-anahtar" not in json.dumps(registry.public())


def test_saving_without_touching_the_key_keeps_it(registry):
    registry.replace(payload(REMOTE, chat=["openai"]))
    # the browser sends back what it was shown: the mask
    registry.replace(payload(dict(REMOTE, api_key=KEY_MASK, label="Yeni ad"), chat=["openai"]))
    provider = registry.get("openai")
    assert provider.api_key == "sk-test-anahtar" and provider.label == "Yeni ad"


def test_the_key_is_written_to_the_config_file(registry):
    # the config folder, never the vault — which the user may sync or put in git
    registry.replace(payload(REMOTE, chat=["openai"]))
    assert "sk-test-anahtar" in registry.path.read_text(encoding="utf-8")


def test_a_saved_registry_is_read_back(registry):
    registry.replace(payload(REMOTE, LOCAL, chat=["openai", "yerel"]))
    again = ProviderRegistry(registry.path)
    assert again.get("openai").api_key == "sk-test-anahtar"
    assert again.roles["chat"] == ["openai", "yerel"]


# ---------------------------------------------------------------- validation
@pytest.mark.parametrize("broken, missing", [
    ({"api_key": ""}, "anahtar"),
    ({"model": ""}, "model"),
    ({"base_url": "http://api.openai.com"}, "https"),
])
def test_a_remote_provider_needs_https_a_key_and_a_model(registry, broken, missing):
    with pytest.raises(ApiError) as err:
        registry.replace(payload(dict(REMOTE, **broken), chat=["openai"]))
    assert missing in str(err.value.message).lower()


def test_two_providers_cannot_share_an_id(registry):
    with pytest.raises(ApiError):
        registry.replace(payload(LOCAL, dict(LOCAL, label="İkinci"), chat=["yerel"]))


def test_a_role_cannot_point_at_a_provider_that_does_not_exist(registry):
    with pytest.raises(ApiError):
        registry.replace(payload(LOCAL, chat=["yok-boyle-biri"]))


def test_an_empty_provider_list_is_refused(registry):
    with pytest.raises(ApiError):
        registry.replace({"providers": [], "roles": {}})


# ---------------------------------------------------------------- routing
def test_a_role_falls_through_to_the_next_provider_when_the_first_is_down(registry):
    registry.replace(payload(REMOTE, LOCAL, chat=["openai", "yerel"]))
    registry.set_health("openai", False)
    registry.set_health("yerel", True)
    assert registry.pick("chat").id == "yerel"


def test_with_nothing_healthy_the_first_choice_is_returned_so_the_error_surfaces(registry):
    registry.replace(payload(REMOTE, LOCAL, chat=["openai", "yerel"]))
    assert registry.pick("chat").id == "openai"


def test_a_private_note_never_picks_a_remote_provider(registry):
    registry.replace(payload(REMOTE, LOCAL, chat=["openai", "yerel"]))
    registry.set_health("openai", True)
    assert registry.pick("chat", local_only=True).id == "yerel"


def test_local_only_with_no_local_provider_picks_nothing(registry):
    registry.replace(payload(REMOTE, chat=["openai"]))
    assert registry.pick("chat", local_only=True) is None


def test_a_disabled_provider_is_skipped(registry):
    registry.replace(payload(dict(REMOTE, enabled=False), LOCAL, chat=["openai", "yerel"]))
    assert registry.pick("chat").id == "yerel"


def test_binding_a_role_leaves_the_others_alone(registry):
    registry.replace(payload(REMOTE, LOCAL, chat=["yerel"], analysis=["yerel"], summary=["yerel"]))
    registry.bind("chat", ["openai", "yerel"])
    assert registry.roles["chat"] == ["openai", "yerel"]
    assert registry.roles["analysis"] == ["yerel"]
    assert registry.get("openai").api_key == "sk-test-anahtar"   # bind must not wipe the key


def test_an_unknown_role_is_refused(registry):
    with pytest.raises(ApiError):
        registry.bind("bilinmeyen", ["yerel"])


# ---------------------------------------------------------------- payloads
def test_each_provider_gets_the_request_shape_it_expects(registry):
    registry.replace(payload(REMOTE, LOCAL, chat=["openai"]))
    remote = registry.get("openai").build_payload([{"role": "user", "content": "selam"}], 0.5, 64, False)
    assert remote["max_completion_tokens"] == 64 and "max_tokens" not in remote
    assert remote["model"] == "gpt-4o-mini"

    local = registry.get("yerel").build_payload([{"role": "user", "content": "selam"}], 0.5, 64, False)
    assert local["max_tokens"] == 64 and "model" not in local   # llama-server serves one model


def test_llama_extras_ride_along(registry):
    fast = registry.get("local-fast")             # default config
    assert fast.build_payload([], 0.5, 64, True)["cache_prompt"] is True


def test_health_and_chat_urls_follow_the_provider_style(registry):
    registry.replace(payload(REMOTE, LOCAL, chat=["openai"]))
    assert registry.get("openai").health_url == "https://api.openai.com/v1/models"
    assert registry.get("yerel").health_url == "http://127.0.0.1:8899/health"
    assert registry.get("yerel").chat_url == "http://127.0.0.1:8899/v1/chat/completions"
    assert registry.get("openai").headers()["Authorization"] == "Bearer sk-test-anahtar"
    assert registry.get("yerel").headers() == {}
