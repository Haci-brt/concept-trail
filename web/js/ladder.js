// The decision ladder of the open note: how far the design has come, broad to
// narrow — scope, architecture, components, details — and the moment it has
// enough in it to become a product. A decision is yours to correct: the model
// can misread the note, so every chip opens what was recorded, and a change
// can be taken back.
import { api } from "./api.js";
import { t } from "./i18n.js";
import { icon } from "./icons.js";
import { esc, html, toast } from "./util.js";

const BY = { not: "notta yazıyor", cevap: "soruya cevap verdin", sen: "sen işaretledin", rota: "rotayı düzelttiğinde söyledin" };

export class LadderPanel {
  /** showWaiting(): bring the list of waiting questions into view. */
  constructor(root, { showWaiting, correctDirection, master, onRender } = {}) {
    this.root = root;
    this.showWaiting = showWaiting;
    this.correctDirection = correctDirection;
    this.master = master;
    this.onRender = onRender;
    this.path = null;
    this.state = null;
    this.mode = null;
    this.direction = null;
    this.shown = null;          // the rung being looked at; null = the current one
    // Show how many questions are still waiting for an answer in this note.
    this.waiting = new Set();
    root.addEventListener("click", (e) => this._click(e));
  }

  /** A note became active: show its ladder (or nothing, for a `tur: fikir` note). */
  async load(path) {
    this.path = path;
    this.shown = null;
    try {
      const { ladder, mode, nodes, direction } = await api.get("/api/assistant/nodes", { path });
      if (path !== this.path) return;
      this.state = ladder;
      this.mode = mode;
      this.direction = direction;
      this.waiting = new Set((nodes || []).filter((n) => n.type === "question" && n.status === "open").map((n) => n.id));
    } catch {
      this.state = null;
      this.waiting = new Set();
    }
    this.render();
  }

  update(path, ladder) {
    if (path !== this.path) return;
    this.state = ladder;
    this.render();
  }

  nodeChanged(path, node) {
    if (path !== this.path || node?.type !== "question") return;
    const before = this.waiting.size;
    if (node.status === "open") this.waiting.add(node.id);
    else this.waiting.delete(node.id);
    if (this.waiting.size !== before) this.render();
  }

  clear() {
    this.path = null;
    this.state = null;
    this.direction = null;
    this.render();
  }

  render() {
    const s = this.state;
    this.onRender?.(this.mode === "fikir" ? null : s);
    if (!s || this.mode === "fikir") {
      this.root.hidden = true;
      this.root.innerHTML = "";
      return;
    }
    this.root.hidden = false;
    const product = s.phase === "urun";
    const level = s.levels.find((l) => l.id === (this.shown || s.current)) || s.levels[s.levels.length - 1];
    const bar = s.levels.map((l) => `<button class="lg-seg${l.id === level.id ? " on" : ""}${l.done ? " done" : ""}${l.id === s.current ? " now" : ""}"
        data-level="${l.id}" title="${esc(l.label)}: ${l.decisions.filter((d) => d.decided).length}/${l.decisions.length} karar">
        ${l.decisions.map((d) => `<i${d.decided ? ' class="y"' : ""}></i>`).join("")}</button>`).join("");
    // the hint is one of the ladder's fixed strings: the dictionary has it
    const chips = level.decisions.map((d) => `<button class="lg-chip${d.decided ? " y" : ""}" data-decision="${d.id}"
        data-decided="${d.decided ? 1 : 0}" aria-haspopup="dialog" title="${esc(t(d.hint))}">
        ${d.decided ? icon("check", 12) : '<span class="lg-dot"></span>'}${esc(d.label)}</button>`).join("");
    const waiting = this.waiting.size
      ? `<button class="lg-wait" data-act="waiting" title="Bekleyen sorular sağdaki listede — göstermek için tıkla">
          ${icon("questionSquare", 12)}${this.waiting.size} soru bekliyor</button>` : "";
    const head = product
      ? `<div class="lg-head product">${icon("sprout", 15)}<span class="lg-title">Ürün evresi</span>${waiting}<button class="lg-correct" data-act="direction">Rotayı düzelt</button><span class="lg-count">${s.made}/${s.total}</span></div>
         <p class="lg-note">Bütün kararlar verildi: kapsam, mimari, bileşenler ve detaylar belli. Bu not yapmaya başlamak için yeterli.</p>
         <button class="lg-master" data-act="master">${icon("wand", 13)}Master prompt hazırla</button>`
      : `<div class="lg-head">${icon("tree", 15)}<span class="lg-title">Yol haritası</span>
         <span class="lg-phase">${esc(s.phase_label)}</span>${waiting}<button class="lg-correct" data-act="direction">Rotayı düzelt</button><span class="lg-count">${s.made}/${s.total}</span></div>`;
    const label = level.id === s.current ? `${esc(level.label)} · şimdi bunu netleştiriyoruz`
      : level.done ? `${esc(level.label)} · tamam` : `${esc(level.label)} · sırası gelmedi`;
    const direction = this.direction ? `<div class="lg-direction" title="${esc(this.direction.text)}">Son yön: ${esc(this.direction.summary || this.direction.text)}</div>` : "";
    this.root.innerHTML = `${head}${direction}<div class="lg-bar">${bar}</div>
      <div class="lg-level">${label}</div><div class="lg-chips">${chips}</div>`;
  }

  async _click(e) {
    if (e.target.closest('[data-act="direction"]')) {
      this.correctDirection?.(this.path);
      return;
    }
    if (e.target.closest('[data-act="master"]')) {
      this.master?.();
      return;
    }
    if (e.target.closest('[data-act="waiting"]')) {
      this.showWaiting?.();
      return;
    }
    const seg = e.target.closest("[data-level]");
    if (seg) {
      this.shown = seg.dataset.level === this.state?.current ? null : seg.dataset.level;
      this.render();
      return;
    }
    const chip = e.target.closest("[data-decision]");
    if (!chip || !this.path) return;
    if (this.pop?.id === chip.dataset.decision) this._closePop();
    else this._openPop(chip);
  }

  _decision(id) {
    for (const level of this.state?.levels || []) {
      const found = level.decisions.find((d) => d.id === id);
      if (found) return found;
    }
    return null;
  }

  /** A click on a chip changes nothing yet: it shows what is recorded, who
   *  recorded it, and the one change that applies. */
  _openPop(chip) {
    this._closePop();
    const d = this._decision(chip.dataset.decision);
    if (!d) return;
    const pop = html(`<div class="lg-pop" role="dialog" aria-label="${esc(d.label)}">
      <div class="lg-pop-head"><b>${esc(d.label)}</b>
        <span class="lg-pop-state${d.decided ? " y" : ""}">${d.decided ? "Karar verildi" : "Henüz karar verilmedi"}</span></div>
      <p class="lg-pop-hint">${esc(d.hint)}</p>
      ${d.decided ? `<dl class="lg-pop-facts">
          <dt>Değer</dt><dd translate="no">${d.value ? esc(d.value) : "—"}</dd>
          ${d.by ? `<dt>Kaynak</dt><dd>${esc(BY[d.by] || d.by)}</dd>` : ""}</dl>`
        : '<input class="field lg-pop-value" type="text" maxlength="160" spellcheck="false" placeholder="Ne karar verdin? (isteğe bağlı)">'}
      <div class="lg-pop-actions">
        <button class="btn btn-sm btn-ghost" data-pop="close">Kapat</button>
        ${d.decided ? '<button class="btn btn-sm btn-accent" data-pop="reopen">Yeniden sor</button>'
          : '<button class="btn btn-sm btn-accent" data-pop="decide">Karar verildi</button>'}
      </div>
    </div>`);
    document.body.append(pop);
    const r = chip.getBoundingClientRect(), p = pop.getBoundingClientRect();
    pop.style.left = `${Math.max(8, Math.min(r.left, innerWidth - p.width - 8))}px`;
    pop.style.top = `${r.bottom + 6 + p.height > innerHeight - 8 ? Math.max(8, r.top - p.height - 6) : r.bottom + 6}px`;
    this.pop = { el: pop, id: d.id, path: this.path };
    pop.addEventListener("click", (e) => {
      const act = e.target.closest("[data-pop]")?.dataset.pop;
      if (act === "close") this._closePop(true);
      else if (act) this._change(d, act === "decide");
    });
    pop.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && e.target.matches("input")) { e.preventDefault(); this._change(d, true); }
    });
    this._dismiss = (e) => {
      if (e.type === "keydown") {
        if (e.key !== "Escape") return;
        e.preventDefault();
        e.stopPropagation();
        this._closePop(true);
      } else if (!pop.contains(e.target) && !e.target.closest?.(`[data-decision="${d.id}"]`)) {
        this._closePop();
      }
    };
    document.addEventListener("mousedown", this._dismiss, true);
    document.addEventListener("keydown", this._dismiss, true);
    (pop.querySelector("input") || pop.querySelector(".btn-accent")).focus();
  }

  _closePop(refocus = false) {
    if (!this.pop) return;
    const { el, id } = this.pop;
    this.pop = null;
    el.remove();
    document.removeEventListener("mousedown", this._dismiss, true);
    document.removeEventListener("keydown", this._dismiss, true);
    if (refocus) this.root.querySelector(`[data-decision="${id}"]`)?.focus();
  }

  async _set(path, id, decided, value = "") {
    const ladder = await api.post("/api/assistant/decision", {
      path, decision: id, decided, ...(decided && value ? { value } : {}),
    });
    this.update(path, ladder);
  }

  /** Mark it made (with what was decided, if written) or open it again — and
   *  offer the way back, recorded value included. */
  async _change(d, decided) {
    const { el, path } = this.pop || {};
    if (!el) return;
    const value = el.querySelector("input")?.value.trim() || "";
    const before = { decided: d.decided, value: d.value || "" };
    el.querySelectorAll("button, input").forEach((b) => { b.disabled = true; });
    try {
      await this._set(path, d.id, decided, value);
    } catch (err) {
      toast(err.message, "error");
      el.querySelectorAll("button, input").forEach((b) => { b.disabled = false; });
      return;
    }
    this._closePop(true);
    toast(decided ? `“${d.label}” karar verildi olarak işaretlendi.` : `“${d.label}” yeniden sorulacak.`, "success", 8000, {
      action: "Geri al",
      onAction: () => this._set(path, d.id, before.decided, before.value).catch((err) => toast(err.message, "error")),
    });
  }
}
