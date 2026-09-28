// "Modeller ve anahtarlar": add providers (local servers or API keys), bind
// each job to one, set the remote budget. This is the UI over /api/providers.
import { api } from "./api.js";
import { openMenu } from "./dialogs.js";
import { icon } from "./icons.js";
import { debounce, esc, html, toast } from "./util.js";

const KEY_MASK = "••••";

const ROLE_INFO = [
  ["analysis", "Not izleme ve araştırma", "15 saniye durduğunda ya da bir şey yapıştırdığında notu sessizce inceler; araştırmayı da yürütür."],
  ["chat", "Sohbet", "Cevabını değerlendirir, anlamadıysa tekrar sorar."],
  ["summary", "Nota yazma", "Sonucu notuna eklenecek cümleye dönüştürür."],
  ["compare", "Araştırma yargıları", "Fikre özel arama kurallarını çıkarır, rakipleri ayıklar ve karşılaştırır; araştırma başına üç çağrı. Daha güçlü bir model burada fark eder (boş bırakılırsa not izleme modeli)."],
  ["master", "Master prompt", "Notu, kararları ve araştırmayı bir kodlama yapay zekâsı için eksiksiz yapım talimatına çevirir; tuşa her basışta bir uzun yazı. Boş bırakılırsa araştırma yargılarının modeli."],
];

const PRESETS = [
  { key: "openai", label: "OpenAI", base_url: "https://api.openai.com", model: "gpt-4o-mini",
    kind: "remote", health: "models", token_field: "max_completion_tokens" },
  { key: "openrouter", label: "OpenRouter", base_url: "https://openrouter.ai/api", model: "openai/gpt-4o-mini",
    kind: "remote", health: "models", token_field: "max_tokens" },
  // for the competitor analysis: its answer comes back empty unless its
  // thinking is switched off (it spends the whole token budget thinking)
  { key: "openrouter-deepseek", label: "OpenRouter · DeepSeek V4 Flash", base_url: "https://openrouter.ai/api",
    model: "deepseek/deepseek-v4-flash", kind: "remote", health: "models", token_field: "max_tokens",
    extras: { reasoning: { enabled: false } } },
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
    // Never awaited: this reply waits on model-endpoint probes and took seconds,
    // so awaiting it here meant the whole dialog opened seconds after the click.
    // It fills its own section in when it lands.
    this.tools = null;
    this._toolsLoading = true;

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
        <section>
          <div class="set-section-head">
            <h3>${icon("search", 15)}Araştırma araçları</h3>
            <button class="btn btn-sm" data-act="restart-tools">${icon("refresh", 14)}Yeniden başlat</button>
          </div>
          <div class="tools-box"></div>
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
    this._renderTools();
    api.get("/api/tools")
      .then((tools) => { this.tools = tools; })
      .catch(() => { this.tools = null; })
      .finally(() => { this._toolsLoading = false; this._renderTools(); });

    this.el.addEventListener("click", (e) => this._click(e));
    // typing a provider name changes what the role dropdowns say, but redrawing
    // them on every keystroke flickers — settle first
    this._renderRolesSoon = debounce(() => { if (this.el) this._renderRoles(); }, 250);
    this.el.addEventListener("input", (e) => {
      // only a provider card's fields change the role pickers; the token does not
      if (e.target.matches("[data-f]") && e.target.closest(".provider")) this._renderRolesSoon();
    });
    this.el.addEventListener("change", (e) => {
      if (e.target.matches("[data-slot]")) this.roles = this._readRoles();
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

  /** What the pickers currently say, so redrawing them never undoes a choice. */
  _readRoles() {
    const roles = { ...this.roles };
    for (const row of this.rolesEl.querySelectorAll(".role-row")) {
      const primary = row.querySelector('[data-slot="primary"]').value;
      const fallback = row.querySelector('[data-slot="fallback"]').value;
      roles[row.dataset.role] = [primary, fallback].filter((v, i, all) => v && all.indexOf(v) === i);
    }
    return roles;
  }

  _renderRoles() {
    const providers = this._readCards().filter((p) => p.enabled);
    // a keystroke in a provider field used to rebuild these selects from
    // this.roles, which silently threw away a pick the user had just made
    this.roles = this._readRoles();
    // and rebuilding when nothing about the choices changed only makes the
    // dropdowns flicker, so skip that too
    const signature = JSON.stringify([providers.map((p) => [p.id, p.label, p.kind]), this.roles]);
    if (signature === this._rolesSignature) return;
    this._rolesSignature = signature;

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
    const { calls = 0, tokens = 0, usd = 0, limits = {} } = this.usage || {};
    this.el.querySelector(".budget").innerHTML = `
      <div class="budget-now">
        <div><b>$${Number(usd).toFixed(4)}</b><span>bugünkü harcama</span></div>
        <div><b>${calls}</b><span>bugünkü uzak istek</span></div>
        <div><b>${tokens.toLocaleString("tr-TR")}</b><span>bugünkü token</span></div>
      </div>
      <div class="budget-limits">
        <label>Günlük harcama sınırı ($)<input class="field" data-limit="daily_usd" type="number" min="0" step="0.05" value="${numberOr(limits.daily_usd, 0.5)}"></label>
        <label>Günlük istek sınırı<input class="field" data-limit="daily_calls" type="number" min="0" value="${numberOr(limits.daily_calls, 2000)}"></label>
        <label>Günlük token sınırı<input class="field" data-limit="daily_tokens" type="number" min="0" value="${numberOr(limits.daily_tokens, 3000000)}"></label>
      </div>
      <p class="hint">Harcama, OpenRouter'ın her istek için bildirdiği gerçek maliyettir. Sınır dolunca uzak model yerine (varsa) yerel modele düşer; yerel çağrılar sayılmaz, sınırlanmaz.</p>`;
  }

  _renderTools() {
    const box = this.el?.querySelector(".tools-box");
    if (!box) return;                       // dialog closed while a save was in flight
    // The status arrives after the dialog is already open, so this redraws
    // under the user's hands: anything they have typed (and their place in the
    // field) has to survive it.
    const before = box.querySelector('[data-f="github_token"]');
    const typed = before && before.value !== this._tokenWas ? before.value : null;
    const hadFocus = before && document.activeElement === before;

    // The token lives in this app's own settings, not on the tool servers, so
    // the field has to be here even when they are down — otherwise a bad token
    // becomes unfixable exactly when you most need to fix it.
    const { servers = {}, errors = {}, count = 0, settings = {} } = this.tools || {};
    const token = settings.github_token || {};
    const known = Boolean(this.tools);
    const rows = Object.entries(servers)
      .map(([name, list]) => `<div class="tool-row good">${icon("check", 12)}<b>${esc(name)}</b><span>${list.length} araç</span></div>`)
      .concat(Object.entries(errors).map(([name, why]) =>
        `<div class="tool-row bad">${icon("alert", 12)}<b>${esc(name)}</b><span>${esc(why)}</span></div>`))
      .join("");
    const status = this._toolsLoading
      ? `<div class="tool-row">${icon("refresh", 12)}<b>Araç durumu okunuyor…</b><span></span></div>`
      : known
        ? (rows || '<p class="hint">Tanımlı araç sunucusu yok.</p>')
        : `<div class="tool-row bad">${icon("alert", 12)}<b>Araç durumu okunamadı</b><span>Token yine de kaydedilebilir.</span></div>`;

    box.innerHTML = `
      <div class="tool-status">${status}</div>
      <label class="tool-key">GitHub token
        <input class="field" data-f="github_token" type="password" autocomplete="off"
               placeholder="${token.has_token ? KEY_MASK : "ghp_… (isteğe bağlı)"}"
               value="${token.has_token && !token.from_env ? KEY_MASK : ""}">
      </label>
      <p class="hint">${token.from_env
        ? "Şu an ortam değişkeninden (GITHUB_RESEARCH_TOKEN) geliyor. Buraya yazarsan o geçerli olur."
        : "Tokensız GitHub'ın kendi sınırı saatte 60 istektir; token bunu 5000'e çıkarır. Token bilgisayarında saklanır, nota ve depoya yazılmaz."}
        Kaydedince araç sunucuları yeniden başlar — token'ı sadece açılışta okuyorlar.</p>
      ${known ? `<p class="hint">Toplam ${count} araç. Araç takımı başka bir klasördeyse <code>FIKIR_TOOLS_ROOT</code>
        ortam değişkenini ayarla.</p>` : ""}`;

    const input = box.querySelector('[data-f="github_token"]');
    // what the field started as, so an untouched token is never re-sent
    this._tokenWas = input?.value ?? "";
    if (input && typed !== null) {
      input.value = typed;                  // give them back what they were typing
      if (hadFocus) {
        input.focus();
        input.setSelectionRange(typed.length, typed.length);
      }
    }
  }

  async _restartTools(button) {
    const original = button.innerHTML;
    button.disabled = true;
    button.innerHTML = `${icon("refresh", 14)}Başlatılıyor…`;
    try {
      this.tools = await api.post("/api/tools/restart");
      this._renderTools();
      const failed = Object.keys(this.tools.errors || {}).length;
      toast(failed ? `${failed} araç sunucusu başlamadı.` : "Araç sunucuları yeniden başladı.",
            failed ? "error" : "success");
    } catch (err) {
      toast(err.message, "error");
    } finally {
      button.disabled = false;
      button.innerHTML = original;
    }
  }

  /** Returns false only if the token was rejected; tools are never fatal to a save. */
  async _saveToken() {
    const input = this.el?.querySelector('[data-f="github_token"]');
    if (!input || input.value === this._tokenWas) return true;
    try {
      this.tools = await api.put("/api/tools/settings", { github_token: input.value.trim() });
    } catch (err) {
      this.errorEl.textContent = err.message;
      return false;
    }
    // rendering the result must never fail the save that already succeeded
    try {
      this._renderTools();
    } catch (err) {
      console.error("araç durumu çizilemedi", err);
    }
    return true;
  }

  // ---------- actions ----------
  _click(e) {
    const act = e.target.closest("[data-act]")?.dataset.act;
    const card = e.target.closest(".provider");
    if (act === "close") return this.close();
    if (act === "save") return this._save();
    if (act === "add") return this._addMenu(e.target.closest("[data-act]"));
    if (act === "restart-tools") return this._restartTools(e.target.closest("[data-act]"));
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
    const roles = this._readRoles();
    this.errorEl.textContent = "";
    // saving a changed token restarts the tool servers, which takes a couple of
    // seconds — without this the dialog just sits there looking broken
    const button = silent ? null : this.el.querySelector('footer [data-act="save"]');
    const label = button?.innerHTML;
    if (button) {
      button.disabled = true;
      button.innerHTML = `${icon("refresh", 14)}Kaydediliyor…`;
    }
    try {
      const result = await api.put("/api/providers", { providers, roles });
      this.roles = result.roles;
      const limits = {};
      for (const input of this.el.querySelectorAll("[data-limit]")) limits[input.dataset.limit] = Number(input.value);
      this.usage = await api.put("/api/usage/limits", limits);
      if (!await this._saveToken()) return false;
      if (!silent) {
        toast("Model ayarları kaydedildi.", "success");
        this.close();
      }
      return true;
    } catch (err) {
      this.errorEl.textContent = err.message;
      if (!silent) toast(err.message, "error", 5000);
      return false;
    } finally {
      // the dialog may already be gone (a successful save closes it)
      if (button?.isConnected) {
        button.disabled = false;
        button.innerHTML = label;
      }
    }
  }
}
