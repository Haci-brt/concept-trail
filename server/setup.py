"""First start: connecting the assistant to a model, in a few plain steps.

A fresh install knows one provider — a llama-server at 127.0.0.1:8899, which
only exists on the machine this app was first built on. Everyone else met an
assistant that silently did nothing until they found Settings → Models and
filled in an address, a model name and a key. This is the guided way in:

* OpenRouter with a key — the recommended path: GPT-4o-mini found 14 of 14
  decisions at about $0.0002 a round (measured);
* a model already running on this computer — Ollama, LM Studio or a
  llama.cpp server, found by asking the ports they listen on;
* any other OpenAI-compatible service.

Nothing is saved until one real call has come back: a wrong key or a
misspelt model name is said in words, while the writer is still looking at
the form, and never becomes a provider that fails later.
"""
import ipaddress
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import requests

from server.errors import ApiError
from server.providers import KEY_MASK, ROLES, Provider, ProviderRegistry

OPENROUTER = {"id": "openrouter", "label": "OpenRouter", "base_url": "https://openrouter.ai/api",
              "kind": "remote", "health": "models", "model": "openai/gpt-4o-mini"}
OPENROUTER_KEYS_URL = "https://openrouter.ai/keys"
# what the writer can pick without knowing model names; the first is the measured default
OPENROUTER_MODELS = ("openai/gpt-4o-mini", "deepseek/deepseek-v4-flash", "google/gemini-2.5-flash",
                     "anthropic/claude-haiku-4.5")
GEMINI = {"id": "gemini", "label": "Google Gemini",
          "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
          "kind": "remote", "health": "models", "model": "gemini-3.5-flash-lite", "tools": True}
GEMINI_KEYS_URL = "https://aistudio.google.com/api-keys"
GEMINI_MODELS = ("gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-3.5-flash")
# Prefixes with a single known owner. Generic sk- keys are deliberately omitted.
KEY_IDENTITIES = (
    ("sk-proj-", "OpenAI", "api.openai.com", "https://api.openai.com", "gpt-4o-mini"),
    ("sk-svcacct-", "OpenAI", "api.openai.com", "https://api.openai.com", "gpt-4o-mini"),
    ("sk-or-v1-", "OpenRouter", "openrouter.ai", "https://openrouter.ai/api", "openai/gpt-4o-mini"),
    ("gsk_", "Groq", "api.groq.com", "https://api.groq.com/openai", "llama-3.3-70b-versatile"),
    ("xai-", "xAI", "api.x.ai", "https://api.x.ai", "grok-4.7"),
    ("AQ.", "Google Gemini", "generativelanguage.googleapis.com",
     GEMINI["base_url"], GEMINI["model"]),
)
# where the common local servers listen by default
LOCAL_SERVERS = (
    ("ollama", "Ollama", "http://127.0.0.1:11434", "models"),
    ("lmstudio", "LM Studio", "http://127.0.0.1:1234", "models"),
    ("llamacpp", "llama.cpp", "http://127.0.0.1:8080", "llama"),
    ("local-chat", "llama.cpp", "http://127.0.0.1:8899", "llama"),
)
DETECT_TIMEOUT_S = 1.5
PROBE_TIMEOUT_S = 40.0


def _is_local(base_url: str) -> bool:
    host = (urlsplit(base_url).hostname or "").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def identify_key(key: str | None) -> tuple | None:
    """A format hint only; the real provider still has to answer the probe."""
    value = (key or "").strip()
    return next((entry for entry in KEY_IDENTITIES if value.startswith(entry[0]) and len(value) > len(entry[0])), None)


def status(registry: ProviderRegistry, dismissed: bool) -> dict:
    """Does the assistant have a model it can use? It does once any enabled
    provider answers its health check, or once a remote one has a key and a
    model (most remote APIs have no health check to answer)."""
    providers = registry.all()
    ready = any(registry.health.get(p.id) for p in providers) or \
        any(p.is_remote and p.api_key and p.model for p in providers)
    return {"needed": not ready, "dismissed": bool(dismissed),
            "openrouter": {"keys_url": OPENROUTER_KEYS_URL, "models": list(OPENROUTER_MODELS)},
            "gemini": {"keys_url": GEMINI_KEYS_URL, "models": list(GEMINI_MODELS)},
            "local": [{"id": sid, "label": label, "base_url": url} for sid, label, url, _ in LOCAL_SERVERS]}


def detect(get=None) -> list[dict]:
    """The model servers answering on this computer's usual ports, with the
    models they have loaded. Only 127.0.0.1 is asked — nothing leaves the machine."""
    get = get or (lambda url: requests.get(url, timeout=DETECT_TIMEOUT_S))

    def ask(server):
        sid, label, base_url, health = server
        try:
            reply = get(f"{base_url}/v1/models")
        except Exception:
            return None
        if getattr(reply, "status_code", 0) != 200:
            return None
        try:
            models = [str(m.get("id")) for m in (reply.json().get("data") or []) if m.get("id")]
        except Exception:
            models = []
        return {"id": sid, "label": label, "base_url": base_url, "health": health, "models": models[:40]}

    # all at once: on Windows a closed port takes about two seconds to refuse
    with ThreadPoolExecutor(max_workers=len(LOCAL_SERVERS)) as pool:
        return [row for row in pool.map(ask, LOCAL_SERVERS) if row]


def build(choice: dict) -> Provider:
    """The provider the writer described, checked for what is missing."""
    preset = str(choice.get("preset") or "")
    model = str(choice.get("model") or "").strip() or None
    key = str(choice.get("api_key") or "").strip() or None
    identity = identify_key(key)
    if preset == "openrouter":
        if not key:
            raise ApiError(400, "OpenRouter anahtarını yapıştır.")
        if identity and identity[2] != "openrouter.ai":
            raise ApiError(400, f"Bu anahtar {identity[1]} biçiminde. OpenRouter yerine doğru sağlayıcıyı seç.")
        return Provider(**{**OPENROUTER, "model": model or OPENROUTER["model"], "api_key": key})
    if preset == "gemini":
        if not key:
            raise ApiError(400, "Gemini anahtarını yapıştır.")
        if identity and identity[2] != "generativelanguage.googleapis.com":
            raise ApiError(400, f"Bu anahtar {identity[1]} biçiminde. Gemini yerine doğru sağlayıcıyı seç.")
        return Provider(**{**GEMINI, "model": model or GEMINI["model"], "api_key": key})
    base_url = str(choice.get("base_url") or "").strip().rstrip("/")
    if preset == "custom" and identity:
        base_url = base_url or identity[3]
        model = model or identity[4]
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]               # the chat path adds it
    if not base_url.startswith(("http://", "https://")):
        raise ApiError(400, "Adres http:// ya da https:// ile başlamalı.")
    local = _is_local(base_url)
    if preset == "local":
        if not local:
            raise ApiError(400, "Bu bilgisayardaki bir model için adres 127.0.0.1 ya da localhost olmalı.")
        sid = str(choice.get("id") or "yerel").strip() or "yerel"
        label = str(choice.get("label") or "Yerel model").strip()
        health = choice.get("health") if choice.get("health") in ("llama", "models") else "models"
        extras = {"cache_prompt": True} if health == "llama" else {}
        return Provider(id=sid, label=label, base_url=base_url, model=model, kind="local", health=health,
                        extras=extras, timeout=300.0)
    if preset == "custom":
        if not local and not base_url.startswith("https://"):
            raise ApiError(400, "Başka bir makinedeki servisin adresi https:// ile başlamalı.")
        if not local and not key:
            raise ApiError(400, "Bu servis için API anahtarı gerekli.")
        if not model:
            raise ApiError(400, "Model adını yaz.")
        host = urlsplit(base_url).hostname or "servis"
        if identity and (host.lower() != identity[2] or
                         (identity[1] == "Google Gemini" and base_url != identity[3])):
            raise ApiError(400, f"Bu anahtar {identity[1]} biçiminde; adres {identity[3]} olmalı.")
        return Provider(id="ozel", label=str(choice.get("label") or (identity[1] if identity else host)), base_url=base_url, model=model,
                        api_key=key, kind="local" if local else "remote",
                        health="models" if local or (identity and identity[1] == "Google Gemini") else "none",
                        tools=bool(identity and identity[1] == "Google Gemini"))
    raise ApiError(400, "Bilinmeyen kurulum seçimi.")


def friendly(exc: Exception, provider: Provider) -> str:
    """What went wrong, in words the writer can act on."""
    status_code = getattr(exc, "status", None)
    if status_code in (401, 403):
        return "Anahtar kabul edilmedi. Anahtarı eksiksiz yapıştırdığından emin ol."
    if status_code == 402:
        if provider.base_url.startswith("https://generativelanguage.googleapis.com/"):
            return "Gemini hesabının faturalandırma ve kota ayarlarını Google AI Studio'da kontrol et."
        return ("Hesapta kredi yok. OpenRouter'a biraz kredi ekle ya da adı ':free' ile biten "
                "ücretsiz bir model seç.")
    if status_code == 404:
        return f"Model bulunamadı: {provider.model or '—'}. Adını kontrol et."
    if status_code == 429:
        return "Servis şu an hız sınırında; biraz sonra yeniden dene."
    text = str(exc)
    if not status_code and ("Connection" in text or "Max retries" in text or "refused" in text.lower()):
        return f"{provider.display} adresine ulaşılamadı. Model sunucusu çalışıyor mu?"
    return text[:300] or "Model yanıt vermedi."


def install(registry: ProviderRegistry, provider: Provider) -> dict:
    """Save the provider and put it first for every job; whatever did the
    jobs before stays behind it as the fallback."""
    current = registry.public()
    others = [dict(p, api_key=KEY_MASK if p["has_key"] else "") for p in current["providers"] if p["id"] != provider.id]
    mine = {k: v for k, v in vars(provider).items()}
    roles = {role: [provider.id] + [pid for pid in current["roles"].get(role, []) if pid != provider.id]
             for role in ROLES}
    return registry.replace({"providers": [mine] + others, "roles": roles})
