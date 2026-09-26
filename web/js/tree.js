// "Fikir Ağacı" — the note's idea tree as a readable, animated mind-map.
//
// The note is the root on the left; questions and edit suggestions branch
// off it; each question's chat collapses into a single thread card and its
// "Nota Yaz" results hang off the question. Cards are HTML (so text wraps
// and stays selectable), branches are SVG curves. New cards grow out of their
// parent, branches draw themselves in, open questions have a slow current
// flowing along their branch, and while the model is reading the note a
// ghost card shows what it is thinking.
import { api } from "./api.js";
import { icon } from "./icons.js";
import { esc, formatClock, splitSentence } from "./util.js";

const ROOT_W = 256;
const SECTION_W = 210;
const NODE_W = 272;
const COL_GAP = 96;
const ROW_GAP = 14;
const FAMILY_GAP = 12;
const MIN_K = 0.25;
const MAX_K = 1.8;
const SVG_NS = "http://www.w3.org/2000/svg";

const TONE = {
  question: "question",
  resolved: "resolved",
  edit: "edit",
  thread: "chat",
  summary: "summary",
  ghost: "question",
  section: "section",
};

// what a question is for — the label and colour it carries through the UI
const FAR_ZOOM = 0.62;   // below this the cards are unreadable anyway
const DOT = 15;          // the point a card collapses into

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
    this.expanded = new Set();
    this.cards = new Map();
    this.edges = new Map();
    this.view = { x: 60, y: 0, k: 1 };
    this.visible = false;
    this._firstLayout = true;
    this._loadSeq = 0;

    host.innerHTML = `
      <div class="tv-viewport">
        <div class="tv-world"><svg class="tv-edges" width="1" height="1"></svg><div class="tv-cards"></div></div>
      </div>
      <div class="tv-bar tv-top">
        <div class="tv-title">
          <span class="tile sm t-question">${icon("tree", 14)}</span>
          <div><div class="t">Fikir Ağacı</div><div class="s tv-note"></div></div>
        </div>
        <div class="tv-stats"></div>
        <div class="tv-controls">
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
        <span><i class="dot depth"></i>Derinleştirme</span><span><i class="dot idea"></i>Alternatif</span>
        <span><i class="dot effect"></i>Sonuç</span><span><i class="dot inspire"></i>İlham</span>
        <span><i class="dot edit"></i>Düzenleme</span><span><i class="dot resolved"></i>Çözüldü</span>
      </div>
      <div class="tv-hint">Sürükle: kaydır · Tekerlek: yakınlaş · Çift tık: sığdır</div>
      <div class="tv-empty" hidden>
        <span class="tile t-question">${icon("sprout", 22)}</span>
        <h3>Henüz bir dal yok</h3>
        <p>Yazmaya devam ettikçe asistanın soruları, önerileri ve sohbetlerin burada dallanarak büyüyecek.</p>
        <button class="btn btn-accent btn-sm" data-act="ask">${icon("sparkles", 14)}Asistana şimdi sor</button>
      </div>`;

    this.viewport = host.querySelector(".tv-viewport");
    this.world = host.querySelector(".tv-world");
    this.svg = host.querySelector(".tv-edges");
    this.cardLayer = host.querySelector(".tv-cards");

    host.addEventListener("click", (e) => this._click(e));
    this._wirePanZoom();
    new ResizeObserver(() => { if (this.visible && this._firstLayout === false && this._autoFit) this.fit(false); }).observe(this.viewport);
  }

  // ---------- public ----------
  async show(path, name) {
    this.visible = true;
    this.host.hidden = false;
    this.name = name;
    this.host.querySelector(".tv-note").textContent = `${name}.md`;
    if (path === this.path) {
      this._update();
      return;
    }
    this.path = path;
    this.nodes = [];
    this.selected = null;
    this.expanded.clear();
    this._clearAll();
    this._firstLayout = true;
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
    if (!this.visible) return;
    if (structural) this._update();
    else this._refreshGhost();
  }

  handleKey(e) {
    if (!this.visible || e.target.closest("input, textarea")) return false;
    if (e.key === "f" || e.key === "F") this.fit(true);
    else if (e.key === "+" || e.key === "=") this._zoomBy(1.2);
    else if (e.key === "-") this._zoomBy(1 / 1.2);
    else if (e.key === "0") this._zoomTo(1);
    else if (e.key === "Escape" && this.selected) { this.selected = null; this.expanded.clear(); this._update(); }
    else return false;
    return true;
  }

  // ---------- structure ----------
  _statusOf(n) {
    if (n.type === "question") return n.status === "resolved" ? "done" : "open";
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

    const root = { id: "root", kind: "root", children: [] };
    const tops = [...(byParent.get("root") || []), ...orphans].filter((n) => n.type === "question" || n.type === "edit" || n.type === "summary");

    // a question about "Teknik Detaylar" belongs under that heading, not next to
    // an unrelated question about another part of the note
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
      const item = { id: n.id, kind: n.type === "question" && n.status === "resolved" ? "resolved" : n.type, data: n, children: [] };
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
      if (n.type === "question") n.status === "resolved" ? done++ : open++;
      else if (n.type === "edit") edits++;
      else if (n.type.startsWith("chat-")) msgs++;
    }
    return { open, done, edits, msgs };
  }

  // ---------- cards ----------
  /** One line of text for a node, for the tooltip a dot shows. */
  _plain(item) {
    const n = item.data || {};
    if (item.kind === "root") return this.path ? this.path.replace(/\.md$/i, "") : "Not";
    if (item.kind === "section") return `Bölüm: ${n.name || ""}`;
    const text = (n.text || item.name || "").replace(/\s+/g, " ").trim();
    const prefix = item.kind === "question" ? `${questionKind(n).label}: `
      : item.kind === "summary" ? "Nota eklenme önerisi: "
      : item.kind === "edit" ? "Düzenleme: " : "";
    return (prefix + text).slice(0, 160);
  }

  _cardHtml(item) {
    const n = item.data || {};
    const time = n.created ? `<span class="tn-time">${formatClock(n.created)}</span>` : "";
    const expanded = this.expanded.has(item.id);
    switch (item.kind) {
      case "root": {
        const s = this._stats();
        return `<div class="tn-eyebrow">${icon("file", 12)}Not</div>
          <div class="tn-root-title">${esc(this.name)}</div>
          <div class="tn-root-stats">
            <div><b>${s.open}</b><span>açık soru</span></div>
            <div><b>${s.edits}</b><span>düzenleme</span></div>
            <div><b>${s.done}</b><span>çözüldü</span></div>
          </div><i class="port-out"></i>`;
      }
      case "section":
        return `<div class="tn-head"><span class="tile sm t-section">${icon("hash", 13)}</span>
            <span class="tn-kind">Bölüm</span></div>
          <div class="tn-section-name">${esc(n.name)}</div>
          <div class="tn-foot">
            ${n.open ? `<span class="chip chip-open">${n.open} açık</span>` : ""}
            ${n.done ? `<span class="chip chip-done">${n.done} sonuçlandı</span>` : ""}
          </div><i class="port-in"></i><i class="port-out"></i>`;
      case "question":
      case "resolved": {
        const done = item.kind === "resolved";
        const [title, sub] = splitSentence(n.text);
        const hasThread = item.children.some((c) => c.kind === "thread");
        const kind = questionKind(n);
        return `<div class="tn-head"><span class="tile sm t-${done ? "resolved" : kind.tone}">${icon(done ? "check" : kind.icon, 13)}</span>
            <span class="tn-kind">${done ? "Çözüldü" : kind.label}</span>${time}</div>
          <div class="tn-body${expanded ? " full" : ""}"><span class="lead">${esc(title)}</span>${sub ? ` <span class="rest">${esc(sub)}</span>` : ""}</div>
          <div class="tn-foot">
            <span class="chip ${done ? "chip-done" : "chip-open"}">${done ? "Çözüldü" : "Açık"}</span>
            ${done && !hasThread ? "" : `<button class="btn btn-sm ${done ? "btn-ghost" : "btn-accent"}" data-act="chat">${icon("message", 13)}${hasThread ? "Sohbete dön" : "Sohbet Et"}</button>`}
          </div><i class="port-in"></i>${item.children.length ? '<i class="port-out"></i>' : ""}`;
      }
      case "edit": {
        const chip = { pending: ["chip-pending", "Bekliyor"], approved: ["chip-done", "Onaylandı"], rejected: ["chip-rejected", "Reddedildi"] }[n.status] || ["", ""];
        return `<div class="tn-head"><span class="tile sm t-edit">${icon("pencil", 13)}</span><span class="tn-kind">Düzenleme önerisi</span>${time}</div>
          <div class="tn-diff${expanded ? " full" : ""}"><del>${esc(n.original)}</del><ins>${esc(n.replacement)}</ins></div>
          ${n.reason && expanded ? `<div class="tn-reason">${esc(n.reason)}</div>` : ""}
          <div class="tn-foot"><span class="chip ${chip[0]}">${chip[1]}</span>
            ${n.status === "pending" ? `<button class="btn btn-sm btn-accent" data-act="approve">${icon("check", 13)}Onayla</button><button class="btn btn-sm" data-act="reject">Reddet</button>` : ""}
          </div><i class="port-in"></i>`;
      }
      case "thread": {
        const msgs = n.messages;
        const shown = expanded ? msgs : msgs.slice(-2);
        return `<div class="tn-head"><span class="tile sm t-chat">${icon("message", 13)}</span><span class="tn-kind">Sohbet</span>
            <span class="tn-time">${msgs.length} mesaj</span></div>
          <div class="tn-thread${expanded ? " full" : ""}">
            ${!expanded && msgs.length > 2 ? `<div class="tn-more">+${msgs.length - 2} önceki mesaj</div>` : ""}
            ${shown.map((m) => `<div class="tn-msg ${m.type === "chat-user" ? "me" : "ai"}"><b>${m.type === "chat-user" ? "Sen" : "Asistan"}</b><span>${esc(m.text)}</span></div>`).join("")}
          </div>
          <div class="tn-foot"><button class="btn btn-sm btn-ghost" data-act="chat">${icon("arrowRight", 13)}Sohbete devam</button></div>
          <i class="port-in"></i>`;
      }
      case "summary": {
        const state = { pending: ["chip-pending", "Onay bekliyor"], approved: ["chip-done", "Nota eklendi"],
                        rejected: ["chip-rejected", "Eklenmedi"] }[n.status] || ["chip-done", "Nota eklendi"];
        return `<div class="tn-head"><span class="tile sm t-summary">${icon("lightbulb", 13)}</span>
            <span class="tn-kind">${n.status === "pending" ? "Nota eklensin mi?" : "Nota eklenecek metin"}</span>${time}</div>
          <div class="tn-body${expanded ? " full" : ""}">${esc(n.text)}</div>
          <div class="tn-foot"><span class="chip ${state[0]}">${state[1]}</span>
            ${n.status === "pending" ? `<button class="btn btn-sm btn-accent" data-act="approve">${icon("check", 13)}Ekle</button><button class="btn btn-sm" data-act="reject">Vazgeç</button>` : ""}
          </div><i class="port-in"></i>`;
      }
      case "ghost":
        return `<div class="tn-head"><span class="tile sm t-question">${icon("sparkle", 13, "spin")}</span><span class="tn-kind">Asistan okuyor<span class="dots"></span></span></div>
          <div class="tn-body ghost-text">${esc(this.thinking || "Notun yeni kısmına bakıyor")}</div>
          <div class="tn-shimmer"></div><i class="port-in"></i>`;
      default:
        return "";
    }
  }

  _signature(item) {
    const extra = item.kind === "root" ? JSON.stringify(this._stats()) + this.name : "";
    const data = item.kind === "ghost" ? "" : JSON.stringify(item.data);
    return `${item.kind}|${this.expanded.has(item.id)}|${item.children.length}|${data}|${extra}`;
  }

  _ensureCard(item, parentCard) {
    let card = this.cards.get(item.id);
    const sig = this._signature(item);
    if (!card) {
      const el = document.createElement("div");
      el.className = `tn tn-${item.kind}`;
      el.dataset.id = item.id;
      el.style.width = `${{ root: ROOT_W, section: SECTION_W }[item.kind] || NODE_W}px`;
      el.style.setProperty("--n", this.cards.size % 12);
      this.cardLayer.append(el);
      card = { el, x: parentCard?.x ?? 0, y: parentCard?.y ?? 0, h: 0, sig: "", entering: true, parentId: parentCard?.id };
      this.cards.set(item.id, card);
    }
    card.kind = item.kind;
    card.id = item.id;
    if (card.sig !== sig) {
      const kindClass = item.kind === "question" ? ` k-${questionKind(item.data).tone}` : "";
      card.el.className = `tn tn-${item.kind}${kindClass}${this.selected === item.id ? " selected" : ""}${this.busy && item.kind === "root" ? " busy" : ""}`;
      card.el.innerHTML = this._cardHtml(item);
      card.el.title = this._plain(item);        // the whole label of a far-view dot
      card.sig = sig;
    }
    card.el.classList.toggle("selected", this.selected === item.id);
    card.el.classList.toggle("busy", item.kind === "root" && this.busy);
    card.w = { root: ROOT_W, section: SECTION_W }[item.kind] || NODE_W;
    return card;
  }

  _refreshGhost() {
    const ghost = this.cards.get("__ghost");
    const text = ghost?.el.querySelector(".ghost-text");
    if (text) text.textContent = this.thinking || "Notun yeni kısmına bakıyor";
  }

  // ---------- layout + render ----------
  _update() {
    const tree = this._build();
    const stats = this._stats();
    this.host.querySelector(".tv-stats").innerHTML = `
      <span class="stat"><i class="dot question"></i><b>${stats.open}</b> açık</span>
      <span class="stat"><i class="dot edit"></i><b>${stats.edits}</b> düzenleme</span>
      <span class="stat"><i class="dot chat"></i><b>${stats.msgs}</b> mesaj</span>
      <span class="stat"><i class="dot resolved"></i><b>${stats.done}</b> çözüldü</span>`;
    this.host.querySelector(".tv-empty").hidden = this.nodes.length > 0 || this.busy;

    // 1. create/update cards, remember which are still wanted
    const wanted = new Set();
    const flat = [];
    const visit = (item, parent, depth) => {
      const card = this._ensureCard(item, parent ? this.cards.get(parent.id) : null);
      wanted.add(item.id);
      flat.push({ item, card, parent, depth });
      item.card = card;
      for (const c of item.children) visit(c, item, depth + 1);
    };
    visit(tree, null, 0);

    // 2. remove cards and edges that are gone
    for (const [id, card] of this.cards) {
      if (wanted.has(id)) continue;
      this.cards.delete(id);
      card.el.classList.add("leaving");
      setTimeout(() => card.el.remove(), 320);
    }
    for (const [id, edge] of this.edges) {
      if (wanted.has(id)) continue;
      this.edges.delete(id);
      edge.g.classList.add("leaving");
      setTimeout(() => edge.g.remove(), 320);
    }

    // 3. measure and lay out
    for (const { card } of flat) card.h = card.el.offsetHeight;
    const widths = [];
    for (const { card, depth } of flat) widths[depth] = Math.max(widths[depth] || 0, card.w);
    const columnX = [0];
    for (let d = 1; d < widths.length; d++) columnX[d] = columnX[d - 1] + (widths[d - 1] || NODE_W) + COL_GAP;
    const place = (item, depth, top) => {
      const c = item.card;
      c.x = columnX[depth] ?? 0;
      if (!item.children.length) { c.y = top; return top + c.h; }
      let y = top, bottom = top;
      for (const child of item.children) {
        bottom = place(child, depth + 1, y);
        y = bottom + ROW_GAP + (child.children.length ? FAMILY_GAP : 0);
      }
      const first = item.children[0].card, last = item.children[item.children.length - 1].card;
      c.y = (first.y + first.h / 2 + last.y + last.h / 2) / 2 - c.h / 2;
      if (c.y < top) {
        const d = top - c.y;
        const shift = (it) => { for (const ch of it.children) { ch.card.y += d; shift(ch); } };
        shift(item);
        c.y = top;
        bottom += d;
      }
      return Math.max(bottom, c.y + c.h);
    };
    place(tree, 0, 0);
    const rootCard = tree.card;
    const dy = -rootCard.y - rootCard.h / 2;
    for (const { card } of flat) card.y += dy;

    // 4. apply positions (new cards grow out of their parent)
    const initial = this._firstLayout;
    const newcomers = [];
    const grown = [];
    flat.forEach(({ card, parent, depth }, i) => {
      const el = card.el;
      const target = `translate(${card.x}px, ${card.y}px)`;
      if (card.entering) {
        card.entering = false;
        if (initial) {
          el.style.transition = "none";
          el.style.transform = target;
          el.style.opacity = "0";
          el.style.setProperty("--delay", `${Math.min(depth * 90 + i * 18, 700)}ms`);
          newcomers.push(() => { el.style.transition = ""; el.classList.add("appear"); el.style.opacity = ""; });
        } else {
          const from = parent ? parent.card : card;
          grown.push(card);
          el.style.transition = "none";
          el.style.transform = `translate(${from.x + (from.w || NODE_W) - 60}px, ${from.y + (from.h - card.h) / 2}px) scale(0.6)`;
          el.style.opacity = "0";
          // read x/y when the frame runs, not now: another layout pass (e.g. the
          // ghost card leaving) can land before this callback and move the card
          newcomers.push(() => {
            el.style.transition = "";
            el.style.transform = `translate(${card.x}px, ${card.y}px)`;
            el.style.opacity = "";
          });
        }
      } else {
        el.style.transform = target;
      }
    });
    if (newcomers.length) {
      void this.cardLayer.offsetHeight; // commit start positions before transitioning
      requestAnimationFrame(() => newcomers.forEach((fn) => fn()));
    }

    // 5. edges
    for (const { item, card, parent, depth } of flat) {
      if (!parent) continue;
      this._drawEdge(item, card, parent.card, initial ? depth : -1);
    }

    if (this._celebrate) {
      const el = this.cards.get(this._celebrate)?.el;
      if (el) { el.classList.remove("celebrate"); void el.offsetWidth; el.classList.add("celebrate"); }
      this._celebrate = null;
    }

    if (initial) {
      this._firstLayout = false;
      this.fit(false);
    } else if (grown.length) {
      this._revealNewest(grown);
    }
    this._applyView();
  }

  /** Recompute every edge in place — used when the view crosses into (or out
   *  of) the far view, where the endpoints move from card edges to dots. */
  _redrawEdges() {
    for (const edge of this.edges.values()) {
      if (!edge.ends) continue;
      const d = this._edgePath(edge.ends.card, edge.ends.parentCard);
      edge.base.style.d = `path("${d}")`;
      edge.flow.style.d = `path("${d}")`;
    }
  }

  _edgePath(card, parentCard) {
    const w = this.far ? DOT : parentCard.w;
    const ph = this.far ? DOT : parentCard.h;
    const ch = this.far ? DOT : card.h;
    const x1 = parentCard.x + w, y1 = parentCard.y + ph / 2;
    const x2 = card.x, y2 = card.y + ch / 2;
    const dx = Math.max(40, (x2 - x1) * 0.55);
    return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
  }

  _drawEdge(item, card, parentCard, initialDepth) {
    const d = this._edgePath(card, parentCard);
    const tone = item.kind === "question" ? questionKind(item.data).tone : (TONE[item.kind] || "question");
    const flowing = item.kind === "question" || item.kind === "ghost";
    let edge = this.edges.get(item.id);
    if (!edge) {
      const g = document.createElementNS(SVG_NS, "g");
      const base = document.createElementNS(SVG_NS, "path");
      base.setAttribute("class", "edge");
      base.setAttribute("pathLength", "1");
      const flow = document.createElementNS(SVG_NS, "path");
      flow.setAttribute("class", "edge-flow");
      g.append(base, flow);
      this.svg.append(g);
      edge = { g, base, flow };
      this.edges.set(item.id, edge);
      edge.ends = { card, parentCard };
      for (const p of [base, flow]) { p.style.transition = "none"; p.style.d = `path("${d}")`; }
      g.setAttribute("class", `edge-g tone-${tone}${flowing ? " flowing" : ""}${item.kind === "ghost" ? " ghost" : ""}`);
      base.style.strokeDashoffset = "1";
      void base.getBoundingClientRect();
      const delay = initialDepth >= 0 ? `${initialDepth * 90 + 120}ms` : "180ms";
      requestAnimationFrame(() => {
        base.style.transition = `stroke-dashoffset 0.75s var(--ease-out) ${delay}, d 0.65s var(--ease-out), stroke 0.4s`;
        flow.style.transition = "d 0.65s var(--ease-out)";
        base.style.strokeDashoffset = "0";
      });
    } else {
      edge.g.setAttribute("class", `edge-g tone-${tone}${flowing ? " flowing" : ""}${item.kind === "ghost" ? " ghost" : ""}`);
      edge.ends = { card, parentCard };
      edge.base.style.d = `path("${d}")`;
      edge.flow.style.d = `path("${d}")`;
    }
  }

  _clearAll() {
    this.cardLayer.innerHTML = "";
    this.svg.innerHTML = "";
    this.cards.clear();
    this.edges.clear();
  }

  // ---------- view transform ----------
  _applyView(glide = false) {
    const { x, y, k } = this.view;
    this.world.classList.toggle("glide", glide);
    this.viewport.classList.toggle("glide", glide);
    this.world.style.transform = `translate(${x}px, ${y}px) scale(${k})`;
    const grid = 26 * k;
    this.viewport.style.backgroundSize = `${grid}px ${grid}px, 100% 100%`;
    this.viewport.style.backgroundPosition = `${x}px ${y}px, 0 0`;
    this.host.querySelector(".zoom-val").textContent = `${Math.round(k * 100)}%`;
    const far = k < FAR_ZOOM;
    if (far !== this.far) {
      this.far = far;
      this.host.classList.toggle("far", far);
      this._redrawEdges();     // the threads now meet the dots, not the cards
    }
    if (glide) {
      clearTimeout(this._glideTimer);
      this._glideTimer = setTimeout(() => { this.world.classList.remove("glide"); this.viewport.classList.remove("glide"); }, 560);
    }
  }

  _bounds(cards = [...this.cards.values()]) {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const c of cards) {
      if (c.el.classList.contains("leaving")) continue;
      minX = Math.min(minX, c.x); minY = Math.min(minY, c.y);
      maxX = Math.max(maxX, c.x + c.w); maxY = Math.max(maxY, c.y + c.h);
    }
    return minX === Infinity ? null : { minX, minY, maxX, maxY };
  }

  fit(animate = true) {
    const b = this._bounds();
    const vw = this.viewport.clientWidth, vh = this.viewport.clientHeight;
    if (!b || !vw || !vh) return;
    const padX = 70, padTop = 96, padBottom = 70;
    const k = Math.min(1, Math.max(MIN_K, Math.min((vw - padX * 2) / (b.maxX - b.minX), (vh - padTop - padBottom) / (b.maxY - b.minY))));
    this.view = {
      k,
      x: (vw - (b.maxX - b.minX) * k) / 2 - b.minX * k,
      y: padTop + (vh - padTop - padBottom - (b.maxY - b.minY) * k) / 2 - b.minY * k,
    };
    this._autoFit = true;
    this._applyView(animate);
  }

  _revealNewest(cards) {
    const b = this._bounds(cards);
    if (!b) return;
    const { x, y, k } = this.view;
    const vw = this.viewport.clientWidth, vh = this.viewport.clientHeight;
    const left = b.minX * k + x, right = b.maxX * k + x, top = b.minY * k + y, bottom = b.maxY * k + y;
    let nx = x, ny = y;
    if (right > vw - 40) nx -= right - (vw - 40);
    if (left < 40) nx += 40 - left;
    if (bottom > vh - 50) ny -= bottom - (vh - 50);
    if (top < 90) ny += 90 - top;
    if (nx !== x || ny !== y) {
      this.view = { x: nx, y: ny, k };
      this._applyView(true);
    }
  }

  _zoomTo(k, cx = this.viewport.clientWidth / 2, cy = this.viewport.clientHeight / 2, glide = true) {
    const nk = Math.min(MAX_K, Math.max(MIN_K, k));
    const { x, y, k: ok } = this.view;
    this.view = { k: nk, x: cx - (cx - x) * (nk / ok), y: cy - (cy - y) * (nk / ok) };
    this._autoFit = false;
    this._applyView(glide);
  }

  _zoomBy(f) { this._zoomTo(this.view.k * f); }

  _wirePanZoom() {
    let drag = null;
    this.viewport.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 || e.target.closest(".tn")) return;
      drag = { sx: e.clientX, sy: e.clientY, x: this.view.x, y: this.view.y, moved: false };
      this.viewport.setPointerCapture(e.pointerId);
      this.viewport.classList.add("panning");
    });
    this.viewport.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const dx = e.clientX - drag.sx, dy = e.clientY - drag.sy;
      if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
      this.view = { ...this.view, x: drag.x + dx, y: drag.y + dy };
      this._autoFit = false;
      this._applyView();
    });
    const end = () => {
      if (!drag) return;
      if (!drag.moved && (this.selected || this.expanded.size)) {
        this.selected = null;
        this.expanded.clear();
        this._update();
      }
      drag = null;
      this.viewport.classList.remove("panning");
    };
    this.viewport.addEventListener("pointerup", end);
    this.viewport.addEventListener("pointercancel", end);
    this.viewport.addEventListener("dblclick", (e) => { if (!e.target.closest(".tn")) this.fit(true); });
    this.viewport.addEventListener("wheel", (e) => {
      e.preventDefault();
      const r = this.viewport.getBoundingClientRect();
      const factor = Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0016));
      this._zoomTo(this.view.k * factor, e.clientX - r.left, e.clientY - r.top, false);
    }, { passive: false });
  }

  // ---------- interaction ----------
  _click(e) {
    const act = e.target.closest("[data-act]")?.dataset.act;
    const cardEl = e.target.closest(".tn");
    if (this.far) {
      const dot = e.target.closest(".tn");
      if (dot) {
        // come back down to the point you pointed at
        const card = this.cards.get(dot.dataset.id);
        if (card) {
          const r = this.viewport.getBoundingClientRect();
          this.view.x = r.width / 2 - (card.x + DOT / 2) * 1;
          this.view.y = r.height / 2 - (card.y + DOT / 2) * 1;
          this.selected = dot.dataset.id;
          this._zoomTo(1);
          return;
        }
      }
    }
    if (act === "zoom-in") return this._zoomBy(1.2);
    if (act === "zoom-out") return this._zoomBy(1 / 1.2);
    if (act === "fit") return this.fit(true);
    if (act === "ask") return this.h.ask(this.path);
    const seg = e.target.closest("[data-filter]");
    if (seg) {
      this.filter = seg.dataset.filter;
      this.host.querySelectorAll("[data-filter]").forEach((b) => b.classList.toggle("on", b === seg));
      this._update();
      setTimeout(() => this.fit(true), 60);
      return;
    }
    if (!cardEl) return;
    const id = cardEl.dataset.id;
    const questionId = id.startsWith("thread:") ? id.slice(7) : id;
    if (act === "chat") return this.h.chat(this.path, questionId);
    if (act === "approve" || act === "reject") return this.h.decide(this.path, id, act);
    if (id === "root") return this.h.openNote(this.path);
    if (id.startsWith("sec:")) return this.h.openSection(this.path, id.slice(4));
    if (id === "__ghost") return;
    if (window.getSelection()?.toString()) return;
    if (this.expanded.has(id)) { this.expanded.delete(id); this.selected = null; } else { this.expanded.add(id); this.selected = id; }
    this._update();
  }
}
