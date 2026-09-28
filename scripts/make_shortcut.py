"""Put a Concept Trail launcher on the desktop and in the app menu.

    python scripts/make_shortcut.py                 # notes in ./notes, as main.py
    python scripts/make_shortcut.py --vault PATH    # notes somewhere else

The launcher runs main.py with the Python running this script — pythonw.exe
beside it on Windows, so the app opens without a console window — and shows
the app icon (assets/icon). install.ps1 / install.sh call it after setting up
the app's own environment; a checkout run by hand can call it the same way.

Windows: a .lnk on the desktop and in the Start menu. Linux: a .desktop entry
in ~/.local/share/applications and on the desktop. macOS: a .command file on
the desktop.
"""
import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "main.py"
ICON_ICO = ROOT / "assets" / "icon" / "concept-trail.ico"
ICON_PNG = ROOT / "assets" / "icon" / "png" / "concept-trail-256.png"
NAME = "Concept Trail"
DESCRIPTION = "Yazılım fikirlerini soru soran bir asistanla olgunlaştıran not defteri"

# the WScript.Shell COM object writes .lnk files; every value arrives through
# an environment variable, so no path is ever quoted into the script
WINDOWS_SCRIPT = (
    "$ErrorActionPreference = 'Stop'; "
    "$shell = New-Object -ComObject WScript.Shell; "
    "foreach ($where in $env:CT_WHERE.Split(',')) { "
    "  $dir = [Environment]::GetFolderPath($where); "
    "  $link = $shell.CreateShortcut((Join-Path $dir ($env:CT_NAME + '.lnk'))); "
    "  $link.TargetPath = $env:CT_TARGET; $link.Arguments = $env:CT_ARGS; "
    "  $link.WorkingDirectory = $env:CT_DIR; $link.IconLocation = $env:CT_ICON + ',0'; "
    "  $link.Description = $env:CT_DESC; $link.Save(); "
    "  Write-Output (Join-Path $dir ($env:CT_NAME + '.lnk')) }"
)


def launcher_python() -> Path:
    exe = Path(sys.executable)
    windowless = exe.with_name("pythonw.exe")
    return windowless if sys.platform == "win32" and windowless.exists() else exe


def main_args(vault: Path | None) -> list[str]:
    args = [str(MAIN)]
    if vault is not None:
        args += ["--vault", str(vault)]
    return args


def windows(vault: Path | None, start_menu: bool) -> list[str]:
    places = ["Desktop"] + (["Programs"] if start_menu else [])
    env = {**os.environ, "CT_WHERE": ",".join(places), "CT_NAME": NAME,
           "CT_TARGET": str(launcher_python()), "CT_ARGS": subprocess.list2cmdline(main_args(vault)),
           "CT_DIR": str(ROOT), "CT_ICON": str(ICON_ICO), "CT_DESC": DESCRIPTION}
    done = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", WINDOWS_SCRIPT],
        env=env, capture_output=True, text=True, check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return [line.strip() for line in done.stdout.splitlines() if line.strip()]


def desktop_dir() -> Path:
    try:
        found = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, check=True).stdout.strip()
        if found:
            return Path(found)
    except (OSError, subprocess.CalledProcessError):
        pass
    return Path.home() / "Desktop"


def linux(vault: Path | None, start_menu: bool) -> list[str]:
    command = " ".join(shlex.quote(part) for part in [str(launcher_python()), *main_args(vault)])
    entry = (f"[Desktop Entry]\nType=Application\nName={NAME}\nComment={DESCRIPTION}\n"
             f"Exec={command}\nPath={ROOT}\nIcon={ICON_PNG}\nTerminal=false\n"
             f"Categories=Office;Development;\nStartupWMClass={NAME}\n")
    places = [desktop_dir()]
    if start_menu:
        places.append(Path.home() / ".local" / "share" / "applications")
    written = []
    for place in places:
        place.mkdir(parents=True, exist_ok=True)
        path = place / "concept-trail.desktop"
        path.write_text(entry, encoding="utf-8")
        path.chmod(0o755)
        written.append(str(path))
    return written


def macos(vault: Path | None, _start_menu: bool) -> list[str]:
    command = " ".join(shlex.quote(part) for part in [str(launcher_python()), *main_args(vault)])
    path = Path.home() / "Desktop" / f"{NAME}.command"
    path.write_text(f"#!/bin/sh\ncd {shlex.quote(str(ROOT))}\nexec {command}\n", encoding="utf-8")
    path.chmod(0o755)
    return [str(path)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Concept Trail kısayolu oluşturur")
    parser.add_argument("--vault", type=Path, help="notların klasörü (verilmezse main.py'nin varsayılanı: ./notes)")
    parser.add_argument("--no-start-menu", action="store_true", help="yalnız masaüstüne koy")
    args = parser.parse_args()
    make = windows if sys.platform == "win32" else macos if sys.platform == "darwin" else linux
    for path in make(args.vault.expanduser().resolve() if args.vault else None, not args.no_start_menu):
        print(f"Kısayol: {path}")


if __name__ == "__main__":
    main()
