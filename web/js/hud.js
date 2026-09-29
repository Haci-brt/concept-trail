// The always-on-top desktop HUD window. It only shows the suggestion card and
// tells the Qt shell how big to be (or to hide) after every change.
//
// The window is hidden most of the time, and hidden pages get no
// requestAnimationFrame or ResizeObserver callbacks — so sizes are measured
// synchronously right after each render instead.
import { api, connectEvents } from "./api.js";
import { desktopCall } from "./desktop.js";
import { HudCard } from "./hudcard.js";
import { startI18n } from "./i18n.js";

await startI18n();

function syncTheme() {
  let theme = "light";
  try { theme = localStorage.getItem("fikir.appearance.v1") || "light"; } catch { /* private window */ }
  document.documentElement.dataset.theme = theme;
}
syncTheme();
window.addEventListener("storage", (event) => {
  if (event.key === "fikir.appearance.v1") syncTheme();
});

const host = document.getElementById("card");
let lastReport = "";

function report(visible) {
  // the body is as tall as the window (base.css), so its scrollHeight would
  // only ever grow: measure the card and the body's padding around it
  const pad = getComputedStyle(document.body);
  const height = visible ? Math.ceil(host.offsetHeight + parseFloat(pad.paddingTop) + parseFloat(pad.paddingBottom)) : 0;
  const key = `${visible}:${height}`;
  if (key === lastReport) return;
  lastReport = key;
  desktopCall("setHudState", visible, height);
}

const card = new HudCard(host, { onChange: report });

// once visible, fonts and wrapping can still settle — re-measure then
new ResizeObserver(() => report(Boolean(host.firstElementChild))).observe(host);

connectEvents({
  snapshot: (s) => { card.setStatus(s.status); card.setHud(s.hud); },
  status: (s) => card.setStatus(s),
  hud: (h) => card.setHud(h),
  thinking: (t) => card.setThinking(t),
  flash: (f) => card.showFlash(f),
  open_chat: () => desktopCall("focusMain"),
});

host.addEventListener("mousedown", (e) => {
  if (e.button !== 0 || e.target.closest("button")) return;
  // a long proposal scrolls inside the card: its scroll bar is not a handle
  const el = e.target;
  if (el.scrollHeight > el.clientHeight && e.offsetX >= el.clientWidth) return;
  desktopCall("startMove");
});

api.get("/api/state").then((s) => { card.setStatus(s.status); card.setHud(s.hud); }).catch(() => {});
