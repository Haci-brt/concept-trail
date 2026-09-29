// Markdown editor: a transparent <textarea> laid exactly over a highlighted
// mirror. Typing, undo, IME and selection stay native; the mirror only adds
// color. Edits go through execCommand("insertText") so toolbar actions and
// assistant edits land on the normal undo stack.
import { esc, mod } from "./util.js";

const TR = "A-Za-zÇĞİÖŞÜçğıöşü";
const TAG_RE = new RegExp(`(^|[\\s(])(#[${TR}][\\w\\-/${TR}]*)`, "g");
const LIST_RE = /^(\s*)([-*+]|\d+[.)])(\s+)(\[[ xX]\])?(\s*)(.*)$/;
const MARKER_RE = /^(\s*)(?:[-*+]\s+\[[ xX]\]\s+|[-*+]\s+|\d+[.)]\s+|>\s?)/;
// how long a pause at the end of a line before the rest of it is suggested
const SUGGEST_IDLE_MS = 700;

/** Headings for the editor's local chapter picker. Code and frontmatter are
 *  skipped so a `#` example does not become a false navigation target. */
export function headingsOf(text) {
  const lines = text.split("\n");
  const headings = [];
  let offset = 0;
  let frontmatter = lines.length > 1 && lines[0].trim() === "---" && lines.slice(1).some((line) => line.trim() === "---");
  let fence = null;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();
    if (frontmatter) {
      if (i > 0 && trimmed === "---") frontmatter = false;
    } else if (fence) {
      if (trimmed.startsWith(fence)) fence = null;
    } else {
      const opening = /^(`{3,}|~{3,})/.exec(trimmed);
      if (opening) fence = opening[1];
      else {
        const match = /^(#{1,6})[ \t]+(.+?)\s*$/.exec(line);
        if (match) headings.push({ level: match[1].length, text: match[2].replace(/\s+#+\s*$/, "").trim(), offset, line: i });
      }
    }
    offset += line.length + 1;
  }
  return headings;
}

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

// A line's markup depends only on its own text (outside front matter and code
// fences), so it is worked out once and remembered: every keystroke used to
// run the inline patterns over every line (843 lines: 14 ms a keystroke).
const LINE_CACHE = new Map();
function cachedBlock(line) {
  let hit = LINE_CACHE.get(line);
  if (hit === undefined) {
    let cls = "";
    const body = blockLine(line, (c) => { cls += c; });
    hit = [cls, body];
    if (LINE_CACHE.size > 20000) LINE_CACHE.clear();
    LINE_CACHE.set(line, hit);
  }
  return hit;
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
        const [extra, markup] = cachedBlock(line);
        cls += extra;
        body = markup;
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
  constructor({ value = "", placeholder = "", onChange, onCursor, onAsk, onScroll, suggest } = {}) {
    this.onChange = onChange;
    this.onCursor = onCursor;
    this.onAsk = onAsk;
    this.onScroll = onScroll;
    // suggest(before, after, signal) -> Promise<string>: the rest of the line
    this.suggest = suggest;
    this._ghost = null;               // { text, at }: the suggestion showing after the cursor
    this._ghostNext = null;           // what is left of it after taking one word
    this._suggestTimer = 0;
    this._suggestAbort = null;
    this._lastAskKey = "";
    this._lines = [];
    this._flash = null;
    this._written = [];
    this._flashTimer = 0;
    this._curLine = -1;
    this._headingSource = null;
    this._headings = [];

    this.root = document.createElement("div");
    this.root.className = "md-editor";
    this.root.innerHTML = `<nav class="md-chapterbar" aria-label="Not bölümleri">
      <span class="md-chapter-kicker">BÖLÜM</span>
      <span class="md-chapter-picker"><select aria-label="Bölüme git"><option value="start">Başlangıç</option></select></span>
      <span class="md-chapter-count" aria-hidden="true"></span>
      <button type="button" class="md-chapter-nav" data-nav="prev" title="Önceki başlık" aria-label="Önceki başlık">↑</button>
      <button type="button" class="md-chapter-nav" data-nav="next" title="Sonraki başlık" aria-label="Sonraki başlık">↓</button>
      <span class="md-chapter-progress" aria-hidden="true"></span>
    </nav><div class="md-scroll"><div class="md-inner"><div class="md-mirror" aria-hidden="true"></div><textarea class="md-input" spellcheck="false" autocapitalize="off" autocomplete="off" aria-label="Not metni"></textarea></div></div>`;
    this.scroller = this.root.querySelector(".md-scroll");
    this.mirror = this.root.querySelector(".md-mirror");
    this.input = this.root.querySelector(".md-input");
    this.chapterSelect = this.root.querySelector(".md-chapter-picker select");
    this.input.placeholder = placeholder;
    this.input.value = value;

    this.input.addEventListener("input", (e) => this._handleInput(e));
    this.input.addEventListener("keydown", (e) => this._keydown(e));
    for (const ev of ["keyup", "click", "focus", "select"]) this.input.addEventListener(ev, () => this._updateCursor());
    this.input.addEventListener("blur", () => { clearTimeout(this._suggestTimer); this._clearGhost(); });
    this.chapterSelect.addEventListener("change", () => {
      const index = Number(this.chapterSelect.value);
      this.jumpToHeading(Number.isInteger(index) && this.chapterSelect.value !== "start" ? index : -1);
    });
    this.root.querySelector(".md-chapterbar").addEventListener("click", (event) => {
      const direction = event.target.closest("[data-nav]")?.dataset.nav;
      if (direction) this.jumpToHeading(direction);
    });
    this.scroller.addEventListener("scroll", () => this.onScroll?.(), { passive: true });
    this._render();
  }

  get value() { return this.input.value; }

  get isVisible() { return this.root.classList.contains("active"); }

  /** Replace the whole text from outside (file reloaded). Not undoable. */
  setValue(text) {
    if (text === this.input.value) return;
    this._clearGhost();
    const { selectionStart: s, selectionEnd: e } = this.input;
    const top = this.scroller.scrollTop;
    this.input.value = text;
    this.input.setSelectionRange(Math.min(s, text.length), Math.min(e, text.length));
    this._render();
    this.scroller.scrollTop = top;
  }

  focus() { this.input.focus({ preventScroll: true }); }

  // ---------- rendering ----------
  _handleInput(event) {
    this._followGhost(event);
    this._render();
    this._updateCursor();
    // something was put in whole (pasted or dropped) rather than typed
    const pasted = event?.inputType === "insertFromPaste" || event?.inputType === "insertFromDrop";
    this.onChange?.(this.input.value, { pasted });
    if (!this._ghost) this._scheduleSuggest();
  }

  // ---------- the rest of the line, suggested ----------
  // Like a code editor's inline completion: a pause at the end of a line
  // asks for the rest of it, which shows in faint text after the cursor. Tab
  // takes it, Ctrl+→ one word of it, Esc (or going on otherwise) drops it,
  // Ctrl+Space asks at once. Typing the very letters it shows keeps it. It is
  // only ever the writer's key that puts it into the note — and then as one
  // step on the ordinary undo stack.

  _scheduleSuggest(delay = SUGGEST_IDLE_MS) {
    clearTimeout(this._suggestTimer);
    this._suggestAbort?.abort();
    if (this.suggest) this._suggestTimer = setTimeout(() => this._askSuggestion(false), delay);
  }

  async _askSuggestion(force) {
    const el = this.input;
    if (!this.suggest || document.activeElement !== el || el.selectionStart !== el.selectionEnd) return;
    const value = el.value, at = el.selectionStart;
    if (value[at] !== undefined && value[at] !== "\n") return;          // only at the end of a line
    const line = value.slice(value.lastIndexOf("\n", at - 1) + 1, at);
    // a bare list marker or heading sign is too little to go on
    if (!force && line.replace(/^[\s>#*+\-\d.)[\]xX]+/, "").trim().length < 3) return;
    const before = value.slice(0, at), after = value.slice(at);
    const key = `${before.slice(-300)}\u0000${after.slice(0, 80)}`;
    if (!force && key === this._lastAskKey) return;                    // asked already, got nothing
    this._lastAskKey = key;
    this._suggestAbort?.abort();
    const abort = new AbortController();
    this._suggestAbort = abort;
    let text = "";
    try { text = await this.suggest(before, after, abort.signal); } catch { return; }
    if (abort.signal.aborted || !text || el.value !== value || document.activeElement !== el
        || el.selectionStart !== at || el.selectionEnd !== at) return;
    this._ghost = { text, at };
    this._attachGhost();
  }

  /** Take the suggestion — all of it, or its next word. */
  acceptGhost(wordOnly = false) {
    const ghost = this._ghost;
    if (!ghost) return false;
    const take = wordOnly ? (/^\s*\S+/.exec(ghost.text)?.[0] || ghost.text) : ghost.text;
    const rest = ghost.text.slice(take.length);
    this._ghost = null;
    this._ghostNext = rest.trim() ? { text: rest, at: ghost.at + take.length } : null;
    this.replaceRange(ghost.at, ghost.at, take);
    return true;
  }

  /** On an edit: typing the very letters the suggestion shows keeps the rest
   *  of it; taking a word leaves the rest; anything else drops it. */
  _followGhost(event) {
    const el = this.input, pos = el.selectionStart;
    const next = this._ghostNext;
    this._ghostNext = null;
    if (next && pos === next.at && el.selectionEnd === pos) { this._ghost = next; return; }
    const ghost = this._ghost;
    if (!ghost) return;
    const typed = event?.inputType === "insertText" ? event.data : null;
    if (typed && ghost.text.startsWith(typed) && pos === ghost.at + typed.length && el.selectionEnd === pos) {
      const rest = ghost.text.slice(typed.length);
      this._ghost = rest.trim() ? { text: rest, at: pos } : null;
    } else {
      this._ghost = null;
    }
  }

  /** Draw the suggestion into the mirror, after the text of its line. The
   *  textarea never holds it; only the mirror shows it. */
  _attachGhost() {
    this.mirror.querySelector(".ghost")?.remove();
    const ghost = this._ghost;
    if (!ghost) return;
    let line = 0;
    const text = this.input.value;
    for (let i = text.indexOf("\n"); i !== -1 && i < ghost.at; i = text.indexOf("\n", i + 1)) line++;
    const tx = this.mirror.children[line]?.querySelector(".tx");
    if (!tx) return;
    const span = document.createElement("span");
    span.className = "ghost";
    span.textContent = ghost.text;
    tx.append(span);
  }

  _clearGhost() {
    this._ghost = null;
    this._ghostNext = null;
    this.mirror.querySelector(".ghost")?.remove();
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
    // line numbers are an attribute, written only where they changed: as a
    // CSS counter, every keystroke renumbered — and laid out again — every
    // line after it (95k characters: a third of a keystroke's layout)
    const renumberTo = prev.length === next.length ? endNext : next.length;
    for (let i = start; i < renumberTo; i++) kids[i].dataset.n = i + 1;
    this._lines = next;
    this._curLine = -1;
    this._markCurrentLine();
    this._refreshHeadings();
    this._attachGhost();
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
    const ghost = this._ghost;
    if (ghost && (this.input.selectionStart !== ghost.at || this.input.selectionEnd !== ghost.at)) this._clearGhost();
    this._markCurrentLine();
    this._updateChapter();
    this.onCursor?.(this.cursorInfo());
  }

  _refreshHeadings() {
    const text = this.input.value;
    if (text !== this._headingSource) {
      this._headingSource = text;
      this._headings = headingsOf(text);
      // the list is rebuilt only when the headings themselves changed, not at
      // every keystroke (a long note: 480 options rebuilt per letter typed)
      const names = this._headings.map((h) => `${h.level} ${h.text}`).join("|");
      if (names !== this._headingNames) {
        this._headingNames = names;
        this.chapterSelect.replaceChildren(new Option("Başlangıç", "start"));
        this._headings.forEach((heading, index) => {
          this.chapterSelect.add(new Option(`${"  ".repeat(heading.level - 1)}${heading.text}`, String(index)));
        });
      }
    }
    this._updateChapter();
  }

  _updateChapter() {
    const pos = this.input.selectionStart;
    let current = -1;
    for (let i = 0; i < this._headings.length && this._headings[i].offset <= pos; i++) current = i;
    this.chapterSelect.value = current < 0 ? "start" : String(current);
    const count = this.root.querySelector(".md-chapter-count");
    count.textContent = this._headings.length ? `${current + 1} / ${this._headings.length}` : "Başlık yok";
    this.root.querySelector('[data-nav="prev"]').disabled = current < 0;
    this.root.querySelector('[data-nav="next"]').disabled = current >= this._headings.length - 1;
    const progress = this.root.querySelector(".md-chapter-progress");
    progress.style.width = `${this.input.value.length ? Math.round(pos / this.input.value.length * 100) : 0}%`;
  }

  jumpToHeading(target) {
    const pos = this.input.selectionStart;
    const current = this._headings.reduce((last, heading, index) => heading.offset <= pos ? index : last, -1);
    const index = target === "prev" ? current - 1 : target === "next" ? current + 1 : target;
    const heading = this._headings[index];
    const offset = heading ? heading.offset + heading.level + 1 : 0;
    this.focus();
    this.input.setSelectionRange(offset, offset);
    this._updateCursor();
    const line = heading?.line ?? 0;
    const top = this.mirror.children[line]?.offsetTop ?? 0;
    this.scroller.scrollTo({ top: Math.max(0, top - this.scroller.clientHeight * 0.2), behavior: "smooth" });
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
    if (this.isVisible) el.focus({ preventScroll: true });
    // an editor hidden behind the idea tree cannot take focus, and execCommand
    // would then type into whatever has it — the chat box, say
    if (document.activeElement === el) {
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

  /** A change the writer approved elsewhere: undoable like typing, while the
   *  box they are writing in (the chat, say) keeps its focus. */
  _fromOutside(change) {
    const had = document.activeElement;
    change();
    if (had !== this.input && had?.isConnected && had.matches("textarea, input")) had.focus({ preventScroll: true });
  }

  applyEdit(original, replacement) {
    const v = this.input.value;
    const at = v.indexOf(original);
    if (at === -1) return false;
    const { selectionStart: s, selectionEnd: e } = this.input;
    const delta = replacement.length - original.length;
    const shift = (p) => (p >= at + original.length ? p + delta : Math.min(p, at + replacement.length));
    this._fromOutside(() => this.replaceRange(at, at + original.length, replacement, shift(s), shift(e)));
    this.flash([at, at + replacement.length], { reveal: true });
    return true;
  }

  appendText(text) {
    const v = this.input.value;
    const prefix = !v || v.endsWith("\n\n") ? "" : v.endsWith("\n") ? "\n" : "\n\n";
    const start = v.length + prefix.length;
    const insert = `${prefix}${text.trim()}\n`;
    this._fromOutside(() => this.replaceRange(v.length, v.length, insert, v.length + insert.length));
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
    if (this._ghost) {
      if (e.key === "Tab" && !m && !e.altKey && !e.shiftKey) { e.preventDefault(); this.acceptGhost(); return; }
      if (e.key === "ArrowRight" && m && !e.altKey && !e.shiftKey) { e.preventDefault(); this.acceptGhost(true); return; }
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); this._clearGhost(); return; }
    }
    if (e.key === " " && m && !e.altKey && !e.shiftKey) {
      e.preventDefault();
      clearTimeout(this._suggestTimer);
      this._askSuggestion(true);
      return;
    }
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
