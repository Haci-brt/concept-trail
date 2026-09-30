#!/usr/bin/env bash
# Concept Trail — macOS / Linux'tan kaldırma:
#
#   curl -fsSL https://raw.githubusercontent.com/Haci-brt/concept-trail/main/uninstall.sh | bash
#
# ya da kurulu kopyasıyla:  bash ~/.local/share/concept-trail/uninstall.sh
#
# Uygulama klasörünü ve install.sh'ın koyduğu kısayolları (masaüstü, Linux'ta
# uygulama menüsü) kaldırır. Ayar klasörünü (~/.config/ConceptTrail: model
# sağlayıcıları, API anahtarları, tercihler) silmeden önce sorar. Notlara
# dokunmaz; notlar uygulama klasörünün içindeyse onları silmek için ayrıca,
# açıkça onay ister.
#
# Ayarlanabilir (ortam değişkeni): CT_APP_DIR (kurulumda verdiysen aynısı),
# CT_PORT (açık uygulamanın arandığı port, varsayılan 8765), CT_NO_PROMPT=1
# (hiçbir şey sorma, her soruya "hayır": ayarlar ve notlar kalır).
set -euo pipefail

MARKER=".concept-trail-app"
PORT="${CT_PORT:-8765}"
APP_DIR="${CT_APP_DIR:-$HOME/.local/share/concept-trail}"
case "$APP_DIR" in /*) ;; *) APP_DIR="$PWD/$APP_DIR" ;; esac
APP_DIR="${APP_DIR%/}"
# the shortcut holds the resolved path (make_shortcut.py resolves it)
APP_REAL="$(cd "$APP_DIR" 2>/dev/null && pwd -P || printf '%s' "$APP_DIR")"
# where the app keeps its settings (server/providers.py: config_dir)
CONFIG_BASE="${FIKIR_CONFIG_DIR:-${APPDATA:-${XDG_CONFIG_HOME:-$HOME/.config}}}"
DEFAULT_VAULT="$HOME/Documents/Concept Trail"

step() { printf '\033[36m» %s\033[0m\n' "$1"; }
done_() { printf '\033[32m✓ %s\033[0m\n' "$1"; }

# Read from the terminal, not stdin: under `curl | bash` stdin is this script.
# No terminal to ask (CI, a pipe) or CT_NO_PROMPT=1 means the answer is no.
answer_from_tty() {
  local answer=""
  if [ -n "${CT_NO_PROMPT:-}" ]; then echo >&2; return; fi
  { read -r answer < /dev/tty; } 2>/dev/null || { answer=""; echo >&2; }
  printf '%s' "$answer"
}

ask() {
  printf '%s [e/H] ' "$1"
  case "$(answer_from_tty)" in e|E|evet|Evet|y|Y|yes|Yes) return 0 ;; *) return 1 ;; esac
}

ours() {
  [ -e "$1/$MARKER" ] || { [ -f "$1/main.py" ] && [ -d "$1/server" ]; }
}

# the same check as install.sh
running() {
  local procs state
  procs="$(ps -A -o command= 2>/dev/null || true)"
  [[ "$procs" == *"$1/main.py"* || "$procs" == *"$1/.venv/"* ]] && return 0
  command -v curl >/dev/null 2>&1 || return 1
  state="$(curl -fsS --max-time 3 "http://127.0.0.1:$PORT/api/state" 2>/dev/null || true)"
  [[ "$state" == *'"app":"concept-trail"'* || "$state" == *'"app": "concept-trail"'* ]]
}

desktop_dir() {
  local found=""
  found="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
  printf '%s' "${found:-$HOME/Desktop}"
}

printf '\n  Concept Trail kaldırılıyor\n  Uygulama: %s\n\n' "$APP_DIR"

REMOVE_APP=""
if [ ! -e "$APP_DIR" ]; then
  echo "  Uygulama klasörü yok (zaten kaldırılmış olabilir); kısayollara ve ayarlara bakılıyor."
elif ! ours "$APP_DIR"; then
  echo "$APP_DIR bir Concept Trail kurulumuna benzemiyor; hiçbir şey silinmedi. Kurulumda CT_APP_DIR verdiysen kaldırırken de aynısını ver." >&2
  exit 1
elif running "$APP_DIR" || { [ "$APP_REAL" != "$APP_DIR" ] && running "$APP_REAL"; }; then
  echo "Concept Trail şu an açık. Önce uygulamayı kapat (açık pencereyi ve varsa sunucuyu), sonra yeniden çalıştır." >&2
  exit 1
else
  REMOVE_APP=1
fi

# Notes kept inside the app folder (main.py's default ./notes) are the
# writer's work: removed only when asked for by name, never by a plain yes.
NOTES="$APP_DIR/notes"
KEEP_NOTES=1
if [ -n "$REMOVE_APP" ] && [ -d "$NOTES" ] && [ -n "$(ls -A "$NOTES" 2>/dev/null)" ]; then
  printf '\033[33m  Uygulama klasörünün içinde notlar var: %s\033[0m\n' "$NOTES"
  printf "  Bu notlar da KALICI olarak silinsin mi? Silmek için 'sil' yaz, korumak için Enter'a bas: "
  if [ "$(answer_from_tty)" = "sil" ]; then KEEP_NOTES=""; fi
fi

if [ -n "$REMOVE_APP" ]; then
  step "Uygulama klasörü kaldırılıyor"
  case "$PWD/" in "$APP_DIR"/*|"$APP_REAL"/*) cd "$HOME" ;; esac
  if [ -n "$KEEP_NOTES" ]; then
    find "$APP_DIR" -mindepth 1 -maxdepth 1 ! -name notes -exec rm -rf {} +
  else
    find "$APP_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  fi
  if rmdir "$APP_DIR" 2>/dev/null; then
    done_ "Uygulama kaldırıldı"
  else
    done_ "Uygulama kaldırıldı; notlar yerinde bırakıldı: $NOTES"
  fi
fi

# Only the shortcuts that open this install; a checkout's own shortcut stays.
step "Kısayollar"
for link in "$(desktop_dir)/concept-trail.desktop" "$HOME/.local/share/applications/concept-trail.desktop" \
            "$HOME/Desktop/Concept Trail.command"; do
  [ -f "$link" ] || continue
  if grep -qF -e "$APP_DIR/main.py" -e "$APP_REAL/main.py" "$link"; then
    rm -f "$link"
    done_ "Kısayol kaldırıldı: $link"
  else
    echo "  Başka bir klasörü açan kısayol bırakıldı: $link"
  fi
done

CONFIG_DIRS=()
for name in ConceptTrail FikirNotDefteri; do
  if [ -d "$CONFIG_BASE/$name" ]; then CONFIG_DIRS+=("$CONFIG_BASE/$name"); fi
done
if [ "${#CONFIG_DIRS[@]}" -gt 0 ]; then
  printf '\n  Ayarlar: %s\n' "${CONFIG_DIRS[*]}"
  echo "  (model sağlayıcıları, API anahtarları, araştırma token'ı, tercihler, günlük)"
  if ask "  Ayarlar da silinsin mi?"; then
    rm -rf "${CONFIG_DIRS[@]}"
    done_ "Ayarlar silindi"
  else
    echo "  Ayarlar yerinde bırakıldı; yeniden kurarsan kaldığın yerden devam eder."
  fi
fi

printf '\n'
done_ "Concept Trail kaldırıldı."
echo "  Notlarına dokunulmadı (kurulumun varsayılan yeri: $DEFAULT_VAULT)."
printf '\n'
