// A direct way for the writer to correct the project's course at any point.
import { api } from "./api.js";
import { esc, html, toast } from "./util.js";

const OPTIONS = [
  { id: "amac", label: "Amaç", example: "Bu proje otomatik karar vermesin; seçenekleri gerekçeleriyle sunsun." },
  { id: "kullanici", label: "Hedef kullanıcı", example: "Öncelikli kullanıcı yalnızca benim; ekip akışlarını şimdilik dışarıda tut." },
  { id: "kapsam", label: "Kapsam", example: "İlk sürüm sadece notları düzenlesin; paylaşım ve mobil uygulama istemiyorum." },
  { id: "cikti", label: "Çıktı biçimi", example: "Soruları kısa tut; seçenekler ve somut örnekler ekle." },
  { id: "diger", label: "Başka bir yön", example: "Bu fikri otomasyon aracı değil, düşünme yardımcısı olarak ele al." },
];

export class DirectionDialog {
  constructor({ beforeOpen, onSaved } = {}) {
    this.beforeOpen = beforeOpen;
    this.onSaved = onSaved;
    this.overlay = null;
  }

  async open(path) {
    if (this.overlay) this.close();
    try {
      await this.beforeOpen?.(path);
      const { nodes, direction } = await api.get("/api/assistant/nodes", { path });
      this.path = path;
      this.current = direction;
      this.openQuestions = nodes.filter((n) => n.type === "question" && n.status === "open").length;
      this.latestQuestion = nodes.filter((n) => n.type === "question" && n.status === "open").at(-1)?.text || "";
      this.pending = nodes.filter((n) => ["edit", "summary"].includes(n.type) && n.status === "pending").length;
      this.category = direction?.category || "";
      this.overlay = html('<div class="overlay direction-overlay"></div>');
      this.dialog = html(`<div class="dialog wide direction-dialog" role="dialog" aria-modal="true" aria-label="Rotayı düzelt">
        <h2>Rotayı düzelt</h2>
        <p>Gidişatta ne farklı? Bir alan seç, sonra kendi cümlenle anlat.</p>
        <div class="direction-context"></div>
        <div class="direction-options" role="group" aria-label="Düzeltme alanı"></div>
        <label class="direction-label" for="directionText">Nasıl ilerlememizi istiyorsun?</label>
        <textarea id="directionText" class="field" rows="4" maxlength="2000"></textarea>
        <p class="direction-example"></p>
        <div class="direction-current"></div>
        <div class="direction-review" hidden></div>
        <div class="field-error" role="alert"></div>
        <div class="actions">
          <button class="btn btn-ghost" data-act="cancel">Vazgeç</button>
          <button class="btn btn-ghost" data-act="back" hidden>Geri</button>
          <button class="btn btn-accent" data-act="next">Önizle</button>
          <button class="btn btn-accent" data-act="save" hidden>Yönü kaydet</button>
        </div>
      </div>`);
      document.body.append(this.overlay, this.dialog);
      this.textarea = this.dialog.querySelector("textarea");
      this.textarea.value = direction?.text || "";
      this.dialog.querySelector(".direction-current").textContent = direction
        ? `Geçerli yön: ${direction.text}` : "";
      this.dialog.querySelector(".direction-context").textContent = this.latestQuestion
        ? `Şu an bekleyen soru: ${this.latestQuestion}` : "";
      this.dialog.querySelector(".direction-options").innerHTML = OPTIONS.map((o) =>
        `<button class="direction-option" type="button" data-category="${o.id}">${esc(o.label)}</button>`).join("");
      this.dialog.addEventListener("click", (e) => this._click(e));
      this.overlay.addEventListener("mousedown", () => this.close());
      this._key = (e) => { if (e.key === "Escape") { e.preventDefault(); this.close(); } };
      document.addEventListener("keydown", this._key, true);
      this._select(this.category);
      this.textarea.focus();
    } catch (err) {
      toast(err.message, "error");
    }
  }

  _select(category) {
    this.category = category;
    for (const button of this.dialog.querySelectorAll("[data-category]")) {
      button.classList.toggle("on", button.dataset.category === category);
      button.setAttribute("aria-pressed", String(button.dataset.category === category));
    }
    const option = OPTIONS.find((o) => o.id === category);
    this.dialog.querySelector(".direction-example").textContent = option
      ? `Örnek: “${option.example}”` : "Önce bir alan seç; örnek bir cümle göstereceğim.";
    if (option && !this.textarea.value.trim()) this.textarea.placeholder = option.example;
  }

  /** The correction goes to the model, which compares it with the note's goal
   *  and decisions: a short summary of the new course and exactly what it
   *  would reopen or close. Nothing changes before "Yönü kaydet". */
  async _review() {
    const text = this.textarea.value.trim();
    const error = this.dialog.querySelector(".field-error");
    if (!this.category) { error.textContent = "Önce neyi düzeltmek istediğini seç."; return; }
    if (!text) { error.textContent = "İstediğin yönü bir cümleyle yaz."; this.textarea.focus(); return; }
    error.textContent = "";
    const next = this.dialog.querySelector('[data-act="next"]');
    next.disabled = true;
    next.textContent = "Etkisi inceleniyor…";
    try {
      this.plan = await api.post("/api/assistant/direction/preview", {
        path: this.path, category: this.category, text,
      });
    } catch (err) {
      error.textContent = err.message;
      return;
    } finally {
      next.disabled = false;
      next.textContent = "Önizle";
    }
    const option = OPTIONS.find((o) => o.id === this.category);
    const group = (title, ids) => ids.length ? `<div class="direction-group"><b>${title}</b>
        ${ids.map((id) => `<label class="direction-item"><input type="checkbox" data-plan-id="${esc(id)}" checked>
          <span>${esc(this.plan.items[id] || id)}</span></label>`).join("")}</div>` : "";
    const review = this.dialog.querySelector(".direction-review");
    review.innerHTML = `<strong>Yeni gidişat</strong>
      <p>${esc(this.plan.summary)}</p>
      <p class="direction-said"><b>${esc(option.label)}:</b> ${esc(text)}</p>
      ${group("Güncellenecek kararlar", Object.keys(this.plan.update || {}))}
      ${group("Yeniden sorulacak kararlar", this.plan.reopen)}
      ${group("Kapanacak sorular", this.plan.drop_questions)}
      ${group("Kaldırılacak öneriler", this.plan.drop_proposals)}
      ${group("Hemen sorulacak yeni sorular", (this.plan.ask || []).map((q) => q.id))}
      ${!Object.keys(this.plan.update || {}).length && !this.plan.reopen.length && !this.plan.drop_questions.length && !this.plan.drop_proposals.length && !(this.plan.ask || []).length
        ? "<p class=\"direction-none\">Verilmiş kararlar ve bekleyen sorular bu yönle çelişmiyor; hepsi korunacak.</p>" : ""}
      <p class="direction-hint">İşaretini kaldırdığın kalem olduğu gibi kalır. Sonraki sorular bu yöne göre gelecek.</p>`;
    review.hidden = false;
    this.textarea.hidden = true;
    this.dialog.querySelector(".direction-options").hidden = true;
    this.dialog.querySelector(".direction-label").hidden = true;
    this.dialog.querySelector(".direction-example").hidden = true;
    this.dialog.querySelector('[data-act="next"]').hidden = true;
    this.dialog.querySelector('[data-act="back"]').hidden = false;
    this.dialog.querySelector('[data-act="save"]').hidden = false;
  }

  _back() {
    this.dialog.querySelector(".direction-review").hidden = true;
    for (const selector of ["textarea", ".direction-options", ".direction-label", ".direction-example", '[data-act="next"]']) {
      this.dialog.querySelector(selector).hidden = false;
    }
    this.dialog.querySelector('[data-act="back"]').hidden = true;
    this.dialog.querySelector('[data-act="save"]').hidden = true;
    this.textarea.focus();
  }

  async _click(e) {
    const category = e.target.closest("[data-category]")?.dataset.category;
    if (category) { this._select(category); return; }
    const action = e.target.closest("[data-act]")?.dataset.act;
    if (action === "cancel") this.close();
    if (action === "back") this._back();
    if (action === "next") this._review();
    if (action !== "save") return;
    const button = this.dialog.querySelector('[data-act="save"]');
    button.disabled = true;
    // only what stayed ticked is applied
    const kept = new Set([...this.dialog.querySelectorAll("[data-plan-id]")]
      .filter((box) => box.checked).map((box) => box.dataset.planId));
    const plan = this.plan && {
      summary: this.plan.summary,
      update: Object.fromEntries(Object.entries(this.plan.update || {}).filter(([id]) => kept.has(id))),
      reopen: this.plan.reopen.filter((id) => kept.has(id)),
      drop_questions: this.plan.drop_questions.filter((id) => kept.has(id)),
      drop_proposals: this.plan.drop_proposals.filter((id) => kept.has(id)),
      ask: (this.plan.ask || []).filter((q) => kept.has(q.id)).map((q) => q.text),
    };
    try {
      const result = await api.post("/api/assistant/direction", {
        path: this.path, category: this.category, text: this.textarea.value.trim(), plan,
      });
      this.close();
      this.onSaved?.(this.path, result);
    } catch (err) {
      this.dialog.querySelector(".field-error").textContent = err.message;
      button.disabled = false;
    }
  }

  close() {
    if (this._key) document.removeEventListener("keydown", this._key, true);
    this.overlay?.remove();
    this.dialog?.remove();
    this.overlay = this.dialog = null;
  }
}
