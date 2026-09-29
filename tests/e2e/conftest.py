"""End-to-end tests: the real app in a real (headless) browser.

The app runs as its own process, exactly as it is started for a writer, on a
temporary vault and settings, against the stand-in model (testkit) — no key,
no bill, no network. Each test works on a note of its own.

    python -m pytest tests/e2e          only these
    python -m pytest -m "not e2e"       everything else

Needs Playwright's Chromium (python -m playwright install chromium); without
it these tests are skipped, not failed.
"""
import sys
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from testkit.fake_model import FakeModel  # noqa: E402
from harness import App, Page  # noqa: E402


@pytest.fixture(scope="session")
def fake_model():
    model = FakeModel(delay=0.05).start()
    yield model
    model.stop()


@pytest.fixture(scope="session")
def app(tmp_path_factory, fake_model):
    running = App(tmp_path_factory.mktemp("uygulama"), fake_model)
    yield running
    running.stop()


@pytest.fixture(scope="session")
def browser():
    with sync_api.sync_playwright() as play:
        try:
            chromium = play.chromium.launch()
        except Exception as exc:          # the browser itself is not installed
            pytest.skip(f"Chromium yok (python -m playwright install chromium): {str(exc)[:120]}")
        yield chromium
        chromium.close()


@pytest.fixture
def page(browser, app):
    context = browser.new_context(viewport={"width": 1400, "height": 880})
    wrapped = Page(context.new_page(), app).open()
    yield wrapped
    context.close()
    assert not wrapped.errors, f"sayfada hata: {wrapped.errors}"
