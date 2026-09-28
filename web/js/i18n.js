// Interface language. The app is written in Turkish; every other language is
// a dictionary in web/locales/<id>.json keyed by the Turkish text as it
// appears on screen. The page is translated as it is drawn: text nodes and a
// few attributes are looked up — exactly, against patterns with {0}-style
// holes ("{0} soru bekliyor"), or piece by piece around " · " — so the
// modules keep building their markup in Turkish and need no wrapping.
// What the writer and the model wrote (the note, the chat, the questions) is
// never touched: those containers are skipped.
export const LANGUAGES = [
  { id: "tr", label: "Türkçe", locale: "tr-TR" },
  { id: "en", label: "English", locale: "en-GB" },
  { id: "de", label: "Deutsch", locale: "de-DE" },
  { id: "es", label: "Español", locale: "es-ES" },
  { id: "fr", label: "Français", locale: "fr-FR" },
];
const KEY = "fikir.ui-lang.v1";
const ATTRS = ["title", "placeholder", "aria-label"];
// the writer's and the model's words, and the editor (which redraws on every key)
const SKIP = [
  ".editor-host", ".preview-body", ".md", ".mp-raw", ".mp-assumed li", ".tn-body", ".tn-thread", ".tn-diff", ".tn-root-title",
  ".tn-section-name", ".cv-tip span", ".msg.user", ".msg.assistant:not(.steps):not(.thinking)",
  ".msg.thinking .body", ".p-text", ".h-text", ".h-reply", ".note-heading h1", ".tab .name", ".sidebar .name",
  ".crumbs", ".tv-note", "[translate=\"no\"]", "code", "pre", "kbd", "script", "style",
].join(",");

function stored() {
  try { return localStorage.getItem(KEY) || ""; } catch { return ""; }
}

export let lang = LANGUAGES.some((l) => l.id === stored()) ? stored() : "tr";
export const locale = () => (LANGUAGES.find((l) => l.id === lang) || LANGUAGES[0]).locale;

let exact = new Map();
let patterns = [];
const written = new WeakMap();      // text node / element+attr -> the value we put there
const missing = new Set();          // Turkish text with no translation (for filling the dictionary)

function compile(dict) {
  exact = new Map();
  patterns = [];
  for (const [tr, out] of Object.entries(dict)) {
    if (!out) continue;
    if (/\{\d+\}/.test(tr)) {
      const source = tr.replace(/[.*+?^$()|[\]\\]/g, "\\$&").replace(/\\?\{(\d+)\\?\}/g, "(?<g$1>.+?)");
      try {
        patterns.push({ re: new RegExp(`^${source}$`, "s"), out, weight: tr.replace(/\{\d+\}/g, "").length });
      } catch { /* a key that is not a usable pattern */ }
    } else {
      exact.set(tr, out);
    }
  }
  patterns.sort((a, b) => b.weight - a.weight);
}

/** The translation of one piece of Turkish text, or null. */
export function translateText(text, depth = 0) {
  if (lang === "tr" || !text) return null;
  const hit = exact.get(text);
  if (hit !== undefined) return hit;
  if (depth > 3) return null;
  for (const p of patterns) {
    const m = p.re.exec(text);
    if (!m) continue;
    return p.out.replace(/\{(\d+)\}/g, (_, k) => {
      const value = m.groups?.[`g${k}`] ?? "";
      return translateText(value.trim(), depth + 1) ?? value;
    });
  }
  // a piece that runs into markup: "13 varsayım ·" before a span
  const edge = /^(·\s+)?([\s\S]*?)(\s+·)?$/.exec(text);
  if (edge && (edge[1] || edge[3]) && edge[2]) {
    const inner = translateText(edge[2], depth + 1);
    if (inner !== null) return `${edge[1] || ""}${inner}${edge[3] || ""}`;
  }
  // "Kapsam · Kullanıcı · cevap bekliyor": each piece on its own
  if (text.includes(" · ")) {
    const parts = text.split(" · ");
    const done = parts.map((part) => translateText(part.trim(), depth + 1));
    if (done.some((d) => d !== null)) return parts.map((part, i) => done[i] ?? part).join(" · ");
  }
  return null;
}

/** For text built in script rather than markup (document.title, a canvas). */
export function t(text, ...args) {
  const out = translateText(text) ?? text;
  return args.length ? out.replace(/\{(\d+)\}/g, (_, k) => args[Number(k)] ?? "") : out;
}

const TURKISH = /[çğıöşüÇĞİÖŞÜ]/;

function translateNode(node) {
  if (node.parentElement?.tagName === "TEXTAREA") return;      // its text is its value
  const raw = node.data;
  if (written.get(node) === raw) return;
  const text = raw.trim();
  if (!text || !/[A-Za-zÀ-ž]/.test(text)) return;
  const out = translateText(text.replace(/\s+/g, " "));
  if (out === null) {
    if (TURKISH.test(text)) missing.add(text);
    return;
  }
  const lead = raw.match(/^\s*/)[0], trail = raw.match(/\s*$/)[0];
  const next = lead + out + trail;
  written.set(node, next);
  if (next !== raw) node.data = next;
}

function translateAttrs(el) {
  for (const name of ATTRS) {
    const raw = el.getAttribute?.(name);
    if (!raw) continue;
    let seen = written.get(el);
    if (seen?.[name] === raw) continue;
    const out = translateText(raw.trim().replace(/\s+/g, " "));
    if (out === null) {
      if (TURKISH.test(raw)) missing.add(raw);
      continue;
    }
    seen = { ...(seen || {}), [name]: out };
    written.set(el, seen);
    if (out !== raw) el.setAttribute(name, out);
  }
}

const skipped = (el) => Boolean(el?.closest?.(SKIP));

function translateTree(root) {
  if (!root) return;
  if (root.nodeType === Node.TEXT_NODE) {
    if (!skipped(root.parentElement)) translateNode(root);
    return;
  }
  if (root.nodeType !== Node.ELEMENT_NODE || skipped(root)) return;
  translateAttrs(root);
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => (n.nodeType === Node.ELEMENT_NODE && n.matches(SKIP)
      ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  });
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (n.nodeType === Node.TEXT_NODE) translateNode(n);
    else translateAttrs(n);
  }
}

function observe() {
  new MutationObserver((records) => {
    for (const r of records) {
      if (r.type === "characterData") {
        if (!skipped(r.target.parentElement)) translateNode(r.target);
      } else if (r.type === "attributes") {
        if (!skipped(r.target)) translateAttrs(r.target);
      } else {
        if (skipped(r.target)) continue;
        for (const n of r.addedNodes) translateTree(n);
      }
    }
  }).observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS });
}

/** Load the dictionary and start translating; resolves before the app draws. */
export async function startI18n() {
  document.documentElement.lang = lang;
  if (lang === "tr") return;
  try {
    const res = await fetch(`/static/locales/${lang}.json`, { cache: "no-cache" });
    compile(await res.json());
  } catch {
    return;       // no dictionary: the Turkish interface stays
  }
  translateTree(document.body);
  document.title = t(document.title);
  observe();
  // for filling the dictionary: window.__i18nMissing() lists what stayed Turkish
  window.__i18nMissing = () => [...missing];
}

export function setLanguage(id) {
  try { localStorage.setItem(KEY, id); } catch { /* private window */ }
}
