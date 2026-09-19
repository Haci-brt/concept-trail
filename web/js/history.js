// "Öneri Geçmişi": every question, edit, resolution and summary, newest first.
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

const FILTERS = [
  ["all", "Tümü"],
  ["question", "Sorular"],
  ["edit", "Düzenlemeler"],
  ["resolved", "Tamamlananlar"],
  ["summary", "Nota eklenenler"],
  ["checked", "İncelemeler"],
];

const STATUS_CHIP = {
  open: ["chip-open", "Açık"],
  resolved: ["chip-done", "Çözüldü"],
  pending: ["chip-pending", "Bekliyor"],
  approved: ["chip-done", "Onaylandı"],
  rejected: ["chip-rejected", "Reddedildi"],
};

export class HistoryPanel {
  constructor(root, handlers) {
    this.root = root;
    this.h = handlers;
    this.items = [];
    this.filter = "all";
    this.onlyCurrent = false;
    this.currentPath = null;

    root.innerHTML = `
      <div class="history-head">
        ${icon("history", 17)}
        <span class="title">Öneri Geçmişi</span>
        <button class="select-btn" data-act="filter"><span class="flabel">Tümü</span>${icon("chevronDown", 14)}</button>
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
    if (this.onlyCurrent) this.render();
  }

  _visible() {
    // "İncelendi" fires on every quiet pass of the model; keep it out of "Tümü" so it doesn't bury real suggestions
    return this.items.filter((e) =>
      (this.filter === "all" ? e.type !== "checked" : e.type === this.filter) &&
      (!this.onlyCurrent || e.path === this.currentPath));
  }

  render() {
    const label = FILTERS.find(([k]) => k === this.filter)[1];
    this.root.querySelector(".flabel").textContent = this.onlyCurrent ? `${label} · bu not` : label;
    const items = this._visible();
    if (!items.length) {
      this.listEl.innerHTML = `<div class="h-empty">
        <span class="tile t-question">${icon("sparkles", 20)}</span>
        <div>${this.items.length ? "Bu filtrede öneri yok." : "Yazmaya başla — asistanın soruları ve önerileri burada birikecek."}</div>
      </div>`;
      return;
    }
    this.listEl.innerHTML = items.slice(0, 200).map((e) => this._item(e)).join("");
  }

  _item(e) {
    // a question carries what it was for ("Derinleştirme", "Alternatif fikir", …)
    const kind = e.type === "question" ? questionKind(e) : (KINDS[e.type] || KINDS.question);
    let text = e.text || "";
    if (e.type === "edit") text = `"${e.original}" → "${e.replacement}"`;
    const chip = STATUS_CHIP[e.status];
    let actions = "";
    if (e.type === "question" && e.status === "open") {
      actions = `<span class="h-actions"><span class="btn btn-sm" data-act="chat">${icon("message", 13)}Sohbet</span></span>`;
    } else if (e.type === "summary" && e.status === "pending") {
      actions = `<span class="h-actions">
        <span class="btn btn-sm btn-accent" data-act="approve" title="Nota ekle">${icon("check", 13)}</span>
        <span class="btn btn-sm" data-act="reject" title="Vazgeç">${icon("x", 13)}</span></span>`;
    } else if (e.type === "edit" && e.status === "pending") {
      actions = `<span class="h-actions">
        <span class="btn btn-sm btn-accent" data-act="approve" title="Onayla">${icon("check", 13)}</span>
        <span class="btn btn-sm" data-act="reject" title="Reddet">${icon("x", 13)}</span></span>`;
    }
    return `<button class="h-item" role="listitem" data-id="${esc(e.id)}">
      <span class="tile t-${kind.tone}">${icon(kind.icon, 18)}</span>
      <span class="h-main">
        <span class="h-top"><span class="h-kind c-${kind.tone}">${kind.label}</span><span class="h-time">${formatClock(e.created)}</span></span>
        <span class="h-text">${esc(text)}</span>
        <span class="h-meta">
          ${chip ? `<span class="chip ${chip[0]}">${chip[1]}</span>` : ""}
          <span class="note">${esc(e.note)}</span>
          ${actions}
        </span>
      </span>
    </button>`;
  }

  _click(ev) {
    if (ev.target.closest('[data-act="filter"]')) {
      const r = ev.target.closest(".select-btn").getBoundingClientRect();
      openMenu(r.left, r.bottom + 4, [
        ...FILTERS.map(([key, label]) => ({
          label, checked: this.filter === key,
          action: () => { this.filter = key; this.render(); },
        })),
        "sep",
        { label: "Sadece açık not", checked: this.onlyCurrent, action: () => { this.onlyCurrent = !this.onlyCurrent; this.render(); } },
      ]);
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
