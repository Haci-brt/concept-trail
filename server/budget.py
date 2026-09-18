"""Spending guard for remote providers.

The watch loop fires every time the writer pauses. Locally that only costs
seconds; behind an API key it is a metered faucet, so remote calls are counted
and capped per day. Local providers are never counted or blocked.

Usage is kept next to the vault (.assistant/usage.json) so the numbers survive
restarts and stay with the notes they belong to.
"""
import json
import os
import threading
from datetime import date
from pathlib import Path

DEFAULT_LIMITS = {
    "daily_calls": 300,        # remote requests per day
    "daily_tokens": 400_000,   # counted from each response's usage block
    "min_seconds_between": 2,  # a floor between remote calls, whatever the app asks for
}


class Budget:
    def __init__(self, vault, limits: dict | None = None):
        self.path = vault.meta_dir / "usage.json"
        self.lock = threading.RLock()
        self.limits = {**DEFAULT_LIMITS, **(limits or {})}
        self.last_call = 0.0
        self.data = self._read()

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("day") == str(date.today()):
                return data
        except (OSError, json.JSONDecodeError):
            pass
        return {"day": str(date.today()), "calls": 0, "tokens": 0, "by_provider": {}}

    def _roll_day(self) -> None:
        if self.data.get("day") != str(date.today()):
            self.data = {"day": str(date.today()), "calls": 0, "tokens": 0, "by_provider": {}}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass

    def check(self, provider) -> str | None:
        """Returns None when the call may go ahead, or why it may not."""
        if not provider.is_remote:
            return None
        with self.lock:
            self._roll_day()
            if self.data["calls"] >= self.limits["daily_calls"]:
                return (f"Günlük uzak model isteği sınırına ulaşıldı "
                        f"({self.limits['daily_calls']}). Ayarlardan artırabilirsin.")
            if self.data["tokens"] >= self.limits["daily_tokens"]:
                return (f"Günlük token bütçesi doldu "
                        f"({self.data['tokens']:,}/{self.limits['daily_tokens']:,}).")
        return None

    def record(self, provider, usage: dict | None) -> None:
        if not provider.is_remote:
            return
        tokens = 0
        if isinstance(usage, dict):
            tokens = int(usage.get("total_tokens") or
                         (usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)) or 0)
        with self.lock:
            self._roll_day()
            self.data["calls"] += 1
            self.data["tokens"] += tokens
            entry = self.data["by_provider"].setdefault(provider.id, {"calls": 0, "tokens": 0})
            entry["calls"] += 1
            entry["tokens"] += tokens
            self._save()

    def public(self) -> dict:
        with self.lock:
            self._roll_day()
            return {**self.data, "limits": self.limits}

    def set_limits(self, limits: dict) -> dict:
        with self.lock:
            for key in DEFAULT_LIMITS:
                if key in limits:
                    self.limits[key] = max(0, int(limits[key]))
            return self.public()
