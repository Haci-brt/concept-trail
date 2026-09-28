"""The one-command install and the desktop launcher."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import make_shortcut  # noqa: E402


@pytest.mark.skipif(shutil.which("powershell") is None, reason="PowerShell yok")
def test_the_windows_installer_parses():
    script = ("$errors = $null; [System.Management.Automation.Language.Parser]::ParseFile("
              f"'{ROOT / 'install.ps1'}', [ref]$null, [ref]$errors) | Out-Null; $errors.Count")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "0", out.stdout


def real_bash() -> str | None:
    """Git Bash on Windows; System32\\bash.exe only starts WSL, which may not be set up."""
    git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    if sys.platform == "win32" and git_bash.exists():
        return str(git_bash)
    found = shutil.which("bash")
    return None if found is None or "system32" in found.lower() else found


@pytest.mark.skipif(real_bash() is None, reason="bash yok")
def test_the_unix_installer_parses():
    subprocess.run([real_bash(), "-n", str(ROOT / "install.sh")], check=True)


def test_the_installers_fetch_this_repository_and_keep_notes_on_update():
    for name in ("install.ps1", "install.sh"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "Haci-brt/concept-trail" in text
        assert ".venv" in text and "notes" in text          # an update keeps both
        assert "make_shortcut.py" in text and "--vault" in text


def test_the_icon_is_there_for_the_launcher_and_the_window():
    assert make_shortcut.ICON_ICO.is_file() and make_shortcut.ICON_PNG.is_file()
    assert (ROOT / "web" / "assets" / "concept-trail.svg").is_file()


def test_the_launcher_opens_the_chosen_vault(tmp_path):
    assert make_shortcut.main_args(None) == [str(ROOT / "main.py")]
    assert make_shortcut.main_args(tmp_path) == [str(ROOT / "main.py"), "--vault", str(tmp_path)]


def test_a_linux_launcher_is_a_desktop_entry_with_the_icon(tmp_path, monkeypatch):
    monkeypatch.setattr(make_shortcut, "desktop_dir", lambda: tmp_path / "Desktop")
    monkeypatch.setattr(make_shortcut.Path, "home", staticmethod(lambda: tmp_path))
    written = make_shortcut.linux(tmp_path / "vault", start_menu=True)
    assert len(written) == 2
    entry = Path(written[0]).read_text(encoding="utf-8")
    assert "Name=Concept Trail" in entry and f"Icon={make_shortcut.ICON_PNG}" in entry
    assert "--vault" in entry and "Terminal=false" in entry
