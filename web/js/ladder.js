// The decision ladder of the open note: how far the design has come, broad to
// narrow — scope, architecture, components, details — and the moment it has
// enough in it to become a product. A decision is yours to correct: the model
// can misread the note, so every chip toggles.
import { api } from "./api.js";
import { icon } from "./icons.js";
import { esc, toast } from "./util.js";

const BY = { not: "notta yazıyor", cevap: "soruya cevap verdin", sen: "sen işaretledin" };

export class LadderPanel {
  constructor(root) {
    this.root = root;
    this.path = null;
    this.state = null;
    this.mode = null;
    this.shown = null;          // the rung being looked at; null = the current one
    root.addEventListener("click", (e) => this._click(e));
  }

  /** A note became active: show its ladder (or nothing, for a `tur: fikir` note). */
  async load(path) {
    this.path = path;
    this.shown = null;
    try {
      const { ladder, mode } = await api.get("/api/assistant/nodes", { path });
      if (path !== this.path) return;
      this.state = ladder;
      this.mode = mode;
    } catch {
      this.state = null;
    }
    this.render();
  }

  update(path, ladder) {
    if (path !== this.path) return;
    this.state = ladder;
    this.render();
  }

  clear() {
    this.path = null;
    this.state = null;
    this.render();
  }

  render() {
    const s = this.state;
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
    const chips = level.decisions.map((d) => {
      const said = d.value ? `: ${d.value}` : "";
      const why = d.decided ? `${said} — ${BY[d.by] || "verildi"}. Geri almak için tıkla.` : " — verildi diye işaretlemek için tıkla.";
      return `<button class="lg-chip${d.decided ? " y" : ""}" data-decision="${d.id}" data-decided="${d.decided ? 1 : 0}"
        title="${esc(d.hint)}${why}">${d.decided ? icon("check", 12) : '<span class="lg-dot"></span>'}${esc(d.label)}</button>`;
    }).join("");
    const head = product
      ? `<div class="lg-head product">${icon("sprout", 15)}<span class="lg-title">Ürün evresi</span><span class="lg-count">${s.made}/${s.total}</span></div>
         <p class="lg-note">Bütün kararlar verildi: kapsam, mimari, bileşenler ve detaylar belli. Bu not yapmaya başlamak için yeterli.</p>`
      : `<div class="lg-head">${icon("tree", 15)}<span class="lg-title">Yol haritası</span>
         <span class="lg-phase">${esc(s.phase_label)}</span><span class="lg-count">${s.made}/${s.total}</span></div>`;
    const label = level.id === s.current ? `${esc(level.label)} · şimdi bunu netleştiriyoruz`
      : level.done ? `${esc(level.label)} · tamam` : `${esc(level.label)} · sırası gelmedi`;
    this.root.innerHTML = `${head}<div class="lg-bar">${bar}</div>
      <div class="lg-level">${label}</div><div class="lg-chips">${chips}</div>`;
  }

  async _click(e) {
    const seg = e.target.closest("[data-level]");
    if (seg) {
      this.shown = seg.dataset.level === this.state?.current ? null : seg.dataset.level;
      this.render();
      return;
    }
    const chip = e.target.closest("[data-decision]");
    if (!chip || !this.path) return;
    chip.disabled = true;
    try {
      const ladder = await api.post("/api/assistant/decision", {
        path: this.path, decision: chip.dataset.decision, decided: chip.dataset.decided !== "1",
      });
      this.update(this.path, ladder);
    } catch (err) {
      toast(err.message, "error");
      chip.disabled = false;
    }
  }
}
