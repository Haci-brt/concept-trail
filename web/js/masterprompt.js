// The master prompt: one button that turns the open note — its decisions,
// answered questions, approved and rejected suggestions and research — into
// the complete instructions a coding AI needs to build the thing without a
// single question back. Anything the note leaves open the model decides
// itself and lists under "Varsayımlar"; the dialog shows those first, so the
// writer sees exactly what was decided for them before handing it over.
import { api, streamPost } from "./api.js";
import { icon } from "./icons.js";
import { LANGUAGES, lang as uiLang, locale } from "./i18n.js";
import { esc, html, toast, trapFocus } from "./util.js";

const LANG_KEY = "fikir.master.lang.v1";
const SECTIONS = ["Ajan kuralları", "Ürün özeti", "Kullanıcılar", "Kapsam", "Platform", "Teknoloji yığını",
  "Mimari", "Veri modeli", "API sözleşmeleri", "Ekranlar ve akışlar", "Hata ve uç durumlar", "Güvenlik",
  "Klasör yapısı", "Kilometre taşları", "Test ve kabul", "Kurulum ve dağıtım", "Kodlama kuralları",
  "Bitti ölçütü", "Varsayımlar"];

const words = (text) => (String(text || "").match(/\S+/g) || []).length;
const fmt = (n) => n.toLocaleString(locale());

export class MasterPromptDialog {
  /** handlers: getContent(path) -> unsaved text or null; openNote(path) */
  constructor(handlers = {}) {
    this.h = handlers;
    this.el = null;
    this.path = null;
    this.result = null;
    this.stats = null;
    this.running = false;
    this.view = "preview";
    // the dialog's own choice if the writer made one, else the assistant's language
    try { this.chosen = localStorage.getItem(LANG_KEY) || ""; } catch { this.chosen = ""; }
    this.lang = LANGUAGES.some((l) => l.id === this.chosen) ? this.chosen : uiLang;
  }

  get isOpen() { return Boolean(this.el); }

  async open(path, name) {
    if (!path) { toast("Master prompt için önce bir not aç."); return; }
    if (this.el) this.close();
    this.path = path;
    this.name = name;
    this.result = null;
    this.stats = null;
    this.overlay = html('<div class="mp-overlay"></div>');
    this.el = html(`<section class="mp-sheet" role="dialog" aria-modal="true" aria-labelledby="mpTitle">
      <div class="mp-aurora" aria-hidden="true"></div>
      <header class="mp-head">
        <div class="mp-mark">${icon("wand", 20)}</div>
        <div class="mp-titles">
          <h2 id="mpTitle">Master prompt</h2>
          <p>${esc(name)} · bir yapay zekâya bu uygulamayı baştan sona yaptıracak, soru bırakmayan talimat</p>
        </div>
        <button class="icon-btn" data-act="close" title="Kapat (Esc)">${icon("x", 17)}</button>
      </header>
      <div class="mp-ready"></div>
      <div class="mp-controls">
        <div class="seg mp-lang" role="radiogroup" aria-label="Dil" translate="no">
          ${LANGUAGES.map((l) => `<button data-lang="${l.id}" title="${esc(l.label)}">${l.id.toUpperCase()}</button>`).join("")}
        </div>
        <button class="btn btn-accent mp-go" data-act="generate"></button>
        <span class="mp-grow"></span>
        <div class="seg mp-view" role="radiogroup" aria-label="Görünüm">
          <button data-view="preview">Önizleme</button><button data-view="raw">Ham metin</button>
        </div>
        <button class="btn btn-sm" data-act="copy" title="Panoya kopyala">${icon("copy", 13)}Kopyala</button>
        <button class="btn btn-sm" data-act="save" title="Bu klasörde yeni bir not olarak kaydet">${icon("filePlus", 13)}Not olarak kaydet</button>
        <button class="btn btn-sm" data-act="download" title=".md dosyası olarak indir">${icon("download", 13)}İndir</button>
      </div>
      <div class="mp-body" tabindex="0"></div>
      <footer class="mp-foot"></footer>
    </section>`);
    document.body.append(this.overlay, this.el);
    document.body.classList.add("mp-open");        // toasts then sit below the sheet, not over its footer
    this._releaseFocus = trapFocus(this.el);
    requestAnimationFrame(() => { this.overlay.classList.add("in"); this.el.classList.add("in"); });
    this.el.addEventListener("click", (e) => this._click(e));
    this.overlay.addEventListener("mousedown", () => this.close());
    this._key = (e) => {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); this.close(); }
      else if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); this.generate(); }
    };
    document.addEventListener("keydown", this._key, true);
    this._paint();
    try {
      const state = await api.get("/api/master-prompt", { path });
      if (path !== this.path || !this.el) return;
      this.stats = state.stats;
      this.result = state.last;
      if (!this.chosen) {
        try { this.lang = (await api.get("/api/preferences")).assistant_language || this.lang; } catch { /* keep */ }
      }
      if (state.last?.language && !this.chosen) this.lang = state.last.language;
      if (state.busy && !this.running) this._waitForOther();
    } catch (err) {
      toast(err.message, "error");
    }
    this._paint();
  }

  close() {
    if (!this.el) return;
    document.removeEventListener("keydown", this._key, true);
    clearInterval(this._poll);
    clearInterval(this._clock);
    const el = this.el, overlay = this.overlay;
    this.el = null;
    document.body.classList.remove("mp-open");
    this._releaseFocus?.();
    el.classList.remove("in");
    overlay.classList.remove("in");
    setTimeout(() => { el.remove(); overlay.remove(); }, 260);
  }

  /** Someone (another window, an earlier open) is already writing it: wait. */
  _waitForOther() {
    this.running = true;
    this.live = "";
    clearInterval(this._poll);
    const before = this.result?.created;
    this._poll = setInterval(async () => {
      try {
        const state = await api.get("/api/master-prompt", { path: this.path });
        if (!state.busy) {
          clearInterval(this._poll);
          this.running = false;
          if (state.last?.created !== before) this.result = state.last;
          this._paint();
        }
      } catch { /* try again */ }
    }, 3000);
  }

  async generate() {
    if (this.running || !this.path) return;
    this.running = true;
    this.phase = "writing";
    this.live = "";
    this.started = performance.now();
    this._paint();
    clearInterval(this._clock);
    this._clock = setInterval(() => this._paintFoot(), 1000);
    const path = this.path;
    try {
      await streamPost("/api/master-prompt", { path, language: this.lang, content: this.h.getContent?.(path) ?? null }, (u) => {
        if (path !== this.path || !this.el) return;
        if (u.type === "start") { this.stats = u.stats; this.provider = u.provider; this._paintReady(); }
        else if (u.type === "progress") { this.live = u.text; this._paintLive(); }
        else if (u.type === "checking") { this.phase = "checking"; this.live = u.text; this._paintLive(); this._paintFoot(); }
        else if (u.type === "done") { this.result = u; }
        else if (u.type === "error") { throw new Error(u.message); }
      });
      if (this.el && this.result) toast(this.result.open ? "Master prompt hazır; birkaç satır hâlâ açık uçlu, kontrol et." : "Master prompt hazır — açık soru kalmadı.", "success");
    } catch (err) {
      toast(err.message, "error", 6000);
    } finally {
      clearInterval(this._clock);
      this.running = false;
      if (this.el) this._paint();
    }
  }

  // ---------- painting ----------
  _paint() {
    if (!this.el) return;
    this.el.querySelectorAll("[data-lang]").forEach((b) => b.classList.toggle("on", b.dataset.lang === this.lang));
    this.el.querySelectorAll("[data-view]").forEach((b) => b.classList.toggle("on", b.dataset.view === this.view));
    const go = this.el.querySelector(".mp-go");
    go.disabled = this.running;
    go.innerHTML = this.running ? `${icon("sparkle", 14, "spin")}Hazırlanıyor…`
      : `${icon("sparkles", 14)}${this.result ? "Yeniden oluştur" : "Master prompt oluştur"}`;
    for (const act of ["copy", "save", "download"]) this.el.querySelector(`[data-act="${act}"]`).disabled = !this.result || this.running;
    this.el.querySelector(".mp-view").hidden = !this.result || this.running;
    this._paintReady();
    this._paintBody();
    this._paintFoot();
  }

  _paintReady() {
    const box = this.el?.querySelector(".mp-ready");
    const s = this.stats;
    if (!box || !s) { if (box) box.innerHTML = ""; return; }
    const product = s.phase === "urun";
    const pct = s.total ? s.made / s.total : 0;
    const open = s.total - s.made;
    const ring = `<svg class="mp-ring" viewBox="0 0 44 44" aria-hidden="true">
        <circle cx="22" cy="22" r="18" class="track"/><circle cx="22" cy="22" r="18" class="fill"
          style="stroke-dasharray:${(pct * 113.1).toFixed(1)} 113.1"/></svg>`;
    const say = product
      ? "<b>Ürün evresi</b><span>Bütün kararlar verildi. Talimat notun kendi kararlarından yazılacak.</span>"
      : `<b>${esc(s.phase_label)} evresi · ${s.made}/${s.total} karar</b><span>${s.waiting
        ? `Açık kalan ${open} kararı ve cevap bekleyen ${s.waiting} soruyu model kendisi karara bağlayıp Varsayımlar bölümüne yazacak.`
        : `Açık kalan ${open} kararı model kendisi karara bağlayıp Varsayımlar bölümüne yazacak.`}</span>`;
    box.className = `mp-ready${product ? " product" : ""}`;
    box.innerHTML = `${ring}<span class="mp-ring-n">${s.made}<small>/${s.total}</small></span>
      <p>${say}</p>
      <div class="mp-facts">
        <span class="chip ${s.answered ? "chip-done" : ""}">${s.answered} cevaplanmış soru</span>
        <span class="chip ${s.research ? "chip-done" : ""}">${s.research ? "Araştırma katıldı" : "Araştırma yok"}</span>
      </div>`;
  }

  _paintBody() {
    const body = this.el.querySelector(".mp-body");
    if (this.running) {
      body.innerHTML = `<div class="mp-live"><pre class="mp-raw"></pre></div>`;
      this._paintLive();
      return;
    }
    if (!this.result) {
      body.innerHTML = `<div class="mp-empty">
        <div class="mp-orbit" aria-hidden="true"><i></i><i></i><i></i>${icon("wand", 26)}</div>
        <h3>Notun, bir yapay zekânın okuyup yapabileceği bir talimata dönüşsün</h3>
        <p>Not, yol haritasındaki kararlar, cevapladığın sorular, onayladığın ve reddettiğin öneriler ve
          araştırma tek metinde toplanır. Model açık kalan her şeyi kendisi karara bağlar; hiçbir soru bırakmaz.</p>
        <div class="mp-sections">${SECTIONS.map((s, i) => `<span style="--i:${i}">${esc(s)}</span>`).join("")}</div>
        <p class="mp-kbd">Oluşturmak için <kbd>Ctrl</kbd> <kbd>Enter</kbd></p>
      </div>`;
      return;
    }
    const r = this.result;
    const assumed = (r.assumptions || []).length
      ? `<details class="mp-assumed" open><summary>${icon("lightbulb", 14)}Modelin senin yerine verdiği kararlar <b>${r.assumptions.length}</b></summary>
          <ul>${r.assumptions.map((a) => `<li>${esc(a.replace(/\*\*|__/g, ""))}</li>`).join("")}</ul></details>` : "";
    if (this.view === "raw") {
      body.innerHTML = `${assumed}<pre class="mp-raw done">${esc(r.text)}</pre>`;
      return;
    }
    body.innerHTML = `${assumed}<article class="md mp-md"><p class="mp-rendering">Hazırlanıyor…</p></article>`;
    const seq = (this._renderSeq = (this._renderSeq || 0) + 1);
    api.post("/api/render", { content: r.text, path: this.path })
      .then(({ html: rendered }) => { if (seq === this._renderSeq && this.el) body.querySelector(".mp-md").innerHTML = rendered; })
      .catch(() => { if (seq === this._renderSeq && this.el) body.querySelector(".mp-md").outerHTML = `<pre class="mp-raw done">${esc(r.text)}</pre>`; });
  }

  _paintLive() {
    const pre = this.el?.querySelector(".mp-live .mp-raw");
    if (!pre) return;
    const stick = pre.parentElement.scrollHeight - pre.parentElement.scrollTop - pre.parentElement.clientHeight < 60;
    pre.textContent = this.live || "";
    pre.classList.toggle("waiting", !this.live);
    if (stick) pre.parentElement.scrollTop = pre.parentElement.scrollHeight;
    this._paintFoot();
  }

  _paintFoot() {
    const foot = this.el?.querySelector(".mp-foot");
    if (!foot) return;
    if (this.running) {
      const secs = Math.round((performance.now() - (this.started || performance.now())) / 1000);
      const doing = this.phase === "checking" ? "Açık uçlu satırlar kapatılıyor" : this.live ? "Yazılıyor" : "Not ve kararlar okunuyor";
      foot.innerHTML = `<span class="mp-pulse"></span>${doing} · ${fmt(words(this.live))} kelime · ${secs} sn${this.provider ? ` · ${esc(this.provider)}` : ""}`;
      return;
    }
    const r = this.result;
    if (!r) { foot.innerHTML = this.stats ? `Hazır olduğunda ${SECTIONS.length} bölüm yazılacak.` : ""; return; }
    const when = r.created ? new Date(r.created).toLocaleString(locale(), { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "";
    foot.innerHTML = [
      `${fmt(words(r.text))} kelime`, `${r.sections} bölüm`, `${(r.assumptions || []).length} varsayım`,
      r.open ? `<span class="warn">${r.open} satır açık uçlu kaldı</span>` : `<span class="ok">${icon("check", 12)}açık soru yok</span>`,
      r.fixed ? `${r.fixed} satır sonradan karara bağlandı` : "", r.provider ? esc(r.provider) : "",
      r.seconds ? `${r.seconds} sn` : "", when,
    ].filter(Boolean).join(" · ");
  }

  // ---------- actions ----------
  async _click(e) {
    const lang = e.target.closest("[data-lang]");
    if (lang) {
      this.lang = lang.dataset.lang;
      this.chosen = this.lang;
      try { localStorage.setItem(LANG_KEY, this.lang); } catch { /* private window */ }
      this._paint();
      return;
    }
    const view = e.target.closest("[data-view]");
    if (view) { this.view = view.dataset.view; this._paint(); return; }
    const act = e.target.closest("[data-act]")?.dataset.act;
    if (act === "close") return this.close();
    if (act === "generate") return this.generate();
    if (!this.result) return;
    const text = this.result.text;
    if (act === "copy") {
      try {
        await navigator.clipboard.writeText(text);
      } catch {
        const area = html("<textarea></textarea>");
        area.value = text;
        document.body.append(area);
        area.select();
        document.execCommand("copy");
        area.remove();
      }
      toast("Master prompt panoya kopyalandı — bir kodlama yapay zekâsına yapıştırabilirsin.", "success");
    } else if (act === "save") {
      const dir = this.path.includes("/") ? this.path.slice(0, this.path.lastIndexOf("/")) : "";
      try {
        // marked as the assistant's output, so it is never asked about as a new idea
        const content = text.startsWith("---") ? text : `---\ntur: master-prompt\n---\n\n${text}`;
        const { path } = await api.post("/api/notes/create", { dir, name: `${this.name} — master prompt`, content });
        toast(`“${path.split("/").pop()}” olarak kaydedildi.`, "success");
        this.close();
        this.h.openNote?.(path);
      } catch (err) {
        toast(err.message, "error");
      }
    } else if (act === "download") {
      const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
      const a = html(`<a download="${esc(this.name)} — master prompt.md" href="${url}"></a>`);
      document.body.append(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
    }
  }
}
