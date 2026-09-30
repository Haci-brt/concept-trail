// Only prefixes that distinguish one provider from the others are used here.
// An opaque key cannot be identified safely without sending it to a service.
export const KEY_PROVIDERS = [
  { id: "openai", label: "OpenAI", prefix: "sk-proj-",
    base_url: "https://api.openai.com", model: "gpt-4o-mini" },
  { id: "openai", label: "OpenAI", prefix: "sk-svcacct-",
    base_url: "https://api.openai.com", model: "gpt-4o-mini" },
  { id: "openrouter", label: "OpenRouter", prefix: "sk-or-v1-",
    base_url: "https://openrouter.ai/api", model: "openai/gpt-4o-mini" },
  { id: "groq", label: "Groq", prefix: "gsk_",
    base_url: "https://api.groq.com/openai", model: "llama-3.3-70b-versatile" },
  { id: "xai", label: "xAI", prefix: "xai-",
    base_url: "https://api.x.ai", model: "grok-4.7" },
  { id: "gemini", label: "Google Gemini", prefix: "AQ.",
    base_url: "https://generativelanguage.googleapis.com/v1beta/openai", model: "gemini-3.5-flash-lite" },
];

export function identifyKey(value) {
  const key = String(value || "").trim();
  return KEY_PROVIDERS.find((provider) => key.startsWith(provider.prefix) && key.length > provider.prefix.length) || null;
}

export function matchesProviderUrl(value, provider) {
  try {
    const current = new URL(value);
    const expected = new URL(provider.base_url);
    if (current.hostname !== expected.hostname) return false;
    // Gemini's OpenAI-compatible API lives below /v1beta/openai, not /v1.
    return provider.id !== "gemini" || current.pathname.replace(/\/$/, "") === expected.pathname.replace(/\/$/, "");
  } catch { return false; }
}
