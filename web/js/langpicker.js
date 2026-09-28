// The language picker: the interface language and the language the
// assistant writes in, side by side. Changing the interface reloads the page
// (every panel draws itself again in the new language); the assistant's
// language changes at once and applies from its next question on. The
// assistant follows the interface unless the writer has set it apart.
import { api } from "./api.js";
import { LANGUAGES, lang, setLanguage } from "./i18n.js";
import { icon } from "./icons.js";
import { esc, html, toast } from "./util.js";

let open = null;

export async function openLanguagePicker(anchor) {
  if (open) { open.close(); return; }
  let prefs = { ui_language: lang, assistant_language: lang };
  try { prefs = await api.get("/api/preferences"); } catch { /* the server keeps the default */ }

  const row = (group, current) => LANGUAGES.map((l) => `
    <button class="lang-opt${l.id === current ? " on" : ""}" data-group="${group}" data-lang="${l.id}"
      role="menuitemradio" aria-checked="${l.id === current}" translate="no">
      <span class="lang-code">${l.id.toUpperCase()}</span><span class="lang-name">${esc(l.label)}</span>${l.id === current ? icon("check", 12) : ""}
    </button>`).join("");
  const pop = html(`<div class="lang-pop" role="menu" aria-label="Dil">
    <div class="lang-head">${icon("globe", 14)}<b>Dil</b></div>
    <div class="lang-label">Arayüz dili</div>
    <div class="lang-grid">${row("ui", lang)}</div>
    <div class="lang-label">Asistanın dili<span>Sorular, öneriler, sohbet ve nota eklenecek metin</span></div>
    <div class="lang-grid">${row("assistant", prefs.assistant_language)}</div>
    <p class="lang-note">Arayüz dili değişince sayfa yeniden yüklenir. Asistan, sen ayrı seçmedikçe arayüzle aynı dilde yazar.</p>
  </div>`);
  document.body.append(pop);
  const r = anchor.getBoundingClientRect();
  pop.style.left = `${Math.max(8, Math.min(r.right - pop.offsetWidth, innerWidth - pop.offsetWidth - 8))}px`;
  pop.style.top = `${r.bottom + 8}px`;
  requestAnimationFrame(() => pop.classList.add("in"));

  pop.addEventListener("click", async (e) => {
    const opt = e.target.closest("[data-lang]");
    if (!opt) return;
    const id = opt.dataset.lang;
    if (opt.dataset.group === "ui") {
      if (id === lang) return close();
      const follows = prefs.assistant_language === lang;
      try {
        await api.put("/api/preferences", follows ? { ui_language: id, assistant_language: id } : { ui_language: id });
      } catch { /* the page language still changes */ }
      setLanguage(id);
      location.reload();
      return;
    }
    try {
      prefs = await api.put("/api/preferences", { assistant_language: id });
      const name = LANGUAGES.find((l) => l.id === id)?.label || id;
      toast(`Asistan artık ${name} yazacak.`, "success");
      close();
    } catch (err) {
      toast(err.message, "error");
    }
  });
  const dismiss = (e) => {
    if (e.type === "keydown" && e.key !== "Escape") return;
    if (e.type === "mousedown" && (pop.contains(e.target) || anchor.contains(e.target))) return;
    close();
  };
  function close() {
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

/** On a first start in another language, bring the stored choice along. */
export async function syncLanguage() {
  try {
    const prefs = await api.get("/api/preferences");
    if (prefs.ui_language && prefs.ui_language !== lang && !localStorage.getItem("fikir.ui-lang.v1")) {
      setLanguage(prefs.ui_language);
      location.reload();
    }
  } catch { /* offline: keep what the page has */ }
}
