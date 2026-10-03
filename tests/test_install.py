"""The one-command install and the desktop launcher."""
import os
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
    assert (ROOT / "web" / "assets" / "concept-trail-64.png").is_file()
    assert (ROOT / "web" / "assets" / "concept-trail-256.png").is_file()


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


def test_without_a_desktop_window_the_app_opens_in_the_browser(monkeypatch):
    """A machine that cannot start the Qt window still gets the app."""
    sys.path.insert(0, str(ROOT))
    import main
    monkeypatch.setitem(sys.modules, "desktop.shell", None)          # the import fails, as without the libraries
    opened = []
    assert main.open_window("http://127.0.0.1:8765/", hud=False, opener=opened.append) is None
    assert opened == ["http://127.0.0.1:8765/"]


def test_a_turkish_message_does_not_fail_on_an_english_windows(tmp_path):
    """What GitHub's Windows runner hit: stdout a pipe in cp1252, and "Kısayol"."""
    script = ("import sys; sys.path.insert(0, sys.argv[1]); import make_shortcut; "
              "make_shortcut.tolerant_output(); print('Kısayol: ı ş ğ İ')")
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    env.pop("PYTHONUTF8", None)
    done = subprocess.run([sys.executable, "-c", script, str(ROOT / "scripts")], env=env, capture_output=True)
    assert done.returncode == 0, done.stderr.decode("cp1252", "replace")
    assert done.stdout.decode("cp1252").startswith("K?sayol")
    # and without it, the very failure
    bare = subprocess.run([sys.executable, "-c", "print('Kısayol')"], env=env, capture_output=True)
    assert bare.returncode != 0 and b"UnicodeEncodeError" in bare.stderr


# ------------------------------------------------- marker, wipe guard, uninstall
def bash_path(path: Path) -> str:
    """A Windows path as Git Bash wants it (/c/x/y); the scripts need an absolute path."""
    text = path.as_posix()
    return f"/{text[0].lower()}{text[2:]}" if sys.platform == "win32" and text[1:2] == ":" else text


def foreign_folder(tmp_path) -> Path:
    """Someone's own folder: not empty, and nothing like an install."""
    folder = tmp_path / "home"
    folder.mkdir()
    (folder / "thesis.docx").write_text("do not delete", encoding="utf-8")
    return folder


def fake_install(tmp_path, with_marker=True) -> Path:
    app = tmp_path / "app"
    (app / "server").mkdir(parents=True)
    (app / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (app / "notes").mkdir()
    (app / "notes" / "idea.md").write_text("# idea\n", encoding="utf-8")
    if with_marker:
        (app / ".concept-trail-app").write_text("ours\n", encoding="utf-8")
    return app


def script_env(tmp_path, app: Path) -> dict:
    return {**os.environ, "CT_APP_DIR": str(app), "CT_NO_PROMPT": "1", "CT_PORT": "1",
            "FIKIR_CONFIG_DIR": str(tmp_path / "config"), "HOME": str(tmp_path / "userhome")}


def test_both_installers_write_the_marker_and_the_uninstallers_look_for_it():
    for name in ("install.ps1", "install.sh", "uninstall.ps1", "uninstall.sh"):
        assert ".concept-trail-app" in (ROOT / name).read_text(encoding="utf-8"), name
    for name in ("install.ps1", "install.sh"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "8765" in text and "main.py" in text            # the running-copy check


@pytest.mark.skipif(real_bash() is None, reason="bash yok")
def test_the_unix_installer_will_not_wipe_a_folder_that_is_not_an_install(tmp_path):
    folder = foreign_folder(tmp_path)
    env = {**script_env(tmp_path, folder), "CT_APP_DIR": bash_path(folder), "CT_SOURCE": str(tmp_path / "none.tar.gz")}
    done = subprocess.run([real_bash(), str(ROOT / "install.sh")], env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    assert done.returncode != 0 and "kurulumuna benzemiyor" in done.stderr
    assert (folder / "thesis.docx").read_text(encoding="utf-8") == "do not delete"


@pytest.mark.skipif(shutil.which("powershell") is None, reason="PowerShell yok")
def test_the_windows_installer_will_not_wipe_a_folder_that_is_not_an_install(tmp_path):
    folder = foreign_folder(tmp_path)
    done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                           "-File", str(ROOT / "install.ps1")],
                          env=script_env(tmp_path, folder), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    assert done.returncode != 0 and "kurulumuna benzemiyor" in (done.stdout + done.stderr)
    assert (folder / "thesis.docx").read_text(encoding="utf-8") == "do not delete"


@pytest.mark.skipif(real_bash() is None, reason="bash yok")
def test_the_unix_uninstaller_refuses_a_foreign_folder_and_keeps_notes_without_a_sil(tmp_path):
    folder = foreign_folder(tmp_path)
    env = {**script_env(tmp_path, folder), "CT_APP_DIR": bash_path(folder)}
    done = subprocess.run([real_bash(), str(ROOT / "uninstall.sh")], env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    assert done.returncode != 0 and (folder / "thesis.docx").exists()

    app = fake_install(tmp_path)
    (tmp_path / "config" / "ConceptTrail").mkdir(parents=True)
    env = {**script_env(tmp_path, app), "CT_APP_DIR": bash_path(app)}
    done = subprocess.run([real_bash(), str(ROOT / "uninstall.sh")], env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    assert done.returncode == 0, done.stderr
    assert not (app / "main.py").exists() and not (app / ".concept-trail-app").exists()
    assert (app / "notes" / "idea.md").exists()                      # no "sil": the notes stay
    assert (tmp_path / "config" / "ConceptTrail").is_dir()           # no yes: the keys stay


@pytest.mark.skipif(shutil.which("powershell") is None, reason="PowerShell yok")
def test_the_windows_uninstaller_refuses_a_foreign_folder_and_keeps_notes_without_a_sil(tmp_path):
    def run(app):
        return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-File", str(ROOT / "uninstall.ps1")],
                              env=script_env(tmp_path, app), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    folder = foreign_folder(tmp_path)
    assert run(folder).returncode != 0 and (folder / "thesis.docx").exists()

    app = fake_install(tmp_path)
    (tmp_path / "config" / "ConceptTrail").mkdir(parents=True)
    done = run(app)
    assert done.returncode == 0, done.stdout + done.stderr
    assert not (app / "main.py").exists() and (app / "notes" / "idea.md").exists()
    assert (tmp_path / "config" / "ConceptTrail").is_dir()
