"""Model providers and which job each one does.

A provider is anything that speaks the OpenAI chat-completions shape: the local
llama-server, or a remote API behind a key. Roles ("analysis", "chat",
"summary") are bound to an ordered list of providers, so the second entry is
the fallback when the first is down.

Everything provider-specific lives here — auth header, whether a `model` field
is required, llama.cpp-only payload extras like cache_prompt, how to health
check — so the rest of the app never asks "is this local or remote?".

Keys are kept in the OS config folder, never in the vault (which the user may
sync or put in git), and are masked on their way to the UI.
"""
import json
import os
import threading
from dataclasses import dataclass, field, replace as dataclass_replace
from pathlib import Path

from server.errors import ApiError

ROLES = ("analysis", "chat", "summary")
KEY_MASK = "••••"
HEALTH_STYLES = ("llama", "models", "none")
KINDS = ("local", "remote")


def config_dir() -> Path:
    base = (os.environ.get("FIKIR_CONFIG_DIR") or os.environ.get("APPDATA")
            or os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config"))
    return Path(base) / "FikirNotDefteri"


@dataclass
class Provider:
    id: str
    label: str
    base_url: str
    model: str | None = None
    api_key: str | None = None
    kind: str = "local"        # "remote" means notes leave this machine
    health: str = "llama"      # llama: GET /health · models: GET /v1/models · none
    extras: dict = field(default_factory=dict)   # e.g. {"cache_prompt": true} for llama.cpp
    token_field: str = "max_tokens"              # newer OpenAI models want max_completion_tokens
    timeout: float = 120.0
    enabled: bool = True

    @property
    def chat_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/v1/chat/completions"

    @property
    def health_url(self) -> str | None:
        base = self.base_url.rstrip("/")
        if self.health == "llama":
            return f"{base}/health"
        if self.health == "models":
            return f"{base}/v1/models"
        return None

    @property
    def display(self) -> str:
        return self.base_url.split("://", 1)[-1].rstrip("/")

    @property
    def is_remote(self) -> bool:
        return self.kind == "remote"

    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def build_payload(self, messages: list[dict], temperature: float, max_tokens: int, stream: bool) -> dict:
        payload = {
            "messages": messages,
            "temperature": temperature,
            self.token_field: max_tokens,
            "stream": stream,
            **self.extras,
        }
        if self.model:
            payload["model"] = self.model
        return payload

    def public(self) -> dict:
        data = {
            "id": self.id, "label": self.label, "base_url": self.base_url, "model": self.model,
            "kind": self.kind, "health": self.health, "extras": self.extras,
            "token_field": self.token_field, "timeout": self.timeout, "enabled": self.enabled,
            "has_key": bool(self.api_key),
        }
        data["api_key"] = KEY_MASK if self.api_key else ""
        return data


def _default_config() -> dict:
    local = os.environ.get("FIKIR_LLM_URL", "http://127.0.0.1:8899").rstrip("/")
    fast = os.environ.get("FIKIR_FAST_URL", "http://127.0.0.1:8901").rstrip("/")
    return {
        "providers": [
            {"id": "local-chat", "label": "Yerel sohbet modeli", "base_url": local, "kind": "local",
             "health": "llama", "extras": {"cache_prompt": True}, "timeout": 300.0},
            {"id": "local-fast", "label": "Yerel hızlı analiz modeli", "base_url": fast, "kind": "local",
             "health": "llama", "extras": {"cache_prompt": True}, "timeout": 300.0},
        ],
        # first entry does the job, the rest are fallbacks when it is down
        "roles": {
            "analysis": ["local-fast", "local-chat"],
            "chat": ["local-chat", "local-fast"],
            "summary": ["local-chat", "local-fast"],
        },
    }


class ProviderRegistry:
    def __init__(self, path: Path | None = None):
        self.path = path or (config_dir() / "providers.json")
        self.lock = threading.RLock()
        self.providers: dict[str, Provider] = {}
        self.roles: dict[str, list[str]] = {}
        self.health: dict[str, bool] = {}
        self._apply(self._read())

    # ---- persistence ----
    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _default_config()
        if not isinstance(data, dict) or not data.get("providers"):
            return _default_config()
        return data

    def save(self) -> None:
        with self.lock:
            data = {
                "providers": [
                    {k: v for k, v in vars(p).items() if v is not None} for p in self.providers.values()
                ],
                "roles": self.roles,
            }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
            if os.name == "nt":  # keys inside: keep it to this user
                os.chmod(self.path, 0o600)
        except OSError:
            pass

    def _apply(self, data: dict) -> None:
        providers: dict[str, Provider] = {}
        for raw in data.get("providers", []):
            try:
                provider = Provider(**{k: v for k, v in raw.items() if k in Provider.__dataclass_fields__})
            except TypeError:
                continue
            providers[provider.id] = provider
        roles = {}
        for role in ROLES:
            chain = data.get("roles", {}).get(role) or []
            roles[role] = [pid for pid in chain if pid in providers]
            if not roles[role]:
                roles[role] = list(providers)[:1]
        with self.lock:
            self.providers = providers
            self.roles = roles
            self.health = {pid: self.health.get(pid, False) for pid in providers}

    # ---- lookup ----
    def all(self) -> list[Provider]:
        with self.lock:
            return [p for p in self.providers.values() if p.enabled]

    def get(self, provider_id: str) -> Provider | None:
        with self.lock:
            return self.providers.get(provider_id)

    def chain(self, role: str) -> list[Provider]:
        with self.lock:
            return [self.providers[pid] for pid in self.roles.get(role, []) if self.providers[pid].enabled]

    def pick(self, role: str, local_only: bool = False) -> Provider | None:
        """The provider that should do this job right now: first healthy one in
        the chain, else the first at all (so the failure surfaces properly)."""
        chain = [p for p in self.chain(role) if not (local_only and p.is_remote)]
        if not chain:
            return None
        for provider in chain:
            if self.health.get(provider.id):
                return provider
        return chain[0]

    def set_health(self, provider_id: str, up: bool) -> bool:
        with self.lock:
            changed = self.health.get(provider_id) != up
            self.health[provider_id] = up
            return changed

    def is_up(self, role: str) -> bool:
        return any(self.health.get(p.id) for p in self.chain(role))

    def public(self) -> dict:
        with self.lock:
            return {
                "providers": [{**p.public(), "up": self.health.get(p.id, False)} for p in self.providers.values()],
                "roles": dict(self.roles),
            }

    # ---- editing (what the key binder will call) ----
    def replace(self, data: dict) -> dict:
        if not isinstance(data, dict):
            raise ApiError(400, "Geçersiz ayar verisi.")
        incoming = data.get("providers")
        if not isinstance(incoming, list) or not incoming:
            raise ApiError(400, "En az bir sağlayıcı gerekli.")

        cleaned: list[dict] = []
        seen: set[str] = set()
        for raw in incoming:
            if not isinstance(raw, dict):
                raise ApiError(400, "Geçersiz sağlayıcı kaydı.")
            pid = str(raw.get("id") or "").strip()
            base_url = str(raw.get("base_url") or "").strip().rstrip("/")
            if not pid or pid in seen:
                raise ApiError(400, f"Sağlayıcı kimliği boş ya da tekrar ediyor: “{pid}”.")
            if not base_url.startswith(("http://", "https://")):
                raise ApiError(400, f"“{pid}” için adres http:// ya da https:// ile başlamalı.")
            kind = raw.get("kind", "local")
            health = raw.get("health", "llama")
            if kind not in KINDS:
                raise ApiError(400, f"“{pid}” için tür local ya da remote olmalı.")
            if health not in HEALTH_STYLES:
                raise ApiError(400, f"“{pid}” için sağlık kontrolü {HEALTH_STYLES} içinden olmalı.")
            if kind == "remote" and not base_url.startswith("https://"):
                raise ApiError(400, f"“{pid}” uzak bir sağlayıcı: adres https:// olmalı.")

            key = raw.get("api_key")
            if key == KEY_MASK or key is None:      # untouched in the UI — keep what we stored
                existing = self.get(pid)
                key = existing.api_key if existing else None
            key = (key or "").strip() or None
            if kind == "remote" and not key:
                raise ApiError(400, f"“{pid}” uzak bir sağlayıcı: API anahtarı gerekli.")
            if kind == "remote" and not str(raw.get("model") or "").strip():
                raise ApiError(400, f"“{pid}” uzak bir sağlayıcı: model adı gerekli.")

            seen.add(pid)
            cleaned.append({
                "id": pid,
                "label": str(raw.get("label") or pid),
                "base_url": base_url,
                "model": (str(raw.get("model")).strip() or None) if raw.get("model") else None,
                "api_key": key,
                "kind": kind,
                "health": health,
                "extras": raw.get("extras") if isinstance(raw.get("extras"), dict) else {},
                "token_field": raw.get("token_field") or "max_tokens",
                "timeout": float(raw.get("timeout") or 120.0),
                "enabled": bool(raw.get("enabled", True)),
            })

        roles = {}
        for role in ROLES:
            chain = data.get("roles", {}).get(role)
            chain = [chain] if isinstance(chain, str) else list(chain or [])
            unknown = [pid for pid in chain if pid not in seen]
            if unknown:
                raise ApiError(400, f"“{role}” için bilinmeyen sağlayıcı: {', '.join(unknown)}")
            roles[role] = chain or [cleaned[0]["id"]]

        self._apply({"providers": cleaned, "roles": roles})
        self.save()
        return self.public()

    def bind(self, role: str, provider_ids: list[str]) -> dict:
        """Point one role at a provider chain — the core of the key binder."""
        if role not in ROLES:
            raise ApiError(400, f"Bilinmeyen görev: {role}")
        current = self.public()
        current["roles"][role] = provider_ids
        payload = {"providers": [dict(p, api_key=KEY_MASK if p["has_key"] else "") for p in current["providers"]],
                   "roles": current["roles"]}
        return self.replace(payload)
