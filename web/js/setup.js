// First start: "Asistanı bir modele bağla".
//
// A fresh install points at a local model server that is not there, and the
// assistant silently did nothing until the writer found Settings → Models.
// This sheet opens by itself on first start while no model answers, and
// offers the three ways in: OpenRouter with a key (recommended), a model
// already running on this computer (Ollama, LM Studio, llama.cpp — found by
// the server on their usual ports), or any other OpenAI-compatible service.
// "Bağlan ve dene" makes one real call before anything is saved, so a wrong
// key is said here, in words, not later as a silent failure.
import { api } from "./api.js";
import { openExternal } from "./desktop.js";
import { icon, logo } from "./icons.js";
import { locale } from "./i18n.js";
import { esc, html, toast } from "./util.js";

const LOCAL_KINDS = [
  { id: "ollama", label: "Ollama", base_url: "http://127.0.0.1:11434", health: "models" },
  { id: "lmstudio", label: "LM Studio", base_url: "http://127.0.0.1:1234", health: "models" },
  { id: "llamacpp", label: "llama.cpp", base_url: "http://127.0.0.1:8080", health: "llama" },
];

export class SetupWizard {
  /** handlers: onConnected(result) */
  constructor(handlers = {}) {
    this.h = handlers;
    this.el = null;
    this.step = "choose";
    this.info = null;
    this.found = null;           // local servers answering, or null while looking
    this.busy = false;
    this.error = "";
    this.result = null;
    this.form = {};
  }

  get isOpen() { return Boolean(this.el); }

  async open(info = null) {
    if (this.el) return;
    this.step = "choose";
    this.error = "";
    this.result = null;
    this.form = { orKey: "", orModel: "", localKind: "ollama", localUrl: LOCAL_KINDS[0].base_url, localModel: "",
                  pick: null, customUrl: "", customKey: "", customModel: "" };
    this.info = info;
    this.overlay = html('<div class="su-overlay"></div>');
    this.el = html(`<section class="su-sheet" role="dialog" aria-modal="true" aria-labelledby="suTitle">
      <div class="su-glow" aria-hidden="true"></div>
      <header class="su-head">
        <span class="su-logo">${logo(40)}</span>
        <div class="su-titles">
          <h2 id="suTitle">Asistanı bir modele bağla</h2>
          <p>Asistanın düşünebilmesi için bir yapay zekâ modeline bağlanması gerekiyor. Bir kez yapılır, birkaç dakika sürer.</p>
        </div>
        <button class="icon-btn" data-act="close" title="Kapat (Esc)">${icon("x", 17)}</button>
      </header>
      <div class="su-body"></div>
      <footer class="su-foot"></footer>
    </section>`);
    document.body.append(this.overlay, this.el);
    requestAnimationFrame(() => { this.overlay.classList.add("in"); this.el.classList.add("in"); });
    this.el.addEventListener("click", (e) => this._click(e));
    this.el.addEventListener("input", (e) => this._input(e));
    this.el.addEventListener("change", (e) => this._input(e));
    this._key = (e) => {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); this.close(); }
      else if (e.key === "Enter" && !e.shiftKey && e.target.closest?.(".su-sheet input")) { e.preventDefault(); this.connect(); }
    };
    document.addEventListener("keydown", this._key, true);
    this._paint();
    try { this.info ??= await api.get("/api/setup"); } catch { /* the defaults below will do */ }
    this._detect();
  }

  close() {
    if (!this.el) return;
    document.removeEventListener("keydown", this._key, true);
    const el = this.el, overlay = this.overlay;
    this.el = null;
    el.classList.remove("in");
    overlay.classList.remove("in");
    setTimeout(() => { el.remove(); overlay.remove(); }, 260);
  }

  async _detect() {
    this.found = null;
    this._paint();
    try { this.found = (await api.get("/api/setup/detect")).found || []; } catch { this.found = []; }
    if (this.found.length && !this.form.pick) {
      const first = this.found[0];
      this.form.pick = first.base_url;
      this.form.localModel = first.models[0] || "";
    }
    if (this.el) this._paint();
  }

  // ---------- drawing ----------
  _paint() {
    if (!this.el) return;
    const body = this.el.querySelector(".su-body");
    const foot = this.el.querySelector(".su-foot");
    const view = { choose: () => this._choose(), openrouter: () => this._openrouter(), local: () => this._local(),
                   custom: () => this._custom(), done: () => this._done() }[this.step];
    const [inner, footer] = view();
    body.innerHTML = inner;
    foot.innerHTML = footer;
    const focus = body.querySelector("[data-autofocus]");
    if (focus && document.activeElement?.closest?.(".su-sheet") == null) focus.focus();
  }

  _choose() {
    const found = this.found;
    const localLine = found === null ? `<span class="su-probe">${icon("refresh", 12)}Bu bilgisayarda çalışan bir model aranıyor…</span>`
      : found.length ? `<span class="su-probe ok">${icon("checkCircle", 12)}Bulundu: ${found.map((f) => `${esc(f.label)}${f.models.length ? ` (${f.models.length} model)` : ""}`).join(", ")}</span>`
      : `<span class="su-probe">Bu bilgisayarda çalışan bir model bulunamadı.</span>`;
    const cards = `
      <button class="su-card rec" data-go="openrouter">
        <span class="su-card-icon">${icon("cloud", 20)}</span>
        <span class="su-card-text"><b>OpenRouter <em>Önerilen</em></b>
          <span>En kolay yol: tek bir anahtarla birçok model. Önerilen modelle bir tur yaklaşık $0,0002. Notun, asistanın düşünmesi için OpenRouter'a gönderilir.</span></span>
        ${icon("arrowRight", 16)}
      </button>
      <button class="su-card" data-go="local">
        <span class="su-card-icon">${icon("cpu", 20)}</span>
        <span class="su-card-text"><b>Bu bilgisayarda çalışan bir model</b>
          <span>Ollama, LM Studio ya da llama.cpp. Notun bilgisayarından hiç çıkmaz ve ücretsizdir, ama güçlü bir bilgisayar ister.</span>
          ${localLine}</span>
        ${icon("arrowRight", 16)}
      </button>
      <button class="su-card" data-go="custom">
        <span class="su-card-icon">${icon("globe", 20)}</span>
        <span class="su-card-text"><b>Başka bir servis</b>
          <span>OpenAI, DeepSeek, Groq ya da OpenAI uyumlu başka bir adres, kendi anahtarınla.</span></span>
        ${icon("arrowRight", 16)}
      </button>`;
    return [`<div class="su-cards">${cards}</div>`,
      `<span class="su-hint">İstediğin zaman değiştirebilirsin: Ayarlar → Modeller ve anahtarlar.</span>
       <span class="su-grow"></span>
       <button class="btn btn-sm" data-act="later">Şimdilik geç</button>`];
  }

  _error() {
    return this.error ? `<div class="su-error" role="alert">${icon("alert", 15)}<span>${esc(this.error)}</span></div>` : "";
  }

  _actions() {
    return `<button class="btn btn-sm" data-go="choose">Geri</button><span class="su-grow"></span>
      <button class="btn btn-accent su-connect" data-act="connect" ${this.busy ? "disabled" : ""}>${this.busy
        ? `<span class="su-spin"></span>Deneniyor…` : `${icon("zap", 14)}Bağlan ve dene`}</button>`;
  }

  _openrouter() {
    const models = this.info?.openrouter?.models || ["openai/gpt-4o-mini"];
    return [`
      <ol class="su-steps">
        <li>openrouter.ai'de ücretsiz bir hesap aç ve hesabına biraz kredi ekle.</li>
        <li>Anahtar sayfasında "Create Key" ile yeni bir anahtar oluştur.
          <button class="btn btn-sm su-link" data-act="keys">${icon("key", 13)}Anahtar sayfasını aç ↗</button></li>
        <li>Anahtarı buraya yapıştır:</li>
      </ol>
      <label class="su-field"><span>OpenRouter anahtarı</span>
        <input class="field" type="password" data-f="orKey" value="${esc(this.form.orKey)}" placeholder="sk-or-v1-…" autocomplete="off" spellcheck="false" data-autofocus></label>
      <label class="su-field"><span>Model</span>
        <input class="field" data-f="orModel" list="suOrModels" value="${esc(this.form.orModel)}" placeholder="${esc(models[0])}" spellcheck="false">
        <datalist id="suOrModels">${models.map((m) => `<option value="${esc(m)}">`).join("")}</datalist>
        <small>Boş bırakırsan ${esc(models[0])} kullanılır: ölçümlerde notlardaki kararların hepsini buldu, hiçbirini uydurmadı.</small></label>
      <p class="su-note">${icon("key", 13)}<span>Anahtar yalnızca bu bilgisayarda, notlarından ayrı bir yerde saklanır. Günlük harcama sınırı $0,50; ayarlardan değiştirebilirsin.</span></p>
      ${this._error()}`, this._actions()];
  }

  _local() {
    const found = this.found;
    let detected = "";
    if (found === null) detected = `<p class="su-probe">${icon("refresh", 12)}Aranıyor…</p>`;
    else if (found.length) {
      detected = `<div class="su-found">${found.map((f) => `
        <label class="su-server${this.form.pick === f.base_url ? " on" : ""}">
          <input type="radio" name="suPick" data-pick="${esc(f.base_url)}" ${this.form.pick === f.base_url ? "checked" : ""}>
          <span class="su-server-name"><b>${esc(f.label)}</b><small>${esc(f.base_url.replace("http://", ""))}</small></span>
          ${f.models.length ? `<select class="field" data-server-model="${esc(f.base_url)}">${f.models.map((m) =>
            `<option${this.form.pick === f.base_url && this.form.localModel === m ? " selected" : ""}>${esc(m)}</option>`).join("")}</select>` : ""}
        </label>`).join("")}</div>`;
    } else {
      detected = `<div class="su-empty">
        <p>Bu bilgisayarda çalışan bir model bulunamadı. En kolayı Ollama:</p>
        <ol class="su-steps">
          <li>Ollama'yı indir ve kur. <button class="btn btn-sm su-link" data-act="ollama" translate="no">ollama.com ↗</button></li>
          <li>Bir komut satırında bir model indir: <code>ollama pull qwen2.5:7b</code></li>
          <li>Buraya dönüp "Yeniden ara" düğmesine bas.</li>
        </ol></div>`;
    }
    const manual = this.form.pick === "manual";
    return [`
      <div class="su-local-head"><b>Bulunan modeller</b><button class="btn btn-sm" data-act="rescan">${icon("refresh", 13)}Yeniden ara</button></div>
      ${detected}
      <label class="su-server manual${manual ? " on" : ""}"><input type="radio" name="suPick" data-pick="manual" ${manual ? "checked" : ""}>
        <span class="su-server-name"><b>Adresi kendim yazacağım</b><small>başka bir port ya da sunucu</small></span></label>
      ${manual ? `<div class="su-manual">
        <div class="seg" role="radiogroup" aria-label="Sunucu">${LOCAL_KINDS.map((k) =>
          `<button data-kind="${k.id}" class="${this.form.localKind === k.id ? "on" : ""}">${esc(k.label)}</button>`).join("")}</div>
        <label class="su-field"><span>Adres</span><input class="field" data-f="localUrl" value="${esc(this.form.localUrl)}" spellcheck="false"></label>
        <label class="su-field"><span>Model adı</span><input class="field" data-f="localModel" value="${esc(this.form.localModel)}" placeholder="ör. qwen2.5:7b" spellcheck="false">
          <small>llama.cpp tek model yüklediği için boş bırakılabilir.</small></label></div>` : ""}
      ${this._error()}`, this._actions()];
  }

  _custom() {
    return [`
      <label class="su-field"><span>Adres</span>
        <input class="field" data-f="customUrl" value="${esc(this.form.customUrl)}" placeholder="https://api.openai.com" spellcheck="false" data-autofocus>
        <small>OpenAI uyumlu servisin kök adresi; /v1/chat/completions kısmını uygulama ekler.</small></label>
      <label class="su-field"><span>API anahtarı</span>
        <input class="field" type="password" data-f="customKey" value="${esc(this.form.customKey)}" autocomplete="off" spellcheck="false"></label>
      <label class="su-field"><span>Model adı</span>
        <input class="field" data-f="customModel" value="${esc(this.form.customModel)}" placeholder="ör. gpt-4o-mini" spellcheck="false"></label>
      <p class="su-note">${icon("cloud", 13)}<span>Notun, asistanın düşünmesi için bu servise gönderilir. Başına "private: true" yazdığın notlar hiç gönderilmez.</span></p>
      ${this._error()}`, this._actions()];
  }

  _done() {
    const r = this.result || {};
    return [`
      <div class="su-done">
        <span class="su-done-mark">${icon("check", 30)}</span>
        <h3>Hazır!</h3>
        <span class="su-model" translate="no">${esc(r.label || "")}${r.model ? ` · ${esc(r.model)}` : ""}</span>
        <p>Asistan artık bu modelle çalışıyor; ilk cevap ${Math.max(0.1, Math.round((r.latency_ms || 0) / 100) / 10).toLocaleString(locale())} sn'de geldi.</p>
        <ul class="su-next">
          <li>${icon("filePlus", 14)}<span>Bir not aç ve fikrini yaz. 15 saniye durduğunda asistan notuna bakar, sorularını sağdaki panele bırakır.</span></li>
          <li>${icon("sparkles", 14)}<span>Beklemek istemezsen Ctrl+Enter ile hemen sor.</span></li>
          <li>${icon("settings", 14)}<span>Model, anahtar ve harcama sınırı: Ayarlar → Modeller ve anahtarlar.</span></li>
        </ul>
      </div>`,
      `<span class="su-grow"></span><button class="btn btn-accent" data-act="close">${icon("arrowRight", 14)}Başla</button>`];
  }

  // ---------- acting ----------
  _input(e) {
    const f = e.target.dataset.f;
    if (f) { this.form[f] = e.target.value; return; }
    if (e.target.dataset.pick) {
      this.form.pick = e.target.dataset.pick;
      const server = this.found?.find((s) => s.base_url === this.form.pick);
      if (server) this.form.localModel = server.models[0] || "";
      this.error = "";
      this._paint();
      return;
    }
    const serverModel = e.target.dataset.serverModel;
    if (serverModel) {
      this.form.pick = serverModel;
      this.form.localModel = e.target.value;
    }
  }

  _click(e) {
    const go = e.target.closest("[data-go]")?.dataset.go;
    if (go) {
      this.step = go;
      this.error = "";
      this._paint();
      return;
    }
    const kind = e.target.closest("[data-kind]")?.dataset.kind;
    if (kind) {
      const k = LOCAL_KINDS.find((x) => x.id === kind);
      this.form.localKind = k.id;
      this.form.localUrl = k.base_url;
      this._paint();
      return;
    }
    const act = e.target.closest("[data-act]")?.dataset.act;
    if (act === "close") return this.close();
    if (act === "later") return this.later();
    if (act === "keys") return openExternal(this.info?.openrouter?.keys_url || "https://openrouter.ai/keys");
    if (act === "ollama") return openExternal("https://ollama.com/download");
    if (act === "rescan") return this._detect();
    if (act === "connect") return this.connect();
  }

  async later() {
    try { await api.post("/api/setup/dismiss"); } catch { /* it will just ask again next time */ }
    this.close();
    toast("Modeli istediğin zaman üstteki model düğmesinden ya da ayarlardan bağlayabilirsin.");
  }

  _choice() {
    const f = this.form;
    if (this.step === "openrouter") return { preset: "openrouter", api_key: f.orKey.trim(), model: f.orModel.trim() || null };
    if (this.step === "custom") {
      return { preset: "custom", base_url: f.customUrl.trim(), api_key: f.customKey.trim() || null, model: f.customModel.trim() };
    }
    if (f.pick === "manual" || !f.pick) {
      const k = LOCAL_KINDS.find((x) => x.id === f.localKind) || LOCAL_KINDS[0];
      return { preset: "local", id: k.id, label: k.label, health: k.health, base_url: f.localUrl.trim(),
               model: f.localModel.trim() || null };
    }
    const server = this.found?.find((s) => s.base_url === f.pick);
    return { preset: "local", id: server.id, label: server.label, health: server.health, base_url: server.base_url,
             model: f.localModel || null };
  }

  async connect() {
    if (this.busy || !["openrouter", "local", "custom"].includes(this.step)) return;
    this.busy = true;
    this.error = "";
    this._paint();
    try {
      const result = await api.post("/api/setup/connect", this._choice());
      if (!this.el) return;
      if (result.ok) {
        this.result = result;
        this.step = "done";
        this.h.onConnected?.(result);
      } else {
        this.error = result.error || "Bağlanılamadı.";
      }
    } catch (err) {
      this.error = err.message;
    } finally {
      this.busy = false;
      this._paint();
    }
  }
}
