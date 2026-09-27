"""A small prepaid balance is guarded in dollars, and the limits the writer sets survive a restart."""
from server.budget import Budget
from server.providers import Provider
from server.vault import Vault


def remote():
    return Provider(id="or", label="OpenRouter", base_url="https://openrouter.ai/api", model="m",
                    api_key="k", kind="remote", health="models")


def test_the_daily_dollar_cap_stops_remote_calls(tmp_path):
    budget = Budget(Vault(tmp_path / "v"), {"daily_usd": 0.001})
    assert budget.check(remote()) is None
    budget.record(remote(), {"total_tokens": 1200, "cost": 0.0012})
    assert "harcama" in budget.check(remote())
    assert budget.public()["usd"] == 0.0012


def test_limits_the_writer_sets_are_kept(tmp_path):
    vault = Vault(tmp_path / "v")
    Budget(vault).set_limits({"daily_usd": 0.25, "daily_calls": 50})
    again = Budget(vault)
    assert again.limits["daily_usd"] == 0.25 and again.limits["daily_calls"] == 50


def test_openrouter_is_always_asked_for_the_real_cost():
    payload = remote().build_payload([{"role": "user", "content": "x"}], 0.2, 10, False)
    assert payload["usage"] == {"include": True}
