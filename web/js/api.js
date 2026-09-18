// Thin client for the local server. Every request carries X-Fikir (required
// by the server for writes) and a per-page client id so pages can ignore
// echoes of their own saves.

export const clientId = crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2);

async function request(method, url, body) {
  const opts = { method, headers: { "X-Fikir": "1", "X-Client-Id": clientId } };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  const isJson = (res.headers.get("content-type") || "").includes("application/json");
  const data = isJson ? await res.json() : await res.text();
  if (!res.ok) {
    const err = new Error((data && data.detail) || res.statusText || "İstek başarısız");
    err.status = res.status;
    throw err;
  }
  return data;
}

export const api = {
  get: (url, params) => request("GET", params ? `${url}?${new URLSearchParams(params)}` : url),
  post: (url, body = {}) => request("POST", url, body),
  put: (url, body = {}) => request("PUT", url, body),
};

/** POST that streams newline-delimited JSON back; calls onUpdate per line. */
export async function streamPost(url, body, onUpdate) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "X-Fikir": "1", "X-Client-Id": clientId, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* not json */ }
    throw new Error(detail);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let nl;
    while ((nl = buffer.indexOf("\n")) !== -1) {
      const line = buffer.slice(0, nl).trim();
      buffer = buffer.slice(nl + 1);
      if (line) onUpdate(JSON.parse(line));
    }
  }
}

/** Subscribe to server events. handlers: { kind: fn(data), onOpen, onError }. */
export function connectEvents(handlers) {
  const source = new EventSource("/api/events");
  for (const [kind, fn] of Object.entries(handlers)) {
    if (kind === "onOpen" || kind === "onError") continue;
    source.addEventListener(kind, (e) => {
      try { fn(JSON.parse(e.data)); } catch (err) { console.error(`event ${kind}`, err); }
    });
  }
  source.onopen = () => handlers.onOpen?.();
  source.onerror = () => handlers.onError?.();
  return source;
}
