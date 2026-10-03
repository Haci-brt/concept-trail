// The assistant's suggestion card. Rendered in the desktop HUD overlay and,
// when there is no overlay (browser mode), at the top of the right panel.
import { api } from "./api.js";
import { icon } from "./icons.js";
import { questionKind } from "./tree.js";
import { esc, splitSentence, toast } from "./util.js";

const FLASH_MS = 4000;

export class HudCard {
  /** onChange(visible) fires after every render — the overlay resizes itself from it. */
  constructor(host, { onChange } = {}) {
    this.host = host;
    this.onChange = onChange;
    this.hud = { event: null, remaining: 0 };
    this.busy = null;
    this.thinking = null;
    this.flash = null;
    this._flashTimer = 0;
    this._lastKey = "";
    host.addEventListener("click", (e) => this._click(e));
  }

  setHud(hud) { this.hud = hud || { event: null, remaining: 0 }; this.render(); }

  setStatus(status) {
    // the live watch's quiet pass never puts a card up; the status bar says it is looking
    this.busy = status.busy_quiet ? null : status.busy;
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
    let markup = "";
    if (view?.kind === "question") markup = this._question(view.ev);
    else if (view?.kind === "edit") markup = this._edit(view.ev);
    else if (view?.kind === "summary") markup = this._proposal(view.ev);
    else if (view?.kind === "thinking") markup = this._thinking();
    else if (view) markup = this._flash(view);

    // re-rendering the same card would restart its entrance animation
    const key = view ? `${view.kind}:${view.ev?.id ?? view.flash?.body ?? ""}:${this.hud.remaining}` : "";
    if (key && key === this._lastKey && view.kind === "thinking") {
      const thought = this.host.querySelector(".hud-thought");
      const label = this.host.querySelector(".hud-eyebrow .lbl");
      if (thought) thought.textContent = this.thinking?.text || "Not inceleniyor";
      if (label) label.textContent = this.thinking?.phase === "writing" ? "Asistan yazıyor" : "Asistan düşünüyor";
    } else if (key !== this._lastKey || !view) {
      this.host.innerHTML = markup;
    }
    this._lastKey = key;
    this.onChange?.(Boolean(view));
  }

  _count() {
    return this.hud.remaining > 0 ? `<span class="hud-count" title="Sırada bekleyen">+${this.hud.remaining}</span>` : "";
  }

  _note(ev) {
    return `<div class="hud-note" translate="no">${icon("file", 12)}${esc(ev.note)}</div>`;
  }

  _question(ev) {
    const [title, sub] = splitSentence(ev.text);
    const kind = questionKind(ev);
    return `<div class="hud-card kind-question tone-${kind.tone}" data-id="${esc(ev.id)}">
      <div class="hud-row">
        <div class="hud-glyph">${icon(kind.icon, 18)}</div>
        <div class="hud-text">
          <div class="hud-eyebrow">${kind.label} <span class="spark">✦</span>${this._count()}</div>
          <div class="hud-title" translate="no">${esc(title)}</div>
          ${sub ? `<div class="hud-sub" translate="no">${esc(sub)}</div>` : ""}
          ${this._note(ev)}
        </div>
      </div>
      <div class="hud-actions">
        <button class="btn btn-accent btn-sm" data-act="chat">${icon("message", 14)}Sohbet Et</button>
        <span class="spacer"></span>
        ${this.hud.remaining ? '<button class="btn btn-sm" data-act="next">Sonrakini Göster</button>' : ""}
        <button class="btn btn-sm" data-act="dismiss">Kapat</button>
      </div>
    </div>`;
  }

  _proposal(ev) {
    return `<div class="hud-card kind-summary" data-id="${esc(ev.id)}">
      <div class="hud-row">
        <div class="hud-glyph">${icon("lightbulb", 17)}</div>
        <div class="hud-text">
          <div class="hud-eyebrow">Nota eklensin mi?${this._count()}</div>
          <div class="hud-sub" translate="no">${esc(ev.text)}</div>
          ${this._note(ev)}
        </div>
      </div>
      <div class="hud-actions">
        <button class="btn btn-accent btn-sm" data-act="approve">${icon("check", 14)}Nota ekle</button>
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
          <div class="hud-diff" translate="no"><del><span>${esc(ev.original)}</span></del><ins>${esc(ev.replacement)}</ins></div>
          ${ev.reason ? `<div class="hud-sub" translate="no">${esc(ev.reason)}</div>` : ""}
          ${this._note(ev)}
        </div>
      </div>
      <div class="hud-actions">
        <button class="btn btn-accent btn-sm" data-act="approve">${icon("check", 14)}Nota ekle</button>
        <button class="btn btn-sm" data-act="reject">Vazgeç</button>
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
          <div class="hud-thought"${this.thinking?.text ? ' translate="no"' : ""}>${esc(this.thinking?.text || "Not inceleniyor")}</div>
          ${note ? `<div class="hud-note" translate="no">${icon("file", 12)}${esc(note)}</div>` : ""}
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

  async _click(e) {
    const btn = e.target.closest("[data-act]");
    const card = e.target.closest(".hud-card[data-id]");
    if (!btn || !card) return;
    btn.disabled = true;
    try {
      await api.post("/api/assistant/hud", { event_id: card.dataset.id, action: btn.dataset.act });
    } catch (err) {
      toast(err.message, "error");
      btn.disabled = false;
    }
  }
}
