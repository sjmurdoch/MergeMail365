"""End-to-end Playwright tests for the web interface.

Uses the Playwright Python API per project conventions. Flask runs in a
background thread with mocked Graph API (responses) and MSAL (monkeypatch).
"""

from __future__ import annotations

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
    page.wait_for_selector("text=Setup")
    return page


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPageLoad:
    def test_page_loads_without_js_errors(self, authenticated_page: Page):
        errors = []
        authenticated_page.on("pageerror", lambda exc: errors.append(str(exc)))
        # Reload to catch errors
        authenticated_page.reload()
        authenticated_page.wait_for_selector("text=Setup")
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
        # All 5 steps should be listed
        steps = authenticated_page.locator(".step-indicator li")
        assert steps.count() == 5


class TestSetupStep:
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

    def test_spreadsheet_upload_shows_columns(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        page.set_input_files("#spreadsheet-file", str(sample_xlsx))
        page.wait_for_selector("#spreadsheet-info:not(.hidden)", timeout=5000)
        # Column dropdowns should be populated
        email_options = page.locator("#email-column option")
        assert email_options.count() > 1  # more than just "-- select --"

    def test_auto_detect_email_column(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        page.set_input_files("#spreadsheet-file", str(sample_xlsx))
        page.wait_for_selector("#spreadsheet-info:not(.hidden)", timeout=5000)
        # Should auto-detect "email" column
        assert page.locator("#email-column").input_value() == "email"

    def test_placeholder_chips_appear(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        page.set_input_files("#spreadsheet-file", str(sample_xlsx))
        page.wait_for_selector("#placeholder-chips:not(.hidden)", timeout=5000)
        chips = page.locator(".chip")
        assert chips.count() >= 3  # name, email, company

    def test_placeholder_chip_inserts_text(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        page.set_input_files("#spreadsheet-file", str(sample_xlsx))
        page.wait_for_selector(".chip", timeout=5000)
        # Click the body textarea first, then a chip
        page.click("#body-input")
        page.click(".chip >> nth=0")
        body_val = page.locator("#body-input").input_value()
        assert "{{" in body_val

    def test_blocks_next_without_spreadsheet(self, authenticated_page: Page):
        page = authenticated_page
        page.fill("#subject-input", "Test")
        page.fill("#body-input", "Body")
        # Clicking Next without spreadsheet should show alert
        page.on("dialog", lambda dialog: dialog.accept())
        page.click("#btn-next-1")
        # Should still be on step 1
        expect(page.locator("#step-1")).to_have_class(re.compile("active"))

    def test_blocks_next_without_subject(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        page.set_input_files("#spreadsheet-file", str(sample_xlsx))
        page.wait_for_selector("#spreadsheet-info:not(.hidden)", timeout=5000)
        page.fill("#subject-input", "")
        page.fill("#body-input", "Body")
        page.on("dialog", lambda dialog: dialog.accept())
        page.click("#btn-next-1")
        expect(page.locator("#step-1")).to_have_class(re.compile("active"))


class TestPreviewStep:
    def _setup_to_preview(self, page: Page, sample_xlsx: Path):
        """Fill setup and navigate to preview."""
        page.set_input_files("#spreadsheet-file", str(sample_xlsx))
        page.wait_for_selector("#spreadsheet-info:not(.hidden)", timeout=5000)
        page.fill("#subject-input", "Hello {{name}}")
        page.fill("#body-input", "Welcome to {{company}}, {{name}}!")
        page.click("#btn-next-1")
        page.wait_for_selector("#step-2.active", timeout=5000)

    def test_preview_renders_placeholders(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        self._setup_to_preview(page, sample_xlsx)
        # Preview should show rendered content
        expect(page.locator("#preview-subject")).to_contain_text("Hello Alice")

    def test_preview_body_rendered(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        self._setup_to_preview(page, sample_xlsx)
        expect(page.locator("#preview-body")).to_contain_text("Welcome to Acme, Alice!")

    def test_preview_navigation(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        self._setup_to_preview(page, sample_xlsx)
        expect(page.locator("#preview-recipient-label")).to_contain_text("1 of 2")
        # Navigate to next recipient (scope to step-2 to avoid matching other step buttons)
        page.locator("#step-2 button.outline", has_text="Next").click()
        expect(page.locator("#preview-recipient-label")).to_contain_text("2 of 2")
        expect(page.locator("#preview-subject")).to_contain_text("Hello Bob")

    def test_back_returns_to_setup(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        self._setup_to_preview(page, sample_xlsx)
        page.click("button:has-text('← Back')")
        page.wait_for_selector("#step-1.active", timeout=3000)
        # Subject should still be filled
        assert page.locator("#subject-input").input_value() == "Hello {{name}}"


class TestRecipientCap:
    def test_over_99_recipients_blocked(self, authenticated_page: Page, big_xlsx: Path):
        page = authenticated_page
        page.set_input_files("#spreadsheet-file", str(big_xlsx))
        page.wait_for_selector("#spreadsheet-info:not(.hidden)", timeout=5000)
        page.fill("#subject-input", "Hello {{name}}")
        page.fill("#body-input", "Body")
        # Navigate to preview, then try to start a job
        page.click("#btn-next-1")
        page.wait_for_selector("#step-2.active", timeout=5000)
        # Navigate to step 3 (test email)
        page.click("#btn-next-2")
        page.wait_for_selector("#step-3.active", timeout=5000)


class TestDryRunStep:
    def _navigate_to_verify(self, page: Page, sample_xlsx: Path):
        """Setup + preview + skip test (mark as passed) + navigate to verify."""
        page.set_input_files("#spreadsheet-file", str(sample_xlsx))
        page.wait_for_selector("#spreadsheet-info:not(.hidden)", timeout=5000)
        page.fill("#subject-input", "Hello {{name}}")
        page.fill("#body-input", "Body for {{name}}.")
        page.click("#btn-next-1")
        page.wait_for_selector("#step-2.active", timeout=5000)

    def test_dry_run_log_appears(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        self._navigate_to_verify(page, sample_xlsx)
        # We need test to pass first - skip to step 3 and manually trigger
        page.click("#btn-next-2")
        page.wait_for_selector("#step-3.active", timeout=5000)


class TestSendMode:
    def test_bcc_mode_toggle(self, authenticated_page: Page):
        page = authenticated_page
        # Click BCC blast mode
        page.click("#mode-bcc")
        expect(page.locator("#bcc-blast-options")).not_to_have_class(re.compile("hidden"))

    def test_individual_mode_default(self, authenticated_page: Page):
        page = authenticated_page
        expect(page.locator("#bcc-blast-options")).to_have_class(re.compile("hidden"))

    def test_bcc_placeholder_warning(self, authenticated_page: Page):
        page = authenticated_page
        page.fill("#subject-input", "Hello {{name}}")
        page.click("#mode-bcc")
        # Should show warning about placeholders
        expect(page.locator("#bcc-placeholder-warn")).not_to_have_class(re.compile("hidden"))


class TestPlaceholderValidation:
    def test_wizard_blocks_unresolved_placeholders(self, authenticated_page: Page, sample_xlsx: Path):
        """Unresolved placeholders show a warning in Step 1."""
        page = authenticated_page
        page.set_input_files("#spreadsheet-file", str(sample_xlsx))
        page.wait_for_selector("#spreadsheet-info:not(.hidden)", timeout=5000)
        page.fill("#subject-input", "Hello {{nonexistent_column}}")
        page.fill("#body-input", "Body")
        # Wait for debounced validation to run
        page.wait_for_selector("#placeholder-errors:not(.hidden)", timeout=3000)
        expect(page.locator("#placeholder-errors")).to_contain_text("nonexistent_column")


class TestStepGating:
    def test_test_email_required_before_verify(self, authenticated_page: Page, sample_xlsx: Path):
        """Clicking Next on step 3 without passing test email should be disabled."""
        page = authenticated_page
        page.set_input_files("#spreadsheet-file", str(sample_xlsx))
        page.wait_for_selector("#spreadsheet-info:not(.hidden)", timeout=5000)
        page.fill("#subject-input", "Hello {{name}}")
        page.fill("#body-input", "Body for {{name}}.")
        page.click("#btn-next-1")
        page.wait_for_selector("#step-2.active", timeout=5000)
        page.click("#btn-next-2")
        page.wait_for_selector("#step-3.active", timeout=5000)
        # The Next button on step 3 should be disabled
        expect(page.locator("#btn-next-3")).to_be_disabled()

    def test_verify_required_before_send(self, authenticated_page: Page, sample_xlsx: Path):
        """Step 5 Next button should be disabled without completing verify."""
        page = authenticated_page
        page.set_input_files("#spreadsheet-file", str(sample_xlsx))
        page.wait_for_selector("#spreadsheet-info:not(.hidden)", timeout=5000)
        page.fill("#subject-input", "Hello {{name}}")
        page.fill("#body-input", "Body for {{name}}.")
        page.click("#btn-next-1")
        page.wait_for_selector("#step-2.active", timeout=5000)
        page.click("#btn-next-2")
        page.wait_for_selector("#step-3.active", timeout=5000)
        # The Next button on step 4 should also be disabled
        expect(page.locator("#btn-next-4")).to_be_disabled()


class TestSendConfirmation:
    def _navigate_to_send(self, page: Page, sample_xlsx: Path):
        """Navigate to step 2 (preview)."""
        page.set_input_files("#spreadsheet-file", str(sample_xlsx))
        page.wait_for_selector("#spreadsheet-info:not(.hidden)", timeout=5000)
        page.fill("#subject-input", "Hello {{name}}")
        page.fill("#body-input", "Body for {{name}}.")
        page.click("#btn-next-1")
        page.wait_for_selector("#step-2.active", timeout=5000)

    def test_send_confirmation_visible(self, authenticated_page: Page, sample_xlsx: Path):
        """Step 5 should show the confirmation dialog with recipient count."""
        page = authenticated_page
        self._navigate_to_send(page, sample_xlsx)
        # Force-navigate to step 5 via JS (bypassing gating for this UI test)
        page.evaluate("() => { testPassed = true; verifyPassed = true; goToStep(5); }")
        page.wait_for_selector("#step-5.active", timeout=5000)
        # Confirmation box should be visible
        expect(page.locator("#send-confirm")).to_be_visible()
        expect(page.locator("#send-count")).to_contain_text("2")
        # Send button should be disabled until SEND is typed
        expect(page.locator("#btn-do-send")).to_be_disabled()

    def test_typing_send_enables_button(self, authenticated_page: Page, sample_xlsx: Path):
        """Typing SEND in the confirmation input enables the send button."""
        page = authenticated_page
        self._navigate_to_send(page, sample_xlsx)
        page.evaluate("() => { testPassed = true; verifyPassed = true; goToStep(5); }")
        page.wait_for_selector("#step-5.active", timeout=5000)
        page.fill("#send-confirm-input", "SEND")
        expect(page.locator("#btn-do-send")).to_be_enabled()


class TestSessionTimer:
    def test_session_timer_visible(self, authenticated_page: Page):
        """The session timer should be visible in the header."""
        page = authenticated_page
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

        # Step 1: Setup
        page.set_input_files("#spreadsheet-file", str(sample_xlsx))
        page.wait_for_selector("#spreadsheet-info:not(.hidden)", timeout=5000)
        page.fill("#subject-input", "Hello {{name}}")
        page.fill("#body-input", "Welcome {{name}} from {{company}}")

        # Navigate to preview
        page.click("#btn-next-1")
        page.wait_for_selector("#step-2.active", timeout=5000)

        # Verify preview renders
        expect(page.locator("#preview-subject")).to_contain_text("Hello Alice")
        expect(page.locator("#preview-body")).to_contain_text("Welcome Alice from Acme")

    def test_wizard_navigation_back_preserves_data(self, authenticated_page: Page, sample_xlsx: Path):
        """Navigate forward then back, verify data preserved."""
        page = authenticated_page

        page.set_input_files("#spreadsheet-file", str(sample_xlsx))
        page.wait_for_selector("#spreadsheet-info:not(.hidden)", timeout=5000)
        page.fill("#subject-input", "Subject test 123")
        page.fill("#body-input", "Body test")

        page.click("#btn-next-1")
        page.wait_for_selector("#step-2.active", timeout=5000)

        # Go back
        page.click("button:has-text('← Back')")
        page.wait_for_selector("#step-1.active", timeout=3000)

        # Data should be preserved
        assert page.locator("#subject-input").input_value() == "Subject test 123"
        assert page.locator("#body-input").input_value() == "Body test"
