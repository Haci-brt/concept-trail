import { locale } from "./i18n.js";

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ESC[c]);

/** Build an element from an HTML string (single root). */
export function html(markup) {
  const t = document.createElement("template");
  t.innerHTML = markup.trim();
  return t.content.firstElementChild;
}

export function debounce(fn, ms) {
  let timer;
  const wrapped = (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
  wrapped.cancel = () => clearTimeout(timer);
  return wrapped;
}

/** Case- and dotted/dotless-i-insensitive form, mirrors server/vault.py fold(). */
export const fold = (s) =>
  String(s ?? "").replace(/[İIı]/g, "i").toLocaleLowerCase("tr").normalize("NFC");

export function fuzzyScore(query, target) {
  const q = fold(query), t = fold(target);
  if (!q) return 1;
  const idx = t.indexOf(q);
  if (idx === 0) return 1000 - t.length;
  if (idx > 0) return 700 - idx - t.length / 10;
  let ti = 0, score = 0, streak = 0;
  for (const ch of q) {
    const found = t.indexOf(ch, ti);
    if (found === -1) return -1;
    streak = found === ti ? streak + 1 : 0;
    score += 10 + streak * 5 - (found - ti);
    ti = found + 1;
  }
  return Math.max(1, score);
}

export function formatClock(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const now = new Date();
  const hm = d.toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === now.toDateString()) return hm;
  const y = new Date(now); y.setDate(now.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return `Dün ${hm}`;
  return d.toLocaleDateString(locale(), { day: "numeric", month: "short" });
}

export function relativeSaved(date) {
  if (!date) return "";
  const s = Math.round((Date.now() - date.getTime()) / 1000);
  if (s < 45) return "az önce";
  if (s < 3600) return `${Math.round(s / 60)} dk önce`;
  return date.toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" });
}

export function wordCount(text) {
  const m = text.match(/[^\s]+/g);
  return m ? m.length : 0;
}

/** Split "Soru cümlesi? Ek açıklama." into a bold title and a softer subtitle. */
export function splitSentence(text) {
  const t = String(text ?? "").trim();
  const m = t.match(/^(.+?[?.!…])\s+(\S.*)$/s);
  if (m && m[1].length >= 12) return [m[1], m[2]];
  return [t, ""];
}

let toastHost;
export function toast(message, kind = "info", ms = 3200) {
  toastHost ??= document.body.appendChild(html('<div class="toasts" role="status" aria-live="polite"></div>'));
  const el = html(`<div class="toast toast-${kind}">${esc(message)}</div>`);
  toastHost.appendChild(el);
  requestAnimationFrame(() => el.classList.add("in"));
  setTimeout(() => {
    el.classList.remove("in");
    setTimeout(() => el.remove(), 250);
  }, ms);
}

export const isMac = navigator.platform.toUpperCase().includes("MAC");
export const mod = (e) => (isMac ? e.metaKey : e.ctrlKey);
