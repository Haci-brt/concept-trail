// Ctrl+P: fuzzy note switcher, full-text + #tag search, and ">" commands.
import { api } from "./api.js";
import { icon } from "./icons.js";
import { debounce, esc, fold, fuzzyScore, html, trapFocus } from "./util.js";

function highlight(name, query) {
  const i = fold(name).indexOf(fold(query));
  if (!query || i === -1) return esc(name);
  return `${esc(name.slice(0, i))}<mark>${esc(name.slice(i, i + query.length))}</mark>${esc(name.slice(i + query.length))}`;
}

export class Palette {
  constructor({ notes, open, create, commands }) {
    this.notes = notes;
    this.onOpen = open;
    this.onCreate = create;
    this.commands = commands;
    this.el = null;
    this.items = [];
    this.index = 0;
    this.contentResults = [];
    this.searchSeq = 0;
    this._search = debounce((q) => this._contentSearch(q), 140);
  }

  get isOpen() { return Boolean(this.el); }

  open(query = "") {
    if (this.el) {
      this.input.value = query;
      this._update();
      this.input.focus();
      return;
    }
    this.overlay = html('<div class="overlay" style="background:rgba(8,6,14,.35)"></div>');
    this.el = html(`<div class="palette" role="dialog" aria-label="Not ara">
      <div class="pal-search">${icon("search", 18)}<input type="text" spellcheck="false" placeholder="Not ara... (Ctrl+P)   ·   > komutlar   ·   #etiket" aria-label="Arama"></div>
      <div class="pal-list" role="listbox"></div>
      <div class="pal-foot">
        <span><kbd>↑</kbd><kbd>↓</kbd> Gezin</span><span><kbd>Enter</kbd> Aç</span><span><kbd>Esc</kbd> Kapat</span>
      </div>
    </div>`);
    document.body.append(this.overlay, this.el);
    this._releaseFocus = trapFocus(this.el);
    this.input = this.el.querySelector("input");
    this.list = this.el.querySelector(".pal-list");
    this.input.value = query;
    this.input.addEventListener("input", () => this._update());
    this.input.addEventListener("keydown", (e) => this._key(e));
    this.overlay.addEventListener("mousedown", () => this.close());
    this.list.addEventListener("mousemove", (e) => {
      const row = e.target.closest(".pal-item");
      if (row && Number(row.dataset.i) !== this.index) this._select(Number(row.dataset.i));
    });
    this.list.addEventListener("click", (e) => {
      const row = e.target.closest(".pal-item");
      if (row) this._run(Number(row.dataset.i));
    });
    this._update();
    this.input.focus();
    this.input.select();
  }

  close() {
    if (!this.el) return;
    this.searchSeq++;
    this.el.remove();
    this.overlay.remove();
    this.el = null;
    this._releaseFocus?.();
  }

  _update() {
    const q = this.input.value;
    this.contentResults = [];
    this.index = 0;
    this._build();
    const trimmed = q.trim();
    if (!trimmed.startsWith(">") && (trimmed.length >= 2 || (trimmed.startsWith("#") && trimmed.length > 1))) {
      this._search(trimmed);
    }
  }

  async _contentSearch(q) {
    const seq = ++this.searchSeq;
    try {
      const results = await api.get("/api/vault/search", { q });
      if (seq !== this.searchSeq || !this.el || this.input.value.trim() !== q) return;
      this.contentResults = results;
      this._build(true);
    } catch { /* search is best-effort */ }
  }

  _build(keepIndex = false) {
    const raw = this.input.value;
    const q = raw.trim();
    const items = [];

    if (q.startsWith(">")) {
      const cq = q.slice(1).trim();
      for (const cmd of this.commands()) {
        const score = fuzzyScore(cq, cmd.label);
        if (score >= 0) items.push({ kind: "command", score, ...cmd });
      }
      items.sort((a, b) => b.score - a.score);
    } else {
      const isTag = q.startsWith("#");
      const nameHits = new Set();
      if (!isTag) {
        const scored = this.notes()
          .map((n) => ({ n, score: q ? Math.max(fuzzyScore(q, n.name), fuzzyScore(q, n.path) - 200) : n.mtime || 0 }))
          .filter((x) => x.score >= 0)
          .sort((a, b) => b.score - a.score)
          .slice(0, q ? 20 : 12);
        if (scored.length) items.push({ kind: "group", label: q ? "Notlar" : "Son düzenlenenler" });
        for (const { n } of scored) {
          nameHits.add(n.path);
          items.push({ kind: "note", path: n.path, name: n.name });
        }
      }
      const content = this.contentResults.filter((r) => !nameHits.has(r.path));
      if (content.length) items.push({ kind: "group", label: isTag ? `${q} etiketli notlar` : "İçerikte geçenler" });
      for (const r of content) items.push({ kind: "content", path: r.path, name: r.name, snippet: r.snippet });

      const exact = this.notes().some((n) => fold(n.name) === fold(q));
      if (q && !isTag && !exact) {
        items.push({ kind: "group", label: "Oluştur" });
        items.push({ kind: "create", name: q });
      }
    }

    this.items = items;
    const selectable = items.map((it, i) => (it.kind === "group" ? -1 : i)).filter((i) => i >= 0);
    if (!keepIndex || !selectable.includes(this.index)) this.index = selectable[0] ?? -1;
    this._render();
  }

  _render() {
    const q = this.input.value.trim();
    if (!this.items.length) {
      this.list.innerHTML = `<div class="pal-empty">${q.startsWith(">") ? "Komut bulunamadı" : "Sonuç yok"}</div>`;
      return;
    }
    this.list.innerHTML = this.items.map((it, i) => {
      if (it.kind === "group") return `<div class="pal-group">${esc(it.label)}</div>`;
      const on = i === this.index ? " on" : "";
      const enter = '<kbd class="enter">Enter</kbd>';
      if (it.kind === "command") {
        return `<div class="pal-item${on}" data-i="${i}" role="option">${icon(it.icon || "command", 16)}
          <div class="main"><div class="name">${esc(it.label)}</div></div>${it.hint ? `<span class="path">${esc(it.hint)}</span>` : ""}${enter}</div>`;
      }
      if (it.kind === "create") {
        return `<div class="pal-item${on}" data-i="${i}" role="option">${icon("filePlus", 16)}
          <div class="main"><div class="name">“${esc(it.name)}” adlı yeni not oluştur</div></div>${enter}</div>`;
      }
      const folder = it.path.includes("/") ? it.path.slice(0, it.path.lastIndexOf("/")) : "";
      return `<div class="pal-item${on}" data-i="${i}" role="option">${icon("file", 16)}
        <div class="main" translate="no"><div class="name">${highlight(`${it.name}.md`, it.kind === "note" ? q : "")}</div>
          ${it.snippet ? `<div class="snippet">${esc(it.snippet)}</div>` : ""}</div>
        <span class="path" translate="no">${esc(folder ? `${folder} / ${it.name}.md` : `${it.name}.md`)}</span>${enter}</div>`;
    }).join("");
    this.list.querySelector(".on")?.scrollIntoView({ block: "nearest" });
  }

  _select(i) {
    this.index = i;
    this.list.querySelectorAll(".pal-item").forEach((el) => el.classList.toggle("on", Number(el.dataset.i) === i));
    this.list.querySelector(".on")?.scrollIntoView({ block: "nearest" });
  }

  _key(e) {
    const selectable = this.items.map((it, i) => (it.kind === "group" ? -1 : i)).filter((i) => i >= 0);
    const pos = selectable.indexOf(this.index);
    if (e.key === "ArrowDown" || (e.key === "Tab" && !e.shiftKey)) {
      e.preventDefault();
      if (selectable.length) this._select(selectable[(pos + 1) % selectable.length]);
    } else if (e.key === "ArrowUp" || (e.key === "Tab" && e.shiftKey)) {
      e.preventDefault();
      if (selectable.length) this._select(selectable[(pos - 1 + selectable.length) % selectable.length]);
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (this.index >= 0) this._run(this.index);
    } else if (e.key === "Escape") {
      e.preventDefault();
      this.close();
    }
  }

  _run(i) {
    const it = this.items[i];
    if (!it || it.kind === "group") return;
    this.close();
    if (it.kind === "command") it.action();
    else if (it.kind === "create") this.onCreate(it.name);
    else this.onOpen(it.path);
  }
}
