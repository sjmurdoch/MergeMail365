#!/usr/bin/env bash
# Checks to run on a developer's machine before a release, which CI does not
# run (docs/phase-h-guards-plan.md, class D):
#
#   1. the browser tests in Playwright's WebKit, the engine nearest the
#      macOS desktop window (CI runs them in Chromium only);
#   2. a merge in the real desktop window, closed and opened again
#      (tests/test_window.py). A window appears on the screen for about
#      fifteen seconds. Run this on macOS and on Windows.
#
# Usage: scripts/pre-release-checks.sh [webkit|window]   (default: both)
#
# Needs the project's virtual environment with every extra
# (uv sync --all-extras). On Windows, run it from Git Bash; WebKit is
# skipped there, because the Windows window is Edge's engine, which the
# Chromium tests already cover.
set -u

which="${1:-all}"
cd "$(dirname "$0")/.." || exit 1

python=".venv/bin/python"
windows=0
if [ -x ".venv/Scripts/python.exe" ]; then
    python=".venv/Scripts/python.exe"
    windows=1
fi
if [ ! -x "$python" ]; then
    echo "No virtual environment: run 'uv sync --all-extras' first." >&2
    exit 1
fi

status=0

if [ "$which" = "all" ] || [ "$which" = "webkit" ]; then
    if [ "$windows" -eq 1 ]; then
        echo "== WebKit: skipped on Windows"
    else
        echo "== Browser tests in WebKit"
        "$python" -m playwright install webkit || status=1
        "$python" -m pytest -q -p no:cacheprovider --browser webkit \
            tests/test_web_e2e.py tests/test_web_e2e_workflow.py \
            tests/test_web_e2e_restart.py tests/test_web_e2e_injection.py \
            tests/test_web_state.py tests/test_conformance_e2e.py || status=1
    fi
fi

if [ "$which" = "all" ] || [ "$which" = "window" ]; then
    echo "== A merge in the real window"
    MERGEMAIL365_WINDOW_TESTS=1 "$python" -m pytest -q -p no:cacheprovider tests/test_window.py || status=1
fi

if [ "$status" -eq 0 ]; then
    echo "== Pre-release checks passed"
else
    echo "== Pre-release checks FAILED" >&2
fi
exit "$status"
