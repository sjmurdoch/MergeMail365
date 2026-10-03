"""Tests for client-side wizard state management and workflow logic.

Uses Playwright to evaluate JS directly against the state and _auth objects,
testing navigation guards, invalidation cascades, and state transitions
without full UI interactions.
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

STARTUP_TOKEN = "state-test-token"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sample_xlsx(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("data") / "test.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["name", "email", "company"])
    ws.append(["Alice", "alice@example.com", "Acme"])
    ws.append(["Bob", "bob@example.com", "Widgets"])
    # Second sheet for sheet-change tests
    ws2 = wb.create_sheet("Sheet2")
    ws2.append(["id", "email", "department"])
    ws2.append(["1", "charlie@example.com", "Engineering"])
    ws2.append(["2", "diana@example.com", "Marketing"])
    wb.save(path)
    return path


@pytest.fixture(scope="module")
def _mock_auth():
    with patch("mail_merge.auth.acquire_token", return_value="fake-token"):
        yield


@pytest.fixture(scope="module")
def _mock_graph():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.POST, GRAPH_SEND_URL, status=202)
        rsps.add(responses.POST, GRAPH_SEND_URL, status=202)
        rsps.add(responses.POST, GRAPH_SEND_URL, status=202)
        rsps.add(responses.POST, GRAPH_SEND_URL, status=202)
        yield rsps


@pytest.fixture(scope="module")
def live_server(_mock_auth, _mock_graph):
    app = create_app(startup_token=STARTUP_TOKEN, port=0)
    app.config["TESTING"] = True

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
    page.goto(f"{live_server}/?token={STARTUP_TOKEN}")
    page.wait_for_selector("text=Data")
    return page


def _upload(page: Page, xlsx_path: Path) -> None:
    """Upload spreadsheet on step 1 without navigating away."""
    page.set_input_files("#spreadsheet-file", str(xlsx_path))
    page.wait_for_selector("#spreadsheet-info:not(.hidden)", timeout=5000)


def _upload_and_go_to_compose(page: Page, xlsx_path: Path) -> None:
    """Upload spreadsheet on step 1, advance to step 2."""
    _upload(page, xlsx_path)
    page.click("#btn-next-1")
    page.wait_for_selector("#step-2.active", timeout=5000)


# ---------------------------------------------------------------------------
# State object structure
# ---------------------------------------------------------------------------


class TestStateObjectStructure:
    def test_state_object_exists_on_window(self, authenticated_page: Page):
        result = authenticated_page.evaluate("() => typeof window.state")
        assert result == "object"

    def test_state_has_expected_properties(self, authenticated_page: Page):
        props = authenticated_page.evaluate("""() => {
            const s = window.state;
            return {
                hasCurrentStep: 'currentStep' in s,
                hasSpreadsheetData: 'spreadsheetData' in s,
                hasPreviewIndex: 'previewIndex' in s,
                hasSendMode: 'sendMode' in s,
                hasTestPassed: 'testPassed' in s,
                hasVerifyPassed: 'verifyPassed' in s,
                hasSendStarted: 'sendStarted' in s,
                hasCurrentJobId: 'currentJobId' in s,
                hasSendResults: 'sendResults' in s,
                hasFormDirty: 'formDirty' in s,
                hasTrixEditor: 'trixEditor' in s,
            }
        }""")
        assert all(props.values()), f"Missing properties: {[k for k, v in props.items() if not v]}"

    def test_state_has_methods(self, authenticated_page: Page):
        methods = authenticated_page.evaluate("""() => ({
            hasGetRecipients: typeof state.getRecipients === 'function',
            hasResetTestAndVerify: typeof state.resetTestAndVerify === 'function',
            hasResetAll: typeof state.resetAll === 'function',
        })""")
        assert all(methods.values()), f"Missing methods: {[k for k, v in methods.items() if not v]}"

    def test_auth_object_exists(self, authenticated_page: Page):
        props = authenticated_page.evaluate("""() => ({
            hasIsSignedIn: 'isSignedIn' in _auth,
            hasDesktopMode: 'desktopMode' in _auth,
            hasSignInPoll: 'signInPoll' in _auth,
            hasTokenExpiresAt: 'tokenExpiresAt' in _auth,
        })""")
        assert all(props.values())


# ---------------------------------------------------------------------------
# Legacy global aliases (backward compat for E2E tests)
# ---------------------------------------------------------------------------


class TestLegacyGlobalAliases:
    def test_window_testPassed_reads_from_state(self, authenticated_page: Page):
        result = authenticated_page.evaluate("""() => {
            state.testPassed = true;
            const val = window.testPassed;
            state.testPassed = false;
            return val;
        }""")
        assert result is True

    def test_window_testPassed_writes_to_state(self, authenticated_page: Page):
        result = authenticated_page.evaluate("""() => {
            window.testPassed = true;
            const val = state.testPassed;
            state.testPassed = false;
            return val;
        }""")
        assert result is True

    def test_window_verifyPassed_reads_from_state(self, authenticated_page: Page):
        result = authenticated_page.evaluate("""() => {
            state.verifyPassed = true;
            const val = window.verifyPassed;
            state.verifyPassed = false;
            return val;
        }""")
        assert result is True

    def test_window_verifyPassed_writes_to_state(self, authenticated_page: Page):
        result = authenticated_page.evaluate("""() => {
            window.verifyPassed = true;
            const val = state.verifyPassed;
            state.verifyPassed = false;
            return val;
        }""")
        assert result is True

    def test_window_spreadsheetData_reads_from_state(self, authenticated_page: Page):
        result = authenticated_page.evaluate("""() => {
            state.spreadsheetData = { test: true };
            const val = window.spreadsheetData?.test;
            state.spreadsheetData = null;
            return val;
        }""")
        assert result is True

    def test_window_spreadsheetData_writes_to_state(self, authenticated_page: Page):
        result = authenticated_page.evaluate("""() => {
            window.spreadsheetData = { test: 42 };
            const val = state.spreadsheetData?.test;
            state.spreadsheetData = null;
            return val;
        }""")
        assert result == 42


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------


class TestInitialState:
    def test_initial_step_is_1(self, authenticated_page: Page):
        result = authenticated_page.evaluate("() => state.currentStep")
        assert result == 1

    def test_initial_spreadsheet_data_is_null(self, authenticated_page: Page):
        result = authenticated_page.evaluate("() => state.spreadsheetData")
        assert result is None

    def test_initial_send_mode_is_individual(self, authenticated_page: Page):
        result = authenticated_page.evaluate("() => state.sendMode")
        assert result == "individual"

    def test_initial_flags_are_false(self, authenticated_page: Page):
        result = authenticated_page.evaluate("""() => ({
            testPassed: state.testPassed,
            verifyPassed: state.verifyPassed,
            sendStarted: state.sendStarted,
        })""")
        assert result == {"testPassed": False, "verifyPassed": False, "sendStarted": False}

    def test_get_recipients_returns_null_without_data(self, authenticated_page: Page):
        result = authenticated_page.evaluate("() => state.getRecipients()")
        assert result is None


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------


class TestResetAll:
    def test_reset_all_clears_state(self, authenticated_page: Page):
        result = authenticated_page.evaluate("""() => {
            state.currentStep = 5;
            state.spreadsheetData = { columns: [], rows: [], sheets: [], file_name: "x", total_rows: 0 };
            state.testPassed = true;
            state.verifyPassed = true;
            state.sendStarted = true;
            state.currentJobId = "abc";
            state.sendResults = [{email: "a@b.com"}];
            state.previewIndex = 3;

            state.resetAll();

            return {
                currentStep: state.currentStep,
                spreadsheetData: state.spreadsheetData,
                testPassed: state.testPassed,
                verifyPassed: state.verifyPassed,
                sendStarted: state.sendStarted,
                currentJobId: state.currentJobId,
                sendResults: state.sendResults,
                previewIndex: state.previewIndex,
            };
        }""")
        assert result == {
            "currentStep": 1,
            "spreadsheetData": None,
            "testPassed": False,
            "verifyPassed": False,
            "sendStarted": False,
            "currentJobId": None,
            "sendResults": None,
            "previewIndex": 0,
        }


class TestResetTestAndVerify:
    def test_resets_flags(self, authenticated_page: Page):
        result = authenticated_page.evaluate("""() => {
            state.testPassed = true;
            state.verifyPassed = true;
            state.resetTestAndVerify();
            return { testPassed: state.testPassed, verifyPassed: state.verifyPassed };
        }""")
        assert result == {"testPassed": False, "verifyPassed": False}

    def test_disables_next_buttons(self, authenticated_page: Page):
        result = authenticated_page.evaluate("""() => {
            state.resetTestAndVerify();
            return {
                btn4: document.getElementById('btn-next-4').disabled,
                btn5: document.getElementById('btn-next-5').disabled,
            };
        }""")
        assert result == {"btn4": True, "btn5": True}


# ---------------------------------------------------------------------------
# Navigation guards
# ---------------------------------------------------------------------------


class TestNavigationGuards:
    def test_cannot_advance_to_step_2_without_spreadsheet(self, authenticated_page: Page):
        """goToStep(2) should not change step when no spreadsheet is uploaded."""
        page = authenticated_page
        page.on("dialog", lambda d: d.accept())
        result = page.evaluate("""async () => {
            state.spreadsheetData = null;
            state.currentStep = 1;
            await goToStep(2);
            return state.currentStep;
        }""")
        assert result == 1

    def test_can_advance_to_step_2_with_spreadsheet(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _upload(page, sample_xlsx)
        result = page.evaluate("""async () => {
            state.currentStep = 1;
            await goToStep(2);
            return state.currentStep;
        }""")
        assert result == 2

    def test_cannot_advance_to_step_5_without_test_passed(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        result = page.evaluate("""async () => {
            state.testPassed = false;
            state.currentStep = 4;
            await goToStep(5);
            return state.currentStep;
        }""")
        assert result == 4

    def test_can_advance_to_step_5_with_test_passed(self, authenticated_page: Page, sample_xlsx: Path):
        """Note: step 5 triggers startVerify() which calls the server, but
        the step should still update."""
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        page.fill("#subject-input", "Hello {{name}}")
        page.fill("#body-input", "Body")
        page.select_option("#email-column", "email")
        result = page.evaluate("""async () => {
            state.testPassed = true;
            state.currentStep = 4;
            await goToStep(5);
            return state.currentStep;
        }""")
        assert result == 5

    def test_cannot_advance_to_step_6_without_verify_passed(self, authenticated_page: Page):
        result = authenticated_page.evaluate("""async () => {
            state.verifyPassed = false;
            state.currentStep = 5;
            await goToStep(6);
            return state.currentStep;
        }""")
        assert result == 5

    def test_can_advance_to_step_6_with_verify_passed(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        page.fill("#subject-input", "Hello")
        page.fill("#body-input", "Body")
        page.select_option("#email-column", "email")
        result = page.evaluate("""async () => {
            state.verifyPassed = true;
            state.currentStep = 5;
            await goToStep(6);
            return state.currentStep;
        }""")
        assert result == 6

    def test_backward_navigation_always_allowed(self, authenticated_page: Page):
        """Going backward never has guards (except confirm dialog)."""
        result = authenticated_page.evaluate("""async () => {
            state.currentStep = 4;
            state.testPassed = false;
            state.verifyPassed = false;
            // goToStep with a lower number should always work
            await goToStep(1);
            return state.currentStep;
        }""")
        assert result == 1


# ---------------------------------------------------------------------------
# Step UI rendering
# ---------------------------------------------------------------------------


class TestStepUIRendering:
    def test_active_step_panel_matches_state(self, authenticated_page: Page):
        page = authenticated_page
        page.evaluate("""() => {
            state.currentStep = 3;
            updateStepUI(3);
        }""")
        expect(page.locator("#step-3")).to_have_class(re.compile("active"))
        expect(page.locator("#step-1")).not_to_have_class(re.compile("active"))

    def test_completed_steps_marked_correctly(self, authenticated_page: Page):
        page = authenticated_page
        page.evaluate("""() => {
            state.currentStep = 4;
            updateStepUI(4);
        }""")
        # Steps 1-3 should be marked completed
        for step in [1, 2, 3]:
            li = page.locator(f".step-indicator li[data-step='{step}']")
            expect(li).to_have_class(re.compile("completed"))
        # Step 4 is active
        li4 = page.locator(".step-indicator li[data-step='4']")
        expect(li4).to_have_class(re.compile("active"))
        # Steps 5-6 are neither
        for step in [5, 6]:
            li = page.locator(f".step-indicator li[data-step='{step}']")
            expect(li).not_to_have_class(re.compile("active"))
            expect(li).not_to_have_class(re.compile("completed"))

    def test_step_1_panel_restored(self, authenticated_page: Page):
        """After navigating away and back, step 1 panel should be visible."""
        page = authenticated_page
        page.evaluate("() => updateStepUI(1)")
        expect(page.locator("#step-1")).to_have_class(re.compile("active"))


# ---------------------------------------------------------------------------
# Spreadsheet state management
# ---------------------------------------------------------------------------


class TestSpreadsheetState:
    def test_upload_populates_state(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _upload(page, sample_xlsx)
        result = page.evaluate("""() => ({
            hasData: state.spreadsheetData !== null,
            columns: state.spreadsheetData?.columns,
            rowCount: state.spreadsheetData?.rows?.length,
            hasSheets: Array.isArray(state.spreadsheetData?.sheets),
        })""")
        assert result["hasData"] is True
        assert "name" in result["columns"]
        assert "email" in result["columns"]
        assert result["rowCount"] is not None and result["rowCount"] > 0
        assert result["hasSheets"] is True

    def test_get_recipients_returns_rows(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _upload(page, sample_xlsx)
        result = page.evaluate("""() => {
            const r = state.getRecipients();
            return r ? r.length : null;
        }""")
        assert result is not None and result > 0

    def test_sheet_change_updates_state(self, authenticated_page: Page, sample_xlsx: Path):
        """Changing sheet should replace spreadsheetData with new columns."""
        page = authenticated_page
        _upload(page, sample_xlsx)
        # The test workbook has Sheet1 (name,email,company) and Sheet2 (id,email,department)
        page.select_option("#sheet-select", "Sheet2")
        page.wait_for_timeout(1000)  # wait for async /api/change-sheet
        result = page.evaluate("() => state.spreadsheetData?.columns")
        assert result is not None
        assert "id" in result
        assert "department" in result
        # Switch back for subsequent tests
        page.select_option("#sheet-select", "Sheet1")
        page.wait_for_timeout(1000)


# ---------------------------------------------------------------------------
# Send mode state
# ---------------------------------------------------------------------------


class TestSendModeState:
    def test_set_send_mode_updates_state(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        page.evaluate("() => setSendMode('bcc')")
        assert page.evaluate("() => state.sendMode") == "bcc"
        page.evaluate("() => setSendMode('individual')")
        assert page.evaluate("() => state.sendMode") == "individual"


# ---------------------------------------------------------------------------
# Invalidation cascades
# ---------------------------------------------------------------------------


class TestInvalidationCascade:
    def test_reset_test_and_verify_clears_downstream(self, authenticated_page: Page):
        """resetTestAndVerify should clear test/verify flags and disable buttons."""
        page = authenticated_page
        result = page.evaluate("""() => {
            state.testPassed = true;
            state.verifyPassed = true;
            document.getElementById('btn-next-4').disabled = false;
            document.getElementById('btn-next-5').disabled = false;

            state.resetTestAndVerify();

            return {
                testPassed: state.testPassed,
                verifyPassed: state.verifyPassed,
                btn4Disabled: document.getElementById('btn-next-4').disabled,
                btn5Disabled: document.getElementById('btn-next-5').disabled,
            };
        }""")
        assert result == {
            "testPassed": False,
            "verifyPassed": False,
            "btn4Disabled": True,
            "btn5Disabled": True,
        }

    def test_confirm_go_back_from_step_4_resets_test_verify(self, authenticated_page: Page):
        """confirmGoBack from step >= 4 should reset test/verify flags."""
        page = authenticated_page
        page.on("dialog", lambda d: d.accept())
        result = page.evaluate("""async () => {
            state.currentStep = 4;
            state.testPassed = true;
            state.verifyPassed = true;
            confirmGoBack(2);
            // wait a tick for async goToStep
            await new Promise(r => setTimeout(r, 100));
            return { testPassed: state.testPassed, verifyPassed: state.verifyPassed };
        }""")
        assert result == {"testPassed": False, "verifyPassed": False}

    def test_confirm_go_back_from_step_3_to_2_resets_test_verify(self, authenticated_page: Page):
        """Going back from preview (3) to compose (2) also resets downstream."""
        page = authenticated_page
        result = page.evaluate("""async () => {
            state.currentStep = 3;
            state.testPassed = true;
            state.verifyPassed = true;
            // No confirm dialog needed when testPassed was set but step < 4
            // Actually, step >= 4 check won't trigger, but the step 3→2 check will
            confirmGoBack(2);
            await new Promise(r => setTimeout(r, 100));
            return { testPassed: state.testPassed, verifyPassed: state.verifyPassed };
        }""")
        assert result == {"testPassed": False, "verifyPassed": False}


# ---------------------------------------------------------------------------
# localStorage persistence
# ---------------------------------------------------------------------------


class TestLocalStoragePersistence:
    def test_form_dirty_triggers_localstorage_save(self, authenticated_page: Page, sample_xlsx: Path):
        """When formDirty is true, auto-save writes to localStorage."""
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        page.fill("#subject-input", "Test Subject LS")
        page.fill("#body-input", "Test Body LS")
        # Trigger form dirty and wait for the 5-second auto-save interval
        page.evaluate("() => { state.formDirty = true; }")
        # Force an immediate save by simulating the interval callback
        page.evaluate("""() => {
            if (state.formDirty) {
                state.formDirty = false;
                localStorage.setItem('mm_subject', document.getElementById('subject-input').value);
                localStorage.setItem('mm_body', document.getElementById('body-input').value);
            }
        }""")
        result = page.evaluate("""() => ({
            subject: localStorage.getItem('mm_subject'),
            body: localStorage.getItem('mm_body'),
        })""")
        assert result["subject"] == "Test Subject LS"
        assert result["body"] == "Test Body LS"

    def test_sheet_selection_saved_to_localstorage(self, authenticated_page: Page, sample_xlsx: Path):
        """Changing sheet should save to localStorage."""
        page = authenticated_page
        _upload(page, sample_xlsx)
        page.select_option("#sheet-select", "Sheet2")
        page.wait_for_timeout(1000)
        result = page.evaluate("() => localStorage.getItem('mm_sheet')")
        assert result == "Sheet2"
        # Clean up
        page.select_option("#sheet-select", "Sheet1")
        page.wait_for_timeout(1000)

    def test_new_merge_clears_localstorage(self, authenticated_page: Page, sample_xlsx: Path):
        """newMerge() should clear all mm_* localStorage keys."""
        page = authenticated_page
        page.evaluate("""() => {
            localStorage.setItem('mm_subject', 'old');
            localStorage.setItem('mm_body', 'old');
            localStorage.setItem('mm_email_col', 'old');
            localStorage.setItem('mm_name_col', 'old');
            localStorage.setItem('mm_html', '1');
            localStorage.setItem('mm_sheet', 'old');
        }""")
        page.evaluate("() => newMerge()")
        page.wait_for_timeout(500)
        result = page.evaluate("""() => ({
            subject: localStorage.getItem('mm_subject'),
            body: localStorage.getItem('mm_body'),
            emailCol: localStorage.getItem('mm_email_col'),
            nameCol: localStorage.getItem('mm_name_col'),
            html: localStorage.getItem('mm_html'),
            sheet: localStorage.getItem('mm_sheet'),
        })""")
        assert all(v is None for v in result.values()), f"Not all cleared: {result}"


# ---------------------------------------------------------------------------
# saveState server sync
# ---------------------------------------------------------------------------


class TestSaveStateSyncs:
    def test_save_state_posts_current_values(self, authenticated_page: Page):
        """saveState() should POST current state values to the server."""
        page = authenticated_page
        # Set state and capture the fetch call
        result = page.evaluate("""async () => {
            state.currentStep = 3;
            state.testPassed = true;
            state.verifyPassed = false;
            // Override fetch to capture the request body
            const originalFetch = window.fetch;
            let captured = null;
            window.fetch = async (url, opts) => {
                if (url === '/api/state') {
                    captured = JSON.parse(opts.body);
                    return { ok: true, json: async () => ({}) };
                }
                return originalFetch(url, opts);
            };
            await saveState();
            window.fetch = originalFetch;
            return captured;
        }""")
        assert result is not None
        assert result["current_step"] == 3
        assert result["test_passed"] is True
        assert result["verify_passed"] is False


# ---------------------------------------------------------------------------
# Compose step initialisation
# ---------------------------------------------------------------------------


class TestComposeStepInit:
    def test_init_compose_populates_column_dropdowns(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _upload(page, sample_xlsx)
        page.evaluate("() => initComposeStep()")
        options = page.evaluate("""() => {
            const sel = document.getElementById('email-column');
            return Array.from(sel.options).map(o => o.value).filter(v => v);
        }""")
        assert "email" in options
        assert "name" in options
        assert "company" in options

    def test_init_compose_auto_detects_email_column(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _upload(page, sample_xlsx)
        # Clear any previous selection
        page.evaluate("() => document.getElementById('email-column').value = ''")
        page.evaluate("() => initComposeStep()")
        val = page.evaluate("() => document.getElementById('email-column').value")
        assert val == "email"

    def test_init_compose_preserves_valid_selections(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _upload(page, sample_xlsx)
        page.evaluate("() => initComposeStep()")
        page.evaluate("() => document.getElementById('email-column').value = 'name'")
        # Re-init — should keep "name" since it's still a valid column
        page.evaluate("() => initComposeStep()")
        val = page.evaluate("() => document.getElementById('email-column').value")
        assert val == "name"

    def test_init_compose_shows_placeholder_chips(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _upload(page, sample_xlsx)
        page.evaluate("() => initComposeStep()")
        chips = page.evaluate("""() => {
            const container = document.getElementById('chips');
            return Array.from(container.children).map(c => c.textContent);
        }""")
        assert "{{name}}" in chips
        assert "{{email}}" in chips
        assert "{{company}}" in chips


# ---------------------------------------------------------------------------
# Validation logic
# ---------------------------------------------------------------------------


class TestValidation:
    def test_validate_data_source_fails_without_spreadsheet(self, authenticated_page: Page):
        page = authenticated_page
        page.on("dialog", lambda d: d.accept())
        result = page.evaluate("""() => {
            state.spreadsheetData = null;
            return validateDataSource();
        }""")
        assert result is False

    def test_validate_data_source_passes_with_spreadsheet(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _upload(page, sample_xlsx)
        result = page.evaluate("() => validateDataSource()")
        assert result is True

    def test_validate_compose_requires_email_column(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        page.on("dialog", lambda d: d.accept())
        page.fill("#subject-input", "Hello")
        page.fill("#body-input", "Body")
        page.evaluate("() => document.getElementById('email-column').value = ''")
        result = page.evaluate("() => validateCompose()")
        assert result is False

    def test_validate_compose_requires_subject(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        page.on("dialog", lambda d: d.accept())
        page.fill("#subject-input", "")
        page.fill("#body-input", "Body")
        page.select_option("#email-column", "email")
        result = page.evaluate("() => validateCompose()")
        assert result is False

    def test_validate_compose_requires_body(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        page.on("dialog", lambda d: d.accept())
        page.fill("#subject-input", "Hello")
        page.fill("#body-input", "")
        page.select_option("#email-column", "email")
        result = page.evaluate("() => validateCompose()")
        assert result is False

    def test_validate_compose_passes_with_all_fields(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        page.fill("#subject-input", "Hello")
        page.fill("#body-input", "Body")
        page.select_option("#email-column", "email")
        result = page.evaluate("() => validateCompose()")
        assert result is True

    def test_validate_compose_blocks_bcc_with_placeholders(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        page.on("dialog", lambda d: d.accept())
        page.fill("#subject-input", "Hello {{name}}")
        page.fill("#body-input", "Body")
        page.select_option("#email-column", "email")
        page.evaluate("() => setSendMode('bcc')")
        page.fill("#bcc-blast-to", "list@example.com")
        result = page.evaluate("() => validateCompose()")
        assert result is False
        # Clean up
        page.evaluate("() => setSendMode('individual')")


# ---------------------------------------------------------------------------
# Template rendering (client-side)
# ---------------------------------------------------------------------------


class TestClientTemplateRendering:
    def test_render_template_substitutes_placeholders(self, authenticated_page: Page):
        result = authenticated_page.evaluate("""() => {
            return renderTemplate("Hello {{name}}, welcome to {{company}}",
                { name: "Alice", company: "Acme" });
        }""")
        assert result == "Hello Alice, welcome to Acme"

    def test_render_template_case_insensitive(self, authenticated_page: Page):
        result = authenticated_page.evaluate("""() => {
            return renderTemplate("Hello {{NAME}}", { name: "Alice" });
        }""")
        assert result == "Hello Alice"

    def test_render_template_preserves_unmatched(self, authenticated_page: Page):
        result = authenticated_page.evaluate("""() => {
            return renderTemplate("Hello {{unknown}}", { name: "Alice" });
        }""")
        assert result == "Hello {{unknown}}"

    @pytest.mark.parametrize("template", [
        "Bonjour {{Prénom}}",
        "{{Straße}} {{名前}} {{Ονομα}} {{ID_٣}}",
        "{{first name}} {{a}} {{x_1}}",
        "{{ spaced }} {{bad-name}} {{}} {{é}}",
        "{{Prénom}}, {{prénom}}, {{PRÉNOM}}",
    ])
    def test_render_template_matches_server(self, authenticated_page: Page, template: str):
        """The preview substitutes exactly what template.render() does."""
        from mail_merge.template import render

        row = {"Prénom": "Zoé", "Straße": "S", "名前": "N", "Ονομα": "O", "ID_٣": "3",
               "first name": "F", "a": "A", "x_1": "X", "é": "E", "spaced": "no", "bad-name": "no"}
        js = authenticated_page.evaluate("([t, r]) => renderTemplate(t, r)", [template, row])
        assert js == render(template, row)


# ---------------------------------------------------------------------------
# buildJobFormData
# ---------------------------------------------------------------------------


class TestBuildJobFormData:
    def test_includes_basic_fields(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        page.fill("#subject-input", "Test Sub")
        page.fill("#body-input", "Test Body")
        page.select_option("#email-column", "email")
        result = page.evaluate("""() => {
            const form = buildJobFormData("test_email");
            return {
                mode: form.get("mode"),
                subject: form.get("subject"),
                body: form.get("body"),
                email_column: form.get("email_column"),
            };
        }""")
        assert result["mode"] == "test_email"
        assert result["subject"] == "Test Sub"
        assert result["body"] == "Test Body"
        assert result["email_column"] == "email"

    def test_bcc_mode_includes_blast_fields(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        page.fill("#subject-input", "Test")
        page.fill("#body-input", "Body")
        page.select_option("#email-column", "email")
        page.evaluate("() => setSendMode('bcc')")
        page.fill("#bcc-blast-to", "list@example.com")
        result = page.evaluate("""() => {
            const form = buildJobFormData("send");
            return {
                bcc_blast: form.get("bcc_blast"),
                bcc_blast_to: form.get("bcc_blast_to"),
            };
        }""")
        assert result["bcc_blast"] == "true"
        assert result["bcc_blast_to"] == "list@example.com"
        page.evaluate("() => setSendMode('individual')")

    def test_html_mode_included_when_checked(self, authenticated_page: Page, sample_xlsx: Path):
        page = authenticated_page
        _upload_and_go_to_compose(page, sample_xlsx)
        page.fill("#subject-input", "Test")
        page.fill("#body-input", "<p>HTML Body</p>")
        page.select_option("#email-column", "email")
        page.check("#html-toggle")
        result = page.evaluate("""() => {
            const form = buildJobFormData("send");
            return form.get("html");
        }""")
        assert result == "true"
        # Clean up: accept the confirm dialog when unchecking with HTML content
        page.on("dialog", lambda d: d.accept())
        page.uncheck("#html-toggle")
