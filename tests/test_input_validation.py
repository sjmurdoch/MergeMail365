"""Every input is validated before the first email (docs/review-fixes-plan.md,
F7, F9, G5).

INVALID has at least one row for every parameter of send_merge() that can be
wrong: a value, and the error it must produce. Each row is run as a real
send (send=True) against a Graph mock, and must fail without a single HTTP
request and without asking for a token: nothing is sent, and nobody is asked
to sign in, for a run that can't work.

The last test reads send_merge()'s signature: a parameter with neither a row
here nor an entry in NO_VALIDATION fails it, so a new parameter can't be
added without deciding which it is.
"""

import inspect
from pathlib import Path
from typing import Any

import openpyxl
import pytest
import responses

from mail_merge.api import send_merge
from mail_merge.cli import main

# Parameters that cannot hold an invalid value, and why.
NO_VALIDATION = {
    "send": "a flag",
    "html": "a flag",
    "save_to_sent_items": "a flag",
    "confirm": "a flag",
    "resume": "a flag",
    "device_code": "a flag",
    "token_provider": "a callable supplied by the calling program",
    "should_stop": "a callable supplied by the calling program",
    "on_result": "a callable supplied by the calling program",
}

MISSING = "/no/such/dir/file"

# (parameter, overrides for an otherwise valid send, expected exception, text in the message)
INVALID: list[tuple[str, dict[str, Any], type[Exception], str]] = [
    ("spreadsheet", {"spreadsheet": MISSING + ".xlsx"}, FileNotFoundError, "Spreadsheet not found"),
    ("body", {"body": MISSING + ".txt", "body_text": None}, FileNotFoundError, "Body template not found"),
    ("body", {"body": None, "body_text": None}, ValueError, "body"),
    ("body_text", {"body_text": "Dear {{nobody}}"}, ValueError, "Unresolvable placeholders: nobody"),
    ("subject", {"subject": "Hi {{nobody}}"}, ValueError, "Unresolvable placeholders: nobody"),
    ("email_column", {"email_column": ""}, ValueError, "email_column is required"),
    ("email_column", {"email_column": "e-mail address"}, ValueError, "not found"),
    ("email_column", {"email_column": "name"}, ValueError, "No recipients remaining"),
    ("name_column", {"name_column": "full name"}, ValueError, "Name column"),
    ("sheet", {"sheet": "No such sheet"}, ValueError, "Sheet 'No such sheet' not found"),
    ("client_id", {"client_id": None, "token_provider": None}, RuntimeError, "client-id is required"),
    ("tenant_id", {"client_id": "cid", "tenant_id": "a/../b", "token_provider": None}, RuntimeError, "Invalid tenant_id"),
    ("test_email", {"test_email": "not-an-address", "send": False}, ValueError, "Invalid test email address"),
    ("test_email", {"test_email": "a@example.com, b@example.com", "send": False}, ValueError, "Expected one test email"),
    ("output", {"output": MISSING + ".csv"}, OSError, ""),
    ("delay", {"delay": -1}, ValueError, "delay must not be negative"),
    ("max_retries", {"max_retries": -1}, ValueError, "max_retries must not be negative"),
    ("importance", {"importance": "urgent"}, ValueError, "Invalid importance"),
    ("cc", {"cc": "boss@example.com, not-an-address"}, ValueError, "Invalid CC address 'not-an-address'"),
    ("cc", {"cc": ["boss@example.com", "Doe, Jane <jane@example.com>"]}, ValueError, "Invalid CC address 'Doe'"),
    ("bcc", {"bcc": "a@"}, ValueError, "Invalid BCC address"),
    ("reply_to", {"reply_to": "nobody"}, ValueError, "Invalid reply-to address"),
    ("attachment", {"attachment": [MISSING + ".pdf"]}, FileNotFoundError, "Attachment not found"),
    ("attachment", {"attachment": ["<big>"]}, ValueError, "Attachment too large"),
    ("attachment", {"attachment": ["<half>", "<half>", "<half>"]}, ValueError, "Attachments too large together"),
    ("filters", {"filters": ["no operator"]}, ValueError, "Invalid filter syntax"),
    ("filters", {"filters": ["nocolumn=x"]}, ValueError, "Filter column"),
    ("filters", {"filters": ["name=Nobody"]}, ValueError, "No recipients match"),
    ("batch_size", {"batch_size": 0}, ValueError, "batch_size must be at least 1"),
    ("batch_size", {"batch_size": -1}, ValueError, "batch_size must be at least 1"),
    ("bcc_blast", {"bcc_blast": True}, ValueError, "bcc_blast_to is required"),
    ("bcc_blast", {"bcc_blast": True, "bcc_blast_to": "list@example.com", "subject": "Hi {{name}}"}, ValueError, "does not support placeholders"),
    ("bcc_blast", {"bcc_blast": True, "bcc_blast_to": "list@example.com", "batch_size": 5, "subject": "Hi"}, ValueError, "not supported with --bcc-blast"),
    ("bcc_blast_to", {"bcc_blast": True, "bcc_blast_to": "nobody", "subject": "Hi"}, ValueError, "Invalid BCC-mode To address"),
]


@pytest.fixture
def valid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    xlsx = tmp_path / "people.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["name", "email"])
    ws.append(["Alice", "alice@example.com"])
    ws.append(["Bob", "bob@example.com"])
    wb.save(xlsx)
    (tmp_path / "big.bin").write_bytes(b"x" * (3 * 1024 * 1024 + 1))
    (tmp_path / "half.bin").write_bytes(b"x" * (1536 * 1024))
    monkeypatch.delenv("MERGEMAIL365_CLIENT_ID", raising=False)
    monkeypatch.delenv("MERGEMAIL365_TENANT_ID", raising=False)
    monkeypatch.setattr("mail_merge.config.DEFAULT_PATH", tmp_path / "no-config.toml")
    monkeypatch.setattr("mail_merge.sender.time.sleep", lambda _s: None)
    # The token cache must not be read: nobody is signed in here.
    monkeypatch.setattr("mail_merge.auth.CACHE_PATH", tmp_path / "no-cache.json")
    return {
        "spreadsheet": xlsx, "subject": "Hello {{name}}", "body_text": "Dear {{name}}",
        "email_column": "email", "send": True, "confirm": False, "delay": 0,
        "_tmp": tmp_path,
    }


def _resolve(overrides: dict[str, Any], tmp_path: Path) -> dict[str, Any]:
    out = dict(overrides)
    if "attachment" in out:
        names = {"<big>": tmp_path / "big.bin", "<half>": tmp_path / "half.bin"}
        out["attachment"] = [names.get(a, a) for a in out["attachment"]]
    return out


@pytest.mark.parametrize(("parameter", "overrides", "error", "text"), INVALID,
                         ids=[f"{p}: {t or e.__name__}" for p, _, e, t in INVALID])
def test_invalid_input_fails_before_anything_is_sent(
    valid: dict[str, Any], parameter: str, overrides: dict[str, Any], error: type[Exception], text: str,
) -> None:
    tmp_path = valid.pop("_tmp")
    token_requests = []

    def token_provider() -> str:
        token_requests.append(1)
        return "tok"

    kwargs = {**valid, "token_provider": token_provider, **_resolve(overrides, tmp_path)}
    assert parameter in overrides or parameter in ("bcc_blast",), "the row must set the parameter it is about"
    with responses.RequestsMock() as graph:  # no answers registered: any request is an error
        with pytest.raises(error) as raised:
            send_merge(**kwargs)
        assert len(graph.calls) == 0, "a request was made before the input was refused"
    assert text in str(raised.value)
    assert not token_requests, "a token was asked for before the input was refused"


def test_the_valid_send_these_rows_start_from_does_send(valid: dict[str, Any]) -> None:
    """Otherwise every row above could be failing for some other reason."""
    from mail_merge.sender import GRAPH_SEND_URL

    valid.pop("_tmp")
    with responses.RequestsMock() as graph:
        graph.add(responses.POST, GRAPH_SEND_URL, status=202)
        results = send_merge(**valid, token_provider=lambda: "tok")
    assert [r.success for r in results] == [True, True]


def test_every_parameter_has_a_row_or_a_reason() -> None:
    parameters = set(inspect.signature(send_merge).parameters)
    covered = {parameter for parameter, *_ in INVALID}
    assert not covered & set(NO_VALIDATION), "a parameter is listed both ways"
    undecided = parameters - covered - set(NO_VALIDATION)
    assert not undecided, (
        f"send_merge() parameters with no invalid-input row and no entry in NO_VALIDATION: {sorted(undecided)}"
    )
    stale = (covered | set(NO_VALIDATION)) - parameters
    assert not stale, f"rows for parameters send_merge() no longer has: {sorted(stale)}"


# ---- The CLI gives the same answers through argparse ----


@pytest.mark.parametrize(("flag", "value", "text"), [
    ("--batch-size", "0", "must be at least 1"),
    ("--batch-size", "-1", "must be at least 1"),
    ("--delay", "-0.5", "must not be negative"),
    ("--max-retries", "-2", "must not be negative"),
    ("--importance", "urgent", "invalid choice"),
])
def test_cli_refuses_out_of_range_options(valid: dict[str, Any], capsys: pytest.CaptureFixture[str],
                                          flag: str, value: str, text: str) -> None:
    tmp_path = valid.pop("_tmp")
    body = tmp_path / "body.txt"
    body.write_text("Hello", encoding="utf-8")
    with pytest.raises(SystemExit) as exit_info:
        main(["--spreadsheet", str(valid["spreadsheet"]), "--body", str(body), "--subject", "Hi",
              "--email-column", "email", f"{flag}={value}"])
    assert exit_info.value.code == 2
    assert text in capsys.readouterr().err
