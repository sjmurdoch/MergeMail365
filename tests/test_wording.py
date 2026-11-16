"""What the app says (docs/phase-h-guards-plan.md, class G).

Phase H found three things said wrongly that no test read: a dry run's
summary said "Sent: 7", a web job didn't name the account it sent from
although the command line does, and a 14-byte attachment was "0 KB". The
outcome matrix (test_outcomes.py) checks success against Graph's answer;
these check the words.
"""

import logging
import re
import time
from pathlib import Path

import openpyxl
import pytest
import responses

from mail_merge.cli import main
from mail_merge.sender import GRAPH_SEND_URL

pytest.importorskip("flask")

MODES = ["dry_run", "test_email", "send", "send_refused", "bcc_dry_run", "bcc_send"]


@pytest.fixture
def people(tmp_path: Path) -> Path:
    path = tmp_path / "people.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["name", "email"])
    ws.append(["Alice", "alice@example.com"])
    ws.append(["Bob", "bob@example.com"])
    wb.save(path)
    return path


@pytest.fixture(autouse=True)
def _fast_and_signed_in(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("mail_merge.sender.time.sleep", lambda _s: None)
    for flow in ("acquire_token", "acquire_token_interactive_flow", "acquire_token_silent"):
        monkeypatch.setattr(f"mail_merge.auth.{flow}", lambda *a, **kw: "fake-token")
    monkeypatch.setattr("mail_merge.auth.account_name", lambda *a, **kw: "me@example.com")
    monkeypatch.setattr("mail_merge.auth.cached_account_names", lambda *a, **kw: ["me@example.com"])


def _graph(rsps: responses.RequestsMock, mode: str) -> None:
    if mode == "send_refused":
        rsps.add(responses.POST, GRAPH_SEND_URL, status=403, json={"error": {"code": "ErrorAccessDenied"}})
    else:
        rsps.add(responses.POST, GRAPH_SEND_URL, status=202)


def _subject(mode: str) -> str:
    return "Hello" if mode.startswith("bcc") else "Hello {{name}}"


def run_cli(mode: str, xlsx: Path) -> None:
    body = xlsx.parent / "body.txt"
    body.write_text("Body", encoding="utf-8")
    argv = ["--spreadsheet", str(xlsx), "--body", str(body), "--subject", _subject(mode),
            "--email-column", "email", "--client-id", "cid", "--delay", "0", "--yes"]
    if mode.startswith("bcc"):
        argv += ["--bcc-blast", "--bcc-blast-to", "list@example.com"]
    if mode == "test_email":
        argv += ["--test-email", "tester@example.com"]
    elif "dry_run" not in mode:
        argv += ["--send"]
    main(argv)


def run_web(mode: str, xlsx: Path) -> None:
    from mail_merge.web.app import create_app

    app = create_app(startup_token="wording-token", client_id="cid", tenant_id="common")
    client = app.test_client()
    client.get("/?token=wording-token")
    client.get("/")
    with client.session_transaction() as sess:
        headers = {"X-CSRF-Token": sess["csrf_token"]}
    with xlsx.open("rb") as f:
        assert client.post("/api/upload-spreadsheet", data={"spreadsheet": (f, xlsx.name)},
                           headers=headers).status_code == 200
    job_mode = "dry_run" if "dry_run" in mode else "test_email" if mode == "test_email" else "send"
    form = {"mode": job_mode, "email_column": "email", "subject": _subject(mode), "body": "Body",
            "test_email": "tester@example.com"}
    if mode.startswith("bcc"):
        form.update(bcc_blast="true", bcc_blast_to="list@example.com")
    resp = client.post("/api/start-job", data=form, headers=headers)
    assert resp.status_code == 200, resp.get_json()
    job_id = resp.get_json()["job_id"]
    deadline = time.monotonic() + 30
    while client.get(f"/api/job/{job_id}/status").get_json()["status"] in ("pending", "running"):
        assert time.monotonic() < deadline, "job did not finish"
        time.sleep(0.01)


INTERFACES = {"cli": run_cli, "web": run_web}


def said(interface: str, mode: str, xlsx: Path, caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """What the app's own loggers said, at INFO and above, during one run."""
    caplog.clear()
    with caplog.at_level(logging.INFO), responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _graph(rsps, mode)
        INTERFACES[interface](mode, xlsx)
    return [r for r in caplog.records if r.name.startswith("mail_merge") and r.levelno >= logging.INFO]


# Lines only one of the two says, with the reason: (mode, "cli" or "web",
# message) -> why. Empty: they say the same.
ONLY_ONE_SAYS: dict[tuple[str, str, str], str] = {}


@pytest.mark.parametrize("mode", MODES)
def test_command_line_and_web_job_say_the_same(mode: str, people: Path, caplog: pytest.LogCaptureFixture) -> None:
    """The web UI's log panel and the terminal describe the same send, so
    a line added for one (as "Sending as ..." was, for the command line)
    must be said by the other, or be listed above with the reason."""
    cli = [(r.levelname, str(r.msg)) for r in said("cli", mode, people, caplog)]
    web = [(r.levelname, str(r.msg)) for r in said("web", mode, people, caplog)]
    assert cli, "the run logged nothing"
    differences = {(mode, "cli", msg) for _, msg in cli if (_, msg) not in web}
    differences |= {(mode, "web", msg) for _, msg in web if (_, msg) not in cli}
    assert differences == {d for d in ONLY_ONE_SAYS if d[0] == mode}
    # Compared as a set of lines, not in order: a web job fetches its token
    # when the first email needs it, so "Sending as" follows the first
    # "Sending ..." line there and precedes it on the command line.
    assert sorted(cli) == sorted(web)


SENDING_WORDS = re.compile(r"\b(sent|sending|delivered)\b", re.IGNORECASE)


@pytest.mark.parametrize("interface", INTERFACES)
@pytest.mark.parametrize("mode", ["dry_run", "bcc_dry_run"])
def test_a_dry_run_never_says_sent(mode: str, interface: str, people: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Phase H: a dry run ended with "Summary: Total: 7, Sent: 7"."""
    with responses.RequestsMock() as nothing_may_be_sent:
        lines = [r.getMessage() for r in said(interface, mode, people, caplog)]
        assert len(nothing_may_be_sent.calls) == 0
    for line in lines:
        if SENDING_WORDS.search(line):
            assert "nothing sent" in line, f"a dry run said: {line!r}"
    assert any("nothing sent" in line for line in lines), lines


@pytest.fixture
def one_person(tmp_path: Path) -> Path:
    path = tmp_path / "one.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["name", "email"])
    ws.append(["Alice", "alice@example.com"])
    wb.save(path)
    return path


# "1 recipients", "1 real emails": one of something, named in the plural.
ONE_OF_MANY = re.compile(r"(?<![\d.,:/-])1 (?:[a-z]+ )?[a-z]{3,}s\b")


@pytest.mark.parametrize("interface", INTERFACES)
@pytest.mark.parametrize("mode", MODES)
def test_one_of_something_is_not_plural(
    mode: str, interface: str, one_person: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """The smallest case is the one a first try uses, and the one whose
    wording nobody reads: "0 KB" for 14 bytes was this kind of mistake."""
    wrong = [line for r in said(interface, mode, one_person, caplog)
             if ONE_OF_MANY.search(line := r.getMessage())]
    assert not wrong, wrong
