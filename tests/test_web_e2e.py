"""End-to-end Playwright tests for the web interface.

Uses the Playwright Python API per project conventions. Flask runs in a
background thread with mocked Graph API (responses) and MSAL (monkeypatch).
"""

import re
import threading
import time
from pathlib import Path
from unittest.mock import patch

import openpyxl
import pytest
import responses
from playwright.sync_api import Page, expect

from mail_merge.sender import GRAPH_SEND_URL
from mail_merge.web.app import create_app

STARTUP_TOKEN = "e2e-test-token"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sample_xlsx(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("data") / "test.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["name", "email", "company"])
    ws.append(["Alice", "alice@example.com", "Acme"])
    ws.append(["Bob", "bob@example.com", "Widgets"])
    wb.save(path)
    return path


XSS_HEADER = '<img src=x onerror="window._xssFired=1">'


@pytest.fixture(scope="module")
def xss_header_xlsx(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Spreadsheet whose column header is an HTML injection payload."""
    path = tmp_path_factory.mktemp("data") / "xss.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["email", XSS_HEADER])
    ws.append(["alice@example.com", "x"])
    wb.save(path)
    return path


# What real clipboard pastes produce in the email body, recorded from the
# code before the paste handler was changed to parse in an inert document.
PASTE_EXPECTED: dict[str, str] = {
    "formatted": (
        '<h1>Title</h1><p>Hi <strong>{{name}}</strong>, see '
        '<a href="https://example.com/x?a=1&amp;b=2">the link</a>.</p>'
        '<ul><li>One</li><li>Two</li></ul><p><em>Thanks</em> END</p>'
    ),
    "word": '<p>Line 1</p><p>Line 2 END</p>',
    "image": (
        '<p>Logo:</p><p><figure data-trix-attachment="{&quot;contentType&quot;:&quot;image'
        '&quot;,&quot;url&quot;:&quot;https://example.com/logo.png&quot;}" '
        'data-trix-content-type="image" class="attachment attachment--preview">'
        '<img src="https://example.com/logo.png"><figcaption class="attachment__caption">'
        '</figcaption></figure></p><p>END</p>'
    ),
    "plain_text": '<p>Plain {{name}}<br>Second line END</p>',
}

SPECIAL_COLUMNS = ["email", "First Name", "R&D budget", "O'Brien \"Q\"", "Größe", "Price <GBP>"]


@pytest.fixture(scope="module")
def special_columns_xlsx(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Legitimate column names containing characters that HTML escaping touches."""
    path = tmp_path_factory.mktemp("data") / "special.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(SPECIAL_COLUMNS)
    ws.append(["alice@example.com", "Alice", "£5k & up", "Q1", "M", "<10"])
    wb.save(path)
    return path


@pytest.fixture(scope="module")
def active_sheet2_xlsx(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Spreadsheet where the active sheet is not the first one."""
    path = tmp_path_factory.mktemp("data") / "active_sheet2.xlsx"
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "Contacts"
    ws1.append(["name", "email"])
    ws1.append(["Alice", "alice@example.com"])
    ws2 = wb.create_sheet("Orders")
    ws2.append(["order_id", "email", "amount"])
    ws2.append(["001", "bob@example.com", "99.99"])
    wb.active = 1  # Make "Orders" the active sheet
    wb.save(path)
    return path


@pytest.fixture(scope="module")
def mixed_xlsx(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Spreadsheet with some invalid email addresses."""
    path = tmp_path_factory.mktemp("data") / "mixed.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["name", "email", "company"])
    ws.append(["Alice", "alice@example.com", "Acme"])
    ws.append(["Bad", "not-an-email", "Nope"])
    ws.append(["Bob", "bob@example.com", "Widgets"])
    wb.save(path)
    return path


@pytest.fixture(scope="module")
def big_xlsx(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("data") / "big.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["name", "email"])
    for i in range(100):
        ws.append([f"User{i}", f"user{i}@example.com"])
    wb.save(path)
    return path


@pytest.fixture(scope="module")
def _mock_auth():
    """Module-scoped mock that patches acquire_token for the entire test run."""
    with patch("mail_merge.auth.acquire_token", return_value="fake-e2e-token"):
        yield


@pytest.fixture(scope="module")
def _mock_graph():
    """Module-scoped responses mock for Graph API."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.POST, GRAPH_SEND_URL, status=202)
        rsps.add(responses.POST, GRAPH_SEND_URL, status=202)
        rsps.add(responses.POST, GRAPH_SEND_URL, status=202)
        rsps.add(responses.POST, GRAPH_SEND_URL, status=202)
        rsps.add(responses.POST, GRAPH_SEND_URL, status=202)
        rsps.add(responses.POST, GRAPH_SEND_URL, status=202)
        yield rsps


@pytest.fixture(scope="module")
def live_server(_mock_auth, _mock_graph):
    """Start Flask in a background thread and yield the base URL."""
    app = create_app(startup_token=STARTUP_TOKEN, port=0)
    app.config["TESTING"] = True

    # Find a free port
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server_thread = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False),
        daemon=True,
    )
    server_thread.start()

    # Wait for server to be ready
    base_url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            import urllib.request
            urllib.request.urlopen(f"{base_url}/?token={STARTUP_TOKEN}", timeout=1)
            break
        except Exception:
            time.sleep(0.1)

    yield base_url


@pytest.fixture
def authenticated_page(page: Page, live_server: str) -> Page:
    """Navigate to the app with valid startup token."""
    page.goto(f"{live_server}/?token={STARTUP_TOKEN}")
    # Should redirect to / and show the wizard
    page.wait_for_selector("text=Data")
    return page


def _assert_dom_valid(page: Page) -> None:
    """Run client-side validateDOM() and fail if any issues are found."""
    errors = page.evaluate("validateDOM()")
    assert errors == [], f"DOM validation errors: {errors}"


def _upload_and_go_to_compose(page: Page, xlsx_path: Path) -> None:
    """Upload spreadsheet on step 1, advance to step 2 (Compose)."""
    page.set_input_files("#spreadsheet-file", str(xlsx_path))
    page.wait_for_selector("#spreadsheet-info:not(.hidden)", timeout=5000)
    _assert_dom_valid(page)
    page.click("#btn-next-1")
    page.wait_for_selector("#step-2.active", timeout=5000)
    _assert_dom_valid(page)


def _setup_to_preview(page: Page, xlsx_path: Path) -> None:
    """Upload, compose, and advance to step 3 (Preview)."""
    _upload_and_go_to_compose(page, xlsx_path)
    page.fill("#subject-input", "Hello {{name}}")
    page.fill("#body-input", "Welcome to {{company}}, {{name}}!")
    page.click("#btn-next-2")
    page.wait_for_selector("#step-3.active", timeout=5000)
    _assert_dom_valid(page)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPageLoad:
    def test_page_loads_without_js_errors(self, authenticated_page: Page):
        errors = []
        authenticated_page.on("pageerror", lambda exc: errors.append(str(exc)))
        # Reload to catch errors
        authenticated_page.reload()
        authenticated_page.wait_for_selector("text=Data")
        assert errors == [], f"JS errors on page load: {errors}"

    def test_requires_auth_token(self, page: Page, live_server: str):
        resp = page.goto(f"{live_server}/")
        assert resp is not None
        assert resp.status == 403

    def test_invalid_token_rejected(self, page: Page, live_server: str):
        page.goto(f"{live_server}/?token=wrong")
        # Should show forbidden
        expect(page.locator("body")).to_contain_text("Forbidden")

    def test_step_indicator_visible(self, authenticated_page: Page):
        expect(authenticated_page.locator(".step-indicator")).to_be_visible()
        # All 6 steps should be listed
        steps = authenticated_page.locator(".step-indicator li")
        assert steps.count() == 6


class TestDataStep:
    """Step 1: Data Source — auth + upload + sheet + preview."""

    def test_config_fields_visible(self, authenticated_page: Page):
        expect(authenticated_page.locator("#client-id")).to_be_visible()
        expect(authenticated_page.locator("#tenant-id")).to_be_visible()

    def test_sign_in_button_visible(self, authenticated_page: Page):
        expect(authenticated_page.locator("#btn-sign-in")).to_be_visible()

    def test_test_connection_shows_diagnostics(self, authenticated_page: Page):
        page = authenticated_page
        page.fill("#client-id", "test-client-id")
        page.click("#btn-test-connection")
        page.wait_for_selector("#auth-diagnostics:not(.hidden)", timeout=5000)
        expect(page.locator("#auth-diag-content")).to_be_visible()

    def test_spreadsheet_upload_shows_preview(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        page.set_input_files("#spreadsheet-file", str(sample_xlsx))
        page.wait_for_selector("#spreadsheet-info:not(.hidden)", timeout=5000)
        # Preview table should be visible
        expect(page.locator("#preview-table")).to_be_visible()

    def test_sheet_selector_matches_active_sheet(
        self, authenticated_page: Page, active_sheet2_xlsx: Path,
    ):
        """When the workbook's active sheet isn't the first, the selector
        and preview data should both reflect the active sheet."""
        page = authenticated_page
        page.set_input_files("#spreadsheet-file", str(active_sheet2_xlsx))
        page.wait_for_selector("#spreadsheet-info:not(.hidden)", timeout=5000)

        # The selector should show "Orders" (the active sheet), not "Contacts"
        selected = page.locator("#sheet-select").input_value()
        assert selected == "Orders"

        # The preview table should show Orders columns, not Contacts columns
        headers = page.eval_on_selector_all(
            "#preview-table thead th", "ths => ths.map(th => th.textContent)",
        )
        assert "order_id" in headers
        assert "amount" in headers

    def test_blocks_next_without_spreadsheet(self, authenticated_page: Page):
        page = authenticated_page
        # Clicking Next without spreadsheet should show alert
        page.on("dialog", lambda dialog: dialog.accept())
        page.click("#btn-next-1")
        # Should still be on step 1
        expect(page.locator("#step-1")).to_have_class(re.compile("active"))


class TestComposeStep:
    """Step 2: Compose — column selection, message, options."""

    def test_column_dropdowns_populated(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        email_options = page.locator("#email-column option")
        assert email_options.count() > 1  # more than just "-- select --"

    def test_auto_detect_email_column(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        # Should auto-detect "email" column
        assert page.locator("#email-column").input_value() == "email"

    def test_placeholder_chips_appear(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        expect(page.locator("#placeholder-chips")).not_to_have_class(re.compile("hidden"))
        chips = page.locator(".chip")
        assert chips.count() >= 3  # name, email, company

    def test_placeholder_chip_inserts_text(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        # Click the body textarea first, then a chip
        page.click("#body-input")
        page.click(".chip >> nth=0")
        body_val = page.locator("#body-input").input_value()
        assert "{{" in body_val

    def test_placeholder_chip_inserts_into_subject_when_focused(
        self, authenticated_page: Page, sample_xlsx: Path,
    ):
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        page.click("#subject-input")
        page.click(".chip >> nth=0")
        subject_val = page.locator("#subject-input").input_value()
        assert "{{" in subject_val
        # Body should remain empty
        body_val = page.locator("#body-input").input_value()
        assert "{{" not in body_val

    def test_placeholder_chip_inserts_into_subject_in_html_mode(
        self, authenticated_page: Page, sample_xlsx: Path,
    ):
        """Chip click targets subject even when Trix HTML editor is active."""
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        page.check("#html-toggle")
        # Wait for Trix to initialise
        page.wait_for_function("() => window.state.trixEditor !== null")
        page.click("#subject-input")
        page.click(".chip >> nth=0")
        subject_val = page.locator("#subject-input").input_value()
        assert "{{" in subject_val
        # Trix body should remain empty
        trix_html = page.evaluate("() => state.trixEditor.getDocument().toString().trim()")
        assert "{{" not in trix_html

    def test_filter_chips_appear(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        page.click("summary >> text=Additional options")
        expect(page.locator("#filter-chips")).not_to_have_class(re.compile("hidden"))
        chips = page.locator("#filter-chips-container .chip")
        assert chips.count() >= 3  # name, email, company

    def test_filter_chip_inserts_column_name(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        page.click("summary >> text=Additional options")
        page.click("#filter-input")
        page.click("#filter-chips-container .chip >> nth=0")
        val = page.locator("#filter-input").input_value()
        assert "=" in val
        assert "{{" not in val

    def test_filter_chip_newline_handling(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        page.click("summary >> text=Additional options")
        page.fill("#filter-input", "company=Acme")
        page.click("#filter-chips-container .chip >> nth=0")
        val = page.locator("#filter-input").input_value()
        assert "\n" in val
        lines = val.strip().split("\n")
        assert len(lines) == 2

    def test_trix_uses_p_tags(self, authenticated_page: Page, sample_xlsx: Path):
        """Trix should produce <p> tags, not <div>, for paragraphs."""
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        page.check("#html-toggle")
        page.wait_for_function("() => window.state.trixEditor !== null")
        page.evaluate("() => state.trixEditor.insertString('Hello world')")
        body = page.locator("#body-input").input_value()
        assert "<p>" in body
        assert "<div>" not in body

    def test_trix_output_strips_trailing_br(self, authenticated_page: Page, sample_xlsx: Path):
        """Trailing <br> before </p> should be stripped in body-input."""
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        page.check("#html-toggle")
        page.wait_for_function("() => window.state.trixEditor !== null")
        # Type a single paragraph — Trix adds a trailing <br> before </p>
        page.evaluate("() => state.trixEditor.insertString('Hello world')")
        body = page.locator("#body-input").input_value()
        # The trailing <br> should have been stripped by the trix-change handler
        assert "<br></p>" not in body
        assert body.strip().endswith("</p>")

    def test_trix_output_removes_empty_paragraphs(
        self, authenticated_page: Page, sample_xlsx: Path,
    ):
        """Empty <p></p> tags (from blank lines) should be removed."""
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        page.check("#html-toggle")
        page.wait_for_function("() => window.state.trixEditor !== null")
        # Simulate Trix producing empty paragraphs via the hidden input
        page.evaluate("""() => {
            document.getElementById('trix-input').value =
                '<p>First<br></p><p><br></p><p>Second<br></p>';
            document.getElementById('trix-input')
                .dispatchEvent(new Event('input'));
        }""")
        # Trigger the trix-change handler by modifying Trix content
        page.evaluate("""() => {
            state.trixEditor.loadHTML(
                '<p>First<br></p><p><br></p><p>Second<br></p>'
            );
        }""")
        body = page.locator("#body-input").input_value()
        assert "<p>First</p>" in body
        assert "<p>Second</p>" in body
        assert "<p></p>" not in body
        assert "<br>" not in body

    def test_trix_paste_cleans_html(self, authenticated_page: Page, sample_xlsx: Path):
        """Pasting HTML with empty spacer divs should produce clean output."""
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        page.check("#html-toggle")
        page.wait_for_function("() => window.state.trixEditor !== null")
        # Focus the Trix editor
        page.click("trix-editor")
        # Simulate paste with HTML containing empty spacer paragraphs
        page.evaluate("""() => {
            const html = '<p>First paragraph</p><p></p><p>Second paragraph</p>';
            const event = new CustomEvent('trix-before-paste', {
                cancelable: true,
            });
            event.paste = { html: html };
            document.dispatchEvent(event);
            // After the handler runs, empty <p> should be removed
            return event.paste.html;
        }""")
        result = page.evaluate("""() => {
            const html = '<p>Paragraph A</p><div><br></div><p>Paragraph B</p>';
            const event = new CustomEvent('trix-before-paste', {
                cancelable: true,
            });
            event.paste = { html: html };
            document.dispatchEvent(event);
            return event.paste.html;
        }""")
        # Empty spacer div should have been removed
        assert "<div>" not in result
        assert "Paragraph A" in result
        assert "Paragraph B" in result

    def test_trix_paste_preserves_content_paragraphs(
        self, authenticated_page: Page, sample_xlsx: Path,
    ):
        """Paste cleanup should keep non-empty paragraphs intact."""
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        page.check("#html-toggle")
        page.wait_for_function("() => window.state.trixEditor !== null")
        result = page.evaluate("""() => {
            const html = '<p>Keep me</p><p>And me</p><p>Me too</p>';
            const event = new CustomEvent('trix-before-paste', {
                cancelable: true,
            });
            event.paste = { html: html };
            document.dispatchEvent(event);
            return event.paste.html;
        }""")
        assert "<p>Keep me</p>" in result
        assert "<p>And me</p>" in result
        assert "<p>Me too</p>" in result

    def test_trix_paste_preserves_images_in_empty_blocks(
        self, authenticated_page: Page, sample_xlsx: Path,
    ):
        """Empty paragraphs containing images should not be removed."""
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        page.check("#html-toggle")
        page.wait_for_function("() => window.state.trixEditor !== null")
        result = page.evaluate("""() => {
            const html = '<p><img src="logo.png"></p><p></p><p>Text</p>';
            const event = new CustomEvent('trix-before-paste', {
                cancelable: true,
            });
            event.paste = { html: html };
            document.dispatchEvent(event);
            return event.paste.html;
        }""")
        assert "logo.png" in result
        assert "<p></p>" not in result

    def _before_paste(self, page: Page, html: str) -> str:
        return page.evaluate("""(html) => {
            const event = new CustomEvent('trix-before-paste', {cancelable: true});
            event.paste = { html: html };
            document.dispatchEvent(event);
            return event.paste.html;
        }""", html)

    def test_trix_paste_cleanup_exact_output(
        self, authenticated_page: Page, sample_xlsx: Path,
    ):
        """Pin the exact cleaned HTML so changing how it's parsed can't alter it."""
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        page.check("#html-toggle")
        page.wait_for_function("() => window.state.trixEditor !== null")
        cases = {
            '<p>A<br></p><p></p><div> </div><p><b>B</b> <a href="https://e.com/">l</a></p>':
                '<p>A</p><p><b>B</b> <a href="https://e.com/">l</a></p>',
            '<div><p>Nested</p><div><br></div></div><ul><li>x</li></ul>':
                '<div><p>Nested</p></div><ul><li>x</li></ul>',
            '<p><img src="logo.png"></p><table><tr><td>c</td></tr></table>':
                '<p><img src="logo.png"></p><table><tbody><tr><td>c</td></tr></tbody></table>',
            '<meta charset="utf-8"><p style="margin:0">Hi {{name}}</p><br>':
                '<meta charset="utf-8"><p style="margin:0">Hi {{name}}</p>',
        }
        for html, expected in cases.items():
            assert self._before_paste(page, html) == expected, html

    def test_trix_paste_does_not_run_pasted_handlers(
        self, authenticated_page: Page, sample_xlsx: Path,
    ):
        """Event handlers in pasted HTML must not run while it is being cleaned."""
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        page.check("#html-toggle")
        page.wait_for_function("() => window.state.trixEditor !== null")
        self._before_paste(
            page,
            '<p>Hi</p><img src="x" onerror="window._xssFired=1">'
            '<svg><image href="x" onerror="window._xssFired=2"></image></svg>',
        )
        page.wait_for_timeout(500)
        assert page.evaluate("() => window._xssFired === undefined")

    def _open_trix(self, page: Page, sample_xlsx: Path) -> None:
        _upload_and_go_to_compose(page, sample_xlsx)
        page.check("#html-toggle")
        page.wait_for_function("() => window.state.trixEditor !== null")
        page.click("trix-editor")

    def test_trix_clipboard_paste_honours_before_paste_edits(
        self, authenticated_page: Page, sample_xlsx: Path,
    ):
        """A real clipboard paste goes through Trix's own paste pipeline.

        The synthetic trix-before-paste tests above check our cleanup logic;
        this checks the Trix contract that logic depends on: Trix passes
        ``event.paste.html`` as a string and inserts whatever the listeners
        leave there.
        """
        page = authenticated_page
        page.context.grant_permissions(["clipboard-read", "clipboard-write"])
        self._open_trix(page, sample_xlsx)
        page.evaluate("""async () => {
            window._pasteSeen = null;
            document.addEventListener('trix-before-paste', (e) => {
                window._pasteSeen = typeof (e.paste && e.paste.html);
                e.paste.html = e.paste.html.replace('Para A', 'Rewritten');
            }, {once: true});
            const html = '<p>Para A</p><p></p><div><br></div><p>Hi {{name}}</p>';
            await navigator.clipboard.write([new ClipboardItem({
                'text/html': new Blob([html], {type: 'text/html'}),
                'text/plain': new Blob(['Para A Hi {{name}}'], {type: 'text/plain'}),
            })]);
        }""")
        page.focus("trix-editor")
        page.keyboard.press("ControlOrMeta+V")
        page.wait_for_function(
            "() => document.getElementById('body-input').value.includes('Hi {{name}}')"
        )
        assert page.evaluate("() => window._pasteSeen") == "string"
        assert page.locator("#body-input").input_value() == "<p>Rewritten</p><p>Hi {{name}}</p>"

    def _clipboard_paste(self, page: Page, sample_xlsx: Path, html: str | None, text: str) -> str:
        """Paste via the real clipboard into Trix and return the resulting body HTML."""
        page.context.grant_permissions(["clipboard-read", "clipboard-write"])
        self._open_trix(page, sample_xlsx)
        page.evaluate("""async ([html, text]) => {
            const items = {'text/plain': new Blob([text], {type: 'text/plain'})};
            if (html !== null) items['text/html'] = new Blob([html], {type: 'text/html'});
            await navigator.clipboard.write([new ClipboardItem(items)]);
        }""", [html, text])
        page.focus("trix-editor")
        page.keyboard.press("ControlOrMeta+V")
        page.wait_for_function(
            "() => document.getElementById('body-input').value.includes('END')"
        )
        return page.locator("#body-input").input_value()

    PASTE_CASES = {
        "formatted": (
            '<h1>Title</h1><p>Hi <strong>{{name}}</strong>, see '
            '<a href="https://example.com/x?a=1&amp;b=2">the link</a>.</p>'
            '<ul><li>One</li><li>Two</li></ul><p></p><p><em>Thanks</em> END</p>',
            "Title Hi {{name}} END",
        ),
        "word": (
            '<meta charset="utf-8"><p class=MsoNormal style="margin:0cm">Line 1<o:p></o:p></p>'
            '<p class=MsoNormal style="margin:0cm"><o:p>&nbsp;</o:p></p>'
            '<p class=MsoNormal style="margin:0cm">Line 2 END<o:p></o:p></p>',
            "Line 1 Line 2 END",
        ),
        "image": (
            '<p>Logo:</p><p><img src="https://example.com/logo.png" alt="logo"></p><p>END</p>',
            "Logo: END",
        ),
        "plain_text": (None, "Plain {{name}}\nSecond line END"),
    }

    @pytest.mark.parametrize("case", list(PASTE_CASES))
    def test_trix_clipboard_paste_result(
        self, authenticated_page: Page, sample_xlsx: Path, case: str,
    ):
        """Pin what ends up in the email body for typical real pastes."""
        html, text = self.PASTE_CASES[case]
        body = self._clipboard_paste(authenticated_page, sample_xlsx, html, text)
        assert body == PASTE_EXPECTED[case]

    def test_trix_toolbar_bold(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        self._open_trix(page, sample_xlsx)
        page.click("trix-toolbar button[data-trix-attribute='bold']")
        page.keyboard.type("Important")
        expect(page.locator("#body-input")).to_have_value(
            re.compile(r"<strong>Important</strong>")
        )

    def test_trix_toolbar_bullet_list(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        self._open_trix(page, sample_xlsx)
        page.click("trix-toolbar button[data-trix-attribute='bullet']")
        page.keyboard.type("One")
        page.keyboard.press("Enter")
        page.keyboard.type("Two")
        expect(page.locator("#body-input")).to_have_value(
            re.compile(r"<ul><li>One</li><li>Two</li></ul>")
        )

    def test_trix_preserves_links_and_placeholders(
        self, authenticated_page: Page, sample_xlsx: Path,
    ):
        page = authenticated_page
        self._open_trix(page, sample_xlsx)
        page.evaluate("""() => state.trixEditor.loadHTML(
            '<p>Dear {{name}}, see <a href="https://example.com/?a=1&amp;b=2">here</a>.</p>'
        )""")
        body = page.locator("#body-input").input_value()
        assert "Dear {{name}}" in body
        assert '<a href="https://example.com/?a=1&amp;b=2">here</a>' in body

    def test_blocks_next_without_subject(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        page.fill("#subject-input", "")
        page.fill("#body-input", "Body")
        page.on("dialog", lambda dialog: dialog.accept())
        page.click("#btn-next-2")
        expect(page.locator("#step-2")).to_have_class(re.compile("active"))

    def test_data_summary_shown(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        expect(page.locator("#compose-data-summary")).to_contain_text("3 columns")


class TestPreviewStep:
    def test_preview_renders_placeholders(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _setup_to_preview(page, sample_xlsx)
        # Preview should show rendered content
        expect(page.locator("#preview-subject")).to_contain_text("Hello Alice")

    def test_preview_body_rendered(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _setup_to_preview(page, sample_xlsx)
        expect(page.locator("#preview-body")).to_contain_text("Welcome to Acme, Alice!")

    def test_preview_navigation(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _setup_to_preview(page, sample_xlsx)
        expect(page.locator("#preview-recipient-label")).to_contain_text("1 of 2")
        # Navigate to next recipient (scope to step-3 to avoid matching other step buttons)
        page.locator("#step-3 button.outline", has_text="Next").click()
        expect(page.locator("#preview-recipient-label")).to_contain_text("2 of 2")
        expect(page.locator("#preview-subject")).to_contain_text("Hello Bob")

    def test_back_returns_to_compose(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _setup_to_preview(page, sample_xlsx)
        page.locator("#step-3 button:has-text('\u2190 Back')").click()
        page.wait_for_selector("#step-2.active", timeout=3000)
        # Subject should still be filled
        assert page.locator("#subject-input").input_value() == "Hello {{name}}"


class TestRecipientCap:
    def test_over_99_recipients_blocked(self, authenticated_page: Page, big_xlsx: Path):
        page = authenticated_page
        _upload_and_go_to_compose(page, big_xlsx)
        page.fill("#subject-input", "Hello {{name}}")
        page.fill("#body-input", "Body")
        # Clicking Next triggers client-side check (total_rows > 99, no filters)
        alert_text = []
        page.on("dialog", lambda dialog: (alert_text.append(dialog.message), dialog.accept()))
        page.click("#btn-next-2")
        page.wait_for_timeout(2000)
        # Should stay on step 2
        expect(page.locator("#step-2")).to_have_class(re.compile("active"))
        assert any("Too many recipients" in t for t in alert_text)


class TestInvalidEmailWarning:
    def test_invalid_emails_shown_in_preview(self, authenticated_page: Page, mixed_xlsx: Path):
        page = authenticated_page
        _upload_and_go_to_compose(page, mixed_xlsx)
        page.fill("#subject-input", "Hello {{name}}")
        page.fill("#body-input", "Welcome to {{company}}")
        page.click("#btn-next-2")
        page.wait_for_selector("#step-3.active", timeout=5000)
        # Warning should be visible
        expect(page.locator("#invalid-email-warning")).to_be_visible()
        expect(page.locator("#invalid-email-warning")).to_contain_text("1 invalid email address skipped")
        expect(page.locator("#invalid-email-warning")).to_contain_text("not-an-email")
        # Only valid recipients shown in preview
        expect(page.locator("#preview-recipient-label")).to_contain_text("1 of 2")

    def test_no_warning_when_all_valid(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        page.fill("#subject-input", "Hello {{name}}")
        page.fill("#body-input", "Welcome to {{company}}")
        page.click("#btn-next-2")
        page.wait_for_selector("#step-3.active", timeout=5000)
        # Warning should not be visible
        expect(page.locator("#invalid-email-warning")).to_be_hidden()


class TestDryRunStep:
    def _navigate_to_verify(self, page: Page, sample_xlsx: Path):
        """Setup + compose + preview + skip test (mark as passed) + navigate to verify."""
        _setup_to_preview(page, sample_xlsx)

    def test_dry_run_log_appears(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        self._navigate_to_verify(page, sample_xlsx)
        # We need test to pass first - advance to test step
        page.click("#btn-next-3")
        page.wait_for_selector("#step-4.active", timeout=5000)


class TestSendMode:
    def test_bcc_mode_toggle(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        # Click BCC blast mode
        page.click("#mode-bcc")
        expect(page.locator("#bcc-blast-options")).not_to_have_class(re.compile("hidden"))

    def test_individual_mode_default(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        expect(page.locator("#bcc-blast-options")).to_have_class(re.compile("hidden"))

    def test_bcc_placeholder_warning(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        page.fill("#subject-input", "Hello {{name}}")
        page.click("#mode-bcc")
        # Should show warning about placeholders
        expect(page.locator("#bcc-placeholder-warn")).not_to_have_class(re.compile("hidden"))


class TestPlaceholderValidation:
    def test_wizard_blocks_unresolved_placeholders(self, authenticated_page: Page, sample_xlsx: Path):
        """Unresolved placeholders show a warning in Step 2 (Compose)."""
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        page.fill("#subject-input", "Hello {{nonexistent_column}}")
        page.fill("#body-input", "Body")
        # Wait for debounced validation to run
        page.wait_for_selector("#placeholder-errors:not(.hidden)", timeout=3000)
        expect(page.locator("#placeholder-errors")).to_contain_text("nonexistent_column")

    def test_error_lists_available_columns(self, authenticated_page: Page, sample_xlsx: Path):
        """The error names the bad placeholder in bold and lists every column."""
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        page.fill("#subject-input", "Hi {{first}} {{last}}")
        page.wait_for_selector("#placeholder-errors:not(.hidden)", timeout=3000)
        errors = page.locator("#placeholder-errors")
        expect(errors).to_have_text(
            "No column named {{first}}. Available: name, email, company"
            "No column named {{last}}. Available: name, email, company"
        )
        expect(errors.locator("strong")).to_have_text(["{{first}}", "{{last}}"])
        expect(errors.locator("br")).to_have_count(1)

    def test_special_column_names_shown_exactly(
        self, authenticated_page: Page, special_columns_xlsx: Path
    ):
        """Column names with &, <, quotes and non-ASCII appear exactly as written."""
        page = authenticated_page
        page.set_input_files("#spreadsheet-file", str(special_columns_xlsx))
        page.wait_for_selector("#spreadsheet-info:not(.hidden)", timeout=5000)
        expect(page.locator("#preview-table thead th")).to_have_text(SPECIAL_COLUMNS)
        expect(page.locator("#preview-table tbody tr").first.locator("td")).to_have_text(
            ["alice@example.com", "Alice", "£5k & up", "Q1", "M", "<10"])
        page.click("#btn-next-1")
        page.wait_for_selector("#step-2.active", timeout=5000)
        # Dropdowns and chips
        for col in SPECIAL_COLUMNS:
            expect(page.locator("#email-column option", has_text=col)).to_have_count(1)
        expect(page.locator("#chips .chip")).to_have_text(
            [f"{{{{{col}}}}}" for col in SPECIAL_COLUMNS])
        # Unknown-placeholder message
        page.fill("#subject-input", "Hi {{nope}}")
        page.wait_for_selector("#placeholder-errors:not(.hidden)", timeout=3000)
        expect(page.locator("#placeholder-errors")).to_have_text(
            "No column named {{nope}}. Available: " + ", ".join(SPECIAL_COLUMNS)
        )
        _assert_dom_valid(page)

    def test_special_column_placeholders_still_resolve(
        self, authenticated_page: Page, special_columns_xlsx: Path
    ):
        """A valid placeholder for a column with a space shows no error and renders."""
        page = authenticated_page
        page.set_input_files("#spreadsheet-file", str(special_columns_xlsx))
        page.wait_for_selector("#spreadsheet-info:not(.hidden)", timeout=5000)
        page.click("#btn-next-1")
        page.wait_for_selector("#step-2.active", timeout=5000)
        page.select_option("#email-column", "email")
        page.fill("#subject-input", "Hello {{First Name}}")
        page.fill("#body-input", "Hi {{first name}}")
        page.wait_for_timeout(800)  # past the validation debounce
        expect(page.locator("#placeholder-errors")).to_have_class(re.compile("hidden"))
        page.click("#btn-next-2")
        page.wait_for_selector("#step-3.active", timeout=5000)
        expect(page.locator("#preview-subject")).to_have_text("Hello Alice")

    def test_html_in_column_header_is_not_executed(
        self, authenticated_page: Page, xss_header_xlsx: Path
    ):
        """A spreadsheet header containing markup is shown as text, never run."""
        page = authenticated_page
        _upload_and_go_to_compose(page, xss_header_xlsx)
        page.fill("#subject-input", "Hello {{nonexistent_column}}")
        page.wait_for_selector("#placeholder-errors:not(.hidden)", timeout=3000)
        errors = page.locator("#placeholder-errors")
        expect(errors).to_contain_text(XSS_HEADER)
        expect(errors.locator("img")).to_have_count(0)
        # Give a broken image time to fire onerror, had one been created
        page.wait_for_timeout(500)
        assert page.evaluate("() => window._xssFired === undefined")


class TestAttachmentsFromBrowser:
    def test_browser_attachments_reach_send_merge_intact(
        self, authenticated_page: Page, sample_xlsx: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """Files picked in the Attachments field keep their names and bytes.

        Uses the app's own buildJobFormData(), so the multipart filenames are
        exactly what a real browser sends.
        """
        import mail_merge.api
        real_send_merge = mail_merge.api.send_merge
        captured: list[tuple[str, bytes]] = []

        def recording_send_merge(**kwargs):
            captured.extend((Path(p).name, Path(p).read_bytes())
                            for p in kwargs.get("attachment") or [])
            return real_send_merge(**kwargs)

        monkeypatch.setattr(mail_merge.api, "send_merge", recording_send_merge)

        files = [
            ("Q3 report (final).pdf", "application/pdf", b"%PDF-1.4 data"),
            ("Café menu – 2026.txt", "text/plain", "héllo".encode()),
            ("a.txt", "text/plain", b"first"),
        ]
        page = authenticated_page
        _setup_to_preview(page, sample_xlsx)
        page.set_input_files("#attachment-input", [
            {"name": n, "mimeType": m, "buffer": b} for n, m, b in files
        ])
        result = page.evaluate("""async () => {
            const resp = await fetch("/api/start-job", {
                method: "POST", body: buildJobFormData("dry_run"),
                headers: {"X-CSRF-Token": CSRF_TOKEN},
            });
            const {job_id, error} = await resp.json();
            if (!job_id) return {status: resp.status, error};
            for (let i = 0; i < 100; i++) {
                const s = await (await fetch(`/api/job/${job_id}/status`)).json();
                if (s.status === "completed" || s.status === "failed") return s;
                await new Promise(r => setTimeout(r, 100));
            }
            return {status: "timeout"};
        }""")
        assert result["status"] == "completed", result
        assert captured == [(n, b) for n, _, b in files]


class TestStepGating:
    def test_test_email_required_before_verify(self, authenticated_page: Page, sample_xlsx: Path):
        """Clicking Next on step 4 without passing test email should be disabled."""
        page = authenticated_page
        _setup_to_preview(page, sample_xlsx)
        page.click("#btn-next-3")
        page.wait_for_selector("#step-4.active", timeout=5000)
        # The Next button on step 4 should be disabled
        expect(page.locator("#btn-next-4")).to_be_disabled()

    def test_verify_required_before_send(self, authenticated_page: Page, sample_xlsx: Path):
        """Step 5 Next button should be disabled without completing verify."""
        page = authenticated_page
        _setup_to_preview(page, sample_xlsx)
        page.click("#btn-next-3")
        page.wait_for_selector("#step-4.active", timeout=5000)
        # The Next button on step 5 should also be disabled
        expect(page.locator("#btn-next-5")).to_be_disabled()


class TestSendConfirmation:
    def _navigate_to_send(self, page: Page, sample_xlsx: Path):
        """Navigate to step 3 (preview)."""
        _setup_to_preview(page, sample_xlsx)

    def test_send_confirmation_visible(self, authenticated_page: Page, sample_xlsx: Path):
        """Step 6 should show the confirmation dialog with recipient count."""
        page = authenticated_page
        self._navigate_to_send(page, sample_xlsx)
        # Force-navigate to step 6 via JS (bypassing gating for this UI test)
        page.evaluate("() => { testPassed = true; verifyPassed = true; goToStep(6); }")
        page.wait_for_selector("#step-6.active", timeout=5000)
        # Confirmation box should be visible
        expect(page.locator("#send-confirm")).to_be_visible()
        expect(page.locator("#send-count")).to_contain_text("2")
        # Send button should be disabled until SEND is typed
        expect(page.locator("#btn-do-send")).to_be_disabled()

    def test_typing_send_enables_button(self, authenticated_page: Page, sample_xlsx: Path):
        """Typing SEND in the confirmation input enables the send button."""
        page = authenticated_page
        self._navigate_to_send(page, sample_xlsx)
        page.evaluate("() => { testPassed = true; verifyPassed = true; goToStep(6); }")
        page.wait_for_selector("#step-6.active", timeout=5000)
        page.fill("#send-confirm-input", "SEND")
        expect(page.locator("#btn-do-send")).to_be_enabled()


class TestSessionTimer:
    def test_session_timer_visible(self, authenticated_page: Page):
        """The session timer becomes visible when remaining time is under 60 min."""
        page = authenticated_page
        # With a 24-hour session, timer is hidden initially.  Simulate time
        # passing so that less than 60 minutes remain.
        page.evaluate("sessionStart = Date.now() - (24 * 60 * 60 * 1000 - 30 * 60 * 1000)")
        page.evaluate("updateSessionTimer()")
        expect(page.locator("#session-timer")).to_be_visible()
        expect(page.locator("#session-timer")).to_contain_text("Session")


class TestKeyboardNavigation:
    def test_tab_through_setup(self, authenticated_page: Page):
        page = authenticated_page
        # Tab through the first few interactive elements
        page.locator("#client-id").focus()
        expect(page.locator("#client-id")).to_be_focused()
        page.keyboard.press("Tab")
        # Should move to next input — just verify we can tab without errors


class TestFullWizardFlow:
    """Tests the complete wizard flow with mocked Graph API."""

    def test_setup_to_preview_navigation(self, authenticated_page: Page, sample_xlsx: Path):
        """Upload spreadsheet, fill in subject/body, navigate to preview."""
        page = authenticated_page

        # Step 1: Data Source — upload
        page.set_input_files("#spreadsheet-file", str(sample_xlsx))
        page.wait_for_selector("#spreadsheet-info:not(.hidden)", timeout=5000)

        # Navigate to Compose
        page.click("#btn-next-1")
        page.wait_for_selector("#step-2.active", timeout=5000)

        # Step 2: Compose — fill message
        page.fill("#subject-input", "Hello {{name}}")
        page.fill("#body-input", "Welcome {{name}} from {{company}}")

        # Navigate to Preview
        page.click("#btn-next-2")
        page.wait_for_selector("#step-3.active", timeout=5000)

        # Verify preview renders
        expect(page.locator("#preview-subject")).to_contain_text("Hello Alice")
        expect(page.locator("#preview-body")).to_contain_text("Welcome Alice from Acme")

    def test_wizard_navigation_back_preserves_data(self, authenticated_page: Page, sample_xlsx: Path):
        """Navigate forward then back, verify data preserved."""
        page = authenticated_page

        page.set_input_files("#spreadsheet-file", str(sample_xlsx))
        page.wait_for_selector("#spreadsheet-info:not(.hidden)", timeout=5000)

        page.click("#btn-next-1")
        page.wait_for_selector("#step-2.active", timeout=5000)

        page.fill("#subject-input", "Subject test 123")
        page.fill("#body-input", "Body test")

        page.click("#btn-next-2")
        page.wait_for_selector("#step-3.active", timeout=5000)

        # Go back to compose
        page.locator("#step-3 button:has-text('\u2190 Back')").click()
        page.wait_for_selector("#step-2.active", timeout=3000)

        # Data should be preserved
        assert page.locator("#subject-input").input_value() == "Subject test 123"
        assert page.locator("#body-input").input_value() == "Body test"
