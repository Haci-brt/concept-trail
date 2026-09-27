"""The competitor analysis has a role of its own, following the analysis role until bound."""
import json

from server.providers import ProviderRegistry

OPENROUTER = {"id": "openrouter", "label": "OpenRouter", "base_url": "https://openrouter.ai/api",
              "model": "openai/gpt-4o-mini", "kind": "remote", "health": "models"}
DEEPSEEK = {**OPENROUTER, "id": "deepseek", "model": "deepseek/deepseek-v4-flash",
            "extras": {"reasoning": {"enabled": False}}}


def registry(tmp_path, roles):
    path = tmp_path / "providers.json"
    path.write_text(json.dumps({"providers": [OPENROUTER, DEEPSEEK], "roles": roles}), encoding="utf-8")
    return ProviderRegistry(path)


def test_an_unbound_compare_role_runs_on_the_analysis_model(tmp_path):
    reg = registry(tmp_path, {"analysis": ["openrouter"], "chat": ["openrouter"], "summary": ["openrouter"]})
    assert reg.roles["compare"] == ["openrouter"]


def test_compare_can_take_a_stronger_model_with_a_fallback(tmp_path):
    reg = registry(tmp_path, {"analysis": ["openrouter"], "compare": ["deepseek", "openrouter"]})
    assert [p.id for p in reg.chain("compare")] == ["deepseek", "openrouter"]
    payload = reg.get("deepseek").build_payload([], 0.2, 100, False)
    assert payload["reasoning"] == {"enabled": False}
