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

/** A few lines of the model's text as safe HTML: every character escaped,
 *  then only "- " / "1. " lists and **bold** turned into markup. */
export function miniMarkdown(text) {
  const inline = (s) => esc(s).replace(/\*\*(?=\S)(.+?)(?<=\S)\*\*/g, "<strong>$1</strong>");
  const out = [];
  let list = null, para = [];
  const flushPara = () => { if (para.length) out.push(`<p>${para.map(inline).join("<br>")}</p>`); para = []; };
  const flushList = () => { if (list) out.push(`<${list.tag}>${list.items.map((i) => `<li>${inline(i)}</li>`).join("")}</${list.tag}>`); list = null; };
  for (const line of String(text ?? "").split("\n")) {
    const m = /^\s*(?:([-*•])|(\d+)[.)])\s+(.*)$/.exec(line);
    if (m) {
      const tag = m[1] ? "ul" : "ol";
      flushPara();
      if (list?.tag !== tag) { flushList(); list = { tag, items: [] }; }
      list.items.push(m[3]);
    } else if (!line.trim()) {
      flushPara(); flushList();
    } else if (list && /^\s{2,}\S/.test(line)) {
      list.items[list.items.length - 1] += ` ${line.trim()}`;    // a wrapped list item
    } else {
      flushList();
      para.push(line);
    }
  }
  flushPara(); flushList();
  return out.join("");
}

let toastHost;
/** opts.action + opts.onAction put a button in the toast ("Geri al");
 *  opts.onClick makes the whole toast a button. */
export function toast(message, kind = "info", ms = 3200, { action, onAction, onClick } = {}) {
  toastHost ??= document.body.appendChild(html('<div class="toasts" role="status" aria-live="polite"></div>'));
  const el = html(`<div class="toast toast-${kind}"><span class="toast-msg">${esc(message)}</span></div>`);
  let timer = 0;
  const dismiss = () => {
    clearTimeout(timer);
    el.classList.remove("in");
    setTimeout(() => el.remove(), 250);
  };
  if (action) {
    const button = html(`<button type="button" class="toast-action">${esc(action)}</button>`);
    button.addEventListener("click", () => { dismiss(); onAction?.(); });
    el.append(button);
    el.classList.add("actionable");
  }
  if (onClick) {
    el.classList.add("actionable", "clickable");
    el.setAttribute("role", "button");
    el.tabIndex = 0;
    el.addEventListener("click", (e) => { if (!e.target.closest(".toast-action")) { dismiss(); onClick(); } });
  }
  toastHost.appendChild(el);
  requestAnimationFrame(() => el.classList.add("in"));
  timer = setTimeout(dismiss, ms);
  return { dismiss, el };
}

export const isMac = navigator.platform.toUpperCase().includes("MAC");
export const mod = (e) => (isMac ? e.metaKey : e.ctrlKey);

const FOCUSABLE = "a[href], button, input:not([type=hidden]), select, textarea, summary, "
  + "[contenteditable]:not([contenteditable=false]), [tabindex]";
const focusTraps = [];

/** Keeps Tab / Shift+Tab inside an open dialog, and gives focus back to what
 *  had it before once the dialog closes. Call it when the dialog is in the
 *  page, before focusing anything in it; call what it returns on close. Only
 *  the newest open dialog traps, so one opened over another works. Tab moves
 *  as the browser moves it; only a step that would leave the dialog wraps. */
export function trapFocus(root) {
  const opener = document.activeElement;
  const trap = { root };
  const onKey = (e) => {
    if (e.key !== "Tab" || e.defaultPrevented || e.ctrlKey || e.altKey || e.metaKey) return;
    if (focusTraps.at(-1) !== trap || !root.isConnected) return;
    const items = $$(FOCUSABLE, root).filter((el) => !el.disabled && el.tabIndex >= 0
      && el.getClientRects().length && getComputedStyle(el).visibility !== "hidden");
    const at = document.activeElement;
    const way = e.shiftKey ? Node.DOCUMENT_POSITION_PRECEDING : Node.DOCUMENT_POSITION_FOLLOWING;
    if (root.contains(at) && items.some((el) => el !== at && at.compareDocumentPosition(el) & way)) return;
    e.preventDefault();
    (e.shiftKey ? items.at(-1) : items[0])?.focus();
  };
  document.addEventListener("keydown", onKey);
  focusTraps.push(trap);
  let released = false;
  return () => {
    if (released) return;
    released = true;
    document.removeEventListener("keydown", onKey);
    focusTraps.splice(focusTraps.indexOf(trap), 1);
    // only when focus is still in the dialog or lost: not when the closing
    // action already sent it somewhere on purpose
    const at = document.activeElement;
    if (at && at !== document.body && !root.contains(at)) return;
    if (opener && opener !== document.body && opener.isConnected) opener.focus({ preventScroll: true });
  };
}
