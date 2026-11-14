"""No secrets in logs (docs/review-fixes-plan.md, F2, F13, G2).

Each test runs a real flow with file logging on and the root logger at
DEBUG, with distinctive canary strings standing in for the credentials and
the message, then searches everything that was logged for them.

The canaries are plain strings, not token-shaped, so the redacting formatter
cannot hide them: these tests check that the code does not log the values in
the first place. The formatter (console.redact) is the second line of
defence and is tested separately at the end.
"""

import base64
import logging
import threading
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import openpyxl
import pytest
import requests
import responses

from mail_merge.cli import main
from mail_merge.console import redact, setup_file_logging
from mail_merge.sender import GRAPH_SEND_URL
from tests.test_msal_contract import (  # noqa: F401  (entra is a fixture)
    CLIENT_ID,
    REDIRECT_URI,
    TENANT_ID,
    TOKEN_ENDPOINT,
    _token_response,
    entra,
)

ACCESS = "CANARY-ACCESS-TOKEN-7f3a"
REFRESH = "CANARY-REFRESH-TOKEN-91bc"
STARTUP = "CANARY-STARTUP-TOKEN-55de"
BODY = "CANARY-BODY-TEXT-2e6f"
ATTACHMENT = b"CANARY-ATTACHMENT-BYTES-c0de"


class Logs:
    """Everything logged during a test: the log file and pytest's capture."""

    def __init__(self, directory: Path, caplog: pytest.LogCaptureFixture) -> None:
        self.directory = directory
        self.caplog = caplog

    def file_text(self) -> str:
        for handler in logging.getLogger().handlers:
            handler.flush()
        return "".join(p.read_text(encoding="utf-8") for p in sorted(self.directory.glob("*.log*")))

    def assert_absent(self, *secrets: str, file_only: bool = False) -> None:
        text = self.file_text()
        assert text, "nothing was written to the log file: is file logging on?"
        for secret in secrets:
            assert secret not in text, f"{secret!r} is in the log file"
            if not file_only:
                assert secret not in self.caplog.text, f"{secret!r} was logged"


@pytest.fixture
def logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> Iterator[Logs]:
    log_dir = tmp_path / "logs"
    monkeypatch.setattr("mail_merge._paths.log_dir", lambda: log_dir)
    root = logging.getLogger()
    before, level = list(root.handlers), root.level
    caplog.set_level(logging.DEBUG)
    assert setup_file_logging() is not None
    try:
        yield Logs(log_dir, caplog)
    finally:
        for handler in list(root.handlers):
            if handler not in before:
                root.removeHandler(handler)
                handler.close()
        root.setLevel(level)


@pytest.fixture
def xlsx(tmp_path: Path) -> Path:
    path = tmp_path / "people.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["name", "email"])
    ws.append(["Alice", "alice@example.com"])
    ws.append(["Bob", "bob@example.com"])
    wb.save(path)
    return path


@pytest.fixture
def attachment(tmp_path: Path) -> Path:
    path = tmp_path / "notes.txt"
    path.write_bytes(ATTACHMENT)
    return path


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("mail_merge.sender.time.sleep", lambda _s: None)
    monkeypatch.setattr("mail_merge.config.DEFAULT_PATH", tmp_path / "no-config.toml")


def message_secrets() -> list[str]:
    return [ACCESS, BODY, ATTACHMENT.decode(), base64.b64encode(ATTACHMENT).decode()]


@responses.activate
def test_cli_send_logs_no_token_body_or_attachment(
    logs: Logs, xlsx: Path, attachment: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses.add(responses.POST, GRAPH_SEND_URL, status=202)
    monkeypatch.setattr("mail_merge.auth.acquire_token", lambda *a, **kw: ACCESS)
    monkeypatch.setattr("mail_merge.auth.acquire_token_interactive_flow", lambda *a, **kw: ACCESS)
    body = tmp_path / "body.txt"
    body.write_text(f"Dear {{{{name}}}}, {BODY}", encoding="utf-8")

    assert main([
        "--spreadsheet", str(xlsx), "--body", str(body), "--subject", "Hello {{name}}",
        "--email-column", "email", "--client-id", "cid", "--attachment", str(attachment),
        "--send", "--yes", "--delay", "0", "--log-level", "DEBUG", "--log-file",
        "--output", str(tmp_path / "out.csv"),
    ]) == 0

    assert len(responses.calls) == 2
    assert ACCESS in responses.calls[0].request.headers["Authorization"], "the canary token was not used"
    assert "alice@example.com" in logs.file_text(), "the send itself should still be logged"
    logs.assert_absent(*message_secrets())


@responses.activate
def test_failed_send_logs_no_token_or_body(
    logs: Logs, xlsx: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Error paths log more than the happy path does: check those too."""
    responses.add(responses.POST, GRAPH_SEND_URL, status=403, json={"error": {"code": "ErrorAccessDenied"}})
    monkeypatch.setattr("mail_merge.auth.acquire_token", lambda *a, **kw: ACCESS)
    monkeypatch.setattr("mail_merge.auth.acquire_token_interactive_flow", lambda *a, **kw: ACCESS)
    body = tmp_path / "body.txt"
    body.write_text(BODY, encoding="utf-8")

    for extra in (["--send", "--yes"], ["--test-email", "me@example.com"]):
        assert main([
            "--spreadsheet", str(xlsx), "--body", str(body), "--subject", "Hello",
            "--email-column", "email", "--client-id", "cid", "--delay", "0",
            "--log-level", "DEBUG", *extra,
        ]) == 1
    logs.assert_absent(ACCESS, BODY)


@responses.activate
def test_web_jobs_log_no_token_body_or_attachment(
    logs: Logs, xlsx: Path, attachment: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("flask")
    from mail_merge.web.app import create_app

    responses.add(responses.POST, GRAPH_SEND_URL, status=202)
    monkeypatch.setattr("mail_merge.auth.acquire_token_silent", lambda *a, **kw: ACCESS)
    app = create_app(startup_token=STARTUP, client_id="cid", tenant_id="common")
    client = app.test_client()
    client.get(f"/?token={STARTUP}")
    client.get("/")
    with client.session_transaction() as sess:
        csrf = sess["csrf_token"]
    headers = {"X-CSRF-Token": csrf}
    with xlsx.open("rb") as f:
        client.post("/api/upload-spreadsheet", data={"spreadsheet": (f, "people.xlsx")}, headers=headers)

    panel = ""
    for mode in ("dry_run", "test_email", "send"):
        with attachment.open("rb") as f:
            job_id = client.post("/api/start-job", data={
                "mode": mode, "email_column": "email", "subject": "Hello {{name}}",
                "body": f"Dear {{{{name}}}}, {BODY}", "test_email": "me@example.com",
                "attachments": (f, "notes.txt"),
            }, headers=headers).get_json()["job_id"]
        # What the browser's log panel receives.
        panel += client.get(f"/api/job/{job_id}/events").get_data(as_text=True)
        status = client.get(f"/api/job/{job_id}/status").get_json()
        assert status["ok"], status

    assert len(responses.calls) == 3, "one test email and two sends should have reached Graph"
    logs.assert_absent(ACCESS, csrf, base64.b64encode(ATTACHMENT).decode())
    # A DEBUG dry run shows the rendered body on the console, on purpose
    # (sender.CONSOLE_ONLY); it must not be in the file.
    assert BODY in logs.caplog.text
    logs.assert_absent(BODY, file_only=True)
    for secret in [*message_secrets(), csrf, STARTUP]:
        assert secret not in panel, f"{secret!r} was sent to the browser's log panel"


def test_server_access_log_hides_startup_token_and_auth_code(
    logs: Logs, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """werkzeug logs each request line, and the startup token and the OAuth
    code arrive in query strings. A real server, so the access log is real."""
    pytest.importorskip("flask")
    from werkzeug.serving import make_server

    from mail_merge.web.app import create_app

    app = create_app(startup_token=STARTUP, client_id="cid", tenant_id="common")
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        # As the entry point logs it (web/__init__.py main()).
        logging.getLogger("mail_merge.web").info("Access URL: %s", f"{base}/?token={STARTUP}")
        session = requests.Session()
        assert session.get(f"{base}/?token={STARTUP}", allow_redirects=False).status_code == 302
        session.get(f"{base}/auth/callback?code=CANARY-AUTH-CODE&state=CANARY-STATE")
        cookie = session.cookies.get("session")
        assert cookie
    finally:
        server.shutdown()
        thread.join(5)

    text = logs.file_text()
    assert "/auth/callback" in text, "the access log should be in the log file"
    # The console must still show the access URL, so only the file is checked.
    logs.assert_absent(STARTUP, "CANARY-AUTH-CODE", "CANARY-STATE", cookie, file_only=True)


def test_sign_in_logs_no_tokens(logs: Logs, entra: responses.RequestsMock) -> None:  # noqa: F811
    """Real msal at DEBUG, against mocked Entra endpoints."""
    from mail_merge.auth import CACHE_PATH, acquire_token_by_auth_code, acquire_token_silent, initiate_auth_code_flow

    flow = initiate_auth_code_flow(CLIENT_ID, TENANT_ID, REDIRECT_URI)
    nonce = parse_qs(urlparse(flow["auth_uri"]).query)["nonce"][0]
    answer = _token_response(nonce=nonce) | {"refresh_token": REFRESH}
    entra.post(TOKEN_ENDPOINT, json=answer)
    token = acquire_token_by_auth_code(
        CLIENT_ID, TENANT_ID, flow, {"code": "CANARY-AUTH-CODE", "state": flow["state"]},
    )
    assert acquire_token_silent(CLIENT_ID, TENANT_ID) == token
    assert REFRESH in CACHE_PATH.read_text(encoding="utf-8"), "the canary never reached the cache"

    logs.assert_absent(REFRESH)
    # msal itself logs the code and the PKCE verifier at DEBUG; they may
    # show on a console someone set to DEBUG, but must not be in the file.
    assert "CANARY-AUTH-CODE" in logs.caplog.text, "msal no longer logs the code: the file filter may be removable"
    logs.assert_absent("CANARY-AUTH-CODE", flow["code_verifier"], token, answer["id_token"], file_only=True)


# --- The second line of defence: the formatter on the file and panel handlers.


@pytest.mark.parametrize(("line", "secret"), [
    ('headers {"Authorization": "Bearer abc.DEF-123_456"}', "abc.DEF-123_456"),
    ("token eyJhbGciOiJub25lIn0.eyJleHAiOjE3MDAwMDAwMDB9.c2ln expired", "eyJhbGciOiJub25lIn0"),
    ('"GET /?token=s3cr3t-Startup_Token HTTP/1.1" 302', "s3cr3t-Startup_Token"),
    ('"GET /auth/callback?code=0.AXkA_abc&state=XyZ123&session_state=9f HTTP/1.1"', "0.AXkA_abc"),
    ("Access URL: http://localhost:5050/?token=abcDEF123", "abcDEF123"),
])
def test_redact_removes_credentials(line: str, secret: str) -> None:
    cleaned = redact(line)
    assert secret not in cleaned
    assert "[redacted" in cleaned


@pytest.mark.parametrize("line", [
    "📧 Sending [3/42] to alice@example.com",
    "Failed: bob@example.com [403] ErrorAccessDenied",
    "Report written to /tmp/out.csv",
    '"POST /api/start-job HTTP/1.1" 200',
])
def test_redact_leaves_ordinary_lines_alone(line: str) -> None:
    assert redact(line) == line


def test_file_handler_redacts_messages_and_tracebacks(logs: Logs) -> None:
    log = logging.getLogger("mail_merge.test_log_secrets")
    log.warning("request failed with header Authorization: Bearer %s", "abc.def.ghi")
    try:
        raise RuntimeError("could not fetch /?token=LEAKY-STARTUP-TOKEN")
    except RuntimeError:
        log.exception("unexpected error in %s", "a request")
    text = logs.file_text()
    assert "unexpected error in a request" in text and "RuntimeError" in text
    assert "abc.def.ghi" not in text
    assert "LEAKY-STARTUP-TOKEN" not in text


def test_console_still_shows_the_access_url(logs: Logs) -> None:
    """Redaction must not reach the console: the user needs the URL."""
    logging.getLogger("mail_merge.web").info("Access URL: %s", "http://localhost:5050/?token=VISIBLE")
    assert "token=VISIBLE" in logs.caplog.text
    assert "VISIBLE" not in logs.file_text()


def test_job_log_panel_is_redacted() -> None:
    pytest.importorskip("flask")
    from mail_merge.sender import SendResult
    from mail_merge.web.jobs import JobStore

    def runner(**kw: object) -> list[SendResult]:
        logging.getLogger("mail_merge.fake").info("retrying with Bearer %s", "abc.def.ghi")
        return []

    store = JobStore()
    job = store.create("dry_run")
    assert job is not None
    level = logging.getLogger("mail_merge").level
    logging.getLogger("mail_merge").setLevel(logging.INFO)
    try:
        store.run(job, {}, runner=runner)
    finally:
        logging.getLogger("mail_merge").setLevel(level)
    messages = []
    while (event := job.events.get(timeout=1)) is not None:
        messages.append(str(event))
    assert any("retrying with Bearer [redacted]" in m for m in messages), messages
    assert not any("abc.def.ghi" in m for m in messages)

