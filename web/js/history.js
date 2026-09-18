// The right panel. Not a log: a short list of what is waiting for you in the
// note you have open. Everything that is already settled moves out of the way
// into a fold you can open when you want it.
import { openMenu } from "./dialogs.js";
import { icon } from "./icons.js";
import { questionKind } from "./tree.js";
import { esc, formatClock } from "./util.js";

export const KINDS = {
  question: { label: "Soru", icon: "questionSquare", tone: "question" },
  edit: { label: "Düzenleme", icon: "pencil", tone: "edit" },
  resolved: { label: "Tamamlandı", icon: "check", tone: "resolved" },
  summary: { label: "Nota eklenme önerisi", icon: "lightbulb", tone: "summary" },
  checked: { label: "İncelendi", icon: "eye", tone: "checked" },
};

const STATUS_CHIP = {
  open: ["chip-open", "Açık"],
  resolved: ["chip-done", "Çözüldü"],
  pending: ["chip-pending", "Bekliyor"],
  approved: ["chip-done", "Onaylandı"],
  rejected: ["chip-rejected", "Reddedildi"],
};

/** Waiting on you, most pressing first: a proposal blocks the note until you
 *  decide; a question only waits. Within a rank, the newest comes first. */
const RANK = { summary: 0, edit: 1, question: 2 };

function waiting(e) {
  if (e.type === "summary" || e.type === "edit") return e.status === "pending";
  return e.type === "question" && e.status === "open";
}

export class HistoryPanel {
  constructor(root, handlers) {
    this.root = root;
    this.h = handlers;
    this.items = [];
    this.allNotes = false;     // this note only, unless you ask for the vault
    this.showDone = false;
    this.currentPath = null;

    root.innerHTML = `
      <div class="history-head">
        ${icon("sparkles", 17)}
        <span class="title">Asistan</span>
        <button class="select-btn" data-act="scope"><span class="flabel">Bu not</span>${icon("chevronDown", 14)}</button>
      </div>
      <div class="history-list" role="list"></div>`;
    this.listEl = root.querySelector(".history-list");
    root.addEventListener("click", (e) => this._click(e));
  }

  setItems(items) { this.items = items; this.render(); }

  add(event) {
    this.items.unshift(event);
    this.render();
  }

  update(event) {
    const i = this.items.findIndex((e) => e.id === event.id);
    if (i !== -1) this.items[i] = event;
    this.render();
  }

  setCurrentPath(path) {
    this.currentPath = path;
    if (!this.allNotes) this.render();
  }

  _mine() {
    // "İncelendi" fires on every quiet pass of the model; it is noise, never news
    return this.items.filter((e) => e.type !== "checked"
      && (this.allNotes || e.path === this.currentPath));
  }

  render() {
    this.root.querySelector(".flabel").textContent = this.allNotes ? "Tüm notlar" : "Bu not";
    const mine = this._mine();
    const open = mine.filter(waiting).sort((a, b) =>
      (RANK[a.type] ?? 9) - (RANK[b.type] ?? 9) || b.created.localeCompare(a.created));
    const done = mine.filter((e) => !waiting(e));

    if (!open.length && !done.length) {
      this.listEl.innerHTML = `<div class="h-empty">
        <span class="tile t-question">${icon("sparkles", 20)}</span>
        <div>${this.allNotes || !this.currentPath
          ? "Yazmaya başla — asistanın soruları burada birikecek."
          : "Bu notta bekleyen bir şey yok."}</div>
      </div>`;
      return;
    }

    const parts = [];
    if (open.length) {
      parts.push(`<div class="h-section">Sıradaki ${open.length > 1 ? `<span class="h-num">${open.length}</span>` : ""}</div>`);
      parts.push(open.map((e) => this._item(e)).join(""));
    }
    if (done.length) {
      parts.push(`<button class="h-fold${this.showDone ? " open" : ""}" data-act="fold">
        ${icon("chevronRight", 13)}<span>Biten ${done.length}</span>
      </button>`);
      if (this.showDone) parts.push(done.slice(0, 60).map((e) => this._item(e, true)).join(""));
    }
    this.listEl.innerHTML = parts.join("");
  }

  _item(e, settled = false) {
    // a question carries what it was for ("Derinleştirme", "Alternatif fikir", …)
    const kind = e.type === "question" ? questionKind(e) : (KINDS[e.type] || KINDS.question);
    let text = e.text || "";
    if (e.type === "edit") text = `"${e.original}" → "${e.replacement}"`;
    const chip = STATUS_CHIP[e.status];
    let actions = "";
    if (e.type === "question" && e.status === "open") {
      actions = `<span class="h-actions"><span class="btn btn-sm" data-act="chat">${icon("message", 13)}Cevapla</span></span>`;
    } else if ((e.type === "summary" || e.type === "edit") && e.status === "pending") {
      actions = `<span class="h-actions">
        <span class="btn btn-sm btn-accent" data-act="approve" title="${e.type === "edit" ? "Onayla" : "Nota ekle"}">${icon("check", 13)}</span>
        <span class="btn btn-sm" data-act="reject" title="Vazgeç">${icon("x", 13)}</span></span>`;
    }
    return `<button class="h-item${settled ? " settled" : ""}" role="listitem" data-id="${esc(e.id)}">
      <span class="tile t-${kind.tone}">${icon(kind.icon, 18)}</span>
      <span class="h-main">
        <span class="h-top"><span class="h-kind c-${kind.tone}">${kind.label}</span><span class="h-time">${formatClock(e.created)}</span></span>
        <span class="h-text">${esc(text)}</span>
        <span class="h-meta">
          ${chip ? `<span class="chip ${chip[0]}">${chip[1]}</span>` : ""}
          ${this.allNotes ? `<span class="note">${esc(e.note)}</span>` : ""}
          ${actions}
        </span>
      </span>
    </button>`;
  }

  _click(ev) {
    if (ev.target.closest('[data-act="scope"]')) {
      const r = ev.target.closest(".select-btn").getBoundingClientRect();
      openMenu(r.left, r.bottom + 4, [
        { label: "Bu not", checked: !this.allNotes, action: () => { this.allNotes = false; this.render(); } },
        { label: "Tüm notlar", checked: this.allNotes, action: () => { this.allNotes = true; this.render(); } },
      ]);
      return;
    }
    if (ev.target.closest('[data-act="fold"]')) {
      this.showDone = !this.showDone;
      this.render();
      return;
    }
    const item = ev.target.closest(".h-item");
    if (!item) return;
    const event = this.items.find((e) => e.id === item.dataset.id);
    if (!event) return;
    const act = ev.target.closest("[data-act]")?.dataset.act;
    this.h.select(event, act || null);
  }
}
