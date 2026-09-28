// Themes: each one is a set of colour tokens on <html data-theme="…">
// (web/css/themes.css; "light" and "dark" live in redesign.css). The picker
// shows every theme as a small painted card and previews it on hover — the
// whole app changes under the pointer, and goes back if nothing is chosen.
import { icon } from "./icons.js";
import { esc, html } from "./util.js";

export const THEMES = [
  { id: "light", label: "Kâğıt", note: "Açık, sakin yeşil", dark: false, sw: ["#edf2ef", "#ffffff", "#147b70", "#23312d"] },
  { id: "dark", label: "Orman gecesi", note: "Koyu yeşil", dark: true, sw: ["#111b19", "#1c2925", "#62b9a5", "#ebf3ed"] },
  { id: "takimyildiz", label: "Takımyıldız", note: "Gece mavisi, fikir ağacıyla aynı gökyüzü", dark: true, sw: ["#070b18", "#10172d", "#6fe0c4", "#b9a6ff"] },
  { id: "gunbatimi", label: "Gün batımı", note: "Mor gece, mercan ışık", dark: true, sw: ["#1a1016", "#261821", "#ff8a5c", "#ffc15e"] },
  { id: "parsomen", label: "Parşömen", note: "Sıcak kâğıt, mürekkep kahvesi", dark: false, sw: ["#efe7d8", "#fdf9f1", "#a4532b", "#3b2f22"] },
  { id: "buzul", label: "Buzul", note: "Serin, net mavi", dark: false, sw: ["#e8eef5", "#ffffff", "#2f6fdb", "#1f2a37"] },
  { id: "kontrast", label: "Yüksek karşıtlık", note: "Siyah zemin, en okunaklı", dark: true, sw: ["#000000", "#0d0d0d", "#ffd400", "#ffffff"] },
];

export const themeOf = (id) => THEMES.find((t) => t.id === id) || THEMES[0];

let open = null;

/** The picker, under `anchor`. onPick(id) commits; the page shows each theme
 *  while the pointer rests on it and returns to `current` otherwise. */
export function openThemePicker(anchor, current, onPick) {
  if (open) { open.close(); return; }
  const root = document.documentElement;
  const pop = html(`<div class="theme-pop" role="menu" aria-label="Tema">
    <div class="theme-pop-head">${icon("sparkles", 14)}<b>Tema</b><span>Üstüne gel: dene · Tıkla: seç</span></div>
    <div class="theme-grid">${THEMES.map((t) => `
      <button class="theme-card${t.id === current ? " on" : ""}" data-theme-id="${t.id}" role="menuitemradio" aria-checked="${t.id === current}">
        <span class="theme-paint" style="--a:${t.sw[0]};--b:${t.sw[1]};--c:${t.sw[2]};--d:${t.sw[3]}">
          <i class="bar"></i><i class="card"></i><i class="dot"></i><i class="line"></i><i class="line s"></i>
        </span>
        <span class="theme-name">${esc(t.label)}${t.id === current ? icon("check", 12) : ""}</span>
        <span class="theme-note">${esc(t.note)}</span>
      </button>`).join("")}</div>
  </div>`);
  document.body.append(pop);
  const r = anchor.getBoundingClientRect();
  const w = pop.offsetWidth;
  pop.style.left = `${Math.max(8, Math.min(r.right - w, innerWidth - w - 8))}px`;
  pop.style.top = `${r.bottom + 8}px`;
  requestAnimationFrame(() => pop.classList.add("in"));

  const show = (id) => { root.dataset.theme = id; };
  pop.addEventListener("mouseover", (e) => {
    const card = e.target.closest("[data-theme-id]");
    if (card) show(card.dataset.themeId);
  });
  pop.addEventListener("mouseleave", () => show(current));
  pop.addEventListener("click", (e) => {
    const card = e.target.closest("[data-theme-id]");
    if (!card) return;
    current = card.dataset.themeId;
    close();
    onPick(current);
  });
  const dismiss = (e) => {
    if (e.type === "keydown" && e.key !== "Escape") return;
    if (e.type === "mousedown" && (pop.contains(e.target) || anchor.contains(e.target))) return;
    close();
  };
  function close() {
    show(current);
    pop.classList.remove("in");
    setTimeout(() => pop.remove(), 180);
    document.removeEventListener("mousedown", dismiss, true);
    document.removeEventListener("keydown", dismiss, true);
    open = null;
  }
  setTimeout(() => {
    document.addEventListener("mousedown", dismiss, true);
    document.addEventListener("keydown", dismiss, true);
  });
  open = { close };
}
