"""Paths and constants shared by the web server and the launchers."""
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
DEFAULT_VAULT = ROOT / "notes"

APP_ID = "fikir-not-defteri"
VERSION = "0.2.0"
DEFAULT_PORT = 8765

LAUNCH_SCRIPTS = {
    # "Qwen3.8 dense" removed 2026-09-17: its binary AND model file are both
    # gone from disk (see project_qwen38_opt memory) — it was a dead button
    # that only errored on click. Re-add once it points at a real model.
    "Qwen3.8 Flash-Next — sohbet (8899)": Path.home() / "qwen38-opt" / "run_flashnext.sh",
    "Qwen3-4B Instruct — hızlı analiz (8901)": Path.home() / "qwen38-opt" / "run_small.sh",
}


@dataclass
class Settings:
    vault: Path
    port: int
    host: str = "127.0.0.1"
