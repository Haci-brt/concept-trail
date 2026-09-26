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
    "Qwen3.8 Flash-Next (8899)": Path.home() / "qwen38-opt" / "run_flashnext.sh",
    # Qwen3-4B (run_small.sh, port 8901) is off the list since 2026-09-27: one
    # big model now does every job, so starting the small one would only take
    # memory. Put it back together with a role bound to local-fast.
}


@dataclass
class Settings:
    vault: Path
    port: int
    host: str = "127.0.0.1"
