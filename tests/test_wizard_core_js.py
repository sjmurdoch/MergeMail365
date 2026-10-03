"""Run the JavaScript unit tests for the wizard core (tests/js) with Node's built-in runner."""

import shutil
import subprocess
from pathlib import Path

import pytest

JS_TESTS = Path(__file__).resolve().parent / "js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_wizard_core_js():
    result = subprocess.run(
        ["node", "--test", *sorted(str(p) for p in JS_TESTS.glob("*.test.js"))],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
