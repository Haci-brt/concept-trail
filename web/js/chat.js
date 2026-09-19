// Slide-over chat about one of the assistant's questions. The thread is
// stored on the question node, so reopening it continues the conversation.
import { api, streamPost } from "./api.js";
import { icon } from "./icons.js";
import { esc, html, toast } from "./util.js";

export class ChatDrawer {
  constructor({ beforeSend }) {
    this.beforeSend = beforeSend;
    this.path = null;
    this.nodeId = null;
    this.sending = false;

    this.el = html(`<aside class="chat" aria-label="Asistanla sohbet">
      <div class="chat-head">
        <span class="tile sm t-question">${icon("message", 14)}</span>
        <div class="grow"><div class="t">Asistanla Sohbet</div><div class="s note"></div></div>
        <button class="icon-btn" data-act="close" title="Kapat (Esc)">${icon("x", 16)}</button>
      </div>
      <div class="chat-seed">
        <div class="eyebrow">${icon("questionSquare", 13)}Soru<span class="chip status"></span></div>
        <div class="q"></div>
      </div>
      <div class="chat-log" aria-live="polite"></div>
      <div class="chat-compose">
        <div class="compose-box">
          <textarea rows="1" placeholder="Cevabını yaz… (Enter gönderir, Shift+Enter yeni satır)"></textarea>
          <button class="icon-btn" data-act="send" title="Gönder">${icon("send", 15)}</button>
        </div>
        <div class="chat-actions">
          <button class="btn btn-accent" data-act="summary" title="Sonucu nota eklemeyi öner — eklemeden önce onayını ister">${icon("pencil", 14)}Nota Öner</button>
          <button class="btn" data-act="resolve">${icon("checkCircle", 14)}Çözüldü</button>
        </div>
      </div>
    </aside>`);
    document.body.append(this.el);
    this.log = this.el.querySelector(".chat-log");
    this.input = this.el.querySelector("textarea");

    this.el.addEventListener("click", (e) => {
      const act = e.target.closest("[data-act]")?.dataset.act;
      if (act === "close") this.close();
      if (act === "send") this.send();
      if (act === "summary") this.summarize();
      if (act === "resolve") this.resolve();
    });
    this.input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        this.send();
      }
      if (e.key === "Escape") this.close();
    });
    this.input.addEventListener("input", () => this._autosize());
  }

  get isOpen() { return this.el.classList.contains("open"); }

  async open(path, nodeId) {
    this.path = path;
    this.nodeId = nodeId;
    this.el.querySelector(".note").textContent = path.split("/").pop();
    this.log.innerHTML = "";
    this.el.classList.add("open");
    this.input.focus();
    try {
      const { nodes } = await api.get("/api/assistant/nodes", { path });
      const question = nodes.find((n) => n.id === nodeId);
      if (!question) throw new Error("Soru bulunamadı.");
      this._setQuestion(question);
      const thread = nodes.filter((n) => n.parentId === nodeId && n.type.startsWith("chat-"));
      for (const n of thread) this._bubble(n.type === "chat-user" ? "user" : "assistant", n.text);
      if (!thread.length) {
        this.log.append(html('<div class="chat-empty">Soruya cevabını yaz. Asistan anlamadıysa tek bir soruyla netleştirir; anladığında notuna ne ekleyeceğini önerir — eklemeden önce senin onayını ister.</div>'));
      }
      this._scroll();
    } catch (err) {
      toast(err.message, "error");
      this.close();
    }
  }

  close() {
    this.el.classList.remove("open");
    this.path = null;
    this.nodeId = null;
  }

  /** Called when the server reports a node change (e.g. the model resolved this question). */
  nodeUpdated(path, node) {
    if (path === this.path && node.id === this.nodeId) this._setQuestion(node);
  }

  _setQuestion(q) {
    this.el.querySelector(".q").textContent = q.text;
    const chip = this.el.querySelector(".status");
    const done = q.status === "resolved";
    chip.className = `chip status ${done ? "chip-done" : "chip-open"}`;
    chip.textContent = done ? "Çözüldü" : "Açık";
    this.el.querySelector('[data-act="resolve"]').disabled = done;
  }

  _bubble(role, text) {
    this.log.querySelector(".chat-empty")?.remove();
    const el = html(`<div class="msg ${role}"></div>`);
    el.textContent = text;
    this.log.append(el);
    this._scroll();
    return el;
  }

  /** Nothing goes into the note until this is approved. */
  _proposal(event) {
    const card = html(`<div class="msg proposal" data-id="${esc(event.id)}">
      <div class="p-head">${icon("lightbulb", 13)}Nota eklensin mi?</div>
      <div class="p-text"></div>
      <div class="p-actions">
        <button class="btn btn-sm btn-accent" data-act="approve">${icon("check", 13)}Nota ekle</button>
        <button class="btn btn-sm" data-act="reject">Vazgeç</button>
      </div>
    </div>`);
    card.querySelector(".p-text").textContent = event.text;
    card.addEventListener("click", async (e) => {
      const act = e.target.closest("[data-act]")?.dataset.act;
      if (!act) return;
      card.querySelectorAll("button").forEach((b) => { b.disabled = true; });
      try {
        await api.post("/api/assistant/hud", { event_id: event.id, action: act });
        card.classList.add(act === "approve" ? "done" : "dropped");
        card.querySelector(".p-actions").innerHTML =
          act === "approve" ? "Nota eklendi." : "Nota eklenmedi.";
      } catch (err) {
        toast(err.message, "error");
        card.querySelectorAll("button").forEach((b) => { b.disabled = false; });
      }
    });
    this.log.append(card);
    this._scroll();
  }

  _scroll() { this.log.scrollTop = this.log.scrollHeight; }

  _autosize() {
    this.input.style.height = "auto";
    this.input.style.height = `${Math.min(this.input.scrollHeight, 140)}px`;
  }

  async send() {
    const message = this.input.value.trim();
    if (!message || this.sending || !this.path) return;
    this.sending = true;
    this.input.value = "";
    this._autosize();
    const { path, nodeId } = this;
    this._bubble("user", message);
    const pending = html(`<div class="msg assistant thinking"><div class="label">${icon("sparkle", 12)}Asistan düşünüyor<span class="dots"></span></div><div class="body"></div></div>`);
    this.log.append(pending);
    this._scroll();
    try {
      await this.beforeSend?.(path);
      await streamPost("/api/assistant/chat", { path, node_id: nodeId, message }, (u) => {
        if (path !== this.path) return;
        if (u.type === "progress") {
          if (u.phase === "writing" && u.text) {
            pending.className = "msg assistant";
            pending.textContent = u.text;
          } else {
            pending.querySelector(".body")?.replaceChildren(document.createTextNode(u.text || ""));
          }
          this._scroll();
        } else if (u.type === "done") {
          pending.className = "msg assistant";
          pending.textContent = u.node.text;
          if (u.proposal) this._proposal(u.proposal);
          else if (!u.understood) pending.classList.add(u.answered ? "answered" : "followup");
          this._scroll();
        } else if (u.type === "error") {
          pending.className = "msg error";
          pending.textContent = u.message;
        }
      });
    } catch (err) {
      pending.className = "msg error";
      pending.textContent = err.message;
    } finally {
      this.sending = false;
    }
  }

  async summarize() {
    if (!this.path || this.sending) return;
    const btn = this.el.querySelector('[data-act="summary"]');
    const { path, nodeId } = this;
    btn.disabled = true;
    const original = btn.innerHTML;
    btn.innerHTML = `${icon("sparkle", 14)}Yazılıyor<span class="dots"></span>`;
    try {
      const { proposal } = await api.post("/api/assistant/summarize", { path, node_id: nodeId });
      if (path === this.path && proposal) this._proposal(proposal);
    } catch (err) {
      toast(err.message, "error");
    } finally {
      btn.disabled = false;
      btn.innerHTML = original;
    }
  }

  async resolve() {
    if (!this.path) return;
    try {
      const node = await api.post("/api/assistant/resolve", { path: this.path, node_id: this.nodeId });
      this._setQuestion(node);
      toast("Soru çözüldü olarak işaretlendi.", "success");
    } catch (err) {
      toast(err.message, "error");
    }
  }
}
