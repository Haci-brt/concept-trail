// The always-on-top desktop HUD window. It only shows the suggestion card and
// tells the Qt shell how big to be (or to hide) after every change.
//
// The window is hidden most of the time, and hidden pages get no
// requestAnimationFrame or ResizeObserver callbacks — so sizes are measured
// synchronously right after each render instead.
import { api, connectEvents } from "./api.js";
import { desktopCall } from "./desktop.js";
import { HudCard } from "./hudcard.js";

const host = document.getElementById("card");
const STEP = 8;          // ignore sub-pixel reflow: the window must not twitch
let lastVisible = null;
let lastHeight = 0;

function report(visible) {
  if (!visible) {
    if (lastVisible === false) return;
    lastVisible = false;
    lastHeight = 0;
    desktopCall("setHudState", false, 0);
    return;
  }
  const height = Math.ceil(document.body.scrollHeight);
  // a card is on screen: a zero here is a measurement taken mid-render, and
  // passing it on would hide the window for a frame — which reads as a glitch
  if (height <= 0) return;
  if (lastVisible === true && Math.abs(height - lastHeight) < STEP) return;
  lastVisible = true;
  lastHeight = height;
  desktopCall("setHudState", true, height);
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
  if (e.button === 0 && !e.target.closest("button, textarea, input")) desktopCall("startMove");
});

api.get("/api/state").then((s) => { card.setStatus(s.status); card.setHud(s.hud); }).catch(() => {});
