"""Tests import the app as `server.…` / `core.…`, so the project root must be
on sys.path however pytest was started."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
