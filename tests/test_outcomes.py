"""Outcome honesty: what the user is told matches what Graph said.

One table (ANSWERS) says, for each way Graph can answer a sendMail request,
whether the email was accepted. Every mode that sends is then run through
every interface (Python API, CLI, web job) against every answer, and each
interface must report success exactly when the email was accepted.

Why this exists: a rejected test email used to end the web job as
"completed", which the page showed as "Test email sent successfully!"
(docs/review-fixes-plan.md, F1 and G1). spec/coverage.toml [assumptions]
names this file as what pins the model's "the email was accepted".
"""

import logging
import time
from collections.abc import Callable
from pathlib import Path

import openpyxl
import pytest
import requests
import responses

from mail_merge.api import send_merge
from mail_merge.cli import main
from mail_merge.sender import GRAPH_SEND_URL, SendAborted

TEST_ADDRESS = "tester@example.com"


def _status(code: int, times: int = 1) -> Callable[[responses.RequestsMock], None]:
    def add(rsps: responses.RequestsMock) -> None:
        for _ in range(times):
            rsps.add(responses.POST, GRAPH_SEND_URL, status=code,
                     json={"error": {"code": "Canary", "message": f"graph said {code}"}})
    return add


def _then(*steps: Callable[[responses.RequestsMock], None]) -> Callable[[responses.RequestsMock], None]:
    def add(rsps: responses.RequestsMock) -> None:
        for step in steps:
            step(rsps)
    return add


def _raises(exc: Exception) -> Callable[[responses.RequestsMock], None]:
    def add(rsps: responses.RequestsMock) -> None:
        rsps.add(responses.POST, GRAPH_SEND_URL, body=exc)
    return add


# How Graph answers each sendMail request -> was the email accepted?
# (`responses` repeats the last registered answer, so one entry also covers
# "the same answer until the retry cap".)
ANSWERS: dict[str, tuple[Callable[[responses.RequestsMock], None], bool]] = {
    "202": (_status(202), True),
    "401 then 202": (_then(_status(401), _status(202)), True),
    "500 then 202": (_then(_status(500), _status(202)), True),
    "429 then 202": (_then(_status(429), _status(202)), True),
    "400": (_status(400), False),
    "401 twice": (_status(401), False),
    "403": (_status(403), False),
    "413": (_status(413), False),
    "429 until the cap": (_status(429), False),
    "500 until the cap": (_status(500), False),
    "connection error": (_raises(requests.ConnectionError("connection refused")), False),
    "read timeout": (_raises(requests.ReadTimeout("read timed out")), False),
}

# Every mode that can send an email. Dry runs are covered separately below:
# they must make no request at all.
SENDING_MODES = ["test_email", "send", "bcc_test", "bcc_send"]


@pytest.fixture
def one_recipient(tmp_path: Path) -> Path:
    path = tmp_path / "one.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["name", "email"])
    ws.append(["Alice", "alice@example.com"])
    wb.save(path)
    return path


@pytest.fixture(autouse=True)
def _fast_and_signed_in(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Retries and the delay between sends sleep; none of that is under test.
    monkeypatch.setattr("mail_merge.sender.time.sleep", lambda _s: None)
    monkeypatch.setattr("mail_merge.auth.acquire_token", lambda *a, **kw: "fake-token")
    monkeypatch.setattr("mail_merge.auth.acquire_token_interactive_flow", lambda *a, **kw: "fake-token")
    monkeypatch.setattr("mail_merge.auth.acquire_token_silent", lambda *a, **kw: "fake-token")
    monkeypatch.setattr("mail_merge.config.DEFAULT_PATH", tmp_path / "no-config.toml")


def _mode_kwargs(mode: str) -> dict[str, object]:
    blast = {"bcc_blast": True, "bcc_blast_to": "list@example.com"}
    return {
        "test_email": {"test_email": TEST_ADDRESS},
        "send": {"send": True},
        "bcc_test": {"test_email": TEST_ADDRESS, **blast},
        "bcc_send": {"send": True, **blast},
    }[mode]


def _subject(mode: str) -> str:
    # BCC mode refuses placeholders.
    return "Hello" if mode.startswith("bcc") else "Hello {{name}}"


# --- The three interfaces: each returns True if it reported success. ---


def via_api(mode: str, xlsx: Path, caplog: pytest.LogCaptureFixture) -> bool:
    try:
        results = send_merge(
            spreadsheet=xlsx, body_text="Body", subject=_subject(mode), email_column="email",
            token_provider=lambda: "fake-token", confirm=False, delay=0, **_mode_kwargs(mode),  # type: ignore[arg-type]
        )
    except SendAborted:
        return False
    assert results, "a sending mode returns a result per email"
    return all(r.success for r in results)


def via_cli(mode: str, xlsx: Path, caplog: pytest.LogCaptureFixture) -> bool:
    body = xlsx.parent / "body.txt"
    body.write_text("Body", encoding="utf-8")
    argv = ["--spreadsheet", str(xlsx), "--body", str(body), "--subject", _subject(mode),
            "--email-column", "email", "--client-id", "cid", "--delay", "0", "--yes"]
    if mode.startswith("bcc"):
        argv += ["--bcc-blast", "--bcc-blast-to", "list@example.com"]
    argv += ["--test-email", TEST_ADDRESS] if mode.endswith("test") or mode == "test_email" else ["--send"]
    with caplog.at_level(logging.INFO):
        exit_code = main(argv)
    problems = [r for r in caplog.records if r.levelno >= logging.WARNING and "not sent" in r.getMessage().lower()
                or r.levelno >= logging.WARNING and "failed" in r.getMessage().lower()]
    if exit_code == 0:
        assert not problems, f"exit 0 but the log reports a failure: {[r.getMessage() for r in problems]}"
        return True
    # A failure the user is not told about is half the bug: exit status 1
    # with nothing in the log.
    assert problems, "non-zero exit with no line saying what failed"
    return False


def via_web(mode: str, xlsx: Path, caplog: pytest.LogCaptureFixture) -> bool:
    pytest.importorskip("flask")
    from mail_merge.web.app import create_app

    app = create_app(startup_token="outcome-token", client_id="cid", tenant_id="common")
    client = app.test_client()
    client.get("/?token=outcome-token")
    client.get("/")
    with client.session_transaction() as sess:
        headers = {"X-CSRF-Token": sess["csrf_token"]}
    with xlsx.open("rb") as f:
        assert client.post("/api/upload-spreadsheet", data={"spreadsheet": (f, "one.xlsx")},
                           headers=headers).status_code == 200
    form = {"mode": "test_email" if "test" in mode else "send", "email_column": "email",
            "subject": _subject(mode), "body": "Body", "test_email": TEST_ADDRESS}
    if mode.startswith("bcc"):
        form.update(bcc_blast="true", bcc_blast_to="list@example.com")
    resp = client.post("/api/start-job", data=form, headers=headers)
    assert resp.status_code == 200, resp.get_json()
    job_id = resp.get_json()["job_id"]
    deadline = time.monotonic() + 30
    while True:
        status = client.get(f"/api/job/{job_id}/status").get_json()
        if status["status"] not in ("pending", "running"):
            break
        assert time.monotonic() < deadline, "job did not finish"
        time.sleep(0.01)
    if status["ok"]:
        assert status["status"] == "completed" and status["summary"]["failed"] == 0
    else:
        # Something on the page must say why: the job's error or a failed row.
        assert status["error"] or status["summary"]["failed"] > 0
    return bool(status["ok"])


INTERFACES = {"api": via_api, "cli": via_cli, "web": via_web}


@pytest.mark.parametrize("interface", INTERFACES)
@pytest.mark.parametrize("mode", SENDING_MODES)
@pytest.mark.parametrize("answer", ANSWERS)
def test_reported_outcome_matches_graph(
    answer: str, mode: str, interface: str, one_recipient: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    add_answers, accepted = ANSWERS[answer]
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        add_answers(rsps)
        reported_ok = INTERFACES[interface](mode, one_recipient, caplog)
        assert len(rsps.calls) >= 1, "a sending mode must reach Graph"
    assert reported_ok == accepted, (
        f"{interface}/{mode}: Graph answered {answer!r} (accepted={accepted}) "
        f"but the user was told {'success' if reported_ok else 'failure'}"
    )


@pytest.mark.parametrize("interface", INTERFACES)
def test_dry_run_makes_no_request_and_succeeds(
    interface: str, one_recipient: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """A dry run sends nothing, so it has no Graph answer to misreport
    (spec/coverage.toml [assumptions], completeJob.accepted for Verify)."""
    with responses.RequestsMock() as rsps:
        if interface == "api":
            results = send_merge(spreadsheet=one_recipient, body_text="Body", subject="Hi {{name}}",
                                 email_column="email")
            assert all(r.success for r in results)
        elif interface == "cli":
            body = one_recipient.parent / "body.txt"
            body.write_text("Body", encoding="utf-8")
            assert main(["--spreadsheet", str(one_recipient), "--body", str(body),
                         "--subject", "Hi {{name}}", "--email-column", "email"]) == 0
        else:
            pytest.importorskip("flask")
            from mail_merge.web.app import create_app
            app = create_app(startup_token="outcome-token", client_id="cid", tenant_id="common")
            client = app.test_client()
            client.get("/?token=outcome-token")
            client.get("/")
            with client.session_transaction() as sess:
                headers = {"X-CSRF-Token": sess["csrf_token"]}
            with one_recipient.open("rb") as f:
                client.post("/api/upload-spreadsheet", data={"spreadsheet": (f, "one.xlsx")}, headers=headers)
            job_id = client.post("/api/start-job", data={
                "mode": "dry_run", "email_column": "email", "subject": "Hi {{name}}", "body": "Body",
            }, headers=headers).get_json()["job_id"]
            deadline = time.monotonic() + 30
            while (status := client.get(f"/api/job/{job_id}/status").get_json())["status"] in ("pending", "running"):
                assert time.monotonic() < deadline
                time.sleep(0.01)
            assert status["ok"] is True
        assert len(rsps.calls) == 0


def test_every_web_job_mode_is_covered() -> None:
    """A new job mode needs a row here before it can be added."""
    pytest.importorskip("flask")
    from mail_merge.web.jobs import _MODEL_KIND

    covered = {"test_email", "send", "dry_run"}
    assert set(_MODEL_KIND) == covered, "add the new mode to SENDING_MODES (or the dry-run test)"
