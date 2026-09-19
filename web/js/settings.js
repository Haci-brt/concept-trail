// "Modeller ve anahtarlar": add providers (local servers or API keys), bind
// each job to one, set the remote budget. This is the UI over /api/providers.
import { api } from "./api.js";
import { openMenu } from "./dialogs.js";
import { icon } from "./icons.js";
import { esc, html, toast } from "./util.js";

const KEY_MASK = "••••";

const ROLE_INFO = [
  ["analysis", "Not izleme", "Yazarken soruları ve düzenleme önerilerini üretir — hızlı bir model seç."],
  ["chat", "Sohbet", "Cevabını değerlendirir, anlamadıysa tekrar sorar."],
  ["summary", "Nota yazma", "Sonucu notuna eklenecek cümleye dönüştürür."],
];

const PRESETS = [
  { key: "openai", label: "OpenAI", base_url: "https://api.openai.com", model: "gpt-4o-mini",
    kind: "remote", health: "models", token_field: "max_completion_tokens" },
  { key: "openrouter", label: "OpenRouter", base_url: "https://openrouter.ai/api", model: "openai/gpt-4o-mini",
    kind: "remote", health: "models", token_field: "max_tokens" },
  { key: "groq", label: "Groq", base_url: "https://api.groq.com/openai", model: "llama-3.3-70b-versatile",
    kind: "remote", health: "models", token_field: "max_tokens" },
  { key: "deepseek", label: "DeepSeek", base_url: "https://api.deepseek.com", model: "deepseek-chat",
    kind: "remote", health: "models", token_field: "max_tokens" },
  { key: "local", label: "Yerel llama-server", base_url: "http://127.0.0.1:8899", model: "",
    kind: "local", health: "llama", token_field: "max_tokens", extras: { cache_prompt: true } },
];

const numberOr = (value, fallback) => (Number.isFinite(Number(value)) ? Number(value) : fallback);

export class SettingsDialog {
  constructor() {
    this.el = null;
  }

  get isOpen() { return Boolean(this.el); }

  async open() {
    if (this.el) return;
    let data, usage;
    try {
      [data, usage] = await Promise.all([api.get("/api/providers"), api.get("/api/usage")]);
    } catch (err) {
      toast(err.message, "error");
      return;
    }
    this.roles = data.roles;
    this.usage = usage;

    this.overlay = html('<div class="overlay"></div>');
    this.el = html(`<div class="dialog settings" role="dialog" aria-modal="true" aria-label="Modeller ve anahtarlar">
      <header class="set-head">
        <div>
          <h2>Modeller ve anahtarlar</h2>
          <p>Hangi işi hangi modelin yapacağını burada seçersin. Yerel sunucu da, API anahtarı da aynı şekilde çalışır.</p>
        </div>
        <button class="icon-btn" data-act="close" title="Kapat (Esc)">${icon("x", 16)}</button>
      </header>
      <div class="set-body">
        <section>
          <div class="set-section-head">
            <h3>${icon("cpu", 15)}Sağlayıcılar</h3>
            <button class="btn btn-sm" data-act="add">${icon("plus", 14)}Ekle</button>
          </div>
          <div class="provider-list"></div>
        </section>
        <section>
          <div class="set-section-head"><h3>${icon("command", 15)}Hangi iş hangi modelde</h3></div>
          <div class="role-list"></div>
        </section>
        <section>
          <div class="set-section-head"><h3>${icon("zap", 15)}Uzak model bütçesi</h3></div>
          <div class="budget"></div>
        </section>
        <section class="privacy-note">
          ${icon("eye", 15)}
          <div>Bir notun başına <code>gizli: true</code> yazarsan o not asla uzak sağlayıcıya gönderilmez;
          o not için hep yerel model kullanılır. Yerel model yoksa istek yapılmaz.</div>
        </section>
      </div>
      <footer class="actions">
        <span class="set-error"></span>
        <button class="btn btn-ghost" data-act="close">Vazgeç</button>
        <button class="btn btn-accent" data-act="save">${icon("check", 14)}Kaydet</button>
      </footer>
    </div>`);
    document.body.append(this.overlay, this.el);

    this.listEl = this.el.querySelector(".provider-list");
    this.rolesEl = this.el.querySelector(".role-list");
    this.errorEl = this.el.querySelector(".set-error");
    for (const provider of data.providers) this._addCard(provider);
    this._renderRoles();
    this._renderBudget();

    this.el.addEventListener("click", (e) => this._click(e));
    this.el.addEventListener("input", (e) => {
      if (e.target.matches("[data-f]")) this._renderRoles();
    });
    this.overlay.addEventListener("mousedown", () => this.close());
    this._keys = (e) => {
      if (e.key === "Escape" && !document.querySelector(".menu")) { e.preventDefault(); this.close(); }
    };
    document.addEventListener("keydown", this._keys, true);
  }

  close() {
    if (!this.el) return;
    document.removeEventListener("keydown", this._keys, true);
    this.el.remove();
    this.overlay.remove();
    this.el = null;
  }

  // ---------- provider cards ----------
  _addCard(provider) {
    const remote = provider.kind === "remote";
    const card = html(`<article class="provider${provider.enabled === false ? " off" : ""}" data-id="${esc(provider.id)}">
      <div class="p-top">
        <span class="p-dot${provider.up ? " up" : ""}" title="${provider.up ? "Çalışıyor" : "Yanıt vermiyor"}"></span>
        <input class="field p-label" data-f="label" value="${esc(provider.label || provider.id)}" aria-label="Ad">
        <span class="chip p-kind">${remote ? "Bulut" : "Yerel"}</span>
        <button class="icon-btn sm" data-act="toggle" title="Devre dışı bırak / aç">${icon(provider.enabled === false ? "eyeOff" : "eye", 15)}</button>
        <button class="icon-btn sm" data-act="remove" title="Kaldır">${icon("trash", 15)}</button>
      </div>
      <div class="p-grid">
        <label>Adres<input class="field" data-f="base_url" value="${esc(provider.base_url || "")}" spellcheck="false"></label>
        <label>Model<input class="field" data-f="model" value="${esc(provider.model || "")}" placeholder="${remote ? "ör. gpt-4o-mini" : "yerelde gerekmez"}" spellcheck="false"></label>
        <label>API anahtarı<input class="field" data-f="api_key" type="password" value="${provider.has_key ? KEY_MASK : ""}" placeholder="${remote ? "gerekli" : "gerekmez"}" spellcheck="false" autocomplete="off"></label>
        <label>Sağlık kontrolü<select class="field" data-f="health">
          <option value="llama"${provider.health === "llama" ? " selected" : ""}>llama.cpp (/health)</option>
          <option value="models"${provider.health === "models" ? " selected" : ""}>OpenAI (/v1/models)</option>
          <option value="none"${provider.health === "none" ? " selected" : ""}>Yok</option>
        </select></label>
        <label>Token alanı<select class="field" data-f="token_field">
          <option value="max_tokens"${provider.token_field !== "max_completion_tokens" ? " selected" : ""}>max_tokens</option>
          <option value="max_completion_tokens"${provider.token_field === "max_completion_tokens" ? " selected" : ""}>max_completion_tokens</option>
        </select></label>
        <label>Zaman aşımı (sn)<input class="field" data-f="timeout" type="number" min="5" max="600" value="${numberOr(provider.timeout, 120)}"></label>
        <label class="check" title="Model, web/GitHub araştırma araçlarını çağırabilsin (sağlayıcı tool calling desteklemiyorsa istek reddedilir)">
          <input type="checkbox" data-f="tools"${provider.tools ? " checked" : ""}>Araştırma araçlarını kullanabilir
        </label>
      </div>
      <div class="p-foot">
        <button class="btn btn-sm" data-act="test">${icon("refresh", 13)}Test et</button>
        <span class="p-result"></span>
      </div>
    </article>`);
    card.dataset.kind = provider.kind || "local";
    card.dataset.extras = JSON.stringify(provider.extras || {});
    this.listEl.append(card);
    return card;
  }

  _readCards() {
    return [...this.listEl.querySelectorAll(".provider")].map((card) => {
      const field = (name) => card.querySelector(`[data-f="${name}"]`).value.trim();
      return {
        id: card.dataset.id,
        label: field("label") || card.dataset.id,
        base_url: field("base_url"),
        model: field("model") || null,
        api_key: field("api_key"),          // KEY_MASK means "keep what is stored"
        kind: card.dataset.kind,
        health: field("health"),
        token_field: field("token_field"),
        timeout: numberOr(field("timeout"), 120),
        tools: card.querySelector('[data-f="tools"]').checked,
        extras: JSON.parse(card.dataset.extras || "{}"),
        enabled: !card.classList.contains("off"),
      };
    });
  }

  _renderRoles() {
    const providers = this._readCards().filter((p) => p.enabled);
    const options = (selected, allowEmpty) =>
      (allowEmpty ? `<option value=""${selected ? "" : " selected"}>— yok —</option>` : "") +
      providers.map((p) => `<option value="${esc(p.id)}"${p.id === selected ? " selected" : ""}>${esc(p.label)}${p.kind === "remote" ? " (bulut)" : ""}</option>`).join("");

    this.rolesEl.innerHTML = ROLE_INFO.map(([role, title, hint]) => {
      const chain = this.roles[role] || [];
      return `<div class="role-row" data-role="${role}">
        <div class="r-info"><b>${title}</b><span>${esc(hint)}</span></div>
        <label class="r-pick">Model<select class="field" data-slot="primary">${options(chain[0], false)}</select></label>
        <label class="r-pick">Yedek<select class="field" data-slot="fallback">${options(chain[1], true)}</select></label>
      </div>`;
    }).join("");
  }

  _renderBudget() {
    const { calls = 0, tokens = 0, limits = {} } = this.usage || {};
    this.el.querySelector(".budget").innerHTML = `
      <div class="budget-now">
        <div><b>${calls}</b><span>bugünkü uzak istek</span></div>
        <div><b>${tokens.toLocaleString("tr-TR")}</b><span>bugünkü token</span></div>
      </div>
      <div class="budget-limits">
        <label>Günlük istek sınırı<input class="field" data-limit="daily_calls" type="number" min="0" value="${numberOr(limits.daily_calls, 300)}"></label>
        <label>Günlük token sınırı<input class="field" data-limit="daily_tokens" type="number" min="0" value="${numberOr(limits.daily_tokens, 400000)}"></label>
      </div>
      <p class="hint">Sınır dolunca uzak model yerine yerel modele düşer. Yerel çağrılar sayılmaz, sınırlanmaz.</p>`;
  }

  // ---------- actions ----------
  _click(e) {
    const act = e.target.closest("[data-act]")?.dataset.act;
    const card = e.target.closest(".provider");
    if (act === "close") return this.close();
    if (act === "save") return this._save();
    if (act === "add") return this._addMenu(e.target.closest("[data-act]"));
    if (!card) return;
    if (act === "remove") {
      card.remove();
      this._renderRoles();
    } else if (act === "toggle") {
      card.classList.toggle("off");
      card.querySelector('[data-act="toggle"]').innerHTML = icon(card.classList.contains("off") ? "eyeOff" : "eye", 15);
      this._renderRoles();
    } else if (act === "test") {
      this._test(card);
    }
  }

  _addMenu(button) {
    const r = button.getBoundingClientRect();
    openMenu(r.left - 60, r.bottom + 6, PRESETS.map((preset) => ({
      label: preset.label,
      icon: preset.kind === "remote" ? "zap" : "cpu",
      action: () => {
        const taken = new Set([...this.listEl.querySelectorAll(".provider")].map((c) => c.dataset.id));
        let id = preset.key;
        for (let n = 2; taken.has(id); n++) id = `${preset.key}-${n}`;
        const card = this._addCard({ ...preset, id, enabled: true, has_key: false, extras: preset.extras || {} });
        card.scrollIntoView({ block: "nearest" });
        card.querySelector('[data-f="api_key"]').focus();
        this._renderRoles();
      },
    })));
  }

  async _test(card) {
    const result = card.querySelector(".p-result");
    result.className = "p-result";
    result.textContent = "Deneniyor…";
    const saved = await this._save({ silent: true });
    if (!saved) {
      result.className = "p-result bad";
      result.textContent = "Önce ayarları düzelt";
      return;
    }
    try {
      const r = await api.post("/api/providers/test", { id: card.dataset.id });
      result.className = `p-result ${r.ok ? "good" : "bad"}`;
      result.textContent = r.ok ? `Çalışıyor · ${r.latency_ms} ms` : r.error;
      card.querySelector(".p-dot").classList.toggle("up", Boolean(r.ok));
    } catch (err) {
      result.className = "p-result bad";
      result.textContent = err.message;
    }
  }

  async _save({ silent = false } = {}) {
    const providers = this._readCards();
    const roles = {};
    for (const row of this.rolesEl.querySelectorAll(".role-row")) {
      const primary = row.querySelector('[data-slot="primary"]').value;
      const fallback = row.querySelector('[data-slot="fallback"]').value;
      roles[row.dataset.role] = [primary, fallback].filter((v, i, all) => v && all.indexOf(v) === i);
    }
    this.errorEl.textContent = "";
    try {
      const result = await api.put("/api/providers", { providers, roles });
      this.roles = result.roles;
      const limits = {};
      for (const input of this.el.querySelectorAll("[data-limit]")) limits[input.dataset.limit] = Number(input.value);
      this.usage = await api.put("/api/usage/limits", limits);
      if (!silent) {
        toast("Model ayarları kaydedildi.", "success");
        this.close();
      }
      return true;
    } catch (err) {
      this.errorEl.textContent = err.message;
      if (!silent) toast(err.message, "error", 5000);
      return false;
    }
  }
}
