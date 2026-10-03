"""Playwright regression tests for wizard workflow bugs found by the Quint model.

Each test replays one counterexample from ``spec/wizard.qnt`` (see the
scenario tests there and ``docs/quint-model-plan.md``). ``send_merge`` is
replaced by a gate so a test decides exactly when each background job
finishes, which is what makes the stale-completion interleavings
reproducible.
"""

import re
import socket
import threading
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import openpyxl
import pytest
from playwright.sync_api import Page, expect

import mail_merge.api
from mail_merge.web.app import create_app

STARTUP_TOKEN = "e2e-workflow-token"
ACTIVE = re.compile(r"\bactive\b")


class JobGate:
    """Stand-in for ``send_merge`` that holds selected jobs until released."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls: list[tuple[str, threading.Event]] = []
        self.finished: list[threading.Event] = []
        self.hold: set[str] = set()

    def __call__(self, **kwargs: Any) -> list[Any]:
        if kwargs.get("test_email"):
            mode = "test"
        elif kwargs.get("send"):
            mode = "send"
        else:
            mode = "dry_run"
        done = threading.Event()
        finished = threading.Event()
        if mode not in self.hold:
            done.set()
        with self._lock:
            self.calls.append((mode, done))
            self.finished.append(finished)
        try:
            if not done.wait(30):
                raise RuntimeError("job gate timed out")
            return []
        finally:
            finished.set()

    def wait_started(self, n: int) -> None:
        """Wait until at least ``n`` jobs have reached send_merge."""
        for _ in range(100):
            if len(self.calls) >= n:
                return
            time.sleep(0.05)
        raise AssertionError(f"expected {n} jobs, got {len(self.calls)}")

    def release(self, i: int) -> None:
        self.calls[i][1].set()

    def release_all(self) -> None:
        for _, done in self.calls:
            done.set()


@pytest.fixture(scope="module")
def workflow_xlsx(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("workflow") / "recipients.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["email", "name"])
    ws.append(["alice@example.com", "Alice"])
    ws.append(["bob@example.com", "Bob"])
    wb.save(path)
    return path


@pytest.fixture(scope="module")
def workflow_server() -> Iterator[str]:
    """Flask with a fixed client ID; /auth/status reports "not signed in".

    Building a real MSAL app would read the user's token cache and fetch
    OpenID metadata, so it is stubbed out (``send_merge`` never needs it here).
    """
    with patch("mail_merge.auth._build_msal_app", side_effect=RuntimeError("no MSAL in tests")):
        app = create_app(startup_token=STARTUP_TOKEN, port=0, client_id="e2e-client")
        app.config["TESTING"] = True
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        threading.Thread(
            target=lambda: app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False),
            daemon=True,
        ).start()
        base_url = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                urllib.request.urlopen(f"{base_url}/?token={STARTUP_TOKEN}", timeout=1)
                break
            except Exception:
                time.sleep(0.1)
        yield base_url


@pytest.fixture
def gate(monkeypatch: pytest.MonkeyPatch) -> Iterator[JobGate]:
    g = JobGate()
    monkeypatch.setattr(mail_merge.api, "send_merge", g)
    yield g
    g.release_all()


class AuthStub:
    """Answers the page's /auth/status and /auth/interactive requests.

    The server has no real token cache, so the browser is told whether it
    is signed in; tests flip ``signed_in`` to model sign-in, sign-out and an
    expired token. POST /auth/interactive (desktop sign-in) signs in.
    """

    def __init__(self, page: Page) -> None:
        self.signed_in = True
        page.route("**/auth/status", self._status)
        page.route("**/auth/interactive", self._interactive)

    def _status(self, route: Any) -> None:
        if self.signed_in:
            route.fulfill(json={"authenticated": True, "email": "me@example.com",
                                "token_expires_at": None})
        else:
            route.fulfill(json={"authenticated": False, "email": None})

    def _interactive(self, route: Any) -> None:
        self.signed_in = True
        route.fulfill(json={"status": "started"})


@pytest.fixture
def auth(page: Page) -> AuthStub:
    return AuthStub(page)


@pytest.fixture
def wizard(page: Page, workflow_server: str, auth: AuthStub) -> Page:
    page.goto(f"{workflow_server}/?token={STARTUP_TOKEN}")
    page.wait_for_selector("text=Data")
    # confirmGoBack() asks before discarding results; answer yes.
    page.on("dialog", lambda d: d.accept())
    return page


# ---------------------------------------------------------------------------
# Wizard actions (names follow the Quint model's actions)
# ---------------------------------------------------------------------------


def _back(page: Page, step: int) -> None:
    page.click(f"#step-{step} button:has-text('Back')")
    page.wait_for_selector(f"#step-{step - 1}.active", timeout=5000)


def _to_step4(page: Page, xlsx: Path, body: str = "Hi {{name}}") -> None:
    page.set_input_files("#spreadsheet-file", str(xlsx))
    page.wait_for_selector("#spreadsheet-info:not(.hidden)", timeout=5000)
    page.click("#btn-next-1")
    page.wait_for_selector("#step-2.active", timeout=5000)
    page.fill("#subject-input", "Hello {{name}}")
    page.fill("#body-input", body)
    page.click("#btn-next-2")
    page.wait_for_selector("#step-3.active", timeout=5000)
    page.click("#btn-next-3")
    page.wait_for_selector("#step-4.active", timeout=5000)
    page.fill("#test-email-input", "me@example.com")


def _forward_to_step4(page: Page) -> None:
    """From step 2, advance to step 4 without re-uploading."""
    page.click("#btn-next-2")
    page.wait_for_selector("#step-3.active", timeout=5000)
    page.click("#btn-next-3")
    page.wait_for_selector("#step-4.active", timeout=5000)


def _complete(page: Page, gate: JobGate, i: int) -> None:
    """Release job ``i`` and give the page time to handle its completion.

    The page may legitimately ignore a stale job, so there is no page-side
    signal to wait for; 1s is ample for SSE "done" plus the /status fetch.
    """
    gate.release(i)
    assert gate.finished[i].wait(10)
    page.wait_for_timeout(1000)


def _pass_test(page: Page) -> None:
    page.click("#btn-send-test")
    expect(page.locator("#test-result")).to_contain_text("successfully", timeout=10000)


def _pass_verify(page: Page) -> None:
    page.click("#btn-next-4")
    page.wait_for_selector("#step-5.active", timeout=5000)
    expect(page.locator("#verify-result")).to_contain_text("ready to send", timeout=10000)


def _send_all(page: Page) -> None:
    page.click("#btn-next-5")
    page.wait_for_selector("#step-6.active", timeout=5000)
    page.fill("#send-confirm-input", "SEND")
    page.click("#btn-do-send")
    expect(page.locator("#send-done-nav")).to_be_visible(timeout=10000)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStaleJobCompletions:
    def test_late_test_email_does_not_pass_edited_content(
        self, wizard: Page, gate: JobGate, workflow_xlsx: Path,
    ):
        """Model: staleTestCompletionTest / next4Honest."""
        page = wizard
        gate.hold = {"test"}
        _to_step4(page, workflow_xlsx)
        page.click("#btn-send-test")
        gate.wait_started(1)
        _back(page, 4)
        _back(page, 3)
        _complete(page, gate, 0)
        page.fill("#body-input", "Edited after the test was sent")
        _forward_to_step4(page)
        expect(page.locator("#btn-next-4")).to_be_disabled()
        assert page.evaluate("state.testPassed") is False

    def test_late_dry_run_does_not_pass_edited_content(
        self, wizard: Page, gate: JobGate, workflow_xlsx: Path,
    ):
        """Model: staleVerifyCompletionTest / next5Honest."""
        page = wizard
        _to_step4(page, workflow_xlsx)
        _pass_test(page)                       # job 0
        gate.hold = {"dry_run"}
        page.click("#btn-next-4")              # dry run A, job 1
        page.wait_for_selector("#step-5.active", timeout=5000)
        gate.wait_started(2)
        _back(page, 5)
        _back(page, 4)
        _back(page, 3)
        page.fill("#body-input", "Edited during the dry run")
        _forward_to_step4(page)
        _pass_test(page)                       # job 2
        page.click("#btn-next-4")              # dry run B, job 3
        page.wait_for_selector("#step-5.active", timeout=5000)
        gate.wait_started(4)
        _complete(page, gate, 1)               # stale dry run A finishes
        expect(page.locator("#btn-next-5")).to_be_disabled()
        assert page.evaluate("state.verifyPassed") is False


class TestButtonState:
    def test_resending_test_disables_next(
        self, wizard: Page, gate: JobGate, workflow_xlsx: Path,
    ):
        """Model: retestLeavesNextEnabledTest / buttonsMatchFlags."""
        page = wizard
        _to_step4(page, workflow_xlsx)
        _pass_test(page)
        gate.hold = {"test"}
        page.click("#btn-send-test")
        gate.wait_started(2)
        expect(page.locator("#btn-next-4")).to_be_disabled()

    def test_back_enabled_on_step6_after_new_merge(
        self, wizard: Page, gate: JobGate, workflow_xlsx: Path,
    ):
        """Model: back6AfterNewMergeTest / back6Usable."""
        page = wizard
        _to_step4(page, workflow_xlsx)
        _pass_test(page)
        _pass_verify(page)
        _send_all(page)
        page.click("#btn-new-merge")
        page.wait_for_selector("#step-1.active", timeout=5000)
        _to_step4(page, workflow_xlsx)
        _pass_test(page)
        _pass_verify(page)
        page.click("#btn-next-5")
        page.wait_for_selector("#step-6.active", timeout=5000)
        expect(page.locator("#btn-back-6")).to_be_enabled()


class TestReload:
    def test_reload_during_test_email_stays_off_send_step(
        self, wizard: Page, gate: JobGate, workflow_xlsx: Path,
    ):
        """Model: reloadDuringTestTest / sendScreenHonest."""
        page = wizard
        gate.hold = {"test"}
        _to_step4(page, workflow_xlsx)
        page.click("#btn-send-test")
        gate.wait_started(1)
        page.reload()
        page.wait_for_selector("text=Data")
        page.wait_for_timeout(500)
        expect(page.locator("#step-1")).to_have_class(ACTIVE)
        expect(page.locator("#step-6")).not_to_have_class(ACTIVE)

    def test_reload_after_test_email_stays_off_send_step(
        self, wizard: Page, gate: JobGate, workflow_xlsx: Path,
    ):
        """Model: reloadAfterTestTest / sendScreenNotStuck."""
        page = wizard
        _to_step4(page, workflow_xlsx)
        _pass_test(page)
        page.reload()
        page.wait_for_selector("text=Data")
        page.wait_for_timeout(500)
        expect(page.locator("#step-1")).to_have_class(ACTIVE)

    def test_reload_after_send_shows_results(
        self, wizard: Page, gate: JobGate, workflow_xlsx: Path,
    ):
        """Model: reloadAfterSendTest / sendScreenNotStuck."""
        page = wizard
        _to_step4(page, workflow_xlsx)
        _pass_test(page)
        _pass_verify(page)
        _send_all(page)
        page.reload()
        page.wait_for_selector("#step-6.active", timeout=5000)
        expect(page.locator("#send-done-nav")).to_be_visible(timeout=5000)


class TestSignInGate:
    def test_signed_out_step4_offers_sign_in(
        self, wizard: Page, gate: JobGate, auth: AuthStub, workflow_xlsx: Path,
    ):
        """Model: signedOutStep4Test / testNeedsSignIn, canProgress."""
        page = wizard
        auth.signed_in = False
        _to_step4(page, workflow_xlsx)
        expect(page.locator("#signin-callout-4")).to_be_visible()
        expect(page.locator("#btn-sign-in-4")).to_be_enabled()
        expect(page.locator("#btn-send-test")).to_be_disabled()

    def test_sign_in_on_step4_enables_test_email(
        self, wizard: Page, gate: JobGate, auth: AuthStub, workflow_xlsx: Path,
    ):
        """Model: signInOnStep4Test (desktop sign-in from the step 4 callout)."""
        page = wizard
        auth.signed_in = False
        _to_step4(page, workflow_xlsx)
        page.evaluate("_auth.desktopMode = true")
        page.click("#btn-sign-in-4")
        expect(page.locator("#btn-send-test")).to_be_enabled(timeout=10000)
        expect(page.locator("#signin-callout-4")).to_be_hidden()
        _pass_test(page)

    def test_failed_test_email_offers_sign_in(
        self, wizard: Page, auth: AuthStub, workflow_xlsx: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """Model: testWithoutTokenTest. The token went after step 4 was shown."""

        def not_signed_in(**kwargs: Any) -> list[Any]:
            raise RuntimeError("Not signed in. Sign in with Microsoft, then try again.")

        monkeypatch.setattr(mail_merge.api, "send_merge", not_signed_in)
        page = wizard
        _to_step4(page, workflow_xlsx)
        expect(page.locator("#btn-send-test")).to_be_enabled()
        auth.signed_in = False
        page.click("#btn-send-test")
        expect(page.locator("#test-result")).to_contain_text("Not signed in", timeout=10000)
        expect(page.locator("#signin-callout-4")).to_be_visible()
        expect(page.locator("#btn-send-test")).to_be_disabled()
        expect(page.locator("#btn-next-4")).to_be_disabled()

    def test_signed_out_step6_disables_send(
        self, wizard: Page, gate: JobGate, auth: AuthStub, workflow_xlsx: Path,
    ):
        """Model: sendNeedsSignIn, canProgress."""
        page = wizard
        _to_step4(page, workflow_xlsx)
        _pass_test(page)
        _pass_verify(page)
        auth.signed_in = False
        page.click("#btn-next-5")
        page.wait_for_selector("#step-6.active", timeout=5000)
        expect(page.locator("#signin-callout-6")).to_be_visible()
        page.fill("#send-confirm-input", "SEND")
        expect(page.locator("#btn-do-send")).to_be_disabled()


@pytest.fixture
def held_preview(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[threading.Event, threading.Event]]:
    """Hold /api/get-recipients until released: (request arrived, release)."""
    import mail_merge.excel

    arrived = threading.Event()
    release = threading.Event()
    real = mail_merge.excel.read_recipients

    def held(*args: Any, **kwargs: Any) -> Any:
        arrived.set()
        release.wait(10)
        return real(*args, **kwargs)

    monkeypatch.setattr(mail_merge.excel, "read_recipients", held)
    yield arrived, release
    release.set()


def _to_step2(page: Page, xlsx: Path) -> None:
    page.set_input_files("#spreadsheet-file", str(xlsx))
    page.wait_for_selector("#spreadsheet-info:not(.hidden)", timeout=5000)
    page.click("#btn-next-1")
    page.wait_for_selector("#step-2.active", timeout=5000)
    page.fill("#subject-input", "Hello {{name}}")
    page.fill("#body-input", "Hi {{name}}")


class TestAwaitWindows:
    def test_back_while_preview_loads_stays_on_step1(
        self, wizard: Page, workflow_xlsx: Path, held_preview: tuple[threading.Event, threading.Event],
    ):
        """Model: previewJumpTest / noStepJump."""
        page = wizard
        arrived, release = held_preview
        _to_step2(page, workflow_xlsx)
        page.click("#btn-next-2")
        assert arrived.wait(5)
        page.click("#step-2 button:has-text('Back')")
        page.wait_for_selector("#step-1.active", timeout=5000)
        release.set()
        page.wait_for_timeout(1000)
        expect(page.locator("#step-1")).to_have_class(ACTIVE)
        assert page.evaluate("state.currentStep") == 1

    def test_edit_while_preview_loads_stays_on_step2(
        self, wizard: Page, workflow_xlsx: Path, held_preview: tuple[threading.Event, threading.Event],
    ):
        """Model: previewStaleTest / previewHonest."""
        page = wizard
        arrived, release = held_preview
        _to_step2(page, workflow_xlsx)
        page.click("#btn-next-2")
        assert arrived.wait(5)
        page.fill("#body-input", "Edited while the preview loads")
        release.set()
        page.wait_for_timeout(1000)
        expect(page.locator("#step-2")).to_have_class(ACTIVE)
        expect(page.locator("#btn-next-2")).to_be_enabled()

    def test_stop_before_start_response_reaches_the_send(
        self, wizard: Page, gate: JobGate, workflow_xlsx: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """Model: earlyStopTest / stopHonoured."""
        import mail_merge.web.app as web_app

        page = wizard
        _to_step4(page, workflow_xlsx)
        _pass_test(page)
        _pass_verify(page)
        page.click("#btn-next-5")
        page.wait_for_selector("#step-6.active", timeout=5000)
        page.fill("#send-confirm-input", "SEND")
        arrived = threading.Event()
        release = threading.Event()
        real_count = web_app._validated_recipient_count

        def held_count(*args: Any, **kwargs: Any) -> int:
            arrived.set()
            release.wait(10)
            return real_count(*args, **kwargs)

        monkeypatch.setattr(web_app, "_validated_recipient_count", held_count)
        gate.hold = {"send"}
        page.click("#btn-do-send")
        assert arrived.wait(5)
        page.click("#btn-stop-send")
        release.set()
        gate.wait_started(3)
        for _ in range(50):
            sends = [j for j in web_app._jobs.values() if j.mode == "send"]
            if sends and sends[-1].stop_requested:
                break
            page.wait_for_timeout(100)
        assert sends and sends[-1].stop_requested


class TestSendOutcome:
    def test_failed_send_lists_emails_already_sent(
        self, wizard: Page, gate: JobGate, workflow_xlsx: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """Model: failedSendTest / failedSendReported."""
        from mail_merge.sender import SendAborted, SendResult

        page = wizard
        _to_step4(page, workflow_xlsx)
        _pass_test(page)
        _pass_verify(page)

        def fail_after_one(**kwargs: Any) -> list[Any]:
            raise SendAborted("Not signed in. Sign in with Microsoft, then try again.",
                              [SendResult(email="alice@example.com", success=True, status_code=202)])

        monkeypatch.setattr(mail_merge.api, "send_merge", fail_after_one)
        page.click("#btn-next-5")
        page.wait_for_selector("#step-6.active", timeout=5000)
        page.fill("#send-confirm-input", "SEND")
        page.click("#btn-do-send")
        expect(page.locator("#send-done-nav")).to_be_visible(timeout=10000)
        expect(page.locator("#send-result")).to_contain_text("Not signed in")
        expect(page.locator("#send-result .results-table")).to_contain_text("alice@example.com")

    def test_second_send_starts_with_fresh_progress(
        self, wizard: Page, gate: JobGate, workflow_xlsx: Path,
    ):
        """Model: staleProgressTest / progressHonest."""
        page = wizard
        _to_step4(page, workflow_xlsx)
        _pass_test(page)
        _pass_verify(page)
        page.click("#btn-next-5")
        page.wait_for_selector("#step-6.active", timeout=5000)
        page.evaluate("showSendProgress(2, 2)")  # as the first send's log lines would
        page.fill("#send-confirm-input", "SEND")
        page.click("#btn-do-send")
        expect(page.locator("#send-done-nav")).to_be_visible(timeout=10000)
        page.click("#btn-new-merge")
        page.wait_for_selector("#step-1.active", timeout=5000)
        _to_step4(page, workflow_xlsx)
        _pass_test(page)
        _pass_verify(page)
        page.click("#btn-next-5")
        page.wait_for_selector("#step-6.active", timeout=5000)
        gate.hold = {"send"}
        page.fill("#send-confirm-input", "SEND")
        page.click("#btn-do-send")
        expect(page.locator("#send-progress-text")).to_have_text("Sending...")

    def test_new_merge_clears_bcc_to(self, wizard: Page, gate: JobGate, workflow_xlsx: Path):
        """Model: bccToLeftTest / newMergeClears."""
        page = wizard
        _to_step2(page, workflow_xlsx)
        # The send-mode buttons are inside a collapsed section.
        page.evaluate("setSendMode('bcc'); $('bcc-blast-to').value = 'Team <team@example.com>'")
        page.evaluate("newMerge()")
        page.wait_for_selector("#step-1.active", timeout=5000)
        assert page.input_value("#bcc-blast-to") == ""


class TestInterruptedSend:
    """R15: a send the last process didn't finish is reported on step 1."""

    def test_report_shows_escapes_downloads_and_dismisses(
        self, page: Page, workflow_server: str, auth: AuthStub, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ):
        import mail_merge.web.app as web_app
        from mail_merge.sender import SendResult
        from mail_merge.web.sendlog import SendLog

        log = SendLog(tmp_path)
        log.start("old")
        log.record("old", SendResult(email="a@example.com", success=True, status_code=202))
        # Spreadsheet content is untrusted: it must not reach the page as HTML.
        log.record("old", SendResult(email="<img src=x onerror=window.pwned=1>@example.com",
                                     success=False, status_code=400, error="<b>bad</b>"))
        store = web_app._job_store
        monkeypatch.setattr(store, "send_log", None)
        monkeypatch.setattr(store, "interrupted", [])
        store.attach_send_log(log)

        page.goto(f"{workflow_server}/?token={STARTUP_TOKEN}")
        report = page.locator("#interrupted-send")
        expect(report).to_be_visible()
        expect(report).to_contain_text("1 email was recorded as sent")
        expect(report).to_contain_text("<img src=x onerror=window.pwned=1>@example.com")
        assert page.evaluate("window.pwned") is None

        with page.expect_download() as download:
            page.click("#btn-interrupted-csv")
        assert "a@example.com" in Path(download.value.path()).read_text(encoding="utf-8")

        page.click("#btn-dismiss-interrupted")
        expect(report).to_be_hidden()
        for _ in range(50):
            if not list(tmp_path.iterdir()):
                break
            time.sleep(0.05)
        assert list(tmp_path.iterdir()) == []
        page.reload()
        page.wait_for_selector("text=Data")
        expect(report).to_be_hidden()
