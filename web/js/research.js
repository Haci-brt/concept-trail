// User-started research for the open idea. Findings can be proposed for the
// note, but the existing assistant approval event is the only write path.
import { api } from "./api.js";
import { icon } from "./icons.js";
import { esc, html, toast } from "./util.js";

const STEP_LABELS = {
  terimler: "Araştırma planı hazırlanıyor",
  arama: "Benzer projeler aranıyor",
  araclar: "Yardımcı araçlar aranıyor",
  kaynaklar: "Web kaynakları okunuyor",
  web: "Web kaynakları karşılaştırılıyor",
  oneriler: "Geliştirme fikirleri hazırlanıyor",
  degerlendirme: "Bulgular değerlendiriliyor",
  rakipler: "Benzer projeler yakından inceleniyor",
  bitti: "Araştırma tamamlandı",
  hata: "Araştırma durdu",
};

const safeUrl = (value) => {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : "";
  } catch { return ""; }
};

function privateContent(content) {
  const lines = String(content || "").replace(/^\uFEFF/, "").split(/\r?\n/);
  if (lines[0]?.trim() !== "---") return false;
  for (const line of lines.slice(1)) {
    if (line.trim() === "---") break;
    const field = /^\s*(?:gizli|private)\s*:\s*(.*?)\s*(?:#.*)?$/i.exec(line);
    if (field && ["true", "yes", "evet", "1"].includes(field[1].replace(/^['"]|['"]$/g, "").trim().toLowerCase())) return true;
  }
  return false;
}

function sourceTitle(source, fallback) {
  return source?.title || fallback || "Kaynak";
}

export class ResearchPanel {
  constructor({ getContent, beforeStart }) {
    this.getContent = getContent;
    this.beforeStart = beforeStart;
    this.path = null;
    this.state = null;
    this.progress = null;
    this.selected = new Set();
    this.items = [];
    this.proposal = null;
    this.proposing = false;
    this.private = false;
    this.expanded = false;
    this.focus = "";
    // every web search opens a visible browser window; the writer decides
    try { this.web = localStorage.getItem("ct.research.web") !== "0"; } catch { this.web = true; }
    this.sourceFilter = "read";
    this.el = html('<section class="research card" id="research" aria-label="Fikir araştırması" hidden></section>');
    this.backdrop = html('<div class="research-backdrop" hidden></div>');
    document.body.append(this.backdrop);
    this.backdrop.addEventListener("click", () => this.close());
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && this.expanded) { e.preventDefault(); this.close(); }
    });
    this.el.addEventListener("click", (e) => {
      const act = e.target.closest("[data-act]")?.dataset.act;
      if (act === "open") this.open();
      else if (act === "close") this.close();
      else if (act === "start") this.start();
      else if (act === "propose") this.propose();
      else if (act === "approve" || act === "reject") this.decide(act);
      else if (act === "filter") {
        this.sourceFilter = e.target.closest("[data-filter]")?.dataset.filter || "all";
        this.render();
      }
    });
    this.el.addEventListener("change", (e) => {
      const input = e.target.closest('input[data-research-pick]');
      if (!input) return;
      if (input.checked && this.selected.size >= 8) {
        input.checked = false;
        toast("Bir öneride en fazla 8 bulgu seçebilirsin.");
        return;
      }
      if (input.checked) this.selected.add(input.dataset.researchPick);
      else this.selected.delete(input.dataset.researchPick);
      this._updateSelection();
    });
    this.el.addEventListener("input", (e) => {
      if (e.target.id === "researchFocus") this.focus = e.target.value;
    });
    this.el.addEventListener("change", (e) => {
      if (e.target.id !== "researchWeb") return;
      this.web = e.target.checked;
      try { localStorage.setItem("ct.research.web", this.web ? "1" : "0"); } catch { /* per-viewer only */ }
    });
  }

  /** A note switch keeps all pending approval events in the shared history. */
  async setNote(path) {
    this.path = path;
    this.progress = null;
    this.state = null;
    this.proposal = null;
    this.selected.clear();
    this.close();
    this.focus = "";
    if (!path) { this.el.hidden = true; return; }
    this.el.hidden = false;
    this.render();
    try {
      const state = await api.get("/api/research", { path });
      if (this.path === path) { this.state = state; this.focus = state.focus || ""; this.render(); }
    } catch { /* Research is optional; the main editor remains usable. */ }
  }

  /** The editor calls this after content changes so the private state is live. */
  contentChanged() {
    if (privateContent(this.getContent?.()) !== this.private) this.render();
  }

  /** An approval from the HUD or history updates the same visible card. */
  onHistoryUpdate(event) {
    if (this.proposal?.id !== event.id || this.path !== event.path) return;
    this.proposal = { ...this.proposal, status: event.status };
    this.render();
  }

  /** A `research` event from the server. */
  onEvent(data) {
    if (data.path !== this.path) return;
    this.progress = data;
    if (data.step === "bitti" && data.result) {
      this.state = data.result;
      this.progress = null;
      this.selected.clear();
      this.proposal = null;
    }
    if (data.step === "hata") {
      this.state = { ...(this.state || {}), status: "error", error: data.note };
      this.progress = null;
    }
    this.render();
  }

  /** Start with a heading the assistant asked to look into. */
  startWith(focus) {
    this.focus = focus;
    const field = this.el.querySelector("#researchFocus");
    if (field) field.value = focus;
    return this.start();
  }

  async start() {
    if (!this.path || this.progress || (this.state?.status === "running" && this.state?.busy)) return;
    const path = this.path;
    this.focus = this.el.querySelector("#researchFocus")?.value.trim() ?? this.focus;
    this.open();
    try {
      await this.beforeStart?.(path);
      if (path !== this.path) return;
      const content = this.getContent?.() ?? null;
      if (privateContent(content)) { this.render(); return; }
      this.progress = { step: "terimler", note: "Başlatılıyor…" };
      this.render();
      await api.post("/api/research/start", { path, content, focus: this.focus, web: this.web });
    } catch (err) {
      if (path !== this.path) return;
      this.progress = null;
      toast(err.message, "error", 6000);
      this.render();
    }
  }

  open() {
    if (!this.path) { toast("Önce bir not aç."); return; }
    if (!this.expanded) {
      this.home = this.el.parentNode;
      this.nextSibling = this.el.nextSibling;
      document.body.append(this.el);
    }
    this.expanded = true;
    this.el.classList.add("expanded");
    this.backdrop.hidden = false;
    this.render();
  }

  close() {
    if (!this.expanded) return;
    this.focus = this.el.querySelector("#researchFocus")?.value.trim() ?? this.focus;
    this.expanded = false;
    this.el.classList.remove("expanded");
    this.backdrop.hidden = true;
    if (this.home) this.home.insertBefore(this.el, this.nextSibling?.parentNode === this.home ? this.nextSibling : null);
    this.render();
  }

  async propose() {
    if (!this.path || this.proposing || !this.selected.size || privateContent(this.getContent?.())) return;
    const path = this.path;
    const items = [...this.selected].map((key) => {
      const separator = key.indexOf(":");
      return { type: key.slice(0, separator), id: key.slice(separator + 1) };
    });
    if (!items.length) return;
    this.proposing = true;
    this._updateSelection();
    try {
      const { proposal } = await api.post("/api/research/propose", { path, items });
      if (path === this.path && proposal) {
        this.proposal = proposal;
        this.selected.clear();
        this.render();
        this.el.querySelector(".r-proposal")?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
    } catch (err) {
      toast(err.message, "error", 6000);
    } finally {
      this.proposing = false;
      this._updateSelection();
    }
  }

  async decide(action) {
    const proposal = this.proposal;
    if (!proposal || this.proposing) return;
    this.proposing = true;
    this._updateSelection();
    try {
      await api.post("/api/assistant/hud", { event_id: proposal.id, action });
      if (this.proposal?.id === proposal.id) {
        this.proposal = { ...proposal, status: action === "approve" ? "approved" : "rejected" };
        this.render();
      }
    } catch (err) {
      toast(err.message, "error", 6000);
    } finally {
      this.proposing = false;
      this._updateSelection();
    }
  }

  render() {
    const previousScroll = this.el.querySelector(".r-body")?.scrollTop || 0;
    const title = `<div class="sb-section-head r-head"><span class="ico">${icon("search", 16)}</span><span class="label">Fikir araştırması</span><button class="r-head-action" data-act="${this.expanded ? "close" : "open"}" aria-label="${this.expanded ? "Araştırmayı kapat" : "Araştırmayı genişlet"}">${this.expanded ? icon("x", 16) : "Aç ↗"}</button></div>`;
    const isPrivate = privateContent(this.getContent?.());
    this.private = isPrivate;
    const running = !isPrivate && (Boolean(this.progress) || (this.state?.status === "running" && this.state?.busy));
    this.el.classList.toggle("is-private", isPrivate);
    this.el.classList.toggle("expanded", this.expanded);
    if (isPrivate) {
      this.el.innerHTML = `${title}<div class="r-body"><p class="r-private">${icon("eyeOff", 14)}Bu not gizli. Web ve GitHub araştırması kapalı.</p></div>`;
      return;
    }
    if (!this.expanded) {
      const s = this.state || {};
      const read = (s.sources || []).filter((source) => source.verified).length;
      const count = (s.candidates || []).length + (s.tools || []).length;
      const status = running ? "Araştırılıyor…" : s.status === "done" ? `${count} proje/araç · ${read} sayfa okundu` : s.status === "error" ? "Araştırma durdu; ayrıntıları aç" : "Benzer projeleri, araçları ve kaynakların içeriğini incele.";
      this.el.innerHTML = `${title}<div class="r-body r-compact"><p>${esc(status)}</p><button class="btn btn-sm btn-accent" data-act="open">${icon("search", 13)}${s.status === "done" ? "Bulguları aç" : "Araştırmayı aç"}</button></div>`;
      return;
    }
    const focusField = `<div class="r-focus-row"><label for="researchFocus"><b>Araştırma odağı</b><span>Belirli bir teknoloji, benzer fikir veya yardımcı araç arayabilirsin.</span></label><div class="r-focus-control"><input id="researchFocus" type="text" maxlength="240" value="${esc(this.focus)}" placeholder="Örn. bu fikir için açık kaynak grafik ve arama araçları"><button class="btn btn-accent" data-act="start" ${running ? "disabled" : ""}>${icon("search", 15)}${this.state?.status === "done" ? "Yeniden araştır" : "Araştır"}</button></div><label class="r-web-toggle" title="Web araması ayrı bir Opera penceresinde yapılır; kişisel profilin kullanılmaz. Kapalıyken yalnız GitHub aranır ve bulunan README'ler okunur."><input type="checkbox" id="researchWeb" ${this.web ? "checked" : ""} ${running ? "disabled" : ""}><span>Web'de de ara <em>(her arama ekranda bir Opera penceresi açar)</em></span></label></div>`;
    if (running) {
      const p = this.progress || {};
      const width = p.total ? Math.max(0, Math.min(100, Math.round(100 * (p.done || 0) / p.total))) : 0;
      const bar = p.total ? `<div class="r-bar" role="progressbar" aria-valuenow="${width}" aria-valuemin="0" aria-valuemax="100"><i style="width:${width}%"></i></div>` : "";
      const ongoing = `${(this.state?.queries || []).length} arama yolu denendi, ${(this.state?.sources || []).length} kaynak bulundu.`;
      this.el.innerHTML = `${title}${focusField}<div class="r-body r-running" aria-live="polite"><div class="r-step">${icon("refresh", 12)}${esc(STEP_LABELS[p.step] || "Araştırılıyor")}<span class="dots"></span></div><div class="r-note">${esc(p.note || ongoing)}</div>${bar}<p>Kaynak sayfaları açılıp okunurken sonuçlar notuna yazılmaz. Araştırma bitince kanıtları seçebilirsin.</p></div>`;
      return;
    }
    this.items = [];
    this.el.innerHTML = `${title}${focusField}<div class="r-body">${this._body()}</div>`;
    this.el.querySelector(".r-body").scrollTop = previousScroll;
    this._updateSelection();
  }

  _body() {
    const s = this.state;
    if (s?.status === "error") return `<div class="r-empty r-err">${esc(s.error || "Araştırma tamamlanamadı.")}</div>`;
    if (s?.status !== "done") {
      return `<div class="r-empty"><h2>Fikrini kaynaklarla araştır</h2><p>Notun içeriğinden benzer projeleri, kullanılabilecek araçları ve yakın fikirleri arar. Uygun sayfaları açıp içeriğini okur; hangi bulgunun neye dayandığını burada gösterir.</p><p>Başlamak için yukarıdaki <b>Araştır</b> düğmesine bas. Araştırma yalnız sen başlattığında dış ağa çıkar.</p></div>`;
    }

    const verdict = s.verdict || {};
    const candidates = Array.isArray(s.candidates) ? s.candidates : [];
    const tools = Array.isArray(s.tools) ? s.tools : [];
    const opportunities = Array.isArray(s.opportunities) ? s.opportunities : [];
    const sources = Array.isArray(s.sources) ? s.sources : [];
    const sourceMap = new Map(sources.map((item) => [item.url, item]));
    const byName = new Map(candidates.map((c) => [c.repo, c]));
    const same = Array.isArray(verdict.same) ? verdict.same : [];
    const adjacent = Array.isArray(verdict.adjacent) ? verdict.adjacent : [];
    const read = sources.filter((source) => source.verified).length;
    // answered and found something; an empty answer is counted on its own so a
    // run of six searches that returned nothing does not read as six successes
    const successful = (s.queries || []).filter((query) => query.ok && query.count !== 0).length;
    const empty = (s.queries || []).filter((query) => query.empty).length;
    let out = `<div class="r-overview"><div class="r-overview-title"><div><span class="r-eyebrow">ARAŞTIRMA RAPORU</span><h2>Fikrin etrafındaki ekosistem</h2></div><div class="r-metrics"><span><b>${candidates.length}</b> proje</span><span><b>${tools.length}</b> araç</span><span><b>${read}</b> okunan sayfa</span>${(s.queries || []).length ? `<span><b>${successful}</b> sonuç veren sorgu</span>` : ""}${empty ? `<span><b>${empty}</b> boş sorgu</span>` : ""}${typeof s.timings?.total === "number" ? `<span><b>${Math.round(s.timings.total)} sn</b> süre</span>` : ""}</div></div>${verdict.verdict ? `<p>${esc(verdict.verdict)}</p>` : ""}</div>`;
    out += this._deep(s.deep);
    let projects = "";

    const projectGroups = [["Aynı alandaki projeler", same], ["Yakın projeler", adjacent]];
    for (const [name, repos] of projectGroups) {
      if (!repos.length) continue;
      projects += this._group(name, repos.map((repo) => this._project(byName.get(repo) || { repo })), true);
    }
    const seen = new Set([...same, ...adjacent]);
    const rest = candidates.filter((c) => !seen.has(c.repo));
    if (rest.length) projects += this._group(`Diğer projeler (${rest.length})`, rest.map((c) => this._project(c)), !same.length && !adjacent.length);

    let evidence = "";
    if (tools.length) evidence += this._group(`Yardımcı araç adayları (${tools.length})`, tools.map((tool) => this._tool(tool, sourceMap)), true);
    if (opportunities.length) evidence += this._group(`Geliştirme fırsatları (${opportunities.length})`, opportunities.map((item) => this._opportunity(item, sourceMap)), true);
    if (!candidates.length && !tools.length && !opportunities.length) projects += '<p class="hint">Bu taramada doğrulanabilir bir eşleşme bulunamadı. Araştırma odağını değiştirerek yeniden deneyebilirsin.</p>';

    out += `<div class="r-results-grid"><div class="r-result-column"><h3>Benzer ve yakın projeler</h3>${projects || '<p class="hint">Proje bulunamadı.</p>'}</div><div class="r-result-column"><h3>Fikri geliştirecek parçalar</h3>${evidence || '<p class="hint">Araç veya geliştirme fırsatı bulunamadı.</p>'}</div></div>`;
    const shownSources = sources.filter((source) => this.sourceFilter === "all" || (this.sourceFilter === "read" ? source.verified : !source.verified));
    const sourceCards = shownSources.map((source) => this._source(source));
    if (this.items.length) out += `<div class="r-selection"><span>Notuna almak istediklerini seç (en fazla 8). Seçim doğrudan nota yazılmaz.</span><button class="btn btn-sm btn-accent" data-act="propose" disabled>${icon("pencil", 13)}Seçilenleri nota öner</button></div>`;
    if (this.proposal) out += this._proposal();
    if (sources.length) out += `<div class="r-evidence-head"><div><span class="r-eyebrow">KAYNAK OKUMASI</span><h3>Kaynakların içinde ne var?</h3></div><div class="r-filter" role="group" aria-label="Kaynak filtresi"><button data-act="filter" data-filter="read" class="${this.sourceFilter === "read" ? "on" : ""}">Okunan ${read}</button><button data-act="filter" data-filter="all" class="${this.sourceFilter === "all" ? "on" : ""}">Tümü ${sources.length}</button><button data-act="filter" data-filter="unread" class="${this.sourceFilter === "unread" ? "on" : ""}">Okunmayan ${sources.length - read}</button></div></div><div class="r-source-grid">${sourceCards.length ? sourceCards.join("") : '<p class="hint">Bu filtrede kaynak yok.</p>'}</div>`;
    if (Array.isArray(s.queries) && s.queries.length) out += this._group(`Arama yolları (${s.queries.length})`, s.queries.map((q) => `<div class="r-query${q.empty ? " empty" : ""}"><b>${esc(q.purpose || q.style || "Arama")}${!q.ok ? " · yanıt alınamadı" : q.empty ? " · boş döndü" : typeof q.count === "number" ? ` ✓ ${q.count} sonuç` : " ✓"}</b><span>${esc(q.query || "")}</span></div>`), false);
    return out + `<p class="r-caveat">Bulunamaması fikrin özgün olduğu anlamına gelmez. Notuna alma işlemi ayrıca onay ister.</p>`;
  }

  /** The closest projects looked at closely: a table of the idea's parts
   *  against them, what each does and lacks, and what would set the idea apart. */
  _deep(deep) {
    if (!deep || !Array.isArray(deep.projects) || !deep.projects.length) return "";
    const projects = deep.projects;
    const short = (repo) => String(repo).split("/").pop();
    // new results only say "var" (with the passage) or nothing; older ones
    // may still carry kısmen / yok from when the model filled the table
    const mark = { var: ["✓", "okunan kanıtta geçiyor"], kismen: ["◐", "kısmen"], yok: ["—", "yok"] };
    const components = (deep.components || []).filter((c) => deep.matrix?.[c]);
    const table = components.length ? `<div class="r-matrix-wrap"><table class="r-matrix">
        <thead><tr><th>Fikrin parçası</th>${projects.map((p) => `<th title="${esc(p.repo)}">${esc(short(p.repo))}</th>`).join("")}</tr></thead>
        <tbody>${components.map((c) => `<tr><th title="${esc(c)}">${esc(deep.labels?.[c] || c)}</th>${projects.map((p) => {
          const cell = mark[deep.matrix[c]?.[p.repo]];
          const quote = deep.quotes?.[c]?.[p.repo];
          return cell ? `<td class="m-${deep.matrix[c][p.repo]}" title="${esc(quote ? `${cell[1]}: ${quote}` : cell[1])}">${cell[0]}</td>` : '<td class="m-unknown" title="okunan kanıtta geçmiyor; bu, projede olmadığını göstermez">?</td>';
        }).join("")}</tr>`).join("")}</tbody></table>
        <p class="r-matrix-key">${deep.quotes ? "✓ projenin README'sinde ya da sitesinde geçiyor (üstüne gel: alıntı) · ? okunan kısımda geçmiyor, yokluk kanıtı değil" : "✓ var · ◐ kısmen · — yok · ? kanıt yok"}</p></div>` : "";
    const list = (title, items) => items?.length ? `<div class="r-deep-list"><b>${title}</b><ul>${items.map((i) => `<li>${esc(i)}</li>`).join("")}</ul></div>` : "";
    const cards = projects.map((p) => {
      const href = safeUrl(p.url || `https://github.com/${p.repo}`);
      const facts = [p.stars != null ? `${Number(p.stars).toLocaleString("tr-TR")} yıldız` : "",
        p.updated ? `son güncelleme ${esc(p.updated)}` : "", p.license ? esc(p.license) : "",
        p.archived ? "arşivlenmiş" : ""].filter(Boolean);
      return `<article class="r-result r-deep-card"><div class="r-deep-top"><strong>${esc(p.repo)}</strong>${href ? `<a class="r-source-link" href="${esc(href)}" target="_blank" rel="noopener noreferrer">Kaynak ↗</a>` : ""}</div>
        ${facts.length ? `<div class="r-meta">${facts.map((f) => `<span>${f}</span>`).join("")}</div>` : ""}
        ${p.summary ? `<p>${esc(p.summary)}</p>` : p.description ? `<p>${esc(p.description)}</p>` : ""}
        ${p.unseen ? `${list("Kanıtında geçen parçalar", p.shared)}${list("Okunan kısımda geçmeyen (yokluk kanıtı değil)", p.unseen)}` : `${list("Fikrinle ortak", p.shared)}${list("Fikrinde olup onda olmayan", p.missing)}`}
        ${list("Zayıf noktası", p.weak)}${p.lesson ? `<p class="r-why"><b>Alınacak ders:</b> ${esc(p.lesson)}</p>` : ""}
        ${p.issues?.length ? `<details class="r-page"><summary>Son issue başlıkları <span>${p.issues.length}</span></summary><ul class="r-issues">${p.issues.map((i) => `<li>${esc(i)}</li>`).join("")}</ul></details>` : ""}
      </article>`;
    });
    const insights = (title, rows) => rows?.length ? this._group(title,
      rows.map((row) => `<article class="r-result r-insight">${this._select("insight", row.id, row.text)}</article>`), true) : "";
    return `<section class="r-deep"><div class="r-evidence-head"><div><span class="r-eyebrow">RAKİP ANALİZİ</span>
        <h3>En yakın ${projects.length} proje, fikrinle karşılaştırıldı</h3></div></div>
      ${table}
      ${insights(deep.quotes ? "Fikrini ayırabilecek noktalar" : "Fikrini ayıracak noktalar", deep.differentiators)}
      ${insights(deep.quotes ? "Rakiplerden çıkan öneriler (alıntıyla)" : "Geliştirme argümanları", deep.arguments)}
      ${this._group(`Projeler yakından (${projects.length})`, cards, false)}</section>`;
  }

  _group(title, contents, open) {
    return `<details class="r-section" ${open ? "open" : ""}><summary>${esc(title)}<span>${icon("chevronDown", 13)}</span></summary><div class="r-list">${contents.join("")}</div></details>`;
  }

  _select(type, id, label) {
    if (!id) return `<strong>${esc(label)}</strong>`;
    const key = `${type}:${id}`;
    this.items.push({ type, id });
    return `<label class="r-pick"><input type="checkbox" data-research-pick="${esc(key)}" ${this.selected.has(key) ? "checked" : ""} aria-label="Not için seç: ${esc(label)}"><span>${esc(label)}</span></label>`;
  }

  _project(c) {
    const name = String(c.repo || "Proje");
    const href = safeUrl(c.url || `https://github.com/${name}`);
    const found = Array.isArray(c.found_by) ? c.found_by.length : 0;
    return `<article class="r-result">${this._select("project", name, name)}${href ? `<a class="r-source-link" href="${esc(href)}" target="_blank" rel="noopener noreferrer" aria-label="${esc(name)} kaynağını aç">Kaynak ↗</a>` : ""}
      ${c.description ? `<p>${esc(String(c.description).slice(0, 500))}</p>` : ""}
      <div class="r-meta">${found ? `<span>${found} arama yolunda bulundu</span>` : ""}${c.language ? `<span>${esc(c.language)}</span>` : ""}</div></article>`;
  }

  _tool(tool, sources) {
    const name = String(tool.name || tool.repo || "Araç");
    const id = String(tool.repo || tool.url || "");
    const href = safeUrl(tool.url);
    return `<article class="r-result">${this._select("tool", id, name)}${href ? `<a class="r-source-link" href="${esc(href)}" target="_blank" rel="noopener noreferrer" aria-label="${esc(name)} kaynağını aç">Kaynak ↗</a>` : ""}
      ${tool.description ? `<p>${esc(tool.description)}</p>` : ""}${tool.why ? `<p class="r-why"><b>Nasıl yardımcı olur:</b> ${esc(tool.why)}</p>` : ""}
      <div class="r-meta"><span>${tool.recommended ? "Model önerisi" : "Araştırma adayı"}</span></div>
      ${this._sourceLinks(tool.source_urls, sources)}</article>`;
  }

  _opportunity(item, sources) {
    const title = String(item.title || "Geliştirme fikri");
    return `<article class="r-result r-opportunity">${this._select("opportunity", item.id, title)}
      ${item.detail ? `<p>${esc(item.detail)}</p>` : ""}${this._sourceLinks(item.source_urls, sources)}</article>`;
  }

  _sourceLinks(urls, sources) {
    if (!Array.isArray(urls) || !urls.length) return "";
    const links = urls.slice(0, 3).map((url) => {
      const href = safeUrl(url);
      if (!href) return "";
      return `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(sourceTitle(sources.get(url), new URL(href).hostname))} ↗</a>`;
    }).filter(Boolean);
    return links.length ? `<div class="r-source-links">${links.join("")}</div>` : "";
  }

  _source(source) {
    const href = safeUrl(source.url);
    if (!href) return "";
    const body = String(source.content || source.excerpt || "").trim();
    const label = source.verified ? "Sayfa okundu" : source.read_error ? "Okunamadı" : "Arama özeti";
    const kind = { prior: "Benzer fikir", support: "Yardımcı araç", adjacent: "Yakın fikir" }[source.kind] || "Kaynak";
    return `<article class="r-source ${source.verified ? "read" : ""}"><div class="r-source-top"><div class="r-source-tags"><span class="r-read-status">${label}</span><span class="r-kind">${kind}</span></div>${source.verified ? this._select("source", href, sourceTitle(source, new URL(href).hostname)) : `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(sourceTitle(source, new URL(href).hostname))}</a>`}<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">Kaynağı aç ↗</a></div><p>${esc(String(source.excerpt || source.snippet || source.read_error || "").slice(0, 700))}</p>${body ? `<details class="r-page"><summary>Sayfa içeriğini oku <span>${Math.min(body.length, 8000).toLocaleString("tr-TR")} karakter</span></summary><div class="r-page-text">${esc(body.slice(0, 8000))}</div></details>` : ""}</article>`;
  }

  _proposal() {
    const p = this.proposal;
    const pending = p.status === "pending";
    return `<div class="r-proposal" aria-live="polite"><b>${pending ? "Nota eklensin mi?" : p.status === "approved" ? "Nota eklendi" : "Nota eklenmedi"}</b><p>${esc(p.text || "")}</p>${pending ? `<div><button class="btn btn-sm btn-accent" data-act="approve">${icon("check", 13)}Nota ekle</button><button class="btn btn-sm" data-act="reject">Vazgeç</button></div>` : ""}</div>`;
  }

  _updateSelection() {
    const button = this.el.querySelector('[data-act="propose"]');
    if (button) {
      const count = this.selected.size;
      button.disabled = !count || this.proposing;
      button.innerHTML = `${icon("pencil", 13)}${count ? `${count} bulguyu nota öner` : "Seçilenleri nota öner"}`;
    }
    this.el.querySelectorAll('.r-proposal [data-act]').forEach((button) => { button.disabled = this.proposing; });
  }

  _button(label) {
    return `<button class="btn btn-sm btn-accent r-start" data-act="start">${icon("search", 13)}${label}</button>`;
  }
}
