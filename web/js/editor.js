// Markdown editor: a transparent <textarea> laid exactly over a highlighted
// mirror. Typing, undo, IME and selection stay native; the mirror only adds
// color. Edits go through execCommand("insertText") so toolbar actions and
// assistant edits land on the normal undo stack.
import { esc, mod } from "./util.js";

const TR = "A-Za-zÇĞİÖŞÜçğıöşü";
const TAG_RE = new RegExp(`(^|[\\s(])(#[${TR}][\\w\\-/${TR}]*)`, "g");
const LIST_RE = /^(\s*)([-*+]|\d+[.)])(\s+)(\[[ xX]\])?(\s*)(.*)$/;
const MARKER_RE = /^(\s*)(?:[-*+]\s+\[[ xX]\]\s+|[-*+]\s+|\d+[.)]\s+|>\s?)/;

function fmt(s) {
  if (!s) return "";
  let h = esc(s);
  h = h.replace(/(\*\*|__)(?=\S)(.+?)(?<=\S)\1/g, '<span class="b"><span class="mk">$1</span>$2<span class="mk">$1</span></span>');
  h = h.replace(/(^|[^*\w])([*_])(?=[^\s*_])([^*_]*?[^\s*_]|[^\s*_])\2(?![*\w])/g, '$1<span class="i"><span class="mk">$2</span>$3<span class="mk">$2</span></span>');
  h = h.replace(/~~(?=\S)(.+?)(?<=\S)~~/g, '<span class="s"><span class="mk">~~</span>$1<span class="mk">~~</span></span>');
  h = h.replace(/==(?=\S)(.+?)(?<=\S)==/g, '<span class="hl"><span class="mk">==</span>$1<span class="mk">==</span></span>');
  h = h.replace(/\[([^\]\n]+)\]\(([^)\s]+)\)/g, '<span class="lk"><span class="mk">[</span>$1<span class="mk">](</span><span class="url">$2</span><span class="mk">)</span></span>');
  h = h.replace(/(^|\s)(https?:\/\/[^\s<]+)/g, '$1<span class="lk"><span class="url">$2</span></span>');
  h = h.replace(TAG_RE, '$1<span class="tag">$2</span>');
  return h;
}

function inline(raw) {
  if (!raw) return "";
  let out = "", last = 0, m;
  const re = /(`+)(.+?)\1/g;
  while ((m = re.exec(raw))) {
    out += fmt(raw.slice(last, m.index)) + `<span class="ic">${esc(m[0])}</span>`;
    last = re.lastIndex;
  }
  return out + fmt(raw.slice(last));
}

function blockLine(line, addClass) {
  let m;
  if ((m = /^(#{1,6})(\s+)(.*)$/.exec(line))) {
    addClass(` hd h${m[1].length}`);
    return `<span class="mk">${m[1]}</span>${m[2]}${inline(m[3])}`;
  }
  if ((m = /^(\s*>+\s?)(.*)$/.exec(line))) {
    addClass(" bq");
    return `<span class="mk">${esc(m[1])}</span>${inline(m[2])}`;
  }
  if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
    addClass(" hr");
    return esc(line);
  }
  if ((m = LIST_RE.exec(line))) {
    const [, indent, marker, gap, box, gap2, rest] = m;
    let h = `${indent}<span class="li">${esc(marker)}</span>${gap}`;
    if (box) {
      const on = box[1] !== " ";
      if (on) addClass(" task-done");
      h += `<span class="cb${on ? " on" : ""}">${esc(box)}</span>${gap2}<span class="body">${inline(rest)}</span>`;
    } else {
      h += gap2 + inline(rest);
    }
    return h;
  }
  return inline(line);
}

/** Ranges of `text` that the assistant wrote (and you approved). Recomputed
 *  from the exact wording: edit the sentence and it becomes yours again. */
export function assistantRanges(text, written) {
  const ranges = [];
  for (const snippet of written || []) {
    const needle = (snippet || "").trim();
    if (needle.length < 12) continue;          // too short to identify anything
    let at = text.indexOf(needle);
    while (at !== -1) {
      ranges.push([at, at + needle.length]);
      at = text.indexOf(needle, at + needle.length);
    }
  }
  return ranges;
}

export function renderLines(text, flash, written) {
  const lines = text.split("\n");
  const out = new Array(lines.length);
  let inFront = lines.length > 1 && lines[0].trim() === "---" && lines.slice(1).some((l) => l.trim() === "---");
  let fence = null;
  let offset = 0;
  const ai = assistantRanges(text, written);
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    let cls = "ln";
    let body;
    if (inFront) {
      if (i === 0 || line.trim() === "---") {
        cls += " fm fm-edge";
        body = esc(line);
        if (i > 0) inFront = false;
      } else {
        cls += " fm";
        const kv = /^(\s*[\w-]+)(:)(.*)$/.exec(line);
        body = kv ? `<span class="k">${esc(kv[1])}</span><span class="mk">:</span>${esc(kv[3])}` : esc(line);
      }
    } else if (fence) {
      cls += " code";
      if (line.trimStart().startsWith(fence)) fence = null;
      body = esc(line);
    } else {
      const f = /^\s*(```+|~~~+)/.exec(line);
      if (f) {
        fence = f[1];
        cls += " code";
        body = esc(line);
      } else {
        body = blockLine(line, (c) => { cls += c; });
      }
    }
    const start = offset, end = offset + line.length;
    offset = end + 1;
    if (flash && line.trim() && end >= flash[0] && start < flash[1]) cls += " flash";
    const byAi = line.trim() && ai.some(([a, b]) => end > a && start < b);
    if (byAi) cls += " ai";
    out[i] = `<div class="${cls}"${byAi ? ' title="Asistanın yazdığı, senin onayladığın metin"' : ""}>`
      + `<span class="tx">${body}</span></div>`;
  }
  return out;
}

export class MarkdownEditor {
  constructor({ value = "", placeholder = "", onChange, onCursor, onAsk, onScroll } = {}) {
    this.onChange = onChange;
    this.onCursor = onCursor;
    this.onAsk = onAsk;
    this.onScroll = onScroll;
    this._lines = [];
    this._flash = null;
    this._written = [];
    this._flashTimer = 0;
    this._curLine = -1;

    this.root = document.createElement("div");
    this.root.className = "md-editor";
    this.root.innerHTML = `<div class="md-scroll"><div class="md-inner"><div class="md-mirror" aria-hidden="true"></div><textarea class="md-input" spellcheck="false" autocapitalize="off" autocomplete="off" aria-label="Not metni"></textarea></div></div>`;
    this.scroller = this.root.querySelector(".md-scroll");
    this.mirror = this.root.querySelector(".md-mirror");
    this.input = this.root.querySelector(".md-input");
    this.input.placeholder = placeholder;
    this.input.value = value;

    this.input.addEventListener("input", () => this._handleInput());
    this.input.addEventListener("keydown", (e) => this._keydown(e));
    for (const ev of ["keyup", "click", "focus", "select"]) this.input.addEventListener(ev, () => this._updateCursor());
    this.scroller.addEventListener("scroll", () => this.onScroll?.(), { passive: true });
    this._render();
  }

  get value() { return this.input.value; }

  get isVisible() { return this.root.classList.contains("active"); }

  /** Replace the whole text from outside (file reloaded). Not undoable. */
  setValue(text) {
    if (text === this.input.value) return;
    const { selectionStart: s, selectionEnd: e } = this.input;
    const top = this.scroller.scrollTop;
    this.input.value = text;
    this.input.setSelectionRange(Math.min(s, text.length), Math.min(e, text.length));
    this._render();
    this.scroller.scrollTop = top;
  }

  focus() { this.input.focus({ preventScroll: true }); }

  // ---------- rendering ----------
  _handleInput() {
    this._render();
    this._updateCursor();
    this.onChange?.(this.input.value);
  }

  _render() {
    this.mirror.children[this._curLine]?.classList.remove("cur"); // indices shift below
    const next = renderLines(this.input.value, this._flash, this._written);
    const prev = this._lines;
    let start = 0;
    const min = Math.min(prev.length, next.length);
    while (start < min && prev[start] === next[start]) start++;
    let endPrev = prev.length, endNext = next.length;
    while (endPrev > start && endNext > start && prev[endPrev - 1] === next[endNext - 1]) { endPrev--; endNext--; }
    const kids = this.mirror.children;
    for (let i = endPrev - 1; i >= start; i--) kids[i].remove();
    const chunk = next.slice(start, endNext).join("");
    if (chunk) {
      const ref = kids[start];
      if (ref) ref.insertAdjacentHTML("beforebegin", chunk);
      else this.mirror.insertAdjacentHTML("beforeend", chunk);
    }
    this._lines = next;
    this._curLine = -1;
    this._markCurrentLine();
  }

  cursorInfo() {
    const pos = this.input.selectionStart;
    const before = this.input.value.slice(0, pos);
    let line = 0;
    for (let i = before.indexOf("\n"); i !== -1; i = before.indexOf("\n", i + 1)) line++;
    return { line, col: pos - (before.lastIndexOf("\n") + 1), selected: Math.abs(this.input.selectionEnd - pos) };
  }

  _markCurrentLine() {
    const { line } = this.cursorInfo();
    if (line === this._curLine) return;
    this.mirror.children[this._curLine]?.classList.remove("cur");
    this.mirror.children[line]?.classList.add("cur");
    this._curLine = line;
  }

  _updateCursor() {
    this._markCurrentLine();
    this.onCursor?.(this.cursorInfo());
  }

  /** What the assistant wrote into this note, as exact text. */
  setWritten(texts) {
    const next = texts || [];
    if (next.length === this._written.length && next.every((s, i) => s === this._written[i])) return;
    this._written = next;
    this._render();
  }

  /** Briefly highlight [start, end]. reveal scrolls it into view — only for
   *  explicit jumps, never while the user is typing somewhere else. */
  flash(range, { reveal = false } = {}) {
    if (!range) return;
    // a note's first analysis covers the whole text; lighting up everything is just noise
    if (!reveal && range[1] - range[0] > this.input.value.length * 0.6 && range[1] - range[0] > 400) return;
    clearTimeout(this._flashTimer);
    this._flash = range;
    this._render();
    const line = this.lineAt(range[0]);
    const el = this.mirror.children[line];
    if (el && reveal) {
      const top = el.offsetTop, view = this.scroller;
      if (top < view.scrollTop || top > view.scrollTop + view.clientHeight - 60) {
        view.scrollTo({ top: Math.max(0, top - view.clientHeight / 3), behavior: "smooth" });
      }
    }
    this._flashTimer = setTimeout(() => { this._flash = null; this._render(); }, 6500);
  }

  lineAt(offset) {
    let line = 0;
    const v = this.input.value;
    for (let i = v.indexOf("\n"); i !== -1 && i < offset; i = v.indexOf("\n", i + 1)) line++;
    return line;
  }

  topLine() {
    const kids = this.mirror.children;
    const y = this.scroller.scrollTop;
    let lo = 0, hi = kids.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (kids[mid].offsetTop <= y) lo = mid; else hi = mid - 1;
    }
    return lo;
  }

  scrollFraction() {
    const s = this.scroller;
    const max = s.scrollHeight - s.clientHeight;
    return max > 0 ? s.scrollTop / max : 0;
  }

  // ---------- editing primitives ----------
  replaceRange(start, end, text, selStart = start + text.length, selEnd = selStart) {
    const el = this.input;
    let ok = false;
    if (this.isVisible) {
      el.focus({ preventScroll: true });
      el.setSelectionRange(start, end);
      ok = text === "" ? (start === end || document.execCommand("delete")) : document.execCommand("insertText", false, text);
    }
    if (!ok) {
      el.setRangeText(text, start, end, "end");
      this._handleInput();
    }
    el.setSelectionRange(selStart, selEnd);
    this._updateCursor();
  }

  wrap(before, after, placeholder) {
    const { selectionStart: s, selectionEnd: e, value: v } = this.input;
    const sel = v.slice(s, e);
    if (s >= before.length && v.slice(s - before.length, s) === before && v.slice(e, e + after.length) === after) {
      this.replaceRange(s - before.length, e + after.length, sel, s - before.length, e - before.length);
      return;
    }
    if (sel.length > before.length + after.length && sel.startsWith(before) && sel.endsWith(after)) {
      const inner = sel.slice(before.length, sel.length - after.length);
      this.replaceRange(s, e, inner, s, s + inner.length);
      return;
    }
    const inner = sel || placeholder;
    this.replaceRange(s, e, before + inner + after, s + before.length, s + before.length + inner.length);
  }

  _lineBlock() {
    const v = this.input.value;
    const s = this.input.selectionStart;
    let e = this.input.selectionEnd;
    if (e > s && v[e - 1] === "\n") e--;
    const start = v.lastIndexOf("\n", s - 1) + 1;
    let end = v.indexOf("\n", e);
    if (end === -1) end = v.length;
    return { start, end, lines: v.slice(start, end).split("\n") };
  }

  _replaceLines(transform) {
    const { start, end, lines } = this._lineBlock();
    const text = transform(lines).join("\n");
    if (text === lines.join("\n")) return;
    if (lines.length === 1) {
      const delta = text.length - (end - start);
      const { selectionStart: s, selectionEnd: e } = this.input;
      this.replaceRange(start, end, text, Math.max(start, s + delta), Math.max(start, e + delta));
    } else {
      this.replaceRange(start, end, text, start, start + text.length);
    }
  }

  heading(level) {
    const exact = new RegExp(`^#{${level}}\\s`);
    this._replaceLines((lines) => {
      const all = lines.every((l) => exact.test(l));
      return lines.map((l) => {
        const bare = l.replace(/^#{1,6}\s+/, "");
        return all ? bare : `${"#".repeat(level)} ${bare}`;
      });
    });
  }

  list(kind) {
    const is = {
      ul: /^\s*[-*+]\s+(?!\[[ xX]\])/,
      ol: /^\s*\d+[.)]\s+/,
      task: /^\s*[-*+]\s+\[[ xX]\]\s+/,
      quote: /^\s*>\s?/,
    }[kind];
    this._replaceLines((lines) => {
      const filled = lines.filter((l) => l.trim());
      const all = filled.length > 0 && filled.every((l) => is.test(l));
      let n = 0;
      return lines.map((l) => {
        if (!l.trim() && lines.length > 1) return l;
        const m = MARKER_RE.exec(l);
        const indent = m ? m[1] : l.match(/^\s*/)[0];
        const body = m ? l.slice(m[0].length) : l.slice(indent.length);
        if (all) return indent + body;
        n++;
        const marker = { ul: "- ", ol: `${n}. `, task: "- [ ] ", quote: "> " }[kind];
        return indent + marker + body;
      });
    });
  }

  link() {
    const { selectionStart: s, selectionEnd: e, value: v } = this.input;
    const sel = v.slice(s, e);
    if (/^https?:\/\/\S+$/.test(sel)) {
      const text = `[bağlantı](${sel})`;
      this.replaceRange(s, e, text, s + 1, s + 9);
    } else {
      const label = sel || "bağlantı";
      const text = `[${label}](https://)`;
      const urlStart = s + label.length + 3;
      this.replaceRange(s, e, text, urlStart, urlStart + 8);
    }
  }

  image() {
    const { selectionStart: s, selectionEnd: e, value: v } = this.input;
    const alt = v.slice(s, e) || "görsel";
    const text = `![${alt}](resim.png)`;
    const at = s + alt.length + 4;
    this.replaceRange(s, e, text, at, at + 9);
  }

  code() {
    const { selectionStart: s, selectionEnd: e, value: v } = this.input;
    const sel = v.slice(s, e);
    if (sel.includes("\n")) {
      const block = `\`\`\`\n${sel.replace(/\n$/, "")}\n\`\`\``;
      this.replaceRange(s, e, block, s + 4, s + 4 + sel.replace(/\n$/, "").length);
    } else {
      this.wrap("`", "`", "kod");
    }
  }

  indent(direction) {
    const { selectionStart: s, selectionEnd: e } = this.input;
    const { lines } = this._lineBlock();
    if (direction > 0 && s === e && lines.length === 1 && !MARKER_RE.test(lines[0])) {
      this.replaceRange(s, e, "  ");
      return;
    }
    this._replaceLines((ls) => ls.map((l) => (direction > 0 ? `  ${l}` : l.replace(/^( {1,2}|\t)/, ""))));
  }

  applyEdit(original, replacement) {
    const v = this.input.value;
    const at = v.indexOf(original);
    if (at === -1) return false;
    const { selectionStart: s, selectionEnd: e } = this.input;
    const delta = replacement.length - original.length;
    const shift = (p) => (p >= at + original.length ? p + delta : Math.min(p, at + replacement.length));
    this.replaceRange(at, at + original.length, replacement, shift(s), shift(e));
    this.flash([at, at + replacement.length], { reveal: true });
    return true;
  }

  appendText(text) {
    const v = this.input.value;
    const prefix = !v || v.endsWith("\n\n") ? "" : v.endsWith("\n") ? "\n" : "\n\n";
    const start = v.length + prefix.length;
    const insert = `${prefix}${text.trim()}\n`;
    this.replaceRange(v.length, v.length, insert, v.length + insert.length);
    this.flash([start, start + text.trim().length], { reveal: true });
  }

  toggleTaskAtLine(lineIndex) {
    const v = this.input.value;
    let start = 0;
    for (let i = 0; i < lineIndex; i++) {
      const nl = v.indexOf("\n", start);
      if (nl === -1) return;
      start = nl + 1;
    }
    let end = v.indexOf("\n", start);
    if (end === -1) end = v.length;
    const m = /^(\s*[-*+]\s+)\[([ xX])\]/.exec(v.slice(start, end));
    if (!m) return;
    const at = start + m[1].length + 1;
    const { selectionStart: s, selectionEnd: e } = this.input;
    this.replaceRange(at, at + 1, m[2] === " " ? "x" : " ", s, e);
  }

  _continueList() {
    const { selectionStart: s, selectionEnd: e, value: v } = this.input;
    if (s !== e) return false;
    const ls = v.lastIndexOf("\n", s - 1) + 1;
    let le = v.indexOf("\n", s);
    if (le === -1) le = v.length;
    const line = v.slice(ls, le);
    const m = /^(\s*)([-*+]|(\d+)([.)]))(\s+)(\[[ xX]\]\s+)?/.exec(line) || /^(\s*)(>)()()(\s?)()/.exec(line);
    if (!m || s < ls + m[0].length) return false;
    if (!line.slice(m[0].length).trim()) {
      if (s !== le) return false;
      this.replaceRange(ls, le, "", ls);
      return true;
    }
    const marker = m[3] ? `${Number(m[3]) + 1}${m[4]}` : m[2];
    this.replaceRange(s, s, `\n${m[1]}${marker}${m[5] || " "}${m[6] ? "[ ] " : ""}`);
    return true;
  }

  _keydown(e) {
    if (e.isComposing) return;
    const m = mod(e);
    if (m && !e.altKey && !e.shiftKey) {
      const key = e.key.toLowerCase();
      const actions = {
        b: () => this.wrap("**", "**", "kalın metin"),
        i: () => this.wrap("*", "*", "italik metin"),
        k: () => this.link(),
        e: () => this.code(),
      };
      if (actions[key]) {
        e.preventDefault();
        actions[key]();
        return;
      }
      if (e.key === "Enter") {
        e.preventDefault();
        this.onAsk?.();
        return;
      }
    }
    if (e.key === "Tab" && !m && !e.altKey) {
      e.preventDefault();
      this.indent(e.shiftKey ? -1 : 1);
      return;
    }
    if (e.key === "Enter" && !e.shiftKey && !m && !e.altKey) {
      if (this._continueList()) e.preventDefault();
    }
  }

  destroy() {
    clearTimeout(this._flashTimer);
    this.root.remove();
  }
}
