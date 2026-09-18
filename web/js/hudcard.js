// The assistant's suggestion card. Rendered in the desktop HUD overlay and,
// when there is no overlay (browser mode), at the top of the right panel.
import { api, streamPost } from "./api.js";
import { icon } from "./icons.js";
import { questionKind } from "./tree.js";
import { esc, splitSentence, toast } from "./util.js";

const FLASH_MS = 4000;

export class HudCard {
  /** onChange(visible) fires after every render — the overlay resizes itself from it.
   *  onTyping(on) tells the desktop shell to accept keystrokes while the writer
   *  is answering inside the card (the HUD refuses focus the rest of the time). */
  constructor(host, { onChange, onTyping } = {}) {
    this.host = host;
    this.onChange = onChange;
    this.onTyping = onTyping;
    this.hud = { event: null, remaining: 0 };
    this.busy = null;
    this.thinking = null;
    this.flash = null;
    this.thread = null;     // an exchange happening inside the card itself
    this.editing = null;    // the proposal being reworded
    this._flashTimer = 0;
    this._lastKey = "";
    this._typing = false;
    host.addEventListener("click", (e) => this._click(e));
    host.addEventListener("keydown", (e) => this._key(e));
    host.addEventListener("focusin", (e) => { if (e.target.closest(".hud-input")) this._typingMode(true); });
    host.addEventListener("focusout", (e) => {
      if (e.target.closest(".hud-input") && !this.host.contains(e.relatedTarget)) this._typingMode(false);
    });
  }

  setHud(hud) {
    this.hud = hud || { event: null, remaining: 0 };
    const id = this.hud.event?.id;
    if (this.thread && this.thread.eventId !== id) this.thread = null;
    if (this.editing && this.editing !== id) this.editing = null;
    if (!id) this._typingMode(false);
    this.render();
  }

  _typingMode(on) {
    if (this._typing === on) return;
    this._typing = on;
    this.onTyping?.(on);
  }

  setStatus(status) {
    this.busy = status.busy;
    if (!this.busy) this.thinking = null;
    this.render();
  }

  setThinking(data) {
    this.thinking = data.phase === "done" ? null : data;
    this.render();
  }

  showFlash(data) {
    clearTimeout(this._flashTimer);
    this.flash = data;
    this.render();
    this._flashTimer = setTimeout(() => { this.flash = null; this.render(); }, FLASH_MS);
  }

  _view() {
    const ev = this.hud.event;
    if (ev) return { kind: ev.type, ev };
    if (this.busy) return { kind: "thinking" };
    if (this.flash) return { kind: this.flash.kind === "error" ? "error" : "checked", flash: this.flash };
    return null;
  }

  render() {
    const view = this._view();
    // never pull the card out from under someone typing in it: status updates
    // arrive every few seconds and a re-render would eat the half-typed answer
    const typing = document.activeElement?.classList?.contains("hud-input")
      && this.host.contains(document.activeElement);
    if (typing && view?.ev && this.host.querySelector(`.hud-card[data-id="${view.ev.id}"]`)) {
      this.onChange?.(true);
      return;
    }
    let markup = "";
    if (view?.kind === "question") markup = this._question(view.ev);
    else if (view?.kind === "edit") markup = this._edit(view.ev);
    else if (view?.kind === "summary") markup = this._proposal(view.ev);
    else if (view?.kind === "thinking") markup = this._thinking();
    else if (view) markup = this._flash(view);

    // re-rendering the same card would restart its entrance animation
    const key = view
      ? [view.kind, view.ev?.id ?? view.flash?.body ?? "", this.hud.remaining,
         this.thread?.text ?? "", this.thread?.busy ? 1 : 0, this.editing ? 1 : 0].join(":")
      : "";
    if (key && key === this._lastKey && view.kind === "thinking") {
      const thought = this.host.querySelector(".hud-thought");
      const label = this.host.querySelector(".hud-eyebrow .lbl");
      if (thought) thought.textContent = this.thinking?.text || "Not inceleniyor";
      if (label) label.textContent = this.thinking?.phase === "writing" ? "Asistan yazıyor" : "Asistan düşünüyor";
    } else if (key !== this._lastKey || !view) {
      const draft = this._draft();
      this.host.innerHTML = markup;
      this._restore(draft);
    }
    this._lastKey = key;
    this.onChange?.(Boolean(view));
  }

  /** A half-typed answer must survive the re-render a status update causes. */
  _draft() {
    const box = this.host.querySelector(".hud-input");
    if (!box || (!box.value && box !== document.activeElement)) return null;
    return { value: box.value, at: box.selectionStart, focused: box === document.activeElement };
  }

  _restore(draft) {
    const box = draft && this.host.querySelector(".hud-input");
    if (!box) return;
    box.value = draft.value;
    if (draft.focused) {
      box.focus();
      box.setSelectionRange(draft.at, draft.at);
    }
  }

  _count() {
    return this.hud.remaining > 0 ? `<span class="hud-count" title="Sırada bekleyen">+${this.hud.remaining}</span>` : "";
  }

  _note(ev) {
    return `<div class="hud-note">${icon("file", 12)}${esc(ev.note)}</div>`;
  }

  _question(ev) {
    // after an inline answer the card carries the assistant's reply instead:
    // either a follow-up question, or its answer to something you asked back
    const reply = this.thread?.eventId === ev.id && !this.thread.busy ? this.thread : null;
    const kind = questionKind(ev);
    const [title, sub] = splitSentence(reply ? reply.text : ev.text);
    const eyebrow = reply
      ? (reply.answered ? "Asistanın cevabı" : "Devam sorusu")
      : `${kind.label} <span class="spark">✦</span>`;
    const waiting = this.thread?.eventId === ev.id && this.thread.busy;
    return `<div class="hud-card kind-question tone-${kind.tone}" data-id="${esc(ev.id)}">
      <div class="hud-row">
        <div class="hud-glyph">${icon(kind.icon, 18)}</div>
        <div class="hud-text">
          <div class="hud-eyebrow">${eyebrow}${this._count()}</div>
          <div class="hud-title">${esc(title)}</div>
          ${sub ? `<div class="hud-sub">${esc(sub)}</div>` : ""}
          ${this._note(ev)}
        </div>
      </div>
      ${waiting
        ? `<div class="hud-waiting">${icon("sparkle", 13)}<span>${esc(this.thread.text || "Asistan düşünüyor")}</span><span class="dots"></span></div>`
        : `<div class="hud-answer">
            <textarea class="hud-input" rows="1" placeholder="Cevabını buraya yaz — Enter gönderir"></textarea>
            <button class="btn btn-accent btn-sm" data-act="answer" title="Gönder (Enter)">${icon("send", 14)}</button>
          </div>`}
      <div class="hud-actions">
        <button class="btn btn-sm" data-act="chat">${icon("message", 14)}Sohbette aç</button>
        <span class="spacer"></span>
        ${this.hud.remaining ? '<button class="btn btn-sm" data-act="next">Sonrakini Göster</button>' : ""}
        <button class="btn btn-sm" data-act="dismiss">Kapat</button>
      </div>
    </div>`;
  }

  _proposal(ev) {
    const editing = this.editing === ev.id;
    return `<div class="hud-card kind-summary" data-id="${esc(ev.id)}">
      <div class="hud-row">
        <div class="hud-glyph">${icon("lightbulb", 17)}</div>
        <div class="hud-text">
          <div class="hud-eyebrow">Nota eklensin mi?${this._count()}</div>
          ${editing
            ? `<textarea class="hud-input hud-rewrite" rows="3">${esc(ev.text)}</textarea>`
            : `<div class="hud-sub">${esc(ev.text)}</div>`}
          ${this._note(ev)}
        </div>
      </div>
      <div class="hud-actions">
        <button class="btn btn-accent btn-sm" data-act="approve">${icon("check", 14)}${editing ? "Böyle ekle" : "Nota ekle"}</button>
        ${editing ? "" : '<button class="btn btn-sm" data-act="edit" title="Kendi sözlerinle yaz">Düzenle</button>'}
        <button class="btn btn-sm" data-act="reject">Vazgeç</button>
        <span class="spacer"></span>
        ${this.hud.remaining ? '<button class="btn btn-sm btn-ghost" data-act="next">Sonraki</button>' : ""}
      </div>
    </div>`;
  }

  _edit(ev) {
    return `<div class="hud-card kind-edit" data-id="${esc(ev.id)}">
      <div class="hud-row">
        <div class="hud-glyph">${icon("pencil", 17)}</div>
        <div class="hud-text">
          <div class="hud-eyebrow">Düzenleme önerisi${this._count()}</div>
          <div class="hud-diff"><del><span>${esc(ev.original)}</span></del><ins>${esc(ev.replacement)}</ins></div>
          ${ev.reason ? `<div class="hud-sub">${esc(ev.reason)}</div>` : ""}
          ${this._note(ev)}
        </div>
      </div>
      <div class="hud-actions">
        <button class="btn btn-accent btn-sm" data-act="approve">${icon("check", 14)}Onayla</button>
        <button class="btn btn-sm" data-act="reject">Reddet</button>
        <span class="spacer"></span>
        ${this.hud.remaining ? '<button class="btn btn-sm btn-ghost" data-act="next">Sonraki</button>' : ""}
      </div>
    </div>`;
  }

  _thinking() {
    const writing = this.thinking?.phase === "writing";
    const note = (this.busy || "").split("/").pop().replace(/\.md$/i, "");
    return `<div class="hud-card kind-thinking">
      <div class="hud-row">
        <div class="hud-glyph">${icon("sparkle", 16)}</div>
        <div class="hud-text">
          <div class="hud-eyebrow"><span class="lbl">${writing ? "Asistan yazıyor" : "Asistan düşünüyor"}</span><span class="dots"></span></div>
          <div class="hud-thought">${esc(this.thinking?.text || "Not inceleniyor")}</div>
          ${note ? `<div class="hud-note">${icon("file", 12)}${esc(note)}</div>` : ""}
        </div>
      </div>
      <div class="hud-progress"></div>
    </div>`;
  }

  _flash({ kind, flash }) {
    return `<div class="hud-card kind-${kind}">
      <div class="hud-row">
        <div class="hud-glyph">${icon(kind === "error" ? "alert" : "eye", 16)}</div>
        <div class="hud-text">
          <div class="hud-eyebrow">${esc(flash.title)}</div>
          <div class="hud-sub">${esc(flash.body)}</div>
        </div>
      </div>
    </div>`;
  }

  _key(e) {
    if (!e.target.closest(".hud-input")) return;
    if (e.key === "Escape") { e.target.blur(); return; }
    if (e.key !== "Enter" || e.shiftKey) return;     // Shift+Enter writes a new line
    const card = e.target.closest(".hud-card[data-id]");
    if (!card) return;
    e.preventDefault();
    if (e.target.classList.contains("hud-rewrite")) this._decide(card, "approve");
    else this._answer(card);
  }

  async _click(e) {
    const btn = e.target.closest("[data-act]");
    const card = e.target.closest(".hud-card[data-id]");
    if (!btn || !card) return;
    const act = btn.dataset.act;
    if (act === "answer") return this._answer(card);
    if (act === "edit") {
      this.editing = card.dataset.id;
      this.render();
      const box = this.host.querySelector(".hud-rewrite");
      box?.focus();
      box?.setSelectionRange(box.value.length, box.value.length);
      return;
    }
    btn.disabled = true;
    await this._decide(card, act, btn);
  }

  async _decide(card, act, btn) {
    // an approved proposal goes in the way the writer left it, not the way it came
    const rewritten = card.querySelector(".hud-rewrite")?.value.trim();
    try {
      await api.post("/api/assistant/hud", {
        event_id: card.dataset.id, action: act,
        ...(act === "approve" && rewritten ? { text: rewritten } : {}),
      });
      this.editing = null;
      this._typingMode(false);
    } catch (err) {
      toast(err.message, "error");
      if (btn) btn.disabled = false;
    }
  }

  /** Answer without leaving the card: the reply lands in the same card. */
  async _answer(card) {
    const ev = this.hud.event;
    const box = card.querySelector(".hud-input");
    const message = box?.value.trim();
    if (!ev || !message || this.thread?.busy) return;
    box.value = "";
    box.blur();                                   // the card may render freely again
    this.thread = { eventId: ev.id, busy: true, text: "" };
    this.render();
    try {
      await streamPost("/api/assistant/chat", { path: ev.path, node_id: ev.node_id, message }, (u) => {
        if (this.hud.event?.id !== ev.id) return;
        if (u.type === "progress") {
          this.thread = { eventId: ev.id, busy: true, text: u.text || "" };
          this.render();
        } else if (u.type === "done") {
          // when the assistant has understood, its proposal takes the card over
          this.thread = u.proposal ? null : { eventId: ev.id, busy: false, text: u.node.text, answered: u.answered };
          this.render();
        } else if (u.type === "error") {
          this.thread = null;
          this.render();
          toast(u.message, "error");
        }
      });
    } catch (err) {
      this.thread = null;
      this.render();
      toast(err.message, "error");
    }
  }
}
