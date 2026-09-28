// Main window: wires the vault sidebar, note tabs, editor/preview, idea tree,
// history panel and chat to the local server.
import { api, clientId, connectEvents } from "./api.js";
import { ChatDrawer } from "./chat.js";
import { desktopCall, desktopHud, desktopReady, isDesktop, openExternal } from "./desktop.js";
import { DirectionDialog } from "./direction.js";
import { confirmDialog, openMenu, promptDialog, shortcutsDialog } from "./dialogs.js";
import { MarkdownEditor } from "./editor.js";
import { HistoryPanel } from "./history.js";
import { LadderPanel } from "./ladder.js";
import { MasterPromptDialog } from "./masterprompt.js";
import { HudCard } from "./hudcard.js";
import { icon, logo } from "./icons.js";
import { Palette } from "./palette.js";
import { ResearchPanel } from "./research.js";
import { SettingsDialog } from "./settings.js";
import { Sidebar } from "./sidebar.js";
import { THEMES, openThemePicker, themeOf } from "./themes.js";
import { IdeaTree } from "./tree.js";
import { $, debounce, esc, mod, relativeSaved, toast, wordCount } from "./util.js";
import { LANGUAGES, lang, startI18n } from "./i18n.js";
import { openLanguagePicker, syncLanguage } from "./langpicker.js";

// the dictionary is in before anything is drawn: no flash of Turkish
await startI18n();
syncLanguage();

const SAVE_MS = 700;
// The live watch looks at natural breaks only: a pause this long, or something
// pasted in (once it has settled). The big model takes 30-55 s a pass, so what
// it finds waits quietly in the panel rather than interrupting the writing.
const LIVE_IDLE_MS = 15000;
const PASTE_MS = 1200;

const state = {
  vault: "Vault",
  tree: [],
  scripts: [],
  model: { model_up: false, endpoint: "", busy: null },
  thinking: null,
  tabs: [],
  activeId: null,
  view: "editor",
  preview: "preview",
  liveWatch: true,
  split: 0.5,
  sidebar: true,
  panel: true,
  pinned: [],
  cursor: { line: 0, col: 0, selected: 0 },
  connected: true,
};
let tabSeq = 0;
const pendingOpens = new Map();
const appearanceKey = "fikir.appearance.v1";
const focusKey = "fikir.focus.v1";
let theme = themeOf(localStorage.getItem(appearanceKey) || "light").id;
let focusMode = localStorage.getItem(focusKey) === "true";
document.documentElement.dataset.theme = theme;

const noteName = (path) => path.split("/").pop().replace(/\.md$/i, "");
const activeTab = () => state.tabs.find((t) => t.id === state.activeId) || null;
const tabByPath = (path) => state.tabs.find((t) => t.path === path) || null;
const under = (path, prefix) => path === prefix || path.startsWith(`${prefix}/`);

// ---------------------------------------------------------------- components
const sidebar = new Sidebar($("#sidebar"), {
  open: (path) => openNote(path),
  openTree: async (path) => { await openNote(path); setView("tree"); },
  newNote: (dir) => newNote(dir),
  newFolder: (dir) => newFolder(dir),
  rename: (path, name, kind) => renameItem(path, name, kind),
  trash: (path, name, kind) => trashItem(path, name, kind),
  move: (path, dir) => moveItem(path, dir),
  search: (q) => palette.open(q),
  addTag: () => addTag(),
  refresh: () => { loadTree({ prunePinned: true }); loadTags(); },
  expandedChanged: () => saveSession(),
  togglePin: (path) => togglePin(path),
});

/** Which sentences in this note came from the assistant (with your approval). */
async function loadWritten(tab) {
  try {
    const { written } = await api.get("/api/assistant/nodes", { path: tab.path });
    if (!tab.closed) tab.editor.setWritten(written || []);
  } catch { /* a note with no assistant history simply has none */ }
}

const historyPanel = new HistoryPanel($("#history"), {
  // answering from the panel writes to the note first, so the model sees what
  // is actually on the page rather than the last autosave
  beforeSend: async (path) => { const tab = tabByPath(path); if (tab) await saveTab(tab); },
  select: async (event, act) => {
    if (act === "chat") return openChat(event.path, event.node_id);
    if (act === "approve" || act === "reject") return hudAction(event.id, act);
    try {
      const tab = await openNote(event.path);
      setView("editor");
      if (event.range && (event.type === "question" || event.type === "edit")) tab.editor.flash(event.range, { reveal: true });
    } catch (err) {
      toast(err.message, "error");
    }
  },
});

const hudCard = desktopHud ? null : new HudCard($("#hudSlot"));
const ladderPanel = new LadderPanel($("#ladder"), {
  showWaiting: () => {
    if (!shown.panel) setPanel(true);
    $("#history .h-section")?.scrollIntoView({ behavior: "smooth", block: "start" });
  },
  correctDirection: (path) => direction.open(path),
  master: () => openMaster(),
  // the master prompt button lights up once the open note is ready to build
  onRender: (ladder) => $("#masterLaunch")?.classList.toggle("ready", ladder?.phase === "urun"),
});

const master = new MasterPromptDialog({
  getContent: (path) => tabByPath(path)?.editor.value ?? null,
  openNote: (path) => openNote(path),
});

function openMaster() {
  const tab = activeTab();
  master.open(tab?.path, tab?.name);
}

const direction = new DirectionDialog({
  beforeOpen: async (path) => {
    const tab = tabByPath(path);
    if (tab) {
      await saveTab(tab);
      if (tab.dirty) throw new Error("Not kaydedilemedi; önce kaydetmeyi tekrar dene.");
    }
  },
  onSaved: (path) => {
    ladderPanel.load(path);
    toast("Yeni yön kaydedildi. Sonraki sorular buna göre üretilecek.");
    const tab = tabByPath(path);
    if (tab && state.model.model_up) analyze(tab);
  },
});

const research = new ResearchPanel({
  getContent: () => activeTab()?.editor.value ?? null,
  beforeStart: async (path) => {
    const tab = tabByPath(path);
    if (!tab) throw new Error("Not artık açık değil.");
    await saveTab(tab);
    if (tab.dirty) throw new Error("Not kaydedilemedi; araştırma başlatılmadı.");
  },
});
$("#rightpanel").insertBefore(research.el, $("#history"));

const tree = new IdeaTree($("#treeView"), {
  chat: (path, nodeId) => openChat(path, nodeId),
  decide: (path, nodeId, action) => {
    const event = historyPanel.items.find((e) => e.path === path && e.node_id === nodeId
      && (e.type === "edit" || e.type === "summary"));
    if (event) hudAction(event.id, action);
    else toast("Bu öneriye ait kayıt bulunamadı.", "error");
  },
  ask: (path) => { const tab = tabByPath(path); if (tab) analyze(tab, true); },
  openNote: (path) => { openNote(path); setView("editor"); },
  openSection: (path, heading) => goToSection(path, heading),
  master: () => openMaster(),
});

/** Put the cursor on a heading in the note and flash it — used by the idea
 *  tree and by the section strip above the preview. */
async function goToSection(path, heading) {
  const tab = await openNote(path);
  setView("editor");
  let at = 0;
  for (const line of tab.editor.value.split("\n")) {
    const match = /^#{1,6}\s+(.*)$/.exec(line);
    if (match && match[1].trim() === heading) {
      tab.editor.flash([at, at + line.length], { reveal: true });
      return;
    }
    at += line.length + 1;
  }
}

const chat = new ChatDrawer({
  beforeSend: async (path) => { const tab = tabByPath(path); if (tab) await saveTab(tab); },
});

const settings = new SettingsDialog();

const palette = new Palette({
  notes: () => flatNotes(),
  open: (path) => openNote(path),
  create: (name) => newNote("", name),
  commands: () => commands(),
});

// ---------------------------------------------------------------- chrome
function buildChrome() {
  $("#brand").innerHTML = `${logo(22)}<span class="brand-name">concept trail<span class="brand-dot">.</span></span>`;
  $("#toggleSidebar").innerHTML = icon("panelLeft", 17);
  $("#togglePanel").innerHTML = icon("panelRight", 17);
  $("#globalSearch").innerHTML = `${icon("search", 15)}<span>Notlarda ara...</span><kbd>Ctrl P</kbd>`;
  $("#globalSearch").onclick = () => palette.open();
  $("#researchLaunch").innerHTML = `${icon("search", 15)}<span>Araştır</span>`;
  $("#researchLaunch").onclick = () => research.open();
  $("#masterLaunch").innerHTML = `${icon("wand", 15)}<span>Master prompt</span>`;
  $("#masterLaunch").onclick = () => openMaster();
  $("#themeBtn").onclick = () => openThemePicker($("#themeBtn"), theme, setTheme);
  $("#langBtn").innerHTML = `${icon("globe", 17)}<span class="lang-badge" translate="no">${lang.toUpperCase()}</span>`;
  $("#langBtn").onclick = () => openLanguagePicker($("#langBtn"));
  $("#focusBtn").onclick = () => setFocusMode(!focusMode);
  applyAppearance();
  $("#launchBtn").innerHTML = icon("play", 15);
  $("#settingsBtn").innerHTML = icon("settings", 16);
  $("#addTab").innerHTML = icon("plus", 15);
  $('[data-win="minimize"]').innerHTML = icon("minus", 15);
  $('[data-win="maximize"]').innerHTML = icon("square", 13);
  $('[data-win="close"]').innerHTML = icon("x", 15);
  $('[data-view="editor"]').innerHTML = `${icon("file", 14)}Editör`;
  renderViewSwitch();

  const tools = [
    ["bold", "Kalın (Ctrl+B)", (e) => e.wrap("**", "**", "kalın metin")],
    ["italic", "İtalik (Ctrl+I)", (e) => e.wrap("*", "*", "italik metin")],
    ["H1", "Başlık 1", (e) => e.heading(1)],
    ["H2", "Başlık 2", (e) => e.heading(2)],
    "sep",
    ["list", "Madde listesi", (e) => e.list("ul")],
    ["listOrdered", "Numaralı liste", (e) => e.list("ol")],
    ["listChecks", "Görev listesi", (e) => e.list("task")],
    "sep",
    ["link", "Bağlantı (Ctrl+K)", (e) => e.link()],
    ["image", "Görsel", (e) => e.image()],
    "sep",
    ["highlighter", "Vurgula", (e) => e.wrap("==", "==", "vurgulu metin")],
    ["code", "Kod (Ctrl+E)", (e) => e.code()],
    ["quote", "Alıntı", (e) => e.list("quote")],
  ];
  const bar = $("#toolbar");
  bar.innerHTML = tools.map((t, i) => {
    if (t === "sep") return '<span class="sep"></span>';
    const [name, title] = t;
    const glyph = name.startsWith("H") ? `<span class="txt">H<sub>${name[1]}</sub></span>` : icon(name, 17);
    return `<button class="icon-btn" data-tool="${i}" title="${esc(title)}">${glyph}</button>`;
  }).join("") +
    `<span class="grow"></span>
     <button class="icon-btn ask" id="askBtn" title="Asistana şimdi sor (Ctrl+Enter)">${icon("sparkles", 18)}</button>
     <button class="btn direction-launch" id="directionBtn" title="Asistanın yönünü düzelt">Rotayı düzelt</button>
     <button class="icon-btn" id="researchEditorBtn" title="Bu notu araştır">${icon("search", 17)}</button>
     <button class="icon-btn" id="previewToggle" title="Önizlemeyi aç/kapat">${icon("columns", 17)}</button>`;
  bar.addEventListener("mousedown", (e) => { if (e.target.closest("button")) e.preventDefault(); });
  bar.addEventListener("click", (e) => {
    const btn = e.target.closest("button");
    const tab = activeTab();
    if (!btn || !tab) return;
    if (btn.id === "askBtn") return analyze(tab, true);
    if (btn.id === "directionBtn") return direction.open(tab.path);
    if (btn.id === "researchEditorBtn") return research.open();
    if (btn.id === "previewToggle") return setPreview(state.preview === "hidden" ? "preview" : "hidden");
    tools[Number(btn.dataset.tool)][2](tab.editor);
  });

  $("#previewHead").innerHTML = `
    <button class="pv-tab on" data-pv="preview">${icon("eye", 15)}Önizleme</button>
    <button class="pv-tab" data-pv="source">${icon("code", 15)}Kaynak</button>
    <span class="grow"></span>
    <button class="icon-btn sm" data-pv="hidden" title="Önizlemeyi kapat">${icon("x", 14)}</button>`;
  $("#previewHead").addEventListener("click", (e) => {
    const b = e.target.closest("[data-pv]");
    if (b) setPreview(b.dataset.pv);
  });
  $("#noteIdentity").addEventListener("click", (e) => {
    if (e.target.closest("#pinNote") && activeTab()) togglePin(activeTab().path);
  });

  $("#statusbar").innerHTML = `
    <span class="item" id="stPos">Satır 1, Sütun 1</span><span class="sepv note-only"></span>
    <span class="item" id="stWords">0 kelime</span><span class="sepv note-only"></span>
    <span class="item note-only" id="stRead"></span><span class="sepv note-only"></span>
    <span class="item note-only">Markdown</span>
    <span class="grow"></span>
    <button class="item watch" id="stWatch" title="Canlı izleme: 15 saniye durduğunda ya da bir şey yapıştırdığında not sessizce incelenir. Tıklayıp aç/kapat."><span class="dot"></span><span class="lbl"></span></button>
    <span class="sepv"></span>
    <span class="item" id="stSaved"></span>
    <button class="item" id="stKeys" title="Klavye kısayolları">${icon("keyboard", 15)}</button>`;
  $("#stWatch").onclick = () => setLiveWatch(!state.liveWatch);
  $("#stKeys").onclick = shortcutsDialog;

  $("#settingsBtn").onclick = () => settings.open();
  $("#llmPill").onclick = () => { if (!state.model.chat_up) launchModel(null, 0); };
  $("#fastPill").onclick = () => { if (!state.model.fast_up) launchModel(null, 1); };
  $("#toggleSidebar").onclick = () => setSidebar(!shown.sidebar);
  $("#togglePanel").onclick = () => setPanel(!shown.panel);
  $("#launchBtn").onclick = (e) => launchModel(e);
  $("#addTab").onclick = () => newNote("");
  $("#viewSwitch").addEventListener("click", (e) => {
    const b = e.target.closest("[data-view]");
    if (b) setView(b.dataset.view);
  });

  $("#tabs").addEventListener("click", (e) => {
    const el = e.target.closest(".tab");
    if (!el) return;
    if (e.target.closest(".close")) closeTab(el.dataset.id);
    else { activate(el.dataset.id); setView("editor"); }
  });
  $("#tabs").addEventListener("auxclick", (e) => {
    const el = e.target.closest(".tab");
    if (el && e.button === 1) closeTab(el.dataset.id);
  });
  $("#tabs").addEventListener("dblclick", (e) => {
    const el = e.target.closest(".tab");
    const tab = el && state.tabs.find((t) => t.id === el.dataset.id);
    if (tab) renameItem(tab.path, tab.name, "note");
  });
  $("#tabs").addEventListener("contextmenu", (e) => {
    const el = e.target.closest(".tab");
    const tab = el && state.tabs.find((t) => t.id === el.dataset.id);
    if (!tab) return;
    e.preventDefault();
    openMenu(e.clientX, e.clientY, [
      { label: state.pinned.includes(tab.path) ? "Sabitlemeyi kaldır" : "Notu sabitle", icon: "star", action: () => togglePin(tab.path) },
      "sep",
      { label: "Yeniden adlandır", icon: "rename", action: () => renameItem(tab.path, tab.name, "note") },
      { label: "Fikir ağacı", icon: "tree", action: () => { activate(tab.id); setView("tree"); } },
      "sep",
      { label: "Kapat", icon: "x", action: () => closeTab(tab.id) },
      { label: "Diğerlerini kapat", action: () => state.tabs.filter((t) => t !== tab).forEach((t) => closeTab(t.id)) },
    ]);
  });

  wireSplitter();
  wirePreview();
  wireDesktop();
}

function renderViewSwitch() {
  const tab = activeTab();
  const open = tab ? historyPanel.items.filter((e) => e.type === "question" && e.status === "open" && e.path === tab.path).length : 0;
  $('[data-view="tree"]').innerHTML = `${icon("tree", 14)}Fikir Ağacı${open ? `<span class="badge">${open}</span>` : ""}`;
  document.querySelectorAll("#viewSwitch [data-view]").forEach((b) => b.classList.toggle("on", b.dataset.view === state.view));
}

function renderTabs() {
  $("#tabs").innerHTML = state.tabs.map((t) => `
    <div class="tab${t.id === state.activeId ? " active" : ""}${t.dirty ? " dirty" : ""}" data-id="${t.id}" role="tab" title="${esc(t.path)}">
      ${icon("file", 14, "kind")}<span class="name">${esc(t.name)}.md</span>
      <button class="close" title="Kapat">${icon("x", 13)}</button>
    </div>`).join("");
  $("#tabs .tab.active")?.scrollIntoView({ block: "nearest", inline: "nearest" });
}

function renderCrumbs() {
  const tab = activeTab();
  const parts = tab ? tab.path.split("/") : [];
  const bits = [`<span>${esc(state.vault)}</span>`];
  parts.forEach((p, i) => {
    bits.push('<span class="sep">/</span>');
    bits.push(i === parts.length - 1 ? `<span class="cur">${esc(p)}</span>` : `<span>${esc(p)}</span>`);
  });
  $("#crumbs").innerHTML = bits.join("");
  $("#noteIdentity").innerHTML = tab ? `
    <div class="note-heading"><span class="note-kicker">AÇIK NOT</span><h1>${esc(tab.name)}</h1></div>
    <div class="note-actions">
      <button class="note-pin${state.pinned.includes(tab.path) ? " on" : ""}" id="pinNote" title="${state.pinned.includes(tab.path) ? "Sabitlemeyi kaldır" : "Notu sabitle"}" aria-label="${state.pinned.includes(tab.path) ? "Sabitlemeyi kaldır" : "Notu sabitle"}" aria-pressed="${state.pinned.includes(tab.path)}">${icon("star", 17)}</button>
      <div class="note-trust" title="Asistan nota yazmadan önce onayını ister">${icon("checkCircle", 14)}<span>Nota yazmak için onayın gerekir</span></div>
    </div>` : "";
  document.title = tab ? `${tab.name} — Concept Trail` : "Concept Trail";
}

function renderStatus() {
  const tab = activeTab();
  $("#statusbar").classList.toggle("no-note", !tab);
  const { line, col, selected } = state.cursor;
  $("#stPos").textContent = tab ? `Satır ${line + 1}, Sütun ${col + 1}${selected ? ` (${selected} seçili)` : ""}` : "";
  const words = tab ? wordCount(tab.editor.value) : 0;
  $("#stWords").textContent = tab ? `${words} kelime` : "";
  $("#stRead").textContent = tab && words ? `${Math.max(1, Math.ceil(words / 220))} dk okuma` : "";
  let saved = "";
  if (tab?.dirty) saved = "Kaydedilmedi";
  else if (tab?.lastSaved) saved = `Son kaydedilme: ${relativeSaved(tab.lastSaved)}`;
  else if (tab) saved = "Kaydedildi";
  $("#stSaved").textContent = saved;

  const busyHere = tab && state.model.busy === tab.path;
  $("#askBtn")?.classList.toggle("busy", Boolean(busyHere));

  const watch = $("#stWatch");
  let label;
  if (!state.connected) label = "Sunucuya bağlanılamıyor";
  else if (!state.liveWatch) label = "Canlı izleme kapalı";
  else if (!state.model.model_up) label = "Model kapalı";
  else if (busyHere) label = state.model.busy_quiet ? "Asistan notuna bakıyor…" : "Asistan düşünüyor…";
  else label = "Canlı izleme açık";
  watch.classList.toggle("on", state.liveWatch && state.model.model_up && state.connected);
  watch.classList.toggle("busy", Boolean(busyHere));
  watch.querySelector(".lbl").textContent = label;
}

function renderModel() {
  const { chat_up: chatUp, fast_up: fastUp, endpoint, fast_endpoint: fastEndpoint, busy } = state.model;
  const short = (e) => String(e || "").replace("127.0.0.1", "localhost");

  const { chat_remote: chatRemote, fast_remote: fastRemote, chat_provider: chatName, analysis_provider: fastName } = state.model;
  // one model doing every job gets one light, not two saying the same thing
  const shared = Boolean(state.model.shared_model);
  const pill = $("#llmPill");
  pill.classList.toggle("up", chatUp && state.connected);
  pill.classList.toggle("busy", Boolean(busy) && (shared || !fastUp));
  pill.classList.toggle("remote", Boolean(chatRemote));
  const role = shared ? "Model" : "Sohbet";
  pill.querySelector(".lbl").innerHTML = !state.connected ? "Sunucu bağlantısı yok"
    : chatUp ? `${chatRemote ? icon("cloud", 12) : ""}${role}: ${esc(chatName || short(endpoint))}` : `${role} kapalı`;
  pill.title = chatRemote
    ? `${role} bulutta: ${chatName} (${short(endpoint)}) — notların bu sağlayıcıya gönderiliyor`
    : chatUp ? `${shared ? "Sohbet, not izleme ve araştırma bu modelde" : "Sohbet modeli çalışıyor"} (${short(endpoint)})`
             : `${role} kapalı — başlatmak için tıkla`;

  // the note-watch and research model, when it is a different one
  const fast = $("#fastPill");
  fast.hidden = !state.connected || shared;
  fast.classList.toggle("up", fastUp);
  fast.classList.toggle("busy", Boolean(busy) && fastUp);
  fast.classList.toggle("remote", Boolean(fastRemote));
  fast.querySelector(".lbl").innerHTML =
    `${icon(fastRemote ? "cloud" : "zap", 12)}${fastUp ? `İzleme: ${esc(fastName || short(fastEndpoint))}` : "İzleme modeli kapalı"}`;
  fast.title = fastRemote
    ? `Not izleme ve araştırma bulutta: ${fastName} (${short(fastEndpoint)})`
    : fastUp ? `Not izleme ve araştırma modeli: ${fastName || short(fastEndpoint)}`
             : "Not izleme modeli kapalı — başlatmak için tıkla";

  const allUp = chatUp && fastUp;
  $("#launchBtn").title = allUp ? "Modeller çalışıyor" : "Model başlat";
  $("#launchBtn").classList.toggle("active", !allUp && state.connected);
}

function renderWelcome() {
  const recent = flatNotes().sort((a, b) => b.mtime - a.mtime).slice(0, 6);
  $("#welcome").innerHTML = `<div class="welcome-inner">
    ${logo(56)}
    <h1>Concept Trail</h1>
    <p class="quote">“Düşüncelerini kaydet. Fikirlerin büyüsün.”</p>
    <div class="actions">
      <button class="btn btn-accent" data-act="new">${icon("filePlus", 15)}Yeni not</button>
      <button class="btn" data-act="search">${icon("search", 15)}Not ara <kbd>Ctrl P</kbd></button>
    </div>
    ${recent.length ? `<div class="recent"><h3>Son notlar</h3>${recent.map((n) => `
      <button data-path="${esc(n.path)}">${icon("file", 15)}<span>${esc(n.name)}</span><span class="path">${esc(n.path.includes("/") ? n.path.slice(0, n.path.lastIndexOf("/")) : "")}</span></button>`).join("")}</div>` : ""}
  </div>`;
}

// ---------------------------------------------------------------- layout state
function updateLayout() {
  const tab = activeTab();
  const showTree = Boolean(tab) && state.view === "tree";
  $("#welcome").hidden = Boolean(tab);
  $("#panes").hidden = !tab || showTree;
  if (showTree) tree.show(tab.path, tab.name); else tree.hide();
  $("#panes").classList.toggle("editor-only", state.preview === "hidden");
  $("#panes").style.setProperty("--split", `${state.split / (1 - state.split)}fr`);
  document.querySelectorAll("[data-pv]").forEach((b) => b.classList.toggle("on", b.dataset.pv === state.preview));
  renderViewSwitch();
}

function setView(view) {
  if (view === state.view) return;
  state.view = view;
  updateLayout();
  if (view === "editor") activeTab()?.editor.focus();
  saveSession();
}

function setPreview(mode) {
  state.preview = mode;
  fitColumnsToWindow();
  updateLayout();
  renderPreview(true);
  saveSession();
}

function applyAppearance() {
  document.documentElement.dataset.theme = theme;
  $("#themeBtn").innerHTML = icon(themeOf(theme).dark ? "moon" : "sun", 17);
  $("#themeBtn").title = `Tema: ${themeOf(theme).label} — değiştirmek için tıkla`;
  $("#themeBtn").setAttribute("aria-label", $("#themeBtn").title);
  $("#app").classList.toggle("focus-mode", focusMode);
  $("#focusBtn").innerHTML = `${icon(focusMode ? "columns" : "fit", 15)}<span>${focusMode ? "Odaktan çık" : "Odak"}</span>`;
  $("#focusBtn").classList.toggle("on", focusMode);
  $("#focusBtn").setAttribute("aria-pressed", String(focusMode));
}

function setTheme(next) {
  theme = themeOf(next).id;
  localStorage.setItem(appearanceKey, theme);
  // a theme change fades across the whole app instead of snapping
  document.documentElement.classList.add("theme-fading");
  clearTimeout(setTheme.timer);
  setTheme.timer = setTimeout(() => document.documentElement.classList.remove("theme-fading"), 450);
  applyAppearance();
}

function setFocusMode(next) {
  focusMode = next;
  localStorage.setItem(focusKey, String(focusMode));
  applyAppearance();
  activeTab()?.editor.focus();
}

// state.sidebar/panel are what the user chose; on small windows they are
// auto-hidden until the window grows back past the breakpoint.
const SIDEBAR_MIN_W = 900;
const PANEL_MIN_W = 1180;
const PREVIEW_SIDEBAR_MIN_W = 1500;
const shown = { sidebar: true, panel: true };
let widthBucket = null;

function setSidebar(on) { state.sidebar = shown.sidebar = on; renderColumns(); saveSession(); }
function setPanel(on) { state.panel = shown.panel = on; renderColumns(); saveSession(); }

function fitColumnsToWindow() {
  const needsTwoColumns = state.preview !== "hidden";
  const bucket = `${innerWidth >= SIDEBAR_MIN_W}${innerWidth >= PANEL_MIN_W}${innerWidth >= PREVIEW_SIDEBAR_MIN_W}${needsTwoColumns}`;
  if (bucket === widthBucket) return;
  widthBucket = bucket;
  shown.sidebar = state.sidebar && innerWidth >= (needsTwoColumns ? PREVIEW_SIDEBAR_MIN_W : SIDEBAR_MIN_W);
  shown.panel = state.panel && innerWidth >= PANEL_MIN_W;
  renderColumns();
}

function renderColumns() {
  $("#app").classList.toggle("no-sidebar", !shown.sidebar);
  $("#app").classList.toggle("no-panel", !shown.panel);
  $("#toggleSidebar").classList.toggle("active", shown.sidebar);
  $("#togglePanel").classList.toggle("active", shown.panel);
}

window.addEventListener("resize", fitColumnsToWindow);
new ResizeObserver(([entry]) => {
  $("#stage").classList.toggle("narrow", entry.contentRect.width < 560);
}).observe($("#stage"));

function togglePin(path) {
  if (state.pinned.includes(path)) state.pinned = state.pinned.filter((p) => p !== path);
  else state.pinned = [path, ...state.pinned];
  sidebar.setPinned(state.pinned);
  renderCrumbs();
  saveSession();
}

const saveSession = debounce(() => {
  api.put("/api/session", {
    tabs: state.tabs.map((t) => t.path),
    active: activeTab()?.path ?? null,
    view: state.view,
    preview: state.preview,
    liveWatch: state.liveWatch,
    split: state.split,
    sidebar: state.sidebar,
    panel: state.panel,
    pinned: state.pinned,
    expanded: [...sidebar.expanded],
  }).catch(() => {});
}, 600);

// ---------------------------------------------------------------- vault
function flatNotes(items = state.tree, out = []) {
  for (const it of items) {
    if (it.type === "dir") flatNotes(it.children, out);
    else out.push(it);
  }
  return out;
}

async function loadTree({ prunePinned = false } = {}) {
  try {
    const data = await api.get("/api/vault/tree");
    state.vault = data.name;
    state.tree = data.tree;
    if (prunePinned) {
      const existing = new Set(flatNotes().map((n) => n.path));
      const valid = state.pinned.filter((path) => existing.has(path));
      if (valid.length !== state.pinned.length) { state.pinned = valid; saveSession(); }
    }
    sidebar.setPinned(state.pinned);
    sidebar.setTree(data);
    renderCrumbs();
    if (!activeTab()) renderWelcome();
  } catch (err) {
    toast(`Vault okunamadı: ${err.message}`, "error");
  }
}

const loadTags = debounce(async () => {
  try { sidebar.setTags(await api.get("/api/vault/tags")); } catch { /* tags are optional */ }
}, 400);

function parentDir(path) {
  return path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
}

async function newNote(dir = "", presetName) {
  const name = presetName ?? await promptDialog({
    title: "Yeni not",
    message: dir ? `“${dir}” klasörüne eklenecek.` : "",
    value: "Adsız Not",
    confirmText: "Oluştur",
  });
  if (!name) return;
  try {
    const { path } = await api.post("/api/notes/create", { dir, name });
    await loadTree();
    const tab = await openNote(path);
    setView("editor");
    tab.editor.focus();
  } catch (err) {
    toast(err.message, "error");
  }
}

async function newFolder(dir = "") {
  const name = await promptDialog({ title: "Yeni klasör", message: dir ? `“${dir}” içine eklenecek.` : "", value: "Yeni Klasör", confirmText: "Oluştur" });
  if (!name) return;
  try {
    const { path } = await api.post("/api/folders/create", { dir, name });
    sidebar.expanded.add(path);
    sidebar.reveal(`${path}/x`);
    await loadTree();
  } catch (err) {
    toast(err.message, "error");
  }
}

async function flushUnder(path) {
  await Promise.all(state.tabs.filter((t) => under(t.path, path)).map((t) => saveTab(t)));
}

async function renameItem(path, name, kind) {
  const next = await promptDialog({ title: kind === "dir" ? "Klasörü yeniden adlandır" : "Notu yeniden adlandır", value: name, confirmText: "Kaydet" });
  if (!next || next === name) return;
  try {
    await flushUnder(path);
    const { path: newPath } = await api.post("/api/vault/rename", { path, name: next });
    applyRename(path, newPath);
  } catch (err) {
    toast(err.message, "error");
  }
}

async function moveItem(path, dir) {
  try {
    await flushUnder(path);
    const { path: newPath } = await api.post("/api/vault/move", { path, dir });
    if (dir) sidebar.expanded.add(dir);
    applyRename(path, newPath);
  } catch (err) {
    toast(err.message, "error");
  }
}

function applyRename(from, to) {
  if (from === to) return;
  state.pinned = [...new Set(state.pinned.map((path) => under(path, from) ? to + path.slice(from.length) : path))];
  for (const tab of state.tabs) {
    if (!under(tab.path, from)) continue;
    const oldPath = tab.path;
    tab.path = to + tab.path.slice(from.length);
    tab.name = noteName(tab.path);
    tree.renamed(oldPath, tab.path, tab.name);
  }
  if (sidebar.expanded.has(from)) { sidebar.expanded.delete(from); sidebar.expanded.add(to); }
  renderTabs();
  renderCrumbs();
  sidebar.setActive(activeTab()?.path ?? null);
  sidebar.setPinned(state.pinned);
  saveSession();
}

async function trashItem(path, name, kind) {
  const ok = await confirmDialog({
    title: kind === "dir" ? "Klasör çöpe taşınsın mı?" : "Not çöpe taşınsın mı?",
    message: `“${name}” vault içindeki .trash klasörüne taşınacak. Gerekirse oradan geri alabilirsin.`,
    confirmText: "Çöpe taşı",
    danger: true,
  });
  if (!ok) return;
  try {
    await api.post("/api/vault/trash", { path });
    dropTabsUnder(path);
  } catch (err) {
    toast(err.message, "error");
  }
}

function dropTabsUnder(path) {
  const remaining = state.pinned.filter((p) => !under(p, path));
  if (remaining.length !== state.pinned.length) {
    state.pinned = remaining;
    sidebar.setPinned(state.pinned);
    renderCrumbs();
    saveSession();
  }
  for (const tab of [...state.tabs]) {
    if (!under(tab.path, path)) continue;
    clearTimeout(tab.saveTimer);
    tab.closed = true; // the file is gone — never write it back
    removeTab(tab);
  }
}

async function addTag() {
  const tab = activeTab();
  if (!tab) return toast("Etiket eklemek için önce bir not aç.");
  const raw = await promptDialog({
    title: "Etiket ekle",
    message: `“${tab.name}” notunun frontmatter'ına eklenecek.`,
    placeholder: "ör. yapay-zeka",
    confirmText: "Ekle",
    validate: (v) => (/^#?[\p{L}\p{N}_/-]+$/u.test(v) ? null : "Etiket boşluk içeremez."),
  });
  if (!raw) return;
  const tag = raw.replace(/^#/, "");
  const ed = tab.editor;
  const v = ed.value;
  const fm = /^---\n([\s\S]*?\n)?---(\n|$)/.exec(v);
  if (fm) {
    const body = fm[1] || "";
    const line = /^tags:[ \t]*\[(.*)\][ \t]*$/m.exec(body);
    if (line) {
      const existing = line[1].split(",").map((s) => s.trim().replace(/^["']|["']$/g, "")).filter(Boolean);
      if (existing.includes(tag)) return toast("Bu etiket zaten var.");
      const close = 4 + line.index + line[0].lastIndexOf("]");
      ed.replaceRange(close, close, existing.length ? `, ${tag}` : tag);
    } else {
      const at = 4 + body.length;
      ed.replaceRange(at, at, `tags: [${tag}]\n`);
    }
  } else {
    ed.replaceRange(0, 0, `---\ntags: [${tag}]\n---\n`);
  }
  await saveTab(tab);
  loadTags();
}

// ---------------------------------------------------------------- tabs
async function openNote(path, { focus = true, activate: doActivate = true } = {}) {
  let tab = tabByPath(path);
  if (!tab) {
    if (!pendingOpens.has(path)) {
      pendingOpens.set(path, api.get("/api/notes", { path }).then(createTab).finally(() => pendingOpens.delete(path)));
    }
    tab = await pendingOpens.get(path);
  }
  if (doActivate) activate(tab.id, { focus });
  return tab;
}

function createTab(note) {
  const existing = tabByPath(note.path);
  if (existing) return existing;
  const tab = {
    id: `t${++tabSeq}`,
    path: note.path,
    name: note.name,
    saved: note.content,
    mtime: note.mtime,
    dirty: false,
    lastSaved: null,
    chain: Promise.resolve(),
  };
  tab.editor = new MarkdownEditor({
    value: note.content,
    placeholder: "Proje fikrini buraya yaz… (# başlık, **kalın**, - liste)\n\nYazmaya 15 saniye ara verdiğinde asistan notuna sessizce bakar; soruları sağdaki panelde bekler.",
    onChange: (_value, info) => onEdit(tab, info),
    onCursor: (c) => { if (tab.id === state.activeId) { state.cursor = c; renderStatus(); } },
    onAsk: () => analyze(tab, true),
    onScroll: () => { if (tab.id === state.activeId) syncPreviewScroll(tab); },
  });
  $("#editorHost").append(tab.editor.root);
  state.tabs.push(tab);
  renderTabs();
  loadWritten(tab);
  return tab;
}

function activate(id, { focus = true } = {}) {
  const tab = state.tabs.find((t) => t.id === id);
  if (!tab) return;
  state.activeId = id;
  for (const t of state.tabs) t.editor.root.classList.toggle("active", t === tab);
  state.cursor = tab.editor.cursorInfo();
  renderTabs();
  renderCrumbs();
  renderStatus();
  sidebar.setActive(tab.path);
  historyPanel.setCurrentPath(tab.path);
  ladderPanel.load(tab.path);
  research.setNote(tab.path);
  updateLayout();
  renderPreview(true);
  if (focus && state.view === "editor") tab.editor.focus();
  saveSession();
}

function removeTab(tab) {
  const index = state.tabs.indexOf(tab);
  if (index === -1) return;
  clearTimeout(tab.liveTimer);
  clearTimeout(tab.pasteTimer);
  tab.editor.destroy();
  state.tabs.splice(index, 1);
  if (state.activeId === tab.id) {
    const next = state.tabs[index] || state.tabs[index - 1];
    state.activeId = null;
    if (next) activate(next.id);
  }
  if (!state.tabs.length) {
    renderWelcome();
    renderCrumbs();
    renderStatus();
    sidebar.setActive(null);
    updateLayout();
  }
  renderTabs();
  saveSession();
}

async function closeTab(id) {
  const tab = state.tabs.find((t) => t.id === id);
  if (!tab) return;
  await saveTab(tab);
  removeTab(tab);
}

function cycleTab(step) {
  if (state.tabs.length < 2) return;
  const i = state.tabs.findIndex((t) => t.id === state.activeId);
  activate(state.tabs[(i + step + state.tabs.length) % state.tabs.length].id);
}

// ---------------------------------------------------------------- saving
function onEdit(tab, { pasted = false } = {}) {
  const wasDirty = tab.dirty;
  tab.dirty = tab.editor.value !== tab.saved;
  if (wasDirty !== tab.dirty) renderTabs();
  clearTimeout(tab.saveTimer);
  tab.saveTimer = setTimeout(() => saveTab(tab), SAVE_MS);
  if (tab.id === state.activeId) {
    research.contentChanged();
    renderPreviewSoon();
    renderStatus();
  }
  scheduleLive(tab);
  if (pasted && state.liveWatch) {
    // typing on right after a paste does not put it off; only another paste does
    clearTimeout(tab.pasteTimer);
    tab.pasteTimer = setTimeout(() => liveLook(tab), PASTE_MS);
  }
}

function saveTab(tab) {
  clearTimeout(tab.saveTimer);
  tab.chain = tab.chain.then(async () => {
    if (tab.closed) return;
    const content = tab.editor.value;
    if (content === tab.saved) {
      if (tab.dirty) { tab.dirty = false; renderTabs(); }
      return;
    }
    try {
      const result = await api.put("/api/notes", { path: tab.path, content });
      tab.saved = content;
      tab.mtime = result.mtime;
      tab.lastSaved = new Date();
      const node = flatNotes().find((n) => n.path === tab.path);
      if (node) node.mtime = result.mtime;
      loadTags();
    } catch (err) {
      if (err.status === 409) {
        // the file is gone (trashed or renamed elsewhere) — don't recreate it
        tab.closed = true;
        removeTab(tab);
        toast(`“${tab.name}” artık yok, sekme kapatıldı.`, "error");
        return;
      }
      toast(`Kaydedilemedi: ${err.message}`, "error");
    }
    const dirty = tab.editor.value !== tab.saved;
    if (dirty !== tab.dirty) { tab.dirty = dirty; renderTabs(); }
    if (tab.id === state.activeId) renderStatus();
  });
  return tab.chain;
}

async function saveAll() {
  await Promise.all(state.tabs.map((t) => saveTab(t)));
}

// ---------------------------------------------------------------- assistant
/** You asked: look now, and show it. */
async function analyze(tab) {
  const content = tab.editor.value;
  await saveTab(tab);
  try {
    const { status } = await api.post("/api/assistant/analyze", { path: tab.path, content, force: true });
    if (status === "model_down") toast("Model kapalı — önce üstteki ▷ ile modeli başlat.", "error");
    else if (status === "busy") toast("Asistan şu an başka bir notla meşgul.");
    else if (status === "skipped") toast("İncelenecek metin yok.");
  } catch (err) {
    toast(err.message, "error");
  }
}

/** The live watch: every edit pushes the look back to the next 15-second pause. */
function scheduleLive(tab) {
  if (!tab) return;
  clearTimeout(tab.liveTimer);
  if (state.liveWatch) tab.liveTimer = setTimeout(() => liveLook(tab), LIVE_IDLE_MS);
}

/** A quiet look. The server skips it when too little changed since the last
 *  one, and never lets it interrupt a running pass or a conversation. */
async function liveLook(tab) {
  if (!state.liveWatch || tab.id !== state.activeId || !state.model.model_up) return;
  await saveTab(tab);
  if (tab.closed) return;
  try {
    await api.post("/api/assistant/analyze", { path: tab.path, content: tab.editor.value, force: false });
  } catch { /* best effort: the next pause tries again */ }
}

function setLiveWatch(on) {
  state.liveWatch = on;
  for (const tab of state.tabs) { clearTimeout(tab.liveTimer); clearTimeout(tab.pasteTimer); }
  if (on) scheduleLive(activeTab());
  renderStatus();
  toast(on ? "Canlı izleme açık — 15 saniye durduğunda ya da bir şey yapıştırdığında notuna sessizce bakacak."
           : "Canlı izleme kapalı — notun yalnızca Ctrl+Enter ile incelenir.");
  saveSession();
}

function applyStatus(status) {
  const wasBusy = state.model.busy;
  state.model = { ...state.model, ...status };
  if (!status.busy) state.thinking = null;
  hudCard?.setStatus(status);
  tree.setBusy(status.busy_quiet ? null : status.busy, state.thinking?.text);
  renderModel();
  renderStatus();
  // a pass just ended — possibly given way to a conversation, or run on text
  // you have since added to: look again at the next pause (the server skips
  // it if nothing much changed)
  if (wasBusy && !status.busy) scheduleLive(activeTab());
}

async function hudAction(eventId, action) {
  try {
    await api.post("/api/assistant/hud", { event_id: eventId, action });
  } catch (err) {
    toast(err.message, "error");
  }
}

async function applyApprovedEdit(event) {
  const tab = tabByPath(event.path);
  if (tab) {
    const { ok } = await api.post("/api/assistant/claim", { event_id: event.id });
    if (!ok) return;
    if (tab.editor.applyEdit(event.original, event.replacement)) {
      toast("Düzenleme uygulandı. Geri almak için Ctrl+Z.", "success");
      saveTab(tab);
    } else {
      toast("Önerilen metin notta artık bulunamadı.", "error");
    }
    return;
  }
  // give pages that have the note open a moment to claim it first
  await new Promise((r) => setTimeout(r, 400));
  try {
    const { applied } = await api.post("/api/notes/apply-edit", {
      path: event.path, original: event.original, replacement: event.replacement, event_id: event.id,
    });
    if (applied) toast(`Düzenleme “${event.note}” notuna uygulandı.`, "success");
  } catch (err) {
    toast(err.message, "error");
  }
}

/** The assistant understood an answer and wrote it up — put it in the note. */
async function appendAssistantText(event) {
  const tab = tabByPath(event.path);
  if (tab) {
    const { ok } = await api.post("/api/assistant/claim", { event_id: event.id });
    if (!ok) return;
    tab.editor.appendText(event.text);
    saveTab(tab);
    toast("Asistan sonucu notuna ekledi.", "success");
    return;
  }
  // give pages that have the note open a moment to claim it first
  await new Promise((r) => setTimeout(r, 400));
  try {
    const { applied } = await api.post("/api/notes/append", { path: event.path, text: event.text, event_id: event.id });
    if (applied) toast(`Asistan sonucu “${event.note}” notuna ekledi.`, "success");
  } catch (err) {
    toast(err.message, "error");
  }
}

async function openChat(path, nodeId) {
  try {
    await openNote(path, { focus: false });
    chat.open(path, nodeId);
  } catch (err) {
    toast(err.message, "error");
  }
}

async function launchModel(e, index) {
  if (index !== undefined && state.scripts[index]) {
    const name = state.scripts[index];
    try {
      await api.post("/api/model/launch", { name });
      toast(`${name} başlatılıyor… Açılan konsolu takip et.`);
    } catch (err) {
      toast(err.message, "error", 5000);
    }
    return;
  }
  if (state.model.chat_up && state.model.fast_up) return toast("Modeller zaten çalışıyor.");
  const launch = async (name) => {
    try {
      await api.post("/api/model/launch", { name });
      toast("Model başlatılıyor… Yeni konsol penceresini takip et, hazır olunca durum yeşile döner.");
    } catch (err) {
      toast(err.message, "error", 5000);
    }
  };
  if (state.scripts.length > 1 && e) {
    const r = e.currentTarget.getBoundingClientRect();
    openMenu(r.left - 160, r.bottom + 6, state.scripts.map((name) => ({ label: name, icon: "cpu", action: () => launch(name) })));
  } else {
    launch(state.scripts[0]);
  }
}

// ---------------------------------------------------------------- preview
/** The note's own headings, as a strip above the preview: the column stops
 *  being a mirror with empty space under it and becomes a way to move. */
function outlineOf(text) {
  const heads = [];
  let fence = null;
  for (const line of text.split("\n")) {
    const f = /^\s*(```+|~~~+)/.exec(line);
    if (f) { fence = fence ? null : f[1]; continue; }
    if (fence) continue;
    const m = /^(#{2,4})\s+(.+?)\s*$/.exec(line);
    if (m) heads.push({ level: m[1].length, title: m[2] });
  }
  if (heads.length < 2) return "";
  return `<div class="pv-outline">${heads.slice(0, 24).map((h) =>
    `<button class="h${h.level}" data-heading="${esc(h.title)}" title="${esc(h.title)} bölümüne git">${esc(h.title)}</button>`).join("")}</div>`;
}

const renderPreviewSoon = debounce(() => renderPreview(), 220);
let previewSeq = 0;

async function renderPreview(resetScroll = false) {
  const tab = activeTab();
  const body = $("#preview");
  if (!tab || state.preview === "hidden") return;
  if (state.preview === "source") {
    body.className = "preview-body source";
    body.textContent = tab.editor.value;
    if (resetScroll) body.scrollTop = 0;
    return;
  }
  const seq = ++previewSeq;
  try {
    const { html } = await api.post("/api/render", { content: tab.editor.value, path: tab.path });
    if (seq !== previewSeq || activeTab() !== tab) return;
    const scroll = body.scrollTop;
    body.className = "preview-body";
    body.innerHTML = outlineOf(tab.editor.value)
      + `<div class="md">${html.trim() ? html : '<p class="md-empty">Önizlenecek bir şey yok — sol tarafta yazmaya başla.</p>'}</div>`;
    body.scrollTop = resetScroll ? 0 : scroll;
  } catch { /* keep the last good preview */ }
}

function syncPreviewScroll(tab) {
  if (state.preview !== "preview") return;
  const body = $("#preview");
  if (tab.editor.scrollFraction() > 0.99) { body.scrollTop = body.scrollHeight; return; }
  const line = tab.editor.topLine();
  let target = null;
  for (const el of body.querySelectorAll("[data-line]")) {
    if (Number(el.dataset.line) <= line) target = el; else break;
  }
  const top = target ? target.getBoundingClientRect().top - body.getBoundingClientRect().top + body.scrollTop - 16 : 0;
  body.scrollTop = Math.max(0, top);
}

function wirePreview() {
  $("#preview").addEventListener("click", (e) => {
    const tab = activeTab();
    const jump = e.target.closest("[data-heading]");
    if (jump && tab) {
      // the strip is for moving around the note, not for reading it twice
      goToSection(tab.path, jump.dataset.heading);
      return;
    }
    const box = e.target.closest(".task-cb");
    if (box && tab) {
      e.preventDefault();
      tab.editor.toggleTaskAtLine(Number(box.dataset.line));
      return;
    }
    const link = e.target.closest("a[href]");
    if (!link || !tab) return;
    e.preventDefault();
    const href = link.getAttribute("href");
    if (/^https?:/i.test(href)) return openExternal(href);
    if (href.startsWith("#")) return;
    const target = decodeURIComponent(href).replace(/^\.\//, "");
    const base = parentDir(tab.path);
    const joined = (base ? `${base}/${target}` : target).split("/").reduce((acc, part) => {
      if (part === "..") acc.pop(); else if (part && part !== ".") acc.push(part);
      return acc;
    }, []).join("/");
    openNote(/\.md$/i.test(joined) ? joined : `${joined}.md`).catch(() => toast("Bağlantılı not bulunamadı.", "error"));
  });
}

function wireSplitter() {
  const splitter = $("#splitter");
  splitter.addEventListener("pointerdown", (e) => {
    splitter.setPointerCapture(e.pointerId);
    splitter.classList.add("dragging");
    const rect = $("#panes").getBoundingClientRect();
    const move = (ev) => {
      state.split = Math.min(0.75, Math.max(0.25, (ev.clientX - rect.left) / rect.width));
      $("#panes").style.setProperty("--split", `${state.split / (1 - state.split)}fr`);
    };
    const up = () => {
      splitter.classList.remove("dragging");
      splitter.removeEventListener("pointermove", move);
      splitter.removeEventListener("pointerup", up);
      saveSession();
    };
    splitter.addEventListener("pointermove", move);
    splitter.addEventListener("pointerup", up);
  });
  splitter.addEventListener("dblclick", () => {
    state.split = 0.5;
    updateLayout();
    saveSession();
  });
}

// ---------------------------------------------------------------- desktop shell
function wireDesktop() {
  if (!isDesktop) return;
  document.documentElement.classList.add("desktop");
  let lastDown = 0;
  $("#titlebar").addEventListener("mousedown", (e) => {
    if (e.button !== 0 || e.target.closest("button, .llm-pill")) return;
    const now = Date.now();
    if (now - lastDown < 350) {
      lastDown = 0;
      desktopCall("toggleMaximize");
      return;
    }
    lastDown = now;
    desktopCall("startMove");
  });
  document.querySelectorAll(".grip").forEach((g) => {
    g.addEventListener("mousedown", (e) => { if (e.button === 0) desktopCall("startResize", g.dataset.edge); });
  });
  document.querySelectorAll("[data-win]").forEach((b) => {
    b.addEventListener("click", () => {
      if (b.dataset.win === "close") window.__requestClose();
      else desktopCall(b.dataset.win === "minimize" ? "minimize" : "toggleMaximize");
    });
  });
  const setMaximized = (on) => {
    document.documentElement.classList.toggle("maximized", Boolean(on));
    $('[data-win="maximize"]').innerHTML = icon(on ? "restore" : "square", on ? 14 : 13);
    $('[data-win="maximize"]').title = on ? "Önceki boyut" : "Büyüt";
  };
  desktopReady.then((bridge) => {
    if (!bridge) return;
    bridge.maximizedChanged.connect(setMaximized);
    bridge.isMaximized(setMaximized);
  });
}

window.__requestClose = async () => {
  await Promise.race([saveAll(), new Promise((r) => setTimeout(r, 2500))]);
  desktopCall("closeNow");
};

// ---------------------------------------------------------------- commands & keys
function commands() {
  const tab = activeTab();
  const list = [
    { label: "Yeni not", icon: "filePlus", hint: "Ctrl N", action: () => newNote("") },
    { label: "Yeni klasör", icon: "folderPlus", action: () => newFolder("") },
    { label: "Asistana şimdi sor", icon: "sparkles", hint: "Ctrl Enter", action: () => tab && analyze(tab, true) },
    { label: "Açık notu araştır", icon: "search", action: () => research.open() },
    { label: "Master prompt hazırla", icon: "wand", hint: "Ctrl Shift M", action: () => openMaster() },
    { label: state.liveWatch ? "Canlı izlemeyi kapat" : "Canlı izlemeyi aç", icon: state.liveWatch ? "eyeOff" : "eye", action: () => setLiveWatch(!state.liveWatch) },
    { label: state.view === "tree" ? "Editöre dön" : "Fikir ağacını göster", icon: state.view === "tree" ? "file" : "tree", hint: "Ctrl G", action: () => setView(state.view === "tree" ? "editor" : "tree") },
    { label: "Modeli başlat", icon: "play", action: () => launchModel() },
    { label: "Model durumunu yenile", icon: "refresh", action: () => api.post("/api/model/check").catch(() => {}) },
    { label: state.preview === "hidden" ? "Önizlemeyi aç" : "Önizlemeyi kapat", icon: "columns", action: () => setPreview(state.preview === "hidden" ? "preview" : "hidden") },
    { label: focusMode ? "Odak kipinden çık" : "Odak kipine geç", icon: "fit", hint: "Ctrl Shift F", action: () => setFocusMode(!focusMode) },
    { label: "Tema seç…", icon: "sparkles", action: () => openThemePicker($("#themeBtn"), theme, setTheme) },
    { label: "Dil seç…", icon: "globe", action: () => openLanguagePicker($("#langBtn")) },
    ...THEMES.filter((t) => t.id !== theme).map((t) => ({ label: `Tema: ${t.label}`, icon: t.dark ? "moon" : "sun", action: () => setTheme(t.id) })),
    { label: "Kenar çubuğunu aç/kapat", icon: "panelLeft", hint: "Ctrl \\", action: () => setSidebar(!shown.sidebar) },
    { label: "Öneri panelini aç/kapat", icon: "panelRight", hint: "Ctrl Shift \\", action: () => setPanel(!shown.panel) },
    { label: "Modeller ve anahtarlar", icon: "settings", hint: "Ctrl ,", action: () => settings.open() },
    { label: "Klavye kısayolları", icon: "keyboard", action: shortcutsDialog },
  ];
  if (tab) {
    list.push(
      { label: state.pinned.includes(tab.path) ? "Sabitlemeyi kaldır" : "Notu sabitle", icon: "star", action: () => togglePin(tab.path) },
      { label: "Notu yeniden adlandır", icon: "rename", action: () => renameItem(tab.path, tab.name, "note") },
      { label: "Nota etiket ekle", icon: "tag", action: addTag },
      { label: "Notu çöpe taşı", icon: "trash", action: () => trashItem(tab.path, tab.name, "note") },
    );
  }
  return list;
}

document.addEventListener("keydown", (e) => {
  if (master.isOpen) return;          // the sheet handles its own keys
  if (e.key === "Escape" && focusMode && !chat.isOpen && !palette.isOpen && !document.querySelector(".dialog, .menu")) {
    setFocusMode(false);
    return;
  }
  if (document.querySelector(".dialog")) {
    if (mod(e) && e.key === "," && !settings.isOpen) { e.preventDefault(); settings.open(); }
    return;
  }
  if (tree.visible && !mod(e) && tree.handleKey(e)) { e.preventDefault(); return; }
  if (e.key === "Escape" && chat.isOpen && !palette.isOpen) { chat.close(); return; }
  if (!mod(e)) return;
  const key = e.key.toLowerCase();
  const tab = activeTab();
  if (e.key === ",") { e.preventDefault(); settings.open(); }
  else if (key === "p" && !e.shiftKey) { e.preventDefault(); palette.open(); }
  else if (key === "n" && !e.shiftKey) { e.preventDefault(); newNote(""); }
  else if (key === "w" && !e.shiftKey) { e.preventDefault(); if (tab) closeTab(tab.id); }
  else if (key === "s") { e.preventDefault(); if (tab) saveTab(tab); }
  else if (key === "g") { e.preventDefault(); if (tab) setView(state.view === "tree" ? "editor" : "tree"); }
  else if (key === "f" && e.shiftKey) { e.preventDefault(); setFocusMode(!focusMode); }
  else if (key === "m" && e.shiftKey) { e.preventDefault(); openMaster(); }
  else if (e.code === "Backslash") { e.preventDefault(); if (e.shiftKey) setPanel(!shown.panel); else setSidebar(!shown.sidebar); }
  else if (e.key === "Tab") { e.preventDefault(); cycleTab(e.shiftKey ? -1 : 1); }
  else if (e.key === "Enter" && tab && !e.target.closest("textarea, input")) { e.preventDefault(); analyze(tab, true); }
});

$("#welcome").addEventListener("click", (e) => {
  const act = e.target.closest("[data-act]")?.dataset.act;
  if (act === "new") return newNote("");
  if (act === "search") return palette.open();
  const recent = e.target.closest("[data-path]");
  if (recent) openNote(recent.dataset.path);
});

window.addEventListener("beforeunload", () => {
  for (const tab of state.tabs) {
    if (tab.closed || tab.editor.value === tab.saved) continue;
    fetch("/api/notes", {
      method: "PUT",
      keepalive: true,
      headers: { "Content-Type": "application/json", "X-Fikir": "1", "X-Client-Id": clientId },
      body: JSON.stringify({ path: tab.path, content: tab.editor.value }),
    });
  }
});

window.addEventListener("focus", () => { loadTree(); });

// ---------------------------------------------------------------- live events
function connect() {
  connectEvents({
    snapshot: (s) => { applyStatus(s.status); hudCard?.setHud(s.hud); },
    status: (s) => applyStatus(s),
    thinking: (t) => {
      state.thinking = t.phase === "done" ? null : t;
      hudCard?.setThinking(t);
      tree.setBusy(state.model.busy, state.thinking?.text);
      renderStatus();
    },
    hud: (h) => hudCard?.setHud(h),
    providers: () => { renderModel(); },
    flash: (f) => hudCard?.showFlash(f),
    history: (event) => {
      historyPanel.add(event);
      renderViewSwitch();
      const tab = activeTab();
      if (event.range && tab && tab.path === event.path && state.view === "editor") tab.editor.flash(event.range);
    },
    history_update: (event) => { historyPanel.update(event); research.onHistoryUpdate(event); renderViewSwitch(); },
    research: (data) => research.onEvent(data),
    start_research: async ({ path, focus }) => {
      // the writer accepted a research the assistant asked for
      try {
        await openNote(path);
        research.startWith(focus);
      } catch (err) {
        toast(err.message, "error");
      }
    },
    node: ({ path, node }) => { tree.nodeChanged(path, node); chat.nodeUpdated(path, node); ladderPanel.nodeChanged(path, node); },
    written: ({ path, texts }) => { const tab = tabByPath(path); if (tab) tab.editor.setWritten(texts); },
    ladder: ({ path, ladder, transition }) => {
      ladderPanel.update(path, ladder);
      if (!transition) return;
      // the note reaching the product phase is the one thing here worth
      // interrupting for; a finished rung is a quieter nod
      const product = transition.phase === "urun";
      toast(`${noteName(path)} · ${transition.title}: ${transition.body}${product ? " Master prompt hazırlamak için Ctrl+Shift+M." : ""}`,
            "success", product ? 12000 : 5000);
    },
    apply_edit: (event) => applyApprovedEdit(event),
    append_note: (event) => appendAssistantText(event),
    open_chat: (event) => openChat(event.path, event.node_id),
    note_changed: async ({ path, mtime, client }) => {
      if (client === clientId) return;
      const tab = tabByPath(path);
      if (!tab || tab.dirty || tab.mtime === mtime) return;
      try {
        const note = await api.get("/api/notes", { path });
        if (tab.dirty || tab.closed) return;
        tab.saved = note.content;
        tab.mtime = note.mtime;
        tab.editor.setValue(note.content);
        if (tab.id === state.activeId) { research.contentChanged(); renderPreview(); renderStatus(); }
      } catch { /* note may have been moved meanwhile */ }
    },
    vault_changed: async (change) => {
      if (change.renamed) {
        applyRename(...change.renamed);
        historyPanel.setItems(await api.get("/api/assistant/history"));
      }
      if (change.trashed) dropTabsUnder(change.trashed);
      loadTree();
      loadTags();
    },
    onOpen: () => {
      if (!state.connected) {
        state.connected = true;
        renderModel();
        renderStatus();
        loadTree();
      }
    },
    onError: () => {
      state.connected = false;
      renderModel();
      renderStatus();
    },
  });
}

// ---------------------------------------------------------------- boot
async function boot() {
  buildChrome();
  const [appState, session] = await Promise.all([
    api.get("/api/state"),
    api.get("/api/session").catch(() => ({})),
  ]);
  state.scripts = appState.scripts;
  state.vault = appState.vault;
  hudCard?.setHud(appState.hud);
  applyStatus(appState.status);

  state.preview = ["preview", "source", "hidden"].includes(session.preview) ? session.preview : "preview";
  state.liveWatch = session.liveWatch ?? true;
  state.split = typeof session.split === "number" ? session.split : 0.5;
  state.sidebar = session.sidebar ?? true;
  state.panel = session.panel ?? true;
  state.pinned = Array.isArray(session.pinned) ? [...new Set(session.pinned.filter((p) => typeof p === "string"))] : [];
  fitColumnsToWindow();
  for (const dir of session.expanded || []) sidebar.expanded.add(dir);

  await loadTree({ prunePinned: true });
  loadTags();
  historyPanel.setItems(await api.get("/api/assistant/history").catch(() => []));

  const known = new Set(flatNotes().map((n) => n.path));
  for (const path of session.tabs || []) {
    if (!known.has(path)) continue;
    try { await openNote(path, { activate: false }); } catch { /* skip missing notes */ }
  }
  const first = tabByPath(session.active) || state.tabs[0];
  state.view = session.view === "tree" && first ? "tree" : "editor";
  if (first) activate(first.id);
  else { renderWelcome(); updateLayout(); }

  connect();
  setInterval(renderStatus, 20000);
}

boot().catch((err) => {
  console.error(err);
  toast(`Uygulama başlatılamadı: ${err.message}`, "error", 8000);
});
