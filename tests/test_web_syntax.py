"""Every module of the page parses. A stray line break inside a string once
kept the whole app from starting (2026-09-29) while `node --check file.js`
said nothing: it reads a .js file as CommonJS. Fed on stdin as a module, it
does not miss it."""
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parent.parent / "web" / "js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node yok")
@pytest.mark.parametrize("module", sorted(p.name for p in WEB.glob("*.js")))
def test_the_module_parses(module):
    source = (WEB / module).read_text(encoding="utf-8")
    result = subprocess.run(["node", "--input-type=module", "--check"], input=source, capture_output=True,
                            text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr[:500]
