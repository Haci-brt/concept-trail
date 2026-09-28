// "Fikir Ağacı" — the note as a constellation.
//
// The note is a bright star in the middle; its questions, suggestions and
// chats branch out from it the way the writer drew it: rays from the centre,
// each carrying its own small cluster. Questions not yet answered glow and
// pulse; answered ones settle into a steady dim light. The threads between
// the stars are real strings (a few jointed points each), so they sway when
// a star moves; a star can be picked up and dragged like a physical object —
// its strings pull the others along — and when let go it swings back into
// place. Clicking a star grows its card out of it; clicking the empty sky
// shrinks the card back into the star.
//
// One canvas draws the sky, the strings and the stars; the card is HTML, so
// its text stays selectable and its buttons stay buttons.
import { api } from "./api.js";
import { icon } from "./icons.js";
import { esc, formatClock, splitSentence } from "./util.js";

const MIN_K = 0.3;
const MAX_K = 2.2;
const RING_1 = 190;          // root -> first ray
const RING_STEP = 118;       // each further level
const ROPE_JOINTS = 5;       // points inside each string
const FIXED_DT = 1 / 60;
const IGNITE_STEP = 0.34;    // seconds between one ring lighting up and the next
const DIM = 0.2;             // how bright the stars off the open card's path stay

export const QUESTION_KINDS = {
  derinlestirme: { label: "Derinleştirme", tone: "depth", icon: "zoomIn" },
  alternatif: { label: "Alternatif fikir", tone: "idea", icon: "lightbulb" },
  sonuc: { label: "Sonuç", tone: "effect", icon: "arrowRight" },
  kapsam: { label: "Kapsam", tone: "scope", icon: "fit" },
  ilham: { label: "İlham", tone: "inspire", icon: "sparkles" },
  netlestirme: { label: "Netleştirme", tone: "question", icon: "questionSquare" },
  // the decision ladder — broad to narrow; tone by rung
  amac: { label: "Kapsam · Amaç", tone: "scope", icon: "fit" },
  kullanici: { label: "Kapsam · Kullanıcı", tone: "scope", icon: "fit" },
  platform: { label: "Kapsam · Platform", tone: "scope", icon: "fit" },
  calisma: { label: "Kapsam · Çalışma ortamı", tone: "scope", icon: "fit" },
  parcalar: { label: "Mimari · Ana parçalar", tone: "depth", icon: "tree" },
  veri: { label: "Mimari · Veri", tone: "depth", icon: "tree" },
  iletisim: { label: "Mimari · İletişim", tone: "depth", icon: "tree" },
  dis: { label: "Mimari · Dış bağımlılıklar", tone: "depth", icon: "tree" },
  sorumluluk: { label: "Bileşen · Sorumluluk", tone: "effect", icon: "cpu" },
  arayuz: { label: "Bileşen · Arayüz", tone: "effect", icon: "cpu" },
  hata: { label: "Bileşen · Hata durumu", tone: "effect", icon: "cpu" },
  teknoloji: { label: "Detay · Teknoloji", tone: "idea", icon: "wand" },
  kenar: { label: "Detay · Uç durumlar", tone: "idea", icon: "wand" },
  test: { label: "Detay · Doğrulama", tone: "idea", icon: "wand" },
  dagitim: { label: "Detay · Dağıtım", tone: "idea", icon: "wand" },
  soru: { label: "Soru", tone: "question", icon: "questionSquare" },
};

export const questionKind = (node) => QUESTION_KINDS[node?.kind] || QUESTION_KINDS.soru;

// star colours, by what the star is
const TONE = {
  root: "#d9fbee", question: "#b9a6ff", depth: "#7cc0ff", idea: "#ffd166", effect: "#4fe0c8",
  scope: "#cfc3ff", inspire: "#ff8fc8", resolved: "#6fe3a1", edit: "#7cc0ff", thread: "#ff8fc8",
  summary: "#ffd166", section: "#9fb3c8", ghost: "#dbe7f5",
};
const RADIUS = { root: 15, section: 8.5, question: 7, resolved: 5, edit: 5.5, summary: 5.5, thread: 4.5, ghost: 6.5 };

const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
const easeOut = (t) => 1 - Math.pow(1 - Math.min(1, Math.max(0, t)), 3);
// a little past the mark and back: how a star pops into being
const easeOutBack = (t) => { const x = Math.min(1, Math.max(0, t)) - 1; return 1 + 2.70158 * x * x * x + 1.70158 * x * x; };
// roughly normal, for the density of the Milky Way across its width
const gauss = (rnd) => (rnd() + rnd() + rnd() + rnd() - 2) * 0.87;

function hexToRgb(hex) {
  const v = parseInt(hex.slice(1), 16);
  return [(v >> 16) & 255, (v >> 8) & 255, v & 255];
}
const rgba = (hex, a) => { const [r, g, b] = hexToRgb(hex); return `rgba(${r},${g},${b},${a})`; };

// a small deterministic generator, so the sky is the same every time
function seeded(seed) {
  let s = seed >>> 0;
  return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
}

export class IdeaTree {
  constructor(host, handlers) {
    this.host = host;
    this.h = handlers;
    this.path = null;
    this.name = "";
    this.nodes = [];
    this.filter = "all";
    this.busy = false;
    this.thinking = "";
    this.selected = null;
    this.visible = false;
    this.cam = { x: 0, y: 0, k: 1 };
    this.glide = null;
    this.stars = new Map();          // id -> simulated star
    this.strings = new Map();        // child id -> string (rope) to its parent
    this.bursts = [];
    this.hovered = null;
    this._loadSeq = 0;
    this._raf = 0;
    this._last = 0;
    this._acc = 0;
    this._time = 0;
    this._fresh = true;
    this._dpr = 1;
    this._focusMix = 0;
    this._coast = null;

    host.innerHTML = `
      <canvas class="cv-canvas" aria-label="Fikir ağacı: notun sorularından oluşan takımyıldızı"></canvas>
      <div class="cv-card tn" hidden></div>
      <div class="cv-tip" aria-hidden="true"><b></b><span></span></div>
      <div class="tv-bar tv-top">
        <div class="tv-title">
          <span class="tile sm t-question">${icon("tree", 14)}</span>
          <div><div class="t">Fikir Ağacı</div><div class="s tv-note"></div></div>
        </div>
        <div class="tv-stats"></div>
        <div class="tv-controls">
          <button class="btn btn-sm cv-next" data-act="next" title="Cevap bekleyen sıradaki soruya git (N)">${icon("sparkles", 13)}Sıradaki soru</button>
          <div class="seg" role="radiogroup" aria-label="Filtre">
            <button data-filter="all" class="on">Tümü</button><button data-filter="open">Açık</button><button data-filter="done">Sonuçlanan</button>
          </div>
          <div class="zoom">
            <button class="icon-btn sm" data-act="zoom-out" title="Uzaklaş (-)">${icon("zoomOut", 15)}</button>
            <span class="zoom-val">100%</span>
            <button class="icon-btn sm" data-act="zoom-in" title="Yakınlaş (+)">${icon("zoomIn", 15)}</button>
            <button class="icon-btn sm" data-act="fit" title="Sığdır (F)">${icon("fit", 15)}</button>
          </div>
        </div>
      </div>
      <div class="tv-bar tv-legend">
        <span><i class="star glow"></i>Cevap bekleyen soru</span><span><i class="star calm"></i>Sonuçlanan</span>
        <span><i class="star warm"></i>Nota eklenecek</span><span><i class="star cool"></i>Düzenleme</span>
        <span><i class="star pink"></i>Sohbet</span>
      </div>
      <div class="tv-hint">Üstüne gel: oku · Tıkla: aç · Yıldızı sürükle: çek · Boşluğa tıkla: kapat · N: sıradaki soru</div>
      <div class="tv-empty" hidden>
        <span class="tile t-question">${icon("sprout", 22)}</span>
        <h3>Gökyüzü henüz boş</h3>
        <p>Yazmaya devam ettikçe asistanın soruları, önerileri ve sohbetlerin burada yıldız yıldız belirecek.</p>
        <button class="btn btn-accent btn-sm" data-act="ask">${icon("sparkles", 14)}Asistana şimdi sor</button>
      </div>`;

    this.canvas = host.querySelector(".cv-canvas");
    this.ctx = this.canvas.getContext("2d");
    this.card = host.querySelector(".cv-card");
    this.tip = host.querySelector(".cv-tip");
    this.sky = this._makeSky();

    host.addEventListener("click", (e) => this._click(e));
    // the pointer went from a star onto a bar or the card: the star is no longer under it
    host.addEventListener("pointerover", (e) => {
      if (e.target !== this.canvas && this.hovered && !this._drag) { this.hovered = null; this.canvas.classList.remove("over-star"); }
    });
    this._wirePointer();
    new ResizeObserver(() => this._resize()).observe(host);
  }

  // ---------- public ----------
  async show(path, name) {
    this.visible = true;
    this.host.hidden = false;
    this.name = name;
    this.host.querySelector(".tv-note").textContent = `${name}.md`;
    this._resize();
    this._start();
    if (path === this.path) {
      this._update();
      return;
    }
    this.path = path;
    this.nodes = [];
    this.selected = null;
    this._closeCard(true);
    this.stars.clear();
    this.strings.clear();
    this._fresh = true;
    const seq = ++this._loadSeq;
    try {
      const { nodes } = await api.get("/api/assistant/nodes", { path });
      if (seq !== this._loadSeq) return;
      this.nodes = nodes;
    } catch {
      this.nodes = [];
    }
    this._update();
  }

  hide() {
    this.visible = false;
    this.host.hidden = true;
    cancelAnimationFrame(this._raf);
    this._raf = 0;
  }

  renamed(oldPath, newPath, newName) {
    if (this.path === oldPath) {
      this.path = newPath;
      this.name = newName;
      this.host.querySelector(".tv-note").textContent = `${newName}.md`;
      this._update();
    }
  }

  nodeChanged(path, node) {
    if (path !== this.path) return;
    const i = this.nodes.findIndex((n) => n.id === node.id);
    const wasOpen = i !== -1 && this.nodes[i].status === "open";
    if (i === -1) this.nodes.push(node); else this.nodes[i] = node;
    if (wasOpen && node.status === "resolved") this._celebrate = node.id;
    if (this.visible) this._update();
  }

  setBusy(busyPath, thinkingText) {
    const busy = Boolean(busyPath) && busyPath === this.path;
    const text = busy ? thinkingText || "" : "";
    if (busy === this.busy && text === this.thinking) return;
    const structural = busy !== this.busy;
    this.busy = busy;
    this.thinking = text;
    if (this.visible && structural) this._update();
  }

  handleKey(e) {
    if (!this.visible || e.target.closest("input, textarea")) return false;
    if (e.key === "f" || e.key === "F") this.fit(true);
    else if (e.key === "+" || e.key === "=") this._zoomBy(1.2);
    else if (e.key === "-") this._zoomBy(1 / 1.2);
    else if (e.key === "0") this._zoomTo(1);
    else if (e.key === "Escape" && this.selected) this._closeCard();
    else if (e.key === "n" || e.key === "N") this.nextQuestion();
    else return false;
    return true;
  }

  /** Fly to the next question that waits for an answer and open it: round
   *  the sky clockwise from the one open now, inner rings first. */
  nextQuestion() {
    const open = [...this.stars.values()].filter((s) => !s.leaving && s.item.kind === "question");
    if (!open.length) return;
    const angle = (s) => (Math.atan2(s.ty, s.tx) + Math.PI * 2.5) % (Math.PI * 2);
    open.sort((a, b) => a.depth - b.depth || angle(a) - angle(b));
    const i = open.findIndex((s) => s.id === this.selected);
    this._openCard(open[(i + 1) % open.length].id);
  }

  // ---------- structure (what hangs off what) ----------
  _statusOf(n) {
    if (n.type === "question") return n.status === "open" ? "open" : "done";
    if (n.type === "edit") return n.status === "pending" ? "open" : "done";
    return null;
  }

  _build() {
    const byParent = new Map();
    for (const n of this.nodes) {
      const key = n.parentId || "root";
      if (!byParent.has(key)) byParent.set(key, []);
      byParent.get(key).push(n);
    }
    const ids = new Set(this.nodes.map((n) => n.id));
    const orphans = this.nodes.filter((n) => n.parentId && !ids.has(n.parentId) && n.type !== "chat-user" && n.type !== "chat-assistant");
    const root = { id: "root", kind: "root", data: {}, children: [] };
    const tops = [...(byParent.get("root") || []), ...orphans].filter((n) => n.type === "question" || n.type === "edit" || n.type === "summary");

    // a question about "Teknik Detaylar" hangs under that heading's star
    const sections = new Map();
    const place = (item, section) => {
      if (!section) { root.children.push(item); return; }
      if (!sections.has(section)) {
        const group = { id: `sec:${section}`, kind: "section", data: { name: section, open: 0, done: 0 }, children: [] };
        sections.set(section, group);
        root.children.push(group);
      }
      sections.get(section).children.push(item);
    };

    const makeItem = (n, ancestors = new Set()) => {
      if (ancestors.has(n.id)) return null; // survive a damaged imported tree
      const item = { id: n.id, kind: n.type === "question" && n.status !== "open" ? "resolved" : n.type, data: n, children: [] };
      if (n.type === "question") {
        const kids = byParent.get(n.id) || [];
        const msgs = kids.filter((k) => k.type === "chat-user" || k.type === "chat-assistant");
        if (msgs.length) item.children.push({ id: `thread:${n.id}`, kind: "thread", data: { question: n, messages: msgs }, children: [] });
        for (const s of kids.filter((k) => k.type === "summary")) item.children.push({ id: s.id, kind: "summary", data: s, children: [] });
        const nextAncestors = new Set(ancestors);
        nextAncestors.add(n.id);
        for (const child of kids.filter((k) => k.type === "question")) {
          const branch = makeItem(child, nextAncestors);
          if (branch) item.children.push(branch);
        }
      }
      const st = this._statusOf(n);
      const visibleChild = item.children.some((child) => child.data?.type === "question");
      if (this.filter !== "all" && st && st !== this.filter && !visibleChild) return null;
      return item;
    };

    for (const n of tops) {
      const item = makeItem(n);
      if (!item) continue;
      const st = this._statusOf(n);
      place(item, n.section || "");
      if (n.section) {
        const group = sections.get(n.section).data;
        if (st === "done") group.done++; else if (st === "open") group.open++;
      }
    }
    if (this.busy) root.children.push({ id: "__ghost", kind: "ghost", data: {}, children: [] });
    return root;
  }

  _stats() {
    let open = 0, done = 0, edits = 0, msgs = 0;
    for (const n of this.nodes) {
      if (n.type === "question") n.status === "open" ? open++ : done++;
      else if (n.type === "edit") edits++;
      else if (n.type.startsWith("chat-")) msgs++;
    }
    return { open, done, edits, msgs };
  }

  /** A star's colour and whether it waits for the writer. */
  _look(item) {
    const n = item.data || {};
    if (item.kind === "question") return { tone: TONE[questionKind(n).tone] || TONE.question, waiting: true };
    if (item.kind === "resolved") return { tone: n.status === "dismissed" ? "#8a97a8" : TONE.resolved, waiting: false };
    if (item.kind === "edit") return { tone: TONE.edit, waiting: n.status === "pending" };
    if (item.kind === "summary") return { tone: TONE.summary, waiting: n.status === "pending" };
    return { tone: TONE[item.kind] || TONE.question, waiting: false };
  }

  /** What the hover tooltip says a star is: a short kind, in the star's colour. */
  _kindLabel(item) {
    const n = item.data || {};
    if (item.kind === "question") return `${questionKind(n).label} · cevap bekliyor`;
    if (item.kind === "resolved") return n.status === "dismissed" ? "Rotadan çıkarıldı" : `${questionKind(n).label} · çözüldü`;
    return { root: "Not", section: "Bölüm", edit: "Düzenleme önerisi", thread: "Sohbet",
             summary: n.status === "pending" ? "Nota eklensin mi?" : "Nota eklendi", ghost: "Asistan okuyor" }[item.kind] || "";
  }

  /** The words a star carries in its tooltip. */
  _label(item) {
    const n = item.data || {};
    if (item.kind === "root") return this.name || "Not";
    if (item.kind === "section") return n.name || "Bölüm";
    if (item.kind === "ghost") return this.thinking ? `Okuyor: ${this.thinking}` : "Asistan okuyor…";
    if (item.kind === "thread") {
      const last = n.messages?.[n.messages.length - 1];
      return `${n.messages?.length || 0} mesaj${last ? ` · son: ${String(last.text || "").replace(/\s+/g, " ").trim()}` : ""}`;
    }
    if (item.kind === "edit") return `Düzenleme: ${n.replacement || ""}`;
    const text = String(n.text || "").replace(/\s+/g, " ").trim();
    return text;
  }

  // ---------- the card that grows out of a star ----------
  _cardHtml(item) {
    const n = item.data || {};
    const time = n.created ? `<span class="tn-time">${formatClock(n.created)}</span>` : "";
    switch (item.kind) {
      case "root": {
        const s = this._stats();
        return `<div class="tn-eyebrow">${icon("file", 12)}Not</div>
          <div class="tn-root-title">${esc(this.name)}</div>
          <div class="tn-root-stats">
            <div><b>${s.open}</b><span>açık soru</span></div>
            <div><b>${s.edits}</b><span>düzenleme</span></div>
            <div><b>${s.done}</b><span>sonuçlandı</span></div>
          </div>
          <div class="tn-foot"><button class="btn btn-sm btn-accent" data-act="open-note">${icon("file", 13)}Notu aç</button>
            <button class="btn btn-sm" data-act="master" title="Bu notu bir yapay zekâya yaptıracak eksiksiz talimat">${icon("wand", 13)}Master prompt</button></div>`;
      }
      case "section":
        return `<div class="tn-head"><span class="tile sm t-section">${icon("hash", 13)}</span><span class="tn-kind">Bölüm</span></div>
          <div class="tn-section-name">${esc(n.name)}</div>
          <div class="tn-foot">
            ${n.open ? `<span class="chip chip-open">${n.open} açık</span>` : ""}
            ${n.done ? `<span class="chip chip-done">${n.done} sonuçlandı</span>` : ""}
            <button class="btn btn-sm" data-act="open-section">${icon("arrowRight", 13)}Bölüme git</button>
          </div>`;
      case "question":
      case "resolved": {
        const done = item.kind === "resolved";
        const doneLabel = n.status === "dismissed" ? "Rotadan çıkarıldı" : "Çözüldü";
        const [title, sub] = splitSentence(n.text);
        const hasThread = item.children.some((c) => c.kind === "thread");
        const kind = questionKind(n);
        return `<div class="tn-head"><span class="tile sm t-${done ? "resolved" : kind.tone}">${icon(done ? "check" : kind.icon, 13)}</span>
            <span class="tn-kind">${done ? doneLabel : kind.label}</span>${time}</div>
          <div class="tn-body full"><span class="lead">${esc(title)}</span>${sub ? ` <span class="rest">${esc(sub)}</span>` : ""}</div>
          <div class="tn-foot">
            <span class="chip ${n.status === "dismissed" ? "chip-rejected" : done ? "chip-done" : "chip-open"}">${done ? doneLabel : "Cevap bekliyor"}</span>
            ${done && !hasThread ? "" : `<button class="btn btn-sm ${done ? "btn-ghost" : "btn-accent"}" data-act="chat">${icon("message", 13)}${hasThread ? "Sohbete dön" : "Sohbet Et"}</button>`}
          </div>`;
      }
      case "edit": {
        const chip = { pending: ["chip-pending", "Bekliyor"], approved: ["chip-done", "Onaylandı"], rejected: ["chip-rejected", "Reddedildi"] }[n.status] || ["", ""];
        return `<div class="tn-head"><span class="tile sm t-edit">${icon("pencil", 13)}</span><span class="tn-kind">Düzenleme önerisi</span>${time}</div>
          <div class="tn-diff full"><del>${esc(n.original)}</del><ins>${esc(n.replacement)}</ins></div>
          ${n.reason ? `<div class="tn-reason">${esc(n.reason)}</div>` : ""}
          <div class="tn-foot"><span class="chip ${chip[0]}">${chip[1]}</span>
            ${n.status === "pending" ? `<button class="btn btn-sm btn-accent" data-act="approve">${icon("check", 13)}Onayla</button><button class="btn btn-sm" data-act="reject">Reddet</button>` : ""}
          </div>`;
      }
      case "thread": {
        const msgs = n.messages || [];
        return `<div class="tn-head"><span class="tile sm t-chat">${icon("message", 13)}</span><span class="tn-kind">Sohbet</span>
            <span class="tn-time">${msgs.length} mesaj</span></div>
          <div class="tn-thread full">
            ${msgs.map((m) => `<div class="tn-msg ${m.type === "chat-user" ? "me" : "ai"}"><b>${m.type === "chat-user" ? "Sen" : "Asistan"}</b><span>${esc(m.text)}</span></div>`).join("")}
          </div>
          <div class="tn-foot"><button class="btn btn-sm btn-ghost" data-act="chat">${icon("arrowRight", 13)}Sohbete devam</button></div>`;
      }
      case "summary": {
        const state = { pending: ["chip-pending", "Onay bekliyor"], approved: ["chip-done", "Nota eklendi"],
                        rejected: ["chip-rejected", "Eklenmedi"] }[n.status] || ["chip-done", "Nota eklendi"];
        return `<div class="tn-head"><span class="tile sm t-summary">${icon("lightbulb", 13)}</span>
            <span class="tn-kind">${n.status === "pending" ? "Nota eklensin mi?" : "Nota eklenecek metin"}</span>${time}</div>
          ${n.why ? `<div class="tn-reason">Notta dayandığı: ${esc(n.why)}</div>` : ""}
          <div class="tn-body full">${esc(n.text)}</div>
          <div class="tn-foot"><span class="chip ${state[0]}">${state[1]}</span>
            ${n.status === "pending" ? `<button class="btn btn-sm btn-accent" data-act="approve">${icon("check", 13)}Ekle</button><button class="btn btn-sm" data-act="reject">Vazgeç</button>` : ""}
          </div>`;
      }
      case "ghost":
        return `<div class="tn-head"><span class="tile sm t-question">${icon("sparkle", 13, "spin")}</span><span class="tn-kind">Asistan okuyor<span class="dots"></span></span></div>
          <div class="tn-body ghost-text">${esc(this.thinking || "Notun yeni kısmına bakıyor")}</div>`;
      default:
        return "";
    }
  }

  _openCard(id) {
    const star = this.stars.get(id);
    if (!star || id === "__ghost" && !this.thinking) return;
    this.selected = id;
    this.card.className = `cv-card tn tn-${star.item.kind === "resolved" ? "resolved" : star.item.kind}`;
    this.card.innerHTML = this._cardHtml(star.item);
    this.card.dataset.id = id;
    this.card.hidden = false;
    this.card.classList.remove("open");
    this._placeCard(true);
    void this.card.offsetWidth;                 // start from the star, then grow
    requestAnimationFrame(() => this.card.classList.add("open"));
    // bring the star in: a little left of centre, so the card has room
    const vw = this.canvas.clientWidth, vh = this.canvas.clientHeight;
    const k = Math.max(this.cam.k, 1);
    this._glideTo({ k, x: vw * 0.38 - star.x * k, y: vh * 0.5 - star.y * k });
  }

  _closeCard(instant = false) {
    if (!this.selected && this.card.hidden) return;
    this.selected = null;
    this.card.classList.remove("open");
    if (instant) { this.card.hidden = true; return; }
    clearTimeout(this._cardTimer);
    this._cardTimer = setTimeout(() => { if (!this.selected) this.card.hidden = true; }, 380);
  }

  /** Keep the card beside its star, and its growth point on the star. */
  _placeCard(force = false) {
    const star = this.selected && this.stars.get(this.selected);
    if (!star || this.card.hidden) return;
    const vw = this.canvas.clientWidth, vh = this.canvas.clientHeight;
    const sx = star.x * this.cam.k + this.cam.x, sy = star.y * this.cam.k + this.cam.y;
    const w = this.card.offsetWidth || 300, h = this.card.offsetHeight || 160;
    const gap = 26 + star.r * this.cam.k;
    let left = sx + gap;
    if (left + w > vw - 16) left = sx - gap - w;
    left = Math.max(16, Math.min(left, vw - w - 16));
    const top = Math.max(76, Math.min(sy - h / 2, vh - h - 16));
    if (force || Math.abs(left - (this._cardLeft || 0)) > 0.5 || Math.abs(top - (this._cardTop || 0)) > 0.5) {
      this._cardLeft = left;
      this._cardTop = top;
      this.card.style.left = `${left}px`;
      this.card.style.top = `${top}px`;
      this.card.style.transformOrigin = `${sx - left}px ${sy - top}px`;
    }
    this._cardAnchor = { sx, sy, left, top, w, h };
  }

  // ---------- the sky ----------
  _makeSky() {
    const rnd = seeded(7);
    const stars = [];
    for (let i = 0; i < 320; i++) {
      stars.push({ x: rnd(), y: rnd(), r: 0.35 + rnd() * rnd() * 1.5, a: 0.25 + rnd() * 0.6,
                   phase: rnd() * Math.PI * 2, speed: 0.4 + rnd() * 1.6, depth: 0.04 + rnd() * 0.12,
                   tint: rnd() < 0.15 ? "#ffe8c2" : rnd() < 0.3 ? "#cfe3ff" : "#ffffff" });
    }
    const nebulae = [
      { x: -0.25, y: -0.2, r: 0.75, c: "rgba(72, 196, 170, 0.10)" },
      { x: 0.35, y: 0.25, r: 0.65, c: "rgba(129, 120, 255, 0.10)" },
      { x: 0.05, y: 0.45, r: 0.5, c: "rgba(255, 143, 200, 0.05)" },
    ];
    return { stars, nebulae, meteor: null, nextMeteor: 8 + Math.random() * 10, band: null };
  }

  /** The Milky Way: a soft diagonal band of countless faint stars with a dark
   *  lane of dust down its middle. Drawn once per size, then only moved. */
  _makeBand(w, h) {
    const W = Math.ceil(w * 1.35), H = Math.ceil(h * 1.35), scale = Math.min(1.5, this._dpr);
    const c = document.createElement("canvas");
    c.width = Math.round(W * scale);
    c.height = Math.round(H * scale);
    const g = c.getContext("2d");
    g.scale(scale, scale);
    const rnd = seeded(21);
    const len = Math.hypot(W, H), thick = Math.min(W, H) * 0.2;
    g.translate(W / 2, H / 2);
    g.rotate(-0.5);
    const hues = ["150, 140, 255", "110, 220, 200", "255, 196, 226", "200, 215, 255"];
    for (let i = 0; i < 34; i++) {
      const x = (rnd() - 0.5) * len, y = gauss(rnd) * thick * 0.35, r = thick * (0.45 + rnd() * 0.8);
      const glow = g.createRadialGradient(x, y, 0, x, y, r);
      const hue = hues[Math.floor(rnd() * hues.length)];
      glow.addColorStop(0, `rgba(${hue}, 0.07)`);
      glow.addColorStop(1, `rgba(${hue}, 0)`);
      g.fillStyle = glow;
      g.fillRect(x - r, y - r, r * 2, r * 2);
    }
    for (let i = 0; i < 3200; i++) {
      const x = (rnd() - 0.5) * len, y = gauss(rnd) * thick * 0.4, big = rnd() < 0.06;
      g.globalAlpha = 0.1 + rnd() * (big ? 0.7 : 0.4);
      g.fillStyle = rnd() < 0.18 ? "#ffe6c8" : rnd() < 0.3 ? "#cfe0ff" : "#f2f5ff";
      g.beginPath();
      g.arc(x, y, big ? 0.9 + rnd() * 0.6 : 0.35 + rnd() * 0.45, 0, Math.PI * 2);
      g.fill();
    }
    g.globalAlpha = 1;
    for (let i = 0; i < 26; i++) {
      const x = (rnd() - 0.5) * len * 0.9, y = gauss(rnd) * thick * 0.07, r = thick * (0.12 + rnd() * 0.22);
      const dust = g.createRadialGradient(x, y, 0, x, y, r);
      dust.addColorStop(0, "rgba(5, 8, 20, 0.34)");
      dust.addColorStop(1, "rgba(5, 8, 20, 0)");
      g.fillStyle = dust;
      g.fillRect(x - r, y - r, r * 2, r * 2);
    }
    return { canvas: c, w, h, W, H };
  }

  _drawSky(ctx, w, h, t, still) {
    const g = ctx.createLinearGradient(0, 0, 0, h);
    g.addColorStop(0, "#060a18");
    g.addColorStop(1, "#0b1224");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, h);
    const size = Math.max(w, h);
    for (const n of this.sky.nebulae) {
      const cx = w / 2 + n.x * size + this.cam.x * 0.08, cy = h / 2 + n.y * size + this.cam.y * 0.08;
      const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, n.r * size);
      grad.addColorStop(0, n.c);
      grad.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, w, h);
    }
    // the Milky Way sits furthest back and moves least
    if (!this.sky.band || this.sky.band.w !== w || this.sky.band.h !== h) this.sky.band = this._makeBand(w, h);
    const band = this.sky.band, room = { x: (band.W - w) / 2, y: (band.H - h) / 2 };
    const bx = Math.max(-room.x, Math.min(room.x, this.cam.x * 0.03)), by = Math.max(-room.y, Math.min(room.y, this.cam.y * 0.03));
    ctx.globalAlpha = 0.9 - this._focusMix * 0.35;
    ctx.drawImage(band.canvas, -room.x + bx, -room.y + by, band.W, band.H);
    ctx.globalAlpha = 1;
    for (const s of this.sky.stars) {
      // a little parallax: the far sky moves less than the constellation
      const x = ((s.x * w + this.cam.x * s.depth) % w + w) % w;
      const y = ((s.y * h + this.cam.y * s.depth) % h + h) % h;
      const twinkle = still ? 1 : 0.65 + 0.35 * Math.sin(t * s.speed + s.phase);
      ctx.globalAlpha = s.a * twinkle;
      ctx.fillStyle = s.tint;
      ctx.beginPath();
      ctx.arc(x, y, s.r, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
    // now and then a shooting star, never while the writer holds a star
    if (!still) {
      const m = this.sky.meteor;
      if (!m && t > this.sky.nextMeteor && !this._drag) {
        this.sky.meteor = { x: Math.random() * w * 0.7 + w * 0.15, y: Math.random() * h * 0.3, born: t,
                            dx: 380 + Math.random() * 180, dy: 150 + Math.random() * 90 };
      } else if (m) {
        const p = (t - m.born) / 0.9;
        if (p >= 1) { this.sky.meteor = null; this.sky.nextMeteor = t + 14 + Math.random() * 16; }
        else {
          const hx = m.x + m.dx * p, hy = m.y + m.dy * p;
          const tail = ctx.createLinearGradient(hx, hy, hx - m.dx * 0.25, hy - m.dy * 0.25);
          tail.addColorStop(0, `rgba(255,255,255,${0.75 * (1 - p)})`);
          tail.addColorStop(1, "rgba(255,255,255,0)");
          ctx.strokeStyle = tail;
          ctx.lineWidth = 1.4;
          ctx.beginPath();
          ctx.moveTo(hx, hy);
          ctx.lineTo(hx - m.dx * 0.25, hy - m.dy * 0.25);
          ctx.stroke();
        }
      }
    }
  }

  // ---------- update: the tree -> stars and strings ----------
  _update() {
    const tree = this._build();
    const s = this._stats();
    this.host.querySelector(".tv-stats").innerHTML = `
      <span class="stat"><i class="star glow"></i><b>${s.open}</b> cevap bekliyor</span>
      <span class="stat"><i class="star cool"></i><b>${s.edits}</b> düzenleme</span>
      <span class="stat"><i class="star pink"></i><b>${s.msgs}</b> mesaj</span>
      <span class="stat"><i class="star calm"></i><b>${s.done}</b> sonuçlandı</span>`;
    this.host.querySelector(".tv-empty").hidden = this.nodes.length > 0 || this.busy;

    // where each star belongs: rays from the centre, each ray's share of the
    // circle by how many leaves hang off it
    const leaves = (it) => (it.children.length ? it.children.reduce((sum, c) => sum + leaves(c), 0) : 1);
    const wanted = new Set();
    const now = this._time;
    const still = reducedMotion();
    const place = (item, parent, depth, a0, a1) => {
      wanted.add(item.id);
      const angle = (a0 + a1) / 2;
      const radius = depth === 0 ? 0 : RING_1 + (depth - 1) * RING_STEP;
      const tx = Math.cos(angle) * radius, ty = Math.sin(angle) * radius;
      let star = this.stars.get(item.id);
      const look = this._look(item);
      if (!star) {
        const from = parent ? this.stars.get(parent.id) : null;
        const jitter = () => (Math.random() - 0.5) * 8;
        // first sight of a note: the centre lights, then each ring in a sweep,
        // every star just as its string reaches it; later arrivals come at once
        const sweep = ((angle + Math.PI / 2) / (Math.PI * 2) + 1) % 1;
        const born = still ? now - 1 : this._fresh ? now + 0.25 + depth * IGNITE_STEP + (depth ? sweep * 0.28 : 0) : now + (from ? 0.26 : 0);
        star = { id: item.id, x: this._fresh || !from ? tx + jitter() : from.x + jitter(), y: this._fresh || !from ? ty + jitter() : from.y + jitter(),
                 vx: 0, vy: 0, born, phase: Math.random() * Math.PI * 2, lit: 1, hov: 0 };
        if (!this._fresh && from) { star.vx = Math.cos(angle) * 4; star.vy = Math.sin(angle) * 4; }
        this.stars.set(item.id, star);
      }
      Object.assign(star, { item, parentId: parent?.id || null, depth, tx, ty, tone: look.tone, waiting: look.waiting,
                            r: RADIUS[item.kind] || 5, leaving: false, label: this._label(item) });
      if (parent) {
        let string = this.strings.get(item.id);
        const rest = Math.hypot(tx - (parent.tx ?? 0), ty - (parent.ty ?? 0)) || RING_STEP;
        if (!string) {
          const a = this.stars.get(parent.id);
          // the string is drawn out from the parent and arrives as the star lights
          string = { id: item.id, points: [], drawFrom: still ? 0 : Math.max(a.born, now) + 0.04, drawTo: still ? 0 : star.born };
          for (let j = 1; j <= ROPE_JOINTS; j++) {
            const f = j / (ROPE_JOINTS + 1);
            const px = a.x + (star.x - a.x) * f, py = a.y + (star.y - a.y) * f;
            string.points.push({ x: px, y: py, px, py });
          }
          this.strings.set(item.id, string);
        }
        Object.assign(string, { a: parent.id, b: item.id, rest, tone: look.tone, waiting: look.waiting, leaving: false });
      }
      item.tx = tx;
      item.ty = ty;
      const total = leaves(item);
      let start = a0;
      // deeper rays keep to their parent's direction, like the drawing
      const spread = depth === 0 ? a1 - a0 : Math.min(a1 - a0, Math.PI * 0.9 / Math.max(1, depth));
      const offset = (a1 - a0 - spread) / 2;
      start = a0 + offset;
      for (const child of item.children) {
        const span = spread * leaves(child) / total;
        place(child, item, depth + 1, start, start + span);
        start += span;
      }
    };
    place(tree, null, 0, -Math.PI / 2, Math.PI * 1.5);

    for (const [id, star] of this.stars) if (!wanted.has(id)) { star.leaving = true; star.leftAt ??= now; }
    for (const [id, string] of this.strings) if (!wanted.has(id)) { string.leaving = true; }

    if (this._celebrate) {
      const star = this.stars.get(this._celebrate);
      if (star) this._burst(star);
      this._celebrate = null;
    }
    if (this.selected) {
      const star = this.stars.get(this.selected);
      if (!star || star.leaving) this._closeCard();
      else { this.card.innerHTML = this._cardHtml(star.item); this._placeCard(true); }
    }
    if (this._fresh && this.canvas.clientWidth) {
      this._fresh = false;
      this.fit(false);
    }
    this._start();
  }

  _burst(star) {
    for (let i = 0; i < 22; i++) {
      const a = Math.random() * Math.PI * 2, v = 40 + Math.random() * 90;
      this.bursts.push({ x: star.x, y: star.y, vx: Math.cos(a) * v, vy: Math.sin(a) * v, born: this._time, tone: star.tone });
    }
  }

  // ---------- physics ----------
  _step(dt) {
    const stars = [...this.stars.values()].filter((s) => !s.leaving);
    // springs to where each star belongs, and between parent and child
    for (const s of stars) {
      if (s === this._drag?.star) continue;
      const home = s.depth === 0 ? 0.08 : 0.012;
      s.vx += (s.tx - s.x) * home;
      s.vy += (s.ty - s.y) * home;
    }
    for (const string of this.strings.values()) {
      if (string.leaving) continue;
      const a = this.stars.get(string.a), b = this.stars.get(string.b);
      if (!a || !b) continue;
      const dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy) || 1;
      const f = (d - string.rest) * 0.02;
      const fx = dx / d * f, fy = dy / d * f;
      if (b !== this._drag?.star) { b.vx -= fx; b.vy -= fy; }
      // a parent is heavier than its child: it is pulled, but less
      if (a !== this._drag?.star && a.depth > 0) { a.vx += fx * 0.45; a.vy += fy * 0.45; }
    }
    // stars keep their distance
    for (let i = 0; i < stars.length; i++) {
      for (let j = i + 1; j < stars.length; j++) {
        const a = stars[i], b = stars[j];
        const dx = b.x - a.x, dy = b.y - a.y, d2 = dx * dx + dy * dy;
        if (d2 > 140 * 140 || d2 < 0.01) continue;
        const d = Math.sqrt(d2), f = Math.min(3, 900 / d2);
        const fx = dx / d * f, fy = dy / d * f;
        if (a !== this._drag?.star && a.depth > 0) { a.vx -= fx; a.vy -= fy; }
        if (b !== this._drag?.star && b.depth > 0) { b.vx += fx; b.vy += fy; }
      }
    }
    for (const s of stars) {
      if (s === this._drag?.star) continue;
      s.vx *= 0.86;
      s.vy *= 0.86;
      s.x += s.vx;
      s.y += s.vy;
    }
    // the strings: jointed points, pinned to their stars, a little slack
    for (const string of this.strings.values()) {
      const a = this.stars.get(string.a), b = this.stars.get(string.b);
      if (!a || !b) continue;
      for (const p of string.points) {
        const vx = (p.x - p.px) * 0.92, vy = (p.y - p.py) * 0.92;
        p.px = p.x; p.py = p.y;
        p.x += vx;
        p.y += vy + 0.06;                       // a whisper of weight: strings hang, not bars
      }
      const chain = [a, ...string.points, b];
      const seg = Math.hypot(b.x - a.x, b.y - a.y) / (ROPE_JOINTS + 1) * 1.03;
      for (let iter = 0; iter < 3; iter++) {
        for (let j = 0; j < chain.length - 1; j++) {
          const p = chain[j], q = chain[j + 1];
          const dx = q.x - p.x, dy = q.y - p.y, d = Math.hypot(dx, dy) || 1;
          const diff = (d - seg) / d;
          const pinP = j === 0, pinQ = j + 1 === chain.length - 1;
          if (pinP && pinQ) continue;
          const share = pinP || pinQ ? 1 : 0.5;
          if (!pinP) { p.x += dx * diff * share; p.y += dy * diff * share; }
          if (!pinQ) { q.x -= dx * diff * share; q.y -= dy * diff * share; }
        }
      }
    }
    for (const bit of this.bursts) {
      bit.x += bit.vx * dt;
      bit.y += bit.vy * dt;
      bit.vx *= 0.94;
      bit.vy *= 0.94;
    }
    this.bursts = this.bursts.filter((bit) => this._time - bit.born < 1.1);
    for (const [id, star] of this.stars) if (star.leaving && this._time - star.leftAt > 0.5) { this.stars.delete(id); this.strings.delete(id); }
    for (const [id, string] of this.strings) if (string.leaving && !this.stars.has(id)) this.strings.delete(id);
  }

  // ---------- drawing ----------
  /** The open card's star, its ancestors back to the note, and its children:
   *  the part of the sky that stays bright while a card is open. */
  _focus() {
    if (!this.selected || !this.stars.has(this.selected)) return null;
    const path = new Set();
    for (let id = this.selected; id; id = this.stars.get(id)?.parentId) path.add(id);
    const lit = new Set(path);
    for (const s of this.stars.values()) if (s.parentId === this.selected) lit.add(s.id);
    return { path, lit };
  }

  /** The first `f` of a string's length, as points. */
  _partial(chain, f) {
    const lens = [];
    let total = 0;
    for (let j = 1; j < chain.length; j++) {
      const d = Math.hypot(chain[j].x - chain[j - 1].x, chain[j].y - chain[j - 1].y);
      lens.push(d);
      total += d;
    }
    let left = total * f;
    const out = [chain[0]];
    for (let j = 1; j < chain.length; j++) {
      if (left >= lens[j - 1]) { out.push(chain[j]); left -= lens[j - 1]; continue; }
      const g = lens[j - 1] ? left / lens[j - 1] : 0;
      out.push({ x: chain[j - 1].x + (chain[j].x - chain[j - 1].x) * g, y: chain[j - 1].y + (chain[j].y - chain[j - 1].y) * g });
      break;
    }
    return out;
  }

  _draw(t) {
    const ctx = this.ctx, w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    const still = reducedMotion();
    const dt = Math.min(0.1, t - (this._drawnAt ?? t));
    this._drawnAt = t;
    const ease = still ? 1 : Math.min(1, dt * 7);
    const focus = this._focus();
    this._focusMix += ((focus ? 1 : 0) - this._focusMix) * ease;
    for (const s of this.stars.values()) {
      s.lit += ((!focus || focus.lit.has(s.id) ? 1 : DIM) - s.lit) * ease;
      s.hov += ((s.id === this.hovered ? 1 : 0) - s.hov) * Math.min(1, dt * 12);
    }
    ctx.setTransform(this._dpr, 0, 0, this._dpr, 0, 0);
    this._drawSky(ctx, w, h, t, still);
    ctx.save();
    ctx.translate(this.cam.x, this.cam.y);
    ctx.scale(this.cam.k, this.cam.k);
    const k = this.cam.k;

    // strings
    for (const string of this.strings.values()) {
      const a = this.stars.get(string.a), b = this.stars.get(string.b);
      if (!a || !b) continue;
      const drawn = string.drawTo > string.drawFrom ? (t - string.drawFrom) / (string.drawTo - string.drawFrom) : 1;
      const fade = string.leaving ? Math.max(0, 1 - (t - (b.leftAt ?? t)) / 0.5) : 1;
      if (drawn <= 0 || fade <= 0) continue;
      const onPath = focus && focus.path.has(a.id) && focus.path.has(b.id);
      const lit = Math.min(a.lit, b.lit);
      let chain = [a, ...string.points, b];
      // the string from the note to the open card burns brighter
      const base = onPath ? 0.9 : string.waiting ? 0.55 : 0.32;
      const grad = ctx.createLinearGradient(a.x, a.y, b.x, b.y);
      grad.addColorStop(0, rgba(a.depth === 0 ? string.tone : a.tone, 1));
      grad.addColorStop(1, rgba(string.tone, 1));
      ctx.globalAlpha = base * lit * fade;
      ctx.strokeStyle = grad;
      ctx.lineWidth = (onPath ? 2.1 : string.waiting ? 1.5 : 1.1) / Math.sqrt(k);
      ctx.beginPath();
      if (drawn < 1) {
        // still being drawn: a straight run to a bright moving tip
        chain = this._partial(chain, easeOut(drawn));
        ctx.moveTo(chain[0].x, chain[0].y);
        for (const p of chain.slice(1)) ctx.lineTo(p.x, p.y);
        ctx.stroke();
        const tip = chain[chain.length - 1];
        const head = ctx.createRadialGradient(tip.x, tip.y, 0, tip.x, tip.y, 9);
        head.addColorStop(0, "rgba(255,255,255,0.95)");
        head.addColorStop(0.3, rgba(string.tone, 0.8));
        head.addColorStop(1, rgba(string.tone, 0));
        ctx.globalAlpha = fade;
        ctx.fillStyle = head;
        ctx.beginPath();
        ctx.arc(tip.x, tip.y, 9, 0, Math.PI * 2);
        ctx.fill();
        continue;
      }
      ctx.moveTo(chain[0].x, chain[0].y);
      for (let j = 1; j < chain.length - 1; j++) {
        const mx = (chain[j].x + chain[j + 1].x) / 2, my = (chain[j].y + chain[j + 1].y) / 2;
        ctx.quadraticCurveTo(chain[j].x, chain[j].y, mx, my);
      }
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
      // a spark of light running out along a string that waits for an answer,
      // and down the lit path to an open card
      if ((string.waiting || onPath) && !still && lit > 0.5) {
        const p = ((t * 0.42 + (b.phase / (Math.PI * 2))) % 1);
        const idx = p * (chain.length - 1), j = Math.floor(idx), f = idx - j;
        const x = chain[j].x + (chain[j + 1].x - chain[j].x) * f, y = chain[j].y + (chain[j + 1].y - chain[j].y) * f;
        const glow = ctx.createRadialGradient(x, y, 0, x, y, 7);
        glow.addColorStop(0, rgba(onPath ? "#ffffff" : string.tone, 0.9 * lit * fade));
        glow.addColorStop(1, rgba(string.tone, 0));
        ctx.globalAlpha = 1;
        ctx.fillStyle = glow;
        ctx.beginPath();
        ctx.arc(x, y, 7, 0, Math.PI * 2);
        ctx.fill();
      }
    }
    ctx.globalAlpha = 1;

    // stars
    const order = [...this.stars.values()].sort((p, q) => q.depth - p.depth);
    for (const s of order) {
      const grow = this._appear(s, t);
      const fade = (s.leaving ? Math.max(0, 1 - (t - s.leftAt) / 0.5) : 1) * s.lit;
      if (grow <= 0 || fade <= 0.01) continue;
      const r = s.r * (0.3 + 0.7 * easeOutBack(grow)) * (1 + 0.22 * s.hov);
      // just lit: a flash and a ring thrown outward
      const age = t - s.born;
      if (!still && age >= 0 && age < 0.9) {
        const p = age / 0.9;
        const flash = ctx.createRadialGradient(s.x, s.y, 0, s.x, s.y, r * (3 + p * 5));
        flash.addColorStop(0, `rgba(255,255,255,${0.55 * (1 - p) * fade})`);
        flash.addColorStop(1, "rgba(255,255,255,0)");
        ctx.fillStyle = flash;
        ctx.beginPath();
        ctx.arc(s.x, s.y, r * (3 + p * 5), 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = rgba(s.tone, 0.7 * (1 - p) * fade);
        ctx.lineWidth = 1.5 / k;
        ctx.beginPath();
        ctx.arc(s.x, s.y, r + easeOut(p) * r * 6, 0, Math.PI * 2);
        ctx.stroke();
      }
      const pulse = s.waiting && !still ? 0.5 + 0.5 * Math.sin(t * 2.4 + s.phase) : 0.5;
      const glowR = r * (s.waiting ? 4.2 + pulse * 1.8 : s.depth === 0 ? 5 : 2.6);
      const glow = ctx.createRadialGradient(s.x, s.y, 0, s.x, s.y, glowR);
      glow.addColorStop(0, rgba(s.tone, (s.waiting ? 0.55 + pulse * 0.3 : s.depth === 0 ? 0.5 : 0.22) * fade));
      glow.addColorStop(1, rgba(s.tone, 0));
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(s.x, s.y, glowR, 0, Math.PI * 2);
      ctx.fill();
      // a waiting star sends out a slow ring, like a ping
      if (s.waiting && !still) {
        const p = ((t + s.phase) % 2.6) / 2.6;
        ctx.strokeStyle = rgba(s.tone, 0.45 * (1 - p) * fade);
        ctx.lineWidth = 1.2 / k;
        ctx.beginPath();
        ctx.arc(s.x, s.y, r + p * r * 4.5, 0, Math.PI * 2);
        ctx.stroke();
      }
      // the core: white at the heart, the star's colour at the rim
      const core = ctx.createRadialGradient(s.x, s.y, 0, s.x, s.y, r);
      core.addColorStop(0, `rgba(255,255,255,${fade})`);
      core.addColorStop(0.45, rgba(s.tone, fade));
      core.addColorStop(1, rgba(s.tone, (s.waiting || s.depth === 0 ? 0.85 : 0.55) * fade));
      ctx.fillStyle = core;
      ctx.beginPath();
      ctx.arc(s.x, s.y, r, 0, Math.PI * 2);
      ctx.fill();
      if (s.waiting || s.depth === 0) {
        // a four-pointed glint, turning slowly
        const len = r * (s.depth === 0 ? 3.2 : 2.4) * (0.8 + pulse * 0.4), rot = still ? 0 : t * 0.25 + s.phase;
        ctx.strokeStyle = `rgba(255,255,255,${0.55 * fade})`;
        ctx.lineWidth = 1 / k;
        ctx.beginPath();
        for (let q = 0; q < 2; q++) {
          const a = rot + q * Math.PI / 2;
          ctx.moveTo(s.x - Math.cos(a) * len, s.y - Math.sin(a) * len);
          ctx.lineTo(s.x + Math.cos(a) * len, s.y + Math.sin(a) * len);
        }
        ctx.stroke();
      }
      if (s.depth === 0) {
        // the note: a double ring, as in the drawing
        ctx.strokeStyle = rgba(s.tone, 0.55 * fade);
        ctx.lineWidth = 1.3 / k;
        for (const f of [1.55, 2.05]) { ctx.beginPath(); ctx.arc(s.x, s.y, r * f, 0, Math.PI * 2); ctx.stroke(); }
        if (this.busy && !still) {
          ctx.strokeStyle = rgba(s.tone, 0.8);
          ctx.beginPath();
          ctx.arc(s.x, s.y, r * 2.5, t * 2, t * 2 + Math.PI * 0.6);
          ctx.stroke();
        }
      }
      if (s.id === this.selected || s.id === this.hovered) {
        ctx.strokeStyle = `rgba(255,255,255,${s.id === this.selected ? 0.9 : 0.5})`;
        ctx.lineWidth = 1.4 / k;
        ctx.beginPath();
        ctx.arc(s.x, s.y, r + 5 / k + 2, 0, Math.PI * 2);
        ctx.stroke();
      }
    }
    for (const bit of this.bursts) {
      const p = (t - bit.born) / 1.1;
      ctx.fillStyle = rgba(bit.tone, Math.max(0, 1 - p));
      ctx.beginPath();
      ctx.arc(bit.x, bit.y, 2 * (1 - p) + 0.5, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();

    // with a card open the edges of the sky close in a little
    if (this._focusMix > 0.01) {
      const v = ctx.createRadialGradient(w / 2, h / 2, Math.min(w, h) * 0.3, w / 2, h / 2, Math.max(w, h) * 0.75);
      v.addColorStop(0, "rgba(2,4,12,0)");
      v.addColorStop(1, `rgba(2,4,12,${0.55 * this._focusMix})`);
      ctx.fillStyle = v;
      ctx.fillRect(0, 0, w, h);
    }

    // a faint thread from the open card back to its star
    const anchor = this.selected && !this.card.hidden && this._cardAnchor;
    if (anchor && this.card.classList.contains("open")) {
      const { sx, sy, left, top, w: cw, h: ch } = anchor;
      const ex = sx < left ? left : sx > left + cw ? left + cw : sx;
      const ey = Math.max(top + 14, Math.min(sy, top + ch - 14));
      ctx.strokeStyle = "rgba(220,235,255,0.35)";
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 4]);
      ctx.beginPath();
      ctx.moveTo(sx, sy);
      ctx.lineTo(ex, ey);
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  /** The tooltip: only for the star under the pointer, never while it is
   *  being dragged or while its card is open. */
  _placeTip() {
    const star = this.hovered && !this._drag?.moved && this.hovered !== this.selected && this.stars.get(this.hovered);
    if (!star || star.leaving) {
      if (this._tipFor) { this.tip.classList.remove("show"); this._tipFor = null; }
      return;
    }
    if (this._tipFor !== star.id) {
      this._tipFor = star.id;
      let text = star.label || "";
      if (text.length > 180) text = `${text.slice(0, 179).trimEnd()}…`;
      this.tip.querySelector("b").textContent = this._kindLabel(star.item);
      this.tip.querySelector("span").textContent = text;
      this.tip.style.setProperty("--tone", star.tone);
      this.tip.classList.add("show");
    }
    const vw = this.canvas.clientWidth, vh = this.canvas.clientHeight;
    const sx = star.x * this.cam.k + this.cam.x, sy = star.y * this.cam.k + this.cam.y;
    const w = this.tip.offsetWidth, h = this.tip.offsetHeight;
    const gap = star.r * this.cam.k + 16;
    let left = sx + gap;
    if (left + w > vw - 12) left = sx - gap - w;
    const top = Math.max(72, Math.min(sy - h / 2, vh - h - 12));
    this.tip.style.transform = `translate(${Math.round(Math.max(12, left))}px, ${Math.round(top)}px)`;
  }

  _appear(s, t) {
    return Math.max(0, Math.min(1, (t - s.born) / 0.6));
  }

  // ---------- the loop ----------
  _start() {
    if (!this.visible || this._raf) return;
    this._last = performance.now();
    const frame = (now) => {
      if (!this.visible) { this._raf = 0; return; }
      const dt = Math.min(0.1, (now - this._last) / 1000);
      this._last = now;
      this._time += dt;
      this._acc += dt;
      while (this._acc >= FIXED_DT) { this._step(FIXED_DT); this._acc -= FIXED_DT; }
      this._camStep(dt);
      this._placeCard();
      this._placeTip();
      this._draw(this._time);
      this._raf = requestAnimationFrame(frame);
    };
    this._raf = requestAnimationFrame(frame);
  }

  _resize() {
    const w = this.host.clientWidth, h = this.host.clientHeight;
    if (!w || !h) return;
    this._dpr = Math.min(2, window.devicePixelRatio || 1);
    this.canvas.width = Math.round(w * this._dpr);
    this.canvas.height = Math.round(h * this._dpr);
    this.canvas.style.width = `${w}px`;
    this.canvas.style.height = `${h}px`;
    if (this._fresh && this.stars.size) { this._fresh = false; this.fit(false); }
    else if (this._autoFit && !this.selected) this.fit(false);
  }

  // ---------- camera ----------
  _setZoomLabel() {
    this.host.querySelector(".zoom-val").textContent = `${Math.round(this.cam.k * 100)}%`;
  }

  _glideTo(target, ms = 560) {
    this._coast = null;
    this.glide = { from: { ...this.cam }, to: target, start: performance.now(), ms };
  }

  _camStep(dt = FIXED_DT) {
    // a pan let go with speed keeps sliding, slowing like a puck on ice
    if (this._coast) {
      const f = dt * 60;
      this.cam = { ...this.cam, x: this.cam.x + this._coast.vx * f, y: this.cam.y + this._coast.vy * f };
      const decay = Math.pow(0.93, f);
      this._coast.vx *= decay;
      this._coast.vy *= decay;
      if (Math.hypot(this._coast.vx, this._coast.vy) < 0.06) this._coast = null;
    }
    if (!this.glide) return;
    const p = easeOut((performance.now() - this.glide.start) / this.glide.ms);
    const { from, to } = this.glide;
    this.cam = { x: from.x + (to.x - from.x) * p, y: from.y + (to.y - from.y) * p, k: from.k + (to.k - from.k) * p };
    this._setZoomLabel();
    if (p >= 1) this.glide = null;
  }

  fit(animate = true) {
    const live = [...this.stars.values()].filter((s) => !s.leaving);
    const vw = this.canvas.clientWidth, vh = this.canvas.clientHeight;
    if (!live.length || !vw || !vh) return;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const s of live) {
      const x = s.tx ?? s.x, y = s.ty ?? s.y;
      minX = Math.min(minX, x); maxX = Math.max(maxX, x); minY = Math.min(minY, y); maxY = Math.max(maxY, y);
    }
    const padX = 150, padTop = 110, padBottom = 90;
    const k = Math.min(1.3, Math.max(MIN_K, Math.min((vw - padX * 2) / Math.max(1, maxX - minX), (vh - padTop - padBottom) / Math.max(1, maxY - minY))));
    const target = { k, x: vw / 2 - ((minX + maxX) / 2) * k, y: padTop + (vh - padTop - padBottom) / 2 - ((minY + maxY) / 2) * k };
    if (animate) this._glideTo(target);
    else { this.cam = target; this.glide = null; this._setZoomLabel(); }
    this._autoFit = true;               // until the writer moves the sky themselves
  }

  _zoomTo(k, cx = this.canvas.clientWidth / 2, cy = this.canvas.clientHeight / 2, animate = true) {
    const nk = Math.min(MAX_K, Math.max(MIN_K, k));
    const { x, y, k: ok } = this.glide ? this.glide.to : this.cam;
    const target = { k: nk, x: cx - (cx - x) * (nk / ok), y: cy - (cy - y) * (nk / ok) };
    if (animate) this._glideTo(target, 320);
    else { this.cam = target; this.glide = null; this._setZoomLabel(); }
  }

  _zoomBy(f) { this._zoomTo((this.glide ? this.glide.to.k : this.cam.k) * f); }

  // ---------- pointer ----------
  _starAt(px, py) {
    let best = null, bestD = Infinity;
    for (const s of this.stars.values()) {
      if (s.leaving) continue;
      const sx = s.x * this.cam.k + this.cam.x, sy = s.y * this.cam.k + this.cam.y;
      const d = Math.hypot(px - sx, py - sy);
      const reach = Math.max(12, s.r * this.cam.k + 8);
      if (d < reach && d < bestD) { best = s; bestD = d; }
    }
    return best;
  }

  _wirePointer() {
    const c = this.canvas;
    const local = (e) => { const r = c.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
    c.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      const [px, py] = local(e);
      const star = this._starAt(px, py);
      c.setPointerCapture(e.pointerId);
      this.glide = null;
      this._coast = null;
      this._autoFit = false;
      if (star) {
        this._drag = { star, sx: px, sy: py, moved: false, lastX: px, lastY: py, lastT: performance.now(), vx: 0, vy: 0 };
      } else {
        this._pan = { sx: px, sy: py, x: this.cam.x, y: this.cam.y, moved: false, lastX: px, lastY: py, lastT: performance.now(), vx: 0, vy: 0 };
        c.classList.add("panning");
      }
    });
    c.addEventListener("pointermove", (e) => {
      const [px, py] = local(e);
      if (this._drag) {
        const d = this._drag;
        if (!d.moved && Math.hypot(px - d.sx, py - d.sy) > 4) { d.moved = true; c.classList.add("dragging"); }
        if (!d.moved) return;
        const now = performance.now(), dtMs = Math.max(1, now - d.lastT);
        const wx = (px - this.cam.x) / this.cam.k, wy = (py - this.cam.y) / this.cam.k;
        // world velocity of the hand, per frame, for the fling on release
        d.vx = ((px - d.lastX) / this.cam.k) / dtMs * 16.7;
        d.vy = ((py - d.lastY) / this.cam.k) / dtMs * 16.7;
        d.lastX = px; d.lastY = py; d.lastT = now;
        d.star.x = wx;
        d.star.y = wy;
        return;
      }
      if (this._pan) {
        const p = this._pan;
        if (Math.hypot(px - p.sx, py - p.sy) > 3) p.moved = true;
        const now = performance.now(), dtMs = Math.max(1, now - p.lastT);
        // the hand's speed, smoothed, in pixels per frame
        p.vx = p.vx * 0.5 + (px - p.lastX) / dtMs * 16.7 * 0.5;
        p.vy = p.vy * 0.5 + (py - p.lastY) / dtMs * 16.7 * 0.5;
        p.lastX = px; p.lastY = py; p.lastT = now;
        this.cam = { ...this.cam, x: p.x + px - p.sx, y: p.y + py - p.sy };
        return;
      }
      const star = this._starAt(px, py);
      const id = star ? star.id : null;
      if (id !== this.hovered) {
        this.hovered = id;
        c.classList.toggle("over-star", Boolean(id));
      }
    });
    const end = (e) => {
      if (this._drag) {
        const d = this._drag;
        this._drag = null;
        c.classList.remove("dragging");
        if (d.moved) {
          // let go: it keeps the hand's speed, then its strings bring it home
          d.star.vx = Math.max(-40, Math.min(40, d.vx));
          d.star.vy = Math.max(-40, Math.min(40, d.vy));
        } else if (e.type === "pointerup") {
          if (this.selected === d.star.id) this._closeCard(); else this._openCard(d.star.id);
        }
        return;
      }
      if (this._pan) {
        const p = this._pan;
        this._pan = null;
        c.classList.remove("panning");
        if (!p.moved && e.type === "pointerup") this._closeCard();
        // let go while still moving: glide on (not if the hand had already stopped)
        else if (p.moved && performance.now() - p.lastT < 90 && !reducedMotion() && Math.hypot(p.vx, p.vy) > 1.2) {
          this._coast = { vx: Math.max(-60, Math.min(60, p.vx)), vy: Math.max(-60, Math.min(60, p.vy)) };
        }
      }
    };
    c.addEventListener("pointerup", end);
    c.addEventListener("pointercancel", end);
    c.addEventListener("pointerleave", () => { if (!this._drag && !this._pan) { this.hovered = null; c.classList.remove("over-star"); } });
    c.addEventListener("dblclick", (e) => { const [px, py] = local(e); if (!this._starAt(px, py)) this.fit(true); });
    c.addEventListener("wheel", (e) => {
      e.preventDefault();
      this._coast = null;
      this._autoFit = false;
      const [px, py] = local(e);
      const factor = Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0016));
      this._zoomTo((this.glide ? this.glide.to.k : this.cam.k) * factor, px, py, false);
      this._setZoomLabel();
    }, { passive: false });
  }

  // ---------- buttons ----------
  _click(e) {
    const act = e.target.closest("[data-act]")?.dataset.act;
    if (act === "zoom-in") return this._zoomBy(1.2);
    if (act === "zoom-out") return this._zoomBy(1 / 1.2);
    if (act === "fit") return this.fit(true);
    if (act === "next") return this.nextQuestion();
    if (act === "ask") return this.h.ask(this.path);
    const seg = e.target.closest("[data-filter]");
    if (seg) {
      this.filter = seg.dataset.filter;
      this.host.querySelectorAll("[data-filter]").forEach((b) => b.classList.toggle("on", b === seg));
      this._update();
      setTimeout(() => this.fit(true), 80);
      return;
    }
    if (!e.target.closest(".cv-card") || !act) return;
    const id = this.card.dataset.id;
    const questionId = id.startsWith("thread:") ? id.slice(7) : id;
    if (act === "chat") return this.h.chat(this.path, questionId);
    if (act === "approve" || act === "reject") return this.h.decide(this.path, id, act);
    if (act === "open-note") return this.h.openNote(this.path);
    if (act === "master") return this.h.master?.(this.path);
    if (act === "open-section") return this.h.openSection(this.path, id.slice(4));
  }
}
