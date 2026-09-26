// The always-on-top desktop HUD window. It only shows the suggestion card and
// tells the Qt shell how big to be (or to hide) after every change.
//
// The window is hidden most of the time, and hidden pages get no
// requestAnimationFrame or ResizeObserver callbacks — so sizes are measured
// synchronously right after each render instead.
import { api, connectEvents } from "./api.js";
import { desktopCall } from "./desktop.js";
import { HudCard } from "./hudcard.js";

function syncTheme() {
  document.documentElement.dataset.theme = localStorage.getItem("fikir.appearance.v1") === "dark" ? "dark" : "light";
}
syncTheme();
window.addEventListener("storage", (event) => {
  if (event.key === "fikir.appearance.v1") syncTheme();
});

const host = document.getElementById("card");
let lastReport = "";

function report(visible) {
  const height = visible ? Math.ceil(document.body.scrollHeight) : 0;
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
  if (e.button === 0 && !e.target.closest("button")) desktopCall("startMove");
});

api.get("/api/state").then((s) => { card.setStatus(s.status); card.setHud(s.hud); }).catch(() => {});
