"""The app in its real window (docs/phase-h-guards-plan.md, class D).

Phase H found faults that only the desktop window has: its storage was
private, so nothing typed survived quitting the app, and the browser tests,
which run the page in Chromium, could not see it. This test starts
`mergemail365-web --desktop` as a user does (tests/window_driver.py), does a
whole merge in the window, closes it, opens it again and checks what the
page remembered.

It opens a window on the screen and takes about half a minute, so it only
runs when asked for, before a release, on macOS and on Windows:

    MERGEMAIL365_WINDOW_TESTS=1 pytest tests/test_window.py

(`scripts/pre-release-checks.sh` does that, and the browser tests in WebKit.)
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import openpyxl
import pytest

from tests import window_driver as driver

pytestmark = pytest.mark.skipif(
    not os.environ.get("MERGEMAIL365_WINDOW_TESTS"),
    reason="opens a real window; set MERGEMAIL365_WINDOW_TESTS=1 (see scripts/pre-release-checks.sh)",
)

# Inside the range the app searches (5050-5099), away from 5050 in case the
# developer has the app open, and from the ports test_web_process.py uses.
PORT = 5085
REMEMBERED = {
    "mm_subject": driver.SUBJECT,
    # As the editor writes the HTML the driver gave it.
    "mm_body": "<p>Dear <strong>{{First Name}}</strong>, see you soon.</p>",
    "mm_html": True,
    "mm_email_col": driver.EMAIL_COLUMN,
    "mm_name_col": driver.NAME_COLUMN,
    "mm_sheet": driver.SHEET,
}


@pytest.fixture
def xlsx(tmp_path: Path) -> Path:
    """Two sheets with the same columns, so the remembered sheet matters;
    "E-mail" is the column the page would choose by itself."""
    path = tmp_path / "people.xlsx"
    wb = openpyxl.Workbook()
    first = wb.active
    assert first is not None
    first.title = "Staff"
    for ws, who in ((first, "Alice"), (wb.create_sheet(driver.SHEET), "Bob")):
        ws.append(["E-mail", driver.EMAIL_COLUMN, driver.NAME_COLUMN])
        ws.append([f"{who.lower()}@home.example", f"{who.lower()}@work.example", who])
    wb.save(path)
    return path


@pytest.fixture
def run(tmp_path: Path, xlsx: Path):  # type: ignore[no-untyped-def]
    """Run the app once, from start to the window closing, in a home
    directory of its own (which is also where the window keeps its storage)."""
    home = tmp_path / "home"
    home.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("MERGEMAIL365_")}
    env.update(HOME=str(home), CFFIXED_USER_HOME=str(home), USERPROFILE=str(home),
               LOCALAPPDATA=str(home / "AppData"), NO_COLOR="1", TERM="dumb")
    env.pop("XDG_STATE_HOME", None)

    def run_phase(phase: str) -> dict[str, Any]:
        result = tmp_path / f"{phase}.json"
        done = subprocess.run(
            [sys.executable, str(Path(driver.__file__)), phase, str(result), str(xlsx),
             "--port", str(PORT), "--client-id", "window-test"],
            env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180, check=False,
        )
        assert result.exists(), f"the app wrote no result:\n{done.stderr[-3000:]}"
        seen: dict[str, Any] = json.loads(result.read_text(encoding="utf-8"))
        assert "error" not in seen, seen["error"]
        assert seen.get("finished")
        assert seen["alerts"] == []
        return seen

    return run_phase


def test_a_merge_in_the_window_and_what_it_remembers_when_reopened(run):
    first = run("merge")
    assert first["desktop_mode"] is True
    assert first["stored_at_start"] == [], "the window's storage was not empty: is it using the temporary home?"
    assert first["composed"] == REMEMBERED

    # Step 3 shows the email as it will be sent.
    assert first["preview_subject"] == "Hello Bob"
    assert first["preview_to"] == "Bob <bob@work.example>"
    frame = first["preview_frame"]
    assert frame["shown"] and frame["width"] > 300 and frame["height"] > 50
    assert "Dear <strong>Bob</strong>, see you soon." in frame["srcdoc"]

    # The test email, to the signed-in account, then the send itself.
    assert first["test_address"] == driver.ACCOUNT
    sent = [(r["message"]["toRecipients"][0]["emailAddress"]["address"], r["message"]["subject"],
             r["message"]["body"]["contentType"]) for r in first["graph_requests"]]
    assert sent == [(driver.ACCOUNT, "Hello Bob", "HTML"), ("bob@work.example", "Hello Bob", "HTML")]
    assert "Total: 1 | Sent: 1 | Failed: 0" in first["send_result"]
    assert first["scrolls_sideways"] is False

    again = run("reopen")
    assert again["origin"] == first["origin"], "the app moved to another port, where nothing is remembered"
    assert again["composed"] == REMEMBERED
    assert again["graph_requests"] == []
