"""Closing the app and opening it again (docs/phase-h-guards-plan.md, class B).

Phase H found four ways the page forgot what it says it remembers once the
app had been quit and reopened; the reload tests had not noticed, because
they reload a page of a server that keeps running. Here the server is
stopped and a new one started on the same port, as a restart of the app is,
and every remembered field is checked, whichever field was changed last
and whether or not the auto-save runs before the spreadsheet is uploaded
again.
"""

import re
import socket
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import openpyxl
import pytest

pytest.importorskip("playwright")

from playwright.sync_api import Page, expect  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

from mail_merge.web.app import create_app  # noqa: E402

APP_JS = Path(__file__).parent.parent / "src" / "mail_merge" / "web" / "static" / "app.js"
AUTOSAVE_MS = 5000

# Every key the page keeps in localStorage, and how to read the field it
# stands for. A key added to app.js needs a row here.
REMEMBERED = {
    "mm_subject": "$('subject-input').value",
    "mm_body": "$('html-toggle').checked ? $('trix-input').value : $('body-input').value",
    "mm_html": "$('html-toggle').checked",
    "mm_email_col": "$('email-column').value",
    "mm_name_col": "$('name-column').value",
    "mm_sheet": "$('sheet-select').value",
}


def test_every_saved_key_is_checked():
    assert set(re.findall(r'"(mm_\w+)"', APP_JS.read_text(encoding="utf-8"))) == set(REMEMBERED)


class RestartableApp:
    """The web UI on a fixed port; restart() replaces the server with a new
    one (new startup token, no sessions), as quitting and reopening does."""

    def __init__(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.starts = 0
        self.start()

    def start(self) -> None:
        self.starts += 1
        self.token = f"restart-token-{self.starts}"
        app = create_app(startup_token=self.token, port=self.port, client_id="e2e-client")
        app.config["TESTING"] = True
        self.server = make_server("127.0.0.1", self.port, app, threaded=True)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def restart(self) -> None:
        self.stop()
        self.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?token={self.token}"


@pytest.fixture
def app() -> Iterator[RestartableApp]:
    with patch("mail_merge.auth._build_msal_app", side_effect=RuntimeError("no MSAL in tests")):
        running = RestartableApp()
        yield running
        running.stop()


@pytest.fixture(scope="module")
def xlsx(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Two sheets with the same columns, so a remembered sheet matters."""
    path = tmp_path_factory.mktemp("restart") / "people.xlsx"
    wb = openpyxl.Workbook()
    first = wb.active
    assert first is not None
    first.title = "Staff"
    second = wb.create_sheet("Students")
    for ws, who in ((first, "Alice"), (second, "Bob")):
        # "E-mail" is what the page would choose by itself, so the test
        # chooses the other address column.
        ws.append(["E-mail", "Work address", "First Name"])
        ws.append([f"{who.lower()}@home.example", f"{who.lower()}@work.example", who])
    wb.save(path)
    return path


@pytest.fixture
def wizard(page: Page, app: RestartableApp) -> Page:
    page.route("**/auth/status", lambda route: route.fulfill(
        json={"authenticated": True, "email": "me@example.com", "token_expires_at": None}))
    page.on("dialog", lambda d: d.accept())
    # The auto-save is a 5-second timer; the tests move the page's clock.
    page.clock.install()
    page.goto(app.url)
    page.wait_for_selector("#step-1.active")
    return page


def _upload(page: Page, xlsx: Path) -> None:
    page.set_input_files("#spreadsheet-file", str(xlsx))
    page.wait_for_selector("#spreadsheet-info:not(.hidden)", timeout=5000)


def _to_compose(page: Page) -> None:
    page.click("#btn-next-1")
    page.wait_for_selector("#step-2.active", timeout=5000)


def _autosave(page: Page) -> None:
    page.clock.fast_forward(AUTOSAVE_MS + 500)


def _fields(page: Page) -> dict[str, Any]:
    return {key: page.evaluate(f"() => {{ const $ = (id) => document.getElementById(id); return {read}; }}")
            for key, read in REMEMBERED.items()}


# The ways to change each remembered field. Each is used as the *last*
# change before the app is closed: a field whose change doesn't lead to a
# save is the bug.
def _set_subject(page: Page) -> None:
    page.fill("#subject-input", "Hello {{First Name}}")


def _set_body(page: Page) -> None:
    if page.is_checked("#html-toggle"):
        page.check("#source-toggle")
        page.fill("#html-source", "<div>Dear <strong>{{First Name}}</strong>, see you soon.</div>")
        page.uncheck("#source-toggle")
    else:
        page.fill("#body-input", "Dear {{First Name}},\nsee you soon.")


def _set_email_column(page: Page) -> None:
    page.select_option("#email-column", "Work address")


def _set_name_column(page: Page) -> None:
    page.select_option("#name-column", "First Name")


def _set_html(page: Page) -> None:
    page.check("#html-toggle")
    page.wait_for_selector("#html-editor-wrap:not(.hidden)")


def _set_sheet(page: Page) -> None:
    page.click("#step-2 button:has-text('Back')")
    page.wait_for_selector("#step-1.active", timeout=5000)
    with page.expect_response("**/api/change-sheet"):
        page.select_option("#sheet-select", "Students")
    _to_compose(page)


CHANGES = {
    "subject": _set_subject,
    "body": _set_body,
    "email column": _set_email_column,
    "name column": _set_name_column,
    "HTML": _set_html,
    "sheet": _set_sheet,
}


def _fill_in(page: Page, xlsx: Path, last: str) -> dict[str, Any]:
    """Upload and set every remembered field, `last` last; returns what
    the fields hold once the auto-save has run."""
    _upload(page, xlsx)
    _to_compose(page)
    for name, change in CHANGES.items():
        if name != last:
            change(page)
    _autosave(page)
    CHANGES[last](page)
    _autosave(page)
    return _fields(page)


def _reopen(page: Page, app: RestartableApp, xlsx: Path, autosave_before_upload: bool) -> dict[str, Any]:
    app.restart()
    page.goto(app.url)
    page.wait_for_selector("#step-1.active")
    if autosave_before_upload:
        # The user reads the page for a while first. Restoring the fields
        # counts as an edit, so the auto-save runs with no spreadsheet yet.
        page.evaluate("document.getElementById('subject-input').dispatchEvent(new Event('input'))")
        _autosave(page)
    _upload(page, xlsx)
    page.wait_for_timeout(300)  # a remembered sheet is fetched after the upload
    _to_compose(page)
    return _fields(page)


@pytest.mark.parametrize("autosave_before_upload", [False, True], ids=["upload at once", "upload later"])
@pytest.mark.parametrize("last", list(CHANGES))
def test_fields_are_restored_after_a_restart(
    wizard: Page, app: RestartableApp, xlsx: Path, last: str, autosave_before_upload: bool,
):
    before = _fill_in(wizard, xlsx, last)
    assert before["mm_email_col"] == "Work address" and before["mm_sheet"] == "Students", before
    after = _reopen(wizard, app, xlsx, autosave_before_upload)
    assert after == before


@pytest.mark.parametrize("autosave_before_upload", [False, True], ids=["upload at once", "upload later"])
def test_no_name_column_is_remembered_too(
    wizard: Page, app: RestartableApp, xlsx: Path, autosave_before_upload: bool,
):
    """A deliberate "none" must not come back as an earlier choice."""
    page = wizard
    _fill_in(page, xlsx, "subject")
    page.select_option("#name-column", "")
    _autosave(page)
    before = _fields(page)
    assert before["mm_name_col"] == ""
    assert _reopen(page, app, xlsx, autosave_before_upload) == before


def test_new_merge_is_not_undone_by_a_restart(wizard: Page, app: RestartableApp, xlsx: Path):
    """New merge forgets the saved fields; reopening must not bring them back."""
    page = wizard
    _fill_in(page, xlsx, "subject")
    # What a first visit shows: the first sheet, and the column the page
    # recognises as the address.
    empty = {"mm_subject": "", "mm_body": "", "mm_html": False, "mm_email_col": "E-mail", "mm_name_col": "",
             "mm_sheet": "Staff"}
    page.evaluate("newMerge()")
    expect(page.locator("#spreadsheet-info")).to_be_hidden()
    _autosave(page)
    assert _reopen(page, app, xlsx, autosave_before_upload=True) == empty
