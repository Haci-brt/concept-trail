"""Spending guard for remote providers.

The live watch looks at the note at every 15-second pause or paste, besides the
requests the writer starts. Locally that only costs seconds; behind an API key
it is a metered faucet, so remote calls are counted and capped per day. Local
providers are never counted or blocked.

Dollars are the limit that matters: OpenRouter reports each call's real cost
(see Provider.build_payload), and a daily dollar cap keeps a runaway loop from
eating a small prepaid balance. Calls and tokens are capped too, for providers
that report no cost.

Usage is kept next to the vault (.assistant/usage.json) so the numbers survive
restarts and stay with the notes they belong to; the limits the writer sets
are kept beside it (usage-limits.json).
"""
import json
import os
import threading
from datetime import date
from pathlib import Path

DEFAULT_LIMITS = {
    "daily_usd": 0.50,          # a few thousand passes of a cheap model; a loop stops here
    "daily_calls": 2000,        # remote requests per day
    "daily_tokens": 3_000_000,  # counted from each response's usage block
    "min_seconds_between": 2,   # a floor between remote calls, whatever the app asks for
}
FLOAT_LIMITS = {"daily_usd"}


def _empty() -> dict:
    return {"day": str(date.today()), "calls": 0, "tokens": 0, "usd": 0.0, "by_provider": {}}


class Budget:
    def __init__(self, vault, limits: dict | None = None):
        self.path = vault.meta_dir / "usage.json"
        self.limits_path = vault.meta_dir / "usage-limits.json"
        self.lock = threading.RLock()
        self.limits = {**DEFAULT_LIMITS, **self._read_limits(), **(limits or {})}
        self.last_call = 0.0
        self.data = self._read()

    def _read_limits(self) -> dict:
        try:
            saved = json.loads(self.limits_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return {key: value for key, value in saved.items()
                if key in DEFAULT_LIMITS and isinstance(value, (int, float))} if isinstance(saved, dict) else {}

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("day") == str(date.today()):
                return {**_empty(), **data}
        except (OSError, json.JSONDecodeError):
            pass
        return _empty()

    def _roll_day(self) -> None:
        if self.data.get("day") != str(date.today()):
            self.data = _empty()

    def _write(self, path: Path, data: dict) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            pass

    def _save(self) -> None:
        self._write(self.path, self.data)

    def check(self, provider) -> str | None:
        """Returns None when the call may go ahead, or why it may not."""
        if not provider.is_remote:
            return None
        with self.lock:
            self._roll_day()
            if self.data.get("usd", 0.0) >= self.limits["daily_usd"] > 0:
                return (f"Günlük harcama sınırına ulaşıldı "
                        f"(${self.data['usd']:.2f}/${self.limits['daily_usd']:.2f}). Ayarlardan artırabilirsin.")
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
        tokens, usd = 0, 0.0
        if isinstance(usage, dict):
            tokens = int(usage.get("total_tokens") or
                         (usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)) or 0)
            try:
                usd = float(usage.get("cost") or 0.0)
            except (TypeError, ValueError):
                usd = 0.0
        with self.lock:
            self._roll_day()
            self.data["calls"] += 1
            self.data["tokens"] += tokens
            self.data["usd"] = round(self.data.get("usd", 0.0) + usd, 6)
            entry = self.data["by_provider"].setdefault(provider.id, {"calls": 0, "tokens": 0, "usd": 0.0})
            entry["calls"] += 1
            entry["tokens"] += tokens
            entry["usd"] = round(entry.get("usd", 0.0) + usd, 6)
            self._save()

    def public(self) -> dict:
        with self.lock:
            self._roll_day()
            return {**self.data, "limits": self.limits}

    def set_limits(self, limits: dict) -> dict:
        with self.lock:
            for key in DEFAULT_LIMITS:
                if key in limits:
                    value = float(limits[key]) if key in FLOAT_LIMITS else int(limits[key])
                    self.limits[key] = max(0, value)
            self._write(self.limits_path, self.limits)
            return self.public()
