// The right panel. Not a log of everything that ever happened: a short stack
// of what is actually waiting for you in the note you have open. You answer a
// question where it stands, it closes itself, and it slides down into a fold
// with the rest of what is settled.
import { api, streamPost } from "./api.js";
import { openMenu } from "./dialogs.js";
import { icon } from "./icons.js";
import { questionKind } from "./tree.js";
import { esc, formatClock, miniMarkdown, toast } from "./util.js";

export const KINDS = {
  question: { label: "Soru", icon: "questionSquare", tone: "question" },
  edit: { label: "Düzenleme", icon: "pencil", tone: "edit" },
  resolved: { label: "Tamamlandı", icon: "check", tone: "resolved" },
  summary: { label: "Nota eklenme önerisi", icon: "lightbulb", tone: "summary" },
  checked: { label: "İncelendi", icon: "eye", tone: "checked" },
  phase: { label: "Evre", icon: "sprout", tone: "resolved" },
  research: { label: "Araştırma önerisi", icon: "search", tone: "summary" },
};
const MODEL_SUGGESTION = { label: "Modelin önerisi", icon: "sparkles", tone: "summary" };
const LENS_LABELS = { mimar: "Mimar gözüyle", urun: "Ürün gözüyle", guvenlik: "Güvenlik gözüyle", gelistirici: "Geliştirici gözüyle" };

const STATUS_CHIP = {
  open: ["chip-open", "Açık"],
  resolved: ["chip-done", "Çözüldü"],
  dismissed: ["chip-rejected", "Rotadan çıkarıldı"],
  pending: ["chip-pending", "Bekliyor"],
  approved: ["chip-done", "Onaylandı"],
  rejected: ["chip-rejected", "Reddedildi"],
};

function waiting(e) {
  if (e.type === "summary" || e.type === "edit" || e.type === "research") return e.status === "pending";
  return e.type === "question" && e.status === "open";
}

export class HistoryPanel {
  constructor(root, handlers) {
    this.root = root;
    this.h = handlers;
    this.items = [];
    this.allNotes = false;      // this note only, unless you ask for the vault
    this.showDone = false;
    this.currentPath = null;
    this.busy = null;           // the event id whose answer is being sent
    this.reply = null;          // { id, text, kind } — what the assistant said back
    this.leaving = new Set();   // ids playing their closing animation

    root.innerHTML = `
      <div class="history-head">
        ${icon("sparkles", 17)}
        <span class="title">Asistan</span>
        <button class="select-btn" data-act="scope"><span class="flabel">Bu not</span>${icon("chevronDown", 14)}</button>
      </div>
      <div class="history-list" role="list"></div>`;
    this.listEl = root.querySelector(".history-list");
    root.addEventListener("click", (e) => this._click(e));
    root.addEventListener("keydown", (e) => this._key(e));
  }

  setItems(items) { this.items = items; this.render(); }

  /** Puts the cursor in the answer box of the first waiting question, in the
   *  order the list shows them; false when none is waiting here. */
  focusNextAnswer() {
    const box = this.listEl.querySelector(".h-item.open .h-answer textarea");
    if (!box) return false;
    box.scrollIntoView({ block: "nearest" });
    box.focus();
    return true;
  }

  /** What waits for you in the panel's scope (this note, or every note). */
  waitingItems() { return this._mine().filter(waiting); }

  /** The assistant card's order: first come, first shown, and a proposal an
   *  answer led to standing where its question stood (server _record). The
   *  items are newest first. */
  _cardOrder(list) {
    const age = new Map(this.items.map((e, i) => [e.id, this.items.length - i]));
    const asked = new Map(this.items.filter((e) => e.type === "question")
      .map((e) => [`${e.path}\n${e.node_id}`, age.get(e.id)]));
    const slot = (e) => (e.question_id && asked.get(`${e.path}\n${e.question_id}`)) || age.get(e.id) || 0;
    return list.sort((a, b) => slot(a) - slot(b));
  }

  add(event) {
    this.items.unshift(event);
    this.render();
  }

  update(event) {
    const i = this.items.findIndex((e) => e.id === event.id);
    if (i === -1) { this.items.unshift(event); this.render(); return; }
    const closing = waiting(this.items[i]) && !waiting(event);
    this.items[i] = event;
    if (closing) this._playOut(event.id);      // it just left the queue: show it leaving
    else this.render();
  }

  setCurrentPath(path) {
    this.currentPath = path;
    this.reply = null;
    if (!this.allNotes) this.render();
  }

  /** Let the card finish its closing animation before it is re-sorted away. */
  _playOut(id) {
    this.leaving.add(id);
    this.render();
    const card = this.listEl.querySelector(`.h-item[data-id="${CSS.escape(id)}"]`);
    if (!card) { this.leaving.delete(id); this.render(); return; }
    card.classList.add("closing");
    setTimeout(() => { this.leaving.delete(id); this.render(); }, 520);
  }

  _mine() {
    // "İncelendi" fires on every quiet pass of the model; it is noise, never news
    return this.items.filter((e) => e.type !== "checked"
      && (this.allNotes || e.path === this.currentPath));
  }

  render() {
    this.root.querySelector(".flabel").textContent = this.allNotes ? "Tüm notlar" : "Bu not";
    const mine = this._mine();
    const open = this._cardOrder(mine.filter((e) => waiting(e) || this.leaving.has(e.id)));
    const done = mine.filter((e) => !waiting(e) && !this.leaving.has(e.id));

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
      parts.push(`<div class="h-section">Sıradaki${open.length > 1 ? `<span class="h-num">${open.length}</span>` : ""}</div>`);
      parts.push(open.map((e) => this._item(e)).join(""));
    } else {
      parts.push(`<div class="h-caught-up">
        <span class="h-caught-icon">${icon("check", 18)}</span>
        <strong>Şu an bekleyen yok</strong>
        <span>Yeni soru ve düzenleme önerileri burada görünecek.</span>
      </div>`);
    }
    if (done.length) {
      parts.push(`<button class="h-fold${this.showDone ? " open" : ""}" data-act="fold">
        ${icon("chevronRight", 13)}<span>Biten ${done.length}</span></button>`);
      if (this.showDone) parts.push(done.slice(0, 60).map((e) => this._item(e, true)).join(""));
    }
    const draft = this._draft();
    this.listEl.innerHTML = parts.join("");
    this._restore(draft);
    this.h.onRender?.();
  }

  /** A half-typed answer must survive the re-render another event causes. */
  _draft() {
    const box = this.listEl.querySelector(".h-answer textarea");
    if (!box || (!box.value && box !== document.activeElement)) return null;
    return { id: box.closest(".h-item").dataset.id, value: box.value,
             at: box.selectionStart, focused: box === document.activeElement };
  }

  _restore(draft) {
    if (!draft) return;
    const box = this.listEl.querySelector(`.h-item[data-id="${CSS.escape(draft.id)}"] textarea`);
    if (!box) return;
    box.value = draft.value;
    if (draft.focused) { box.focus(); box.setSelectionRange(draft.at, draft.at); }
  }

  _item(e, settled = false) {
    const kind = e.type === "question" ? questionKind(e)
      : e.type === "summary" && e.source === "model" ? MODEL_SUGGESTION : (KINDS[e.type] || KINDS.question);
    let text = e.text || "";
    if (e.type === "edit") text = `"${e.original}" → "${e.replacement}"`;
    const chip = STATUS_CHIP[e.status];
    const open = e.type === "question" && e.status === "open" && !settled;
    const answering = this.busy === e.id;
    const reply = this.reply && this.reply.id === e.id ? this.reply : null;

    let actions = "";
    if ((e.type === "summary" || e.type === "edit") && e.status === "pending") {
      actions = `<div class="h-actions">
        ${e.why ? `<span class="h-why">Notta dayandığı: ${esc(e.why)}</span>` : ""}
        <button class="btn btn-sm btn-accent" data-act="approve">${icon("check", 13)}Nota ekle</button>
        <button class="btn btn-sm" data-act="reject">Vazgeç</button></div>`;
    } else if (e.type === "research" && e.status === "pending") {
      actions = `<div class="h-actions">
        ${e.why ? `<span class="h-why">${esc(e.why)}</span>` : ""}
        <button class="btn btn-sm btn-accent" data-act="approve">${icon("search", 13)}Araştır</button>
        <button class="btn btn-sm" data-act="reject">Vazgeç</button></div>`;
    }

    // an open question is answered where it stands; the chat is one click away
    const answer = !open ? "" : answering
      ? `<div class="h-thinking">${icon("sparkle", 12)}<span>${esc(this.busyText || "Asistan düşünüyor")}</span><span class="dots"></span></div>`
      : `<div class="h-answer">
          <textarea rows="1" placeholder="Cevabını yaz — Enter gönderir"></textarea>
          <span class="btn btn-sm btn-accent" data-act="send" title="Gönder (Enter)">${icon("send", 13)}</span>
          <span class="btn btn-sm" data-act="chat" title="Sohbette aç">${icon("message", 13)}</span>
        </div>`;

    return `<div class="h-item${settled ? " settled" : ""}${open ? " open" : ""}" role="listitem" data-id="${esc(e.id)}">
      <button class="h-head" data-act="reveal">
        <span class="tile t-${kind.tone}">${icon(kind.icon, 18)}</span>
        <span class="h-main">
          <span class="h-top"><span class="h-kind c-${kind.tone}">${kind.label}</span><span class="h-time">${formatClock(e.created)}</span></span>
          <span class="h-text">${esc(text)}</span>
          <span class="h-meta">
            ${chip ? `<span class="chip ${chip[0]}">${chip[1]}</span>` : ""}
            ${e.lens && LENS_LABELS[e.lens] ? `<span class="h-lens">${LENS_LABELS[e.lens]}</span>` : ""}
            ${this.allNotes ? `<span class="note">${esc(e.note)}</span>` : ""}
          </span>
        </span>
      </button>
      ${actions}
      ${reply ? `<div class="h-reply${reply.kind === "answer" ? " answer" : ""}">${miniMarkdown(reply.text)}</div>` : ""}
      ${answer}
    </div>`;
  }

  // ---- answering in place ----
  _key(ev) {
    if (ev.target.tagName !== "TEXTAREA") return;
    if (ev.key === "Escape") { ev.target.blur(); return; }
    if (ev.key !== "Enter" || ev.shiftKey) return;
    ev.preventDefault();
    this._send(ev.target.closest(".h-item"));
  }

  async _send(card) {
    const event = this.items.find((e) => e.id === card?.dataset.id);
    const box = card?.querySelector("textarea");
    const message = box?.value.trim();
    if (!event || !message || this.busy) return;
    box.value = "";
    box.blur();
    this.busy = event.id;
    this.busyText = "";
    this.reply = null;
    this.render();
    try {
      await this.h.beforeSend?.(event.path);
      await streamPost("/api/assistant/chat",
        { path: event.path, node_id: event.node_id, message }, (u) => {
          if (u.type === "progress") { this.busyText = u.text || ""; this.render(); }
          else if (u.type === "done") {
            this.busy = null;
            // an understood answer resolves the question itself — the card will
            // slide out on its own event; anything else stays and shows the reply
            this.reply = u.understood ? null : { id: event.id, text: u.node.text,
                                                 kind: u.answered ? "answer" : "question" };
            this.render();
          } else if (u.type === "error") {
            this.busy = null; this.render(); toast(u.message, "error");
          }
        });
    } catch (err) {
      toast(err.message, "error");
    } finally {
      if (this.busy === event.id) { this.busy = null; this.render(); }
    }
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
    const card = ev.target.closest(".h-item");
    if (!card) return;
    const event = this.items.find((e) => e.id === card.dataset.id);
    if (!event) return;
    const act = ev.target.closest("[data-act]")?.dataset.act;
    if (act === "send") return this._send(card);
    this.h.select(event, act === "reveal" ? null : act);
  }
}
