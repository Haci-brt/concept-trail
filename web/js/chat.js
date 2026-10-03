// Slide-over chat about one of the assistant's questions. The thread is
// stored on the question node, so reopening it continues the conversation.
import { api, streamPost } from "./api.js";
import { icon } from "./icons.js";
import { esc, html, miniMarkdown, toast } from "./util.js";

// What each research tool is doing, in the user's words. web_search says out
// loud that a browser opens, so the window appearing is never a surprise.
const TOOL_LABELS = {
  web_search: "Web'de arandı (tarayıcı açıldı)",
  web_read_evidence: "Kayıtlı web sonucu okundu",
  web_status: "Web arama durumu okundu",
  git_search: "GitHub'da depo arandı",
  git_repo: "Depo bilgisi okundu",
  git_issues: "Depo konuları okundu",
  git_releases: "Sürüm notları okundu",
  git_read_file: "Depodaki dosya okundu",
  git_tree: "Depo dosya listesi okundu",
  git_revision: "Depo sürümü sabitlendi",
  git_catalog: "Toplanan depolar listelendi",
  git_read_evidence: "Kayıtlı kanıt okundu",
};

const toolLabel = (name) => TOOL_LABELS[name] || name;
/** An assistant bubble's text: "- " / "1. " lists and **bold** as markup, every
 *  other character escaped — the model's words never become raw HTML. */
const setRich = (el, text) => { el.classList.add("rich"); el.innerHTML = miniMarkdown(text); };
const threadKey = (path, nodeId) => `${path}\n${nodeId}`;

export class ChatDrawer {
  constructor({ beforeSend }) {
    this.beforeSend = beforeSend;
    this.path = null;
    this.nodeId = null;
    this.sending = false;
    this.opens = 0;
    this.drafts = new Map();    // unsent text per thread, so it never leaks into another

    this.el = html(`<aside class="chat" aria-label="Asistanla sohbet">
      <div class="chat-head">
        <span class="tile sm t-question">${icon("message", 14)}</span>
        <div class="grow"><div class="t">Asistanla Sohbet</div><div class="s note"></div></div>
        <button class="icon-btn" data-act="close" title="Kapat (Esc)">${icon("x", 16)}</button>
      </div>
      <div class="chat-seed">
        <div class="chat-lineage" hidden></div>
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
      const ancestor = e.target.closest("[data-ancestor]");
      if (ancestor && this.path) { this.open(this.path, ancestor.dataset.ancestor); return; }
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
    this._stash();
    this.path = path;
    this.nodeId = nodeId;
    // a later open (or a close) wins over this one's late answers
    const seq = ++this.opens;
    const current = () => seq === this.opens && this.path === path;
    this.el.querySelector(".note").textContent = path.split("/").pop();
    this.log.innerHTML = "";
    this.input.value = this.drafts.get(threadKey(path, nodeId)) || "";
    this.el.classList.add("open");
    this._autosize();
    this.input.focus();
    try {
      const { nodes } = await api.get("/api/assistant/nodes", { path });
      if (!current()) return;
      const question = nodes.find((n) => n.id === nodeId);
      if (!question) throw new Error("Soru bulunamadı.");
      this._showLineage(nodes, question);
      this._setQuestion(question);
      const thread = nodes.filter((n) => n.parentId === nodeId
        && (n.type.startsWith("chat-") || n.type === "summary"));
      // approving takes the proposal's history event, not its node
      const events = thread.some((n) => n.type === "summary" && n.status === "pending")
        ? await api.get("/api/assistant/history").catch(() => []) : [];
      if (!current()) return;
      for (const n of thread) {
        if (n.type === "summary") {
          const event = events.find((e) => e.type === "summary" && e.path === path && e.node_id === n.id);
          this._proposal({ id: event?.id, node_id: n.id, text: n.text }, n.status);
          continue;
        }
        if (n.tools?.length) this._provenance(n.tools);
        this._bubble(n.type === "chat-user" ? "user" : "assistant", n.text);
      }
      if (!thread.length) {
        this.log.append(html('<div class="chat-empty">Soruya cevabını yaz. Bilmiyorsan ya da fikir istersen seçenekler sunar; anlamadıysa bir soruyla netleştirir; bir karar verdiğinde notuna ne ekleyeceğini önerir — eklemeden önce senin onayını ister.</div>'));
      }
      this._scroll();
    } catch (err) {
      if (!current()) return;
      toast(err.message, "error");
      this.close();
    }
  }

  close() {
    this._stash();
    this.el.classList.remove("open");
    this.path = null;
    this.nodeId = null;
  }

  /** Keep what was typed but not sent with the thread it was typed in. */
  _stash() {
    if (!this.path) return;
    const key = threadKey(this.path, this.nodeId);
    if (this.input.value) this.drafts.set(key, this.input.value);
    else this.drafts.delete(key);
  }

  /** Called when the server reports a node change (e.g. the model resolved this question). */
  nodeUpdated(path, node) {
    if (path !== this.path) return;
    if (node.id === this.nodeId) this._setQuestion(node);
    // decided elsewhere (the side panel, the assistant card): no live buttons left behind
    const card = node.type === "summary" && node.status !== "pending"
      && this.log.querySelector(`.proposal[data-node="${CSS.escape(node.id)}"]`);
    if (card && !card.matches(".done, .dropped")) this._settle(card, node.status === "approved");
  }

  _showLineage(nodes, question) {
    const holder = this.el.querySelector(".chat-lineage");
    holder.replaceChildren();
    const byId = new Map(nodes.map((node) => [node.id, node]));
    const seen = new Set([question.id]);
    const ancestors = [];
    let parent = byId.get(question.parentId);
    while (parent?.type === "question" && !seen.has(parent.id)) {
      ancestors.unshift(parent);
      seen.add(parent.id);
      parent = byId.get(parent.parentId);
    }
    holder.hidden = !ancestors.length;
    if (!ancestors.length) return;
    const label = document.createElement("span");
    label.textContent = "Önceki dal";
    holder.append(label);
    for (const ancestor of ancestors) {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.ancestor = ancestor.id;
      button.title = ancestor.text;
      button.textContent = ancestor.text;
      holder.append(button);
    }
  }

  _setQuestion(q) {
    this.el.querySelector(".q").textContent = q.text;
    const chip = this.el.querySelector(".status");
    const done = q.status !== "open";
    const dismissed = q.status === "dismissed";
    chip.className = `chip status ${done ? "chip-done" : "chip-open"}`;
    chip.textContent = dismissed ? "Rotadan çıkarıldı" : done ? "Çözüldü" : "Açık";
    this.el.querySelector('[data-act="resolve"]').disabled = done;
  }

  _bubble(role, text) {
    this.log.querySelector(".chat-empty")?.remove();
    const el = html(`<div class="msg ${role}"></div>`);
    if (role === "assistant") setRich(el, text);
    else el.textContent = text;
    this.log.append(el);
    this._scroll();
    return el;
  }

  /** Nothing goes into the note until this is approved. A settled one comes
   *  back as it was left; one whose event is gone comes back without buttons. */
  _proposal(event, status = "pending") {
    const card = html(`<div class="msg proposal" data-id="${esc(event.id)}" data-node="${esc(event.node_id || "")}">
      <div class="p-head">${icon("lightbulb", 13)}Nota eklensin mi?</div>
      <div class="p-text"></div>
      <div class="p-actions">
        <button class="btn btn-sm btn-accent" data-act="approve">${icon("check", 13)}Nota ekle</button>
        <button class="btn btn-sm" data-act="reject">Vazgeç</button>
      </div>
    </div>`);
    card.querySelector(".p-text").textContent = event.text;
    const settle = (approved) => this._settle(card, approved);
    if (status !== "pending") settle(status === "approved");
    else if (!event.id) card.querySelector(".p-actions").remove();
    card.addEventListener("click", async (e) => {
      const act = e.target.closest("[data-act]")?.dataset.act;
      if (!act) return;
      card.querySelectorAll("button").forEach((b) => { b.disabled = true; });
      try {
        await api.post("/api/assistant/hud", { event_id: event.id, action: act });
        settle(act === "approve");
      } catch (err) {
        toast(err.message, "error");
        card.querySelectorAll("button").forEach((b) => { b.disabled = false; });
      }
    });
    this.log.append(card);
    this._scroll();
  }

  _settle(card, approved) {
    card.classList.add(approved ? "done" : "dropped");
    const actions = card.querySelector(".p-actions") || card.appendChild(html('<div class="p-actions"></div>'));
    actions.textContent = approved ? "Nota eklendi." : "Nota eklenmedi.";
  }

  /** Where a saved answer came from, shown when the thread is reopened. */
  _provenance(tools) {
    const box = html('<div class="msg assistant steps"></div>');
    for (const t of tools) {
      const row = html(`<div class="step${t.ok ? "" : " bad"}"></div>`);
      row.textContent = toolLabel(t.name);
      box.append(row);
    }
    this.log.append(box);
    return box;
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
    this.drafts.delete(threadKey(path, nodeId));
    this._bubble("user", message);
    const pending = html(`<div class="msg assistant thinking"><div class="label">${icon("sparkle", 12)}<span class="txt">Asistan düşünüyor</span><span class="dots"></span></div><div class="body"></div></div>`);
    this.log.append(pending);
    this._scroll();
    // research steps live in their own bubble above the answer, so a streamed
    // reply overwriting `pending` never erases the record of what was searched
    let steps = null;
    try {
      await this.beforeSend?.(path);
      await streamPost("/api/assistant/chat", { path, node_id: nodeId, message }, (u) => {
        // another thread is showing, or this one was redrawn: the reply is saved
        // on the server and comes back with the thread
        if (path !== this.path || nodeId !== this.nodeId || !pending.isConnected) return;
        if (u.type === "tool") {
          // the writing branch replaces pending's contents, so .txt may be gone
          const label = pending.querySelector(".txt");
          if (label) label.textContent = "Asistan araştırıyor";
          if (!steps) {
            steps = html('<div class="msg assistant steps"></div>');
            this.log.insertBefore(steps, pending);
          }
          const row = html(`<div class="step${u.ok ? "" : " bad"}"></div>`);
          row.textContent = `${toolLabel(u.name)}${u.query ? `: “${u.query.slice(0, 90)}”` : ""}`
            + ` · ${u.seconds} sn${u.ok ? "" : " · başarısız"}`;
          steps.append(row);
          this._scroll();
        } else if (u.type === "progress") {
          if (u.phase === "writing" && u.text) {
            pending.className = "msg assistant";
            setRich(pending, u.text);
          } else {
            pending.querySelector(".body")?.replaceChildren(document.createTextNode(u.text || ""));
          }
          this._scroll();
        } else if (u.type === "done") {
          pending.className = "msg assistant";
          setRich(pending, u.node.text);
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
      if (path === this.path && nodeId === this.nodeId && proposal) this._proposal(proposal);
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
