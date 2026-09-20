// "Bu fikir yapılmış mı?" — prior-art research for the open note.
//
// The run takes about a minute (GitHub throttles searches to one per six
// seconds), so it reports progress over the `research` event stream rather
// than blocking anything. It never says an idea is original: the search that
// backs it found only some of the known projects even at its best.
import { api } from "./api.js";
import { icon } from "./icons.js";
import { esc, html, toast } from "./util.js";

const STEP_LABELS = {
  terimler: "Arama terimleri çıkarılıyor",
  arama: "GitHub'da aranıyor",
  web: "Web'de çapraz kontrol",
  degerlendirme: "Bulunanlar karşılaştırılıyor",
  bitti: "Bitti",
  hata: "Hata",
};

export class ResearchPanel {
  constructor({ getContent }) {
    this.getContent = getContent;
    this.path = null;
    this.state = null;
    this.progress = null;
    this.el = html('<div class="research card" id="research" hidden></div>');
    this.el.addEventListener("click", (e) => {
      if (e.target.closest('[data-act="start"]')) this.start();
    });
  }

  /** The open note changed; show whatever is already known about it. */
  async setNote(path) {
    this.path = path;
    this.progress = null;
    this.state = null;
    if (!path) { this.el.hidden = true; return; }
    this.el.hidden = false;
    this.render();
    try {
      const state = await api.get("/api/research", { path });
      if (this.path === path) { this.state = state; this.render(); }
    } catch { /* the panel is optional; a failure just leaves the button */ }
  }

  /** A `research` event from the server. */
  onEvent(data) {
    if (data.path !== this.path) return;
    this.progress = data;
    if (data.step === "bitti" && data.result) { this.state = data.result; this.progress = null; }
    if (data.step === "hata") this.state = { ...(this.state || {}), status: "error", error: data.note };
    this.render();
  }

  async start() {
    if (!this.path) return;
    this.progress = { step: "terimler", note: "Başlatılıyor…" };
    this.render();
    try {
      await api.post("/api/research/start", { path: this.path, content: this.getContent?.() ?? null });
    } catch (err) {
      this.progress = null;
      toast(err.message, "error", 6000);
      this.render();
    }
  }

  render() {
    const running = Boolean(this.progress) || this.state?.status === "running";
    const head = `<div class="sb-section-head"><span class="ico">${icon("search", 14)}</span>
      <span class="label">Bu fikir yapılmış mı?</span></div>`;
    if (running) {
      const p = this.progress || {};
      const bar = p.total ? `<div class="r-bar"><i style="width:${Math.round(100 * (p.done || 0) / p.total)}%"></i></div>` : "";
      this.el.innerHTML = `${head}<div class="r-body">
        <div class="r-step">${icon("refresh", 12)}${esc(STEP_LABELS[p.step] || "Çalışıyor")}<span class="dots"></span></div>
        <div class="r-note">${esc(p.note || "")}</div>${bar}</div>`;
      return;
    }
    this.el.innerHTML = `${head}<div class="r-body">${this._body()}</div>`;
  }

  _body() {
    const s = this.state;
    if (s?.status === "error") {
      return `<p class="r-err">${esc(s.error || "Araştırma tamamlanamadı.")}</p>${this._button("Tekrar dene")}`;
    }
    if (s?.status !== "done") {
      return `<p class="hint">Notundaki fikri GitHub'da ve web'de aratır, benzer projeleri getirir.
        Yaklaşık bir dakika sürer ve tarayıcı penceresi açılır.</p>${this._button("Araştır")}`;
    }
    const v = s.verdict || {};
    const byName = new Map((s.candidates || []).map((c) => [c.repo, c]));
    const groups = [["Aynı işi yapanlar", v.same || [], "same"], ["Yakın duranlar", v.adjacent || [], "near"]];
    let out = v.verdict ? `<p class="r-verdict">${esc(v.verdict)}</p>` : "";
    for (const [title, repos, cls] of groups) {
      if (!repos.length) continue;
      out += `<div class="r-group ${cls}"><b>${title}</b>` +
        repos.map((r) => this._repo(byName.get(r) || { repo: r })).join("") + "</div>";
    }
    const rest = (s.candidates || []).filter((c) => !(v.same || []).includes(c.repo) && !(v.adjacent || []).includes(c.repo));
    if (rest.length) {
      out += `<details class="r-rest"><summary>Diğer ${rest.length} aday</summary>` +
        rest.map((c) => this._repo(c)).join("") + "</details>";
    }
    out += `<p class="hint">Bulunamamış olması fikrin özgün olduğunu göstermez — bu arama
      bilinen projelerin ancak bir kısmını bulabiliyor.</p>`;
    return out + this._button("Yeniden araştır");
  }

  _repo(c) {
    const stars = c.stars ? `${(c.stars / 1000).toFixed(c.stars >= 10000 ? 0 : 1)}k` : "";
    return `<a class="r-repo" href="${esc(c.url || `https://github.com/${c.repo}`)}" target="_blank" rel="noreferrer">
      <span class="n">${esc(c.repo)}</span><span class="s">${stars}</span>
      <span class="d">${esc(String(c.description || "").slice(0, 90))}</span></a>`;
  }

  _button(label) {
    return `<button class="btn btn-sm btn-accent" data-act="start">${icon("search", 13)}${label}</button>`;
  }
}
