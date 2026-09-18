// Bridge to the Qt desktop shell (desktop/shell.py). In a normal browser
// there is no bridge and every call is a no-op.

const params = new URLSearchParams(location.search);
export const isDesktop = params.has("desktop");
export const desktopHud = isDesktop && params.get("hud") !== "0";

export const desktopReady = new Promise((resolve) => {
  if (!isDesktop) return resolve(null);
  if (window.desktop) return resolve(window.desktop);
  window.addEventListener("desktop-ready", () => resolve(window.desktop), { once: true });
  setTimeout(() => resolve(window.desktop ?? null), 4000);
});

export async function desktopCall(method, ...args) {
  const bridge = await desktopReady;
  if (bridge && typeof bridge[method] === "function") bridge[method](...args);
}

export function openExternal(url) {
  if (isDesktop) desktopCall("openExternal", url);
  else window.open(url, "_blank", "noopener");
}
