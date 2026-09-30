#!/usr/bin/env bash
# Concept Trail — macOS / Linux için tek komutla kurulum:
#
#   curl -fsSL https://raw.githubusercontent.com/Haci-brt/concept-trail/main/install.sh | bash
#
# Uygulamayı ~/.local/share/concept-trail içine indirir, kendi Python ortamını
# kurar, masaüstüne (Linux'ta uygulama menüsüne de) bir kısayol koyar ve
# uygulamayı açar. Notlar ~/Documents/Concept Trail içinde durur; güncelleme
# (aynı komutu yeniden çalıştırmak) onlara dokunmaz.
#
# Ayarlanabilir (ortam değişkeni): CT_APP_DIR, CT_VAULT, CT_SOURCE (tar.gz yolu
# ya da adresi), CT_NO_LAUNCH=1, CT_NO_SHORTCUT=1, CT_PORT (açık uygulamanın
# arandığı port, varsayılan 8765).
#
# Kaldırmak için: uninstall.sh (README, "Kaldırma").
set -euo pipefail

REPO="Haci-brt/concept-trail"
BRANCH="main"
MARKER=".concept-trail-app"      # written into the app folder: "this one is ours to replace"
PORT="${CT_PORT:-8765}"
APP_DIR="${CT_APP_DIR:-$HOME/.local/share/concept-trail}"
case "$APP_DIR" in /*) ;; *) APP_DIR="$PWD/$APP_DIR" ;; esac
APP_DIR="${APP_DIR%/}"
VAULT="${CT_VAULT:-$HOME/Documents/Concept Trail}"
SOURCE="${CT_SOURCE:-https://github.com/$REPO/archive/refs/heads/$BRANCH.tar.gz}"

step() { printf '\033[36m» %s\033[0m\n' "$1"; }
done_() { printf '\033[32m✓ %s\033[0m\n' "$1"; }

# Only an earlier install of this app may be emptied: the marker, or main.py
# and server/ from before the marker existed. A CT_APP_DIR pointed at a
# folder in use (the home folder, say) must never be wiped.
ours() {
  [ -e "$1/$MARKER" ] || { [ -f "$1/main.py" ] && [ -d "$1/server" ]; }
}

# A running copy keeps its old code in memory, and a new launch would only
# reuse its server on the same port.
running() {
  local procs state
  procs="$(ps -A -o command= 2>/dev/null || true)"
  [[ "$procs" == *"$1/main.py"* || "$procs" == *"$1/.venv/"* ]] && return 0
  command -v curl >/dev/null 2>&1 || return 1
  state="$(curl -fsS --max-time 3 "http://127.0.0.1:$PORT/api/state" 2>/dev/null || true)"
  [[ "$state" == *'"app":"concept-trail"'* || "$state" == *'"app": "concept-trail"'* ]]
}

printf '\n  Concept Trail kuruluyor\n  Uygulama: %s\n  Notlar:   %s\n\n' "$APP_DIR" "$VAULT"

# before anything is downloaded: may this folder be replaced, and now?
if [ -d "$APP_DIR" ] && [ -n "$(ls -A "$APP_DIR" 2>/dev/null)" ]; then
  if ! ours "$APP_DIR"; then
    echo "$APP_DIR boş değil ve bir Concept Trail kurulumuna benzemiyor. İçindekiler silinmesin diye kurulum durdu; hiçbir şeye dokunulmadı. CT_APP_DIR ile boş ya da yeni bir klasör ver." >&2
    exit 1
  fi
  if running "$APP_DIR"; then
    echo "Concept Trail şu an açık. Önce uygulamayı kapat (açık pencereyi ve varsa sunucuyu), sonra komutu yeniden çalıştır." >&2
    exit 1
  fi
fi

step "Python aranıyor"
PYTHON=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && \
     "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PYTHON="$(command -v "$candidate")"; break
  fi
done
if [ -z "$PYTHON" ]; then
  echo "Python 3.10 ya da üstü gerekli (python3 -m venv ile birlikte). Kurup komutu yeniden çalıştır." >&2
  exit 1
fi
done_ "Python: $PYTHON"

step "Uygulama indiriliyor"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
if [ -f "$SOURCE" ]; then cp "$SOURCE" "$TMP/app.tar.gz"; else curl -fsSL "$SOURCE" -o "$TMP/app.tar.gz"; fi
mkdir -p "$TMP/x"
tar -xzf "$TMP/app.tar.gz" -C "$TMP/x"
EXTRACTED="$(find "$TMP/x" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
[ -f "$EXTRACTED/main.py" ] || { echo "İndirilen arşivde main.py yok: $SOURCE" >&2; exit 1; }
mkdir -p "$APP_DIR"
# an update replaces the code, never the environment or notes kept beside it
find "$APP_DIR" -mindepth 1 -maxdepth 1 ! -name .venv ! -name notes -exec rm -rf {} +
cp -R "$EXTRACTED"/. "$APP_DIR"/
printf 'Concept Trail kurulum klasörü. install.sh güncellerken bu klasörün içini yeniler; uninstall.sh kaldırır.\n' > "$APP_DIR/$MARKER"
done_ "Uygulama indirildi"

VENV="$APP_DIR/.venv"
if [ ! -x "$VENV/bin/python" ]; then
  step "Python ortamı oluşturuluyor"
  "$PYTHON" -m venv "$VENV"
fi
step "Bağımlılıklar kuruluyor (ilk kurulumda birkaç dakika sürebilir; PyQt6 WebEngine büyük)"
"$VENV/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade pip
"$VENV/bin/python" -m pip install --quiet --disable-pip-version-check -r "$APP_DIR/requirements.txt"
done_ "Bağımlılıklar kuruldu"

mkdir -p "$VAULT"
if [ -z "${CT_NO_SHORTCUT:-}" ]; then
  step "Kısayol oluşturuluyor"
  "$VENV/bin/python" "$APP_DIR/scripts/make_shortcut.py" --vault "$VAULT"
fi

printf '\n'
done_ "Concept Trail kuruldu."
echo "  Açmak için masaüstündeki Concept Trail kısayoluna çift tıkla."
echo "  Güncellemek için aynı komutu yeniden çalıştır; notların korunur."
echo "  Kaldırmak için: bash \"$APP_DIR/uninstall.sh\" (notların $VAULT içinde kalır)."
printf '\n'

if [ -z "${CT_NO_LAUNCH:-}" ]; then
  (cd "$APP_DIR" && nohup "$VENV/bin/python" "$APP_DIR/main.py" --vault "$VAULT" >/dev/null 2>&1 &)
fi
