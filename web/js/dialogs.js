// Small modal prompt/confirm dialogs and a context menu.
import { api } from "./api.js";
import { icon } from "./icons.js";
import { esc, html, trapFocus } from "./util.js";

let versionAsked = null;

/** "0.3.0", as the server has it (server/settings.py is the one source); "" if unknown. */
export function appVersion() {
  versionAsked ??= api.get("/api/version").then((v) => v.version || "").catch(() => {
    versionAsked = null;              // a server that was not up yet is asked again next time
    return "";
  });
  return versionAsked;
}

function modal(markup, { onKey } = {}) {
  const overlay = html('<div class="overlay"></div>');
  const dialog = html(markup);
  document.body.append(overlay, dialog);
  const releaseFocus = trapFocus(dialog);
  const close = () => {
    overlay.remove();
    dialog.remove();
    document.removeEventListener("keydown", keyHandler, true);
    releaseFocus();
  };
  const keyHandler = (e) => onKey?.(e, close);
  document.addEventListener("keydown", keyHandler, true);
  overlay.addEventListener("mousedown", () => onKey?.({ key: "Escape", preventDefault() {}, stopPropagation() {} }, close));
  return { dialog, close };
}

export function promptDialog({ title, message = "", value = "", placeholder = "", confirmText = "Tamam", validate }) {
  return new Promise((resolve) => {
    let done = false;
    const finish = (result, close) => {
      if (done) return;
      done = true;
      close();
      resolve(result);
    };
    const { dialog, close } = modal(
      `<div class="dialog" role="dialog" aria-modal="true">
        <h2>${esc(title)}</h2>
        ${message ? `<p>${esc(message)}</p>` : ""}
        <input class="field" type="text" spellcheck="false" placeholder="${esc(placeholder)}">
        <div class="field-error"></div>
        <div class="actions">
          <button class="btn btn-ghost" data-act="cancel">Vazgeç</button>
          <button class="btn btn-accent" data-act="ok">${esc(confirmText)}</button>
        </div>
      </div>`,
      {
        onKey: (e, closeFn) => {
          if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); finish(null, closeFn); }
          if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); submit(); }
        },
      },
    );
    const input = dialog.querySelector("input");
    const error = dialog.querySelector(".field-error");
    input.value = value;
    const submit = () => {
      const v = input.value.trim();
      const problem = !v ? "Bir isim yaz." : validate?.(v);
      if (problem) { error.textContent = problem; input.focus(); return; }
      finish(v, close);
    };
    dialog.querySelector('[data-act="ok"]').onclick = submit;
    dialog.querySelector('[data-act="cancel"]').onclick = () => finish(null, close);
    input.focus();
    const dot = value.lastIndexOf(".");
    input.setSelectionRange(0, dot > 0 ? dot : value.length);
  });
}

export function confirmDialog({ title, message, confirmText = "Onayla", danger = false }) {
  return new Promise((resolve) => {
    let done = false;
    const finish = (result, close) => {
      if (done) return;
      done = true;
      close();
      resolve(result);
    };
    const { dialog, close } = modal(
      `<div class="dialog" role="alertdialog" aria-modal="true">
        <h2>${esc(title)}</h2>
        <p>${esc(message)}</p>
        <div class="actions">
          <button class="btn btn-ghost" data-act="cancel">Vazgeç</button>
          <button class="btn ${danger ? "btn-danger" : "btn-accent"}" data-act="ok">${esc(confirmText)}</button>
        </div>
      </div>`,
      {
        onKey: (e, closeFn) => {
          if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); finish(false, closeFn); }
          if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); finish(true, closeFn); }
        },
      },
    );
    dialog.querySelector('[data-act="ok"]').onclick = () => finish(true, close);
    dialog.querySelector('[data-act="cancel"]').onclick = () => finish(false, close);
    dialog.querySelector('[data-act="ok"]').focus();
  });
}

/** One of several named ways out; Escape and a click outside give `fallback`. */
export function choiceDialog({ title, message, choices, fallback }) {
  return new Promise((resolve) => {
    let done = false;
    const finish = (result, close) => {
      if (done) return;
      done = true;
      close();
      resolve(result);
    };
    const { dialog, close } = modal(
      `<div class="dialog choice-dialog" role="alertdialog" aria-modal="true">
        <h2>${esc(title)}</h2>
        <p>${esc(message)}</p>
        <div class="choices">
          ${choices.map((c) => `<button class="btn ${c.accent ? "btn-accent" : ""}" data-choice="${esc(c.id)}">
            <span>${esc(c.label)}</span>${c.hint ? `<small>${esc(c.hint)}</small>` : ""}</button>`).join("")}
        </div>
      </div>`,
      {
        onKey: (e, closeFn) => {
          if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); finish(fallback, closeFn); }
        },
      },
    );
    dialog.addEventListener("click", (e) => {
      const id = e.target.closest("[data-choice]")?.dataset.choice;
      if (id) finish(id, close);
    });
    dialog.querySelector("[data-choice]").focus();
  });
}

const SHORTCUTS = [
  ["Not ara / komutlar", "Ctrl P"],
  ["Yeni not", "Ctrl N · Ctrl Alt N"],
  ["Sekmeyi kapat", "Ctrl W · Ctrl Alt W"],
  ["Sonraki sekme", "Ctrl Tab"],
  ["Hemen kaydet", "Ctrl S"],
  ["Asistana şimdi sor", "Ctrl Enter"],
  ["Önerilen devamı al / bir kelimesini al", "Tab · Ctrl →"],
  ["Devam önerisi iste / kapat", "Ctrl Space · Esc"],
  ["Fikir ağacı", "Ctrl G"],
  ["Ağaçta sıradaki soru / sığdır", "N · F"],
  ["Master prompt", "Ctrl Shift M"],
  ["Odak kipi", "Ctrl Shift F"],
  ["Kalın / italik / kod", "Ctrl B · Ctrl I · Ctrl E"],
  ["Bağlantı", "Ctrl K"],
  ["Girinti", "Tab · Shift Tab"],
  ["Kenar çubuğu / panel", "Ctrl \\ · Ctrl Shift \\"],
  ["Liste, not ve panel arasında gez", "F6 · Shift F6"],
  ["Sıradaki soruyu cevapla (komut)", "Ctrl P"],
  ["Rotayı düzelt (komut)", "Ctrl P"],
];

export function shortcutsDialog() {
  const rows = SHORTCUTS.map(([label, keys]) =>
    `<span>${esc(label)}</span><span>${keys.split(" · ").map((combo) => combo.split(" ").map((k) => `<kbd>${esc(k)}</kbd>`).join(" ")).join(" &nbsp;/&nbsp; ")}</span>`,
  ).join("");
  const { dialog, close } = modal(
    `<div class="dialog wide" role="dialog" aria-modal="true">
      <h2>Klavye kısayolları</h2>
      <p>Tarayıcıda Ctrl N / Ctrl W tarayıcıya gider — orada Ctrl Alt ile kullan.</p>
      <div class="shortcut-grid">${rows}</div>
      <div class="actions"><span class="app-version" translate="no"></span><button class="btn" data-act="ok">Kapat</button></div>
    </div>`,
    { onKey: (e, closeFn) => { if (e.key === "Escape" || e.key === "Enter") { e.preventDefault(); closeFn(); } } },
  );
  dialog.querySelector('[data-act="ok"]').onclick = close;
  appVersion().then((version) => {
    if (version) dialog.querySelector(".app-version").textContent = `Concept Trail ${version}`;
  });
}

let openMenuEl = null;

export function closeMenu() {
  openMenuEl?.remove();
  openMenuEl = null;
}

/** items: [{ label, icon, action, danger, checked, hint } | "sep"] */
export function openMenu(x, y, items) {
  closeMenu();
  const menu = html('<div class="menu" role="menu"></div>');
  for (const item of items) {
    if (item === "sep") {
      menu.append(html('<div class="menu-sep"></div>'));
      continue;
    }
    const el = html(`<button class="menu-item${item.danger ? " danger" : ""}${item.checked ? " checked" : ""}" role="menuitem">
      ${item.icon ? icon(item.icon, 15) : ""}<span>${esc(item.label)}</span>${item.hint ? `<span class="hint">${esc(item.hint)}</span>` : ""}
    </button>`);
    el.onclick = () => { closeMenu(); item.action?.(); };
    menu.append(el);
  }
  document.body.append(menu);
  const r = menu.getBoundingClientRect();
  menu.style.left = `${Math.min(x, innerWidth - r.width - 8)}px`;
  menu.style.top = `${y + r.height > innerHeight - 8 ? Math.max(8, y - r.height) : y}px`;
  openMenuEl = menu;
  const dismiss = (e) => {
    if (e.type === "keydown" && e.key !== "Escape") return;
    if (e.type === "mousedown" && menu.contains(e.target)) return;
    closeMenu();
    document.removeEventListener("mousedown", dismiss, true);
    document.removeEventListener("keydown", dismiss, true);
    window.removeEventListener("blur", dismiss);
  };
  setTimeout(() => {
    document.addEventListener("mousedown", dismiss, true);
    document.addEventListener("keydown", dismiss, true);
    window.addEventListener("blur", dismiss);
  });
}
