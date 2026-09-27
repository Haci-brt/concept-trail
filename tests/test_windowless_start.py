"""pythonw.exe: no console streams, and the app still has to start."""
import sys

import main


def test_missing_streams_go_to_the_log(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    log = tmp_path / "logs" / "concept-trail.log"
    main.attach_log_when_windowless(log)
    try:
        assert not sys.stdout.isatty()      # what uvicorn's formatter asks
        print("merhaba", file=sys.stderr)
        assert "merhaba" in log.read_text(encoding="utf-8")
    finally:
        sys.stdout.close()


def test_a_console_launch_is_left_alone(tmp_path, monkeypatch):
    before = sys.stdout
    main.attach_log_when_windowless(tmp_path / "x.log")
    assert sys.stdout is before and not (tmp_path / "x.log").exists()
