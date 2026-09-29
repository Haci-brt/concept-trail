"""Tests import the app as `server.…` / `core.…`, so the project root must be
on sys.path however pytest was started."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def anyio_backend():
    """Every async test here runs on asyncio; trio is not a dependency."""
    return "asyncio"


def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: the real app in a real browser (tests/e2e); skip with -m 'not e2e'")


def pytest_collection_modifyitems(config, items):
    """The browser tests are marked e2e and run last: Playwright keeps an
    event loop on the main thread while its browser is open, and a later
    test's asyncio.run would fail under it (70 did, measured)."""
    for item in items:
        if "e2e" in item.nodeid.split("/"):
            item.add_marker(pytest.mark.e2e)
    items.sort(key=lambda item: "e2e" in item.nodeid.split("/"))
