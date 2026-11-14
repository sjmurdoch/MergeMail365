"""Placeholders through send_merge() and the CLI (docs/review-fixes-plan.md,
F4, F8, D1-D3): what reaches Graph, what is refused, what is warned about.
The grammar itself is tested in tests/test_template.py."""

import json
import logging
from pathlib import Path

import openpyxl
import pytest
import responses

from mail_merge.api import send_merge
from mail_merge.cli import main
from mail_merge.sender import GRAPH_SEND_URL


@pytest.fixture
def xlsx(tmp_path: Path) -> Path:
    path = tmp_path / "people.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["E-mail", "First-Name", "Price <GBP>", "Notes"])
    ws.append(["alice@example.com", "Alice", "12 < 20", "R&D <b>team</b>\nRoom 2"])
    wb.save(path)
    return path


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mail_merge.sender.time.sleep", lambda _s: None)


def sent_messages() -> list[dict]:
    return [json.loads(call.request.body)["message"] for call in responses.calls]


def run(xlsx: Path, subject: str, body: str, **kwargs: object) -> list[dict]:
    send_merge(spreadsheet=xlsx, subject=subject, body_text=body, email_column="E-mail",
               send=True, confirm=False, delay=0, token_provider=lambda: "tok", **kwargs)  # type: ignore[arg-type]
    return sent_messages()


@responses.activate
def test_punctuated_column_names_and_spaces_inside_braces_are_substituted(xlsx: Path) -> None:
    responses.add(responses.POST, GRAPH_SEND_URL, status=202)
    [message] = run(xlsx, "For {{ first-name }}", "Dear {{First-Name}}, it costs {{Price <GBP>}}. {{ Notes }}")
    assert message["subject"] == "For Alice"
    assert message["body"] == {
        "contentType": "Text",
        "content": "Dear Alice, it costs 12 < 20. R&D <b>team</b>\nRoom 2",
    }


@responses.activate
def test_html_body_gets_escaped_values_and_the_subject_does_not(xlsx: Path) -> None:
    responses.add(responses.POST, GRAPH_SEND_URL, status=202)
    [message] = run(xlsx, "{{Notes}}", "<p>{{Price &lt;GBP&gt;}}: {{Notes}}</p>", html=True)
    assert message["subject"] == "R&D <b>team</b>\nRoom 2"
    assert message["body"]["contentType"] == "HTML"
    assert "<p>12 &lt; 20: R&amp;D &lt;b&gt;team&lt;/b&gt;<br>Room 2</p>" in message["body"]["content"]
    assert "<b>team</b>" not in message["body"]["content"]


@responses.activate
@pytest.mark.parametrize(("subject", "body"), [
    ("Hi {{nope}}", "Body"),
    ("Hi", "Dear {{ First Name }}"),   # the column is First-Name
    ("Hi", "Dear {{}}"),
])
def test_a_placeholder_naming_no_column_stops_the_send(xlsx: Path, subject: str, body: str) -> None:
    with pytest.raises(ValueError, match="Unresolvable placeholders"):
        run(xlsx, subject, body)
    assert len(responses.calls) == 0


@responses.activate
@pytest.mark.parametrize(("subject", "body", "where"), [
    ("Hi {{First-Name}", "Body", "subject"),
    ("Hi", "Dear {First-Name}}", "body"),
])
def test_an_unfinished_placeholder_is_sent_as_written_with_a_warning(
    xlsx: Path, subject: str, body: str, where: str, caplog: pytest.LogCaptureFixture,
) -> None:
    responses.add(responses.POST, GRAPH_SEND_URL, status=202)
    with caplog.at_level(logging.WARNING):
        [message] = run(xlsx, subject, body)
    assert message["subject"] == subject and message["body"]["content"] == body
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and f"The {where} has" in warnings[0] and "placeholder" in warnings[0]


@responses.activate
def test_a_normal_send_logs_no_warnings(xlsx: Path, caplog: pytest.LogCaptureFixture) -> None:
    responses.add(responses.POST, GRAPH_SEND_URL, status=202)
    with caplog.at_level(logging.WARNING):
        run(xlsx, "Hi {{First-Name}}", "Costs {{Price <GBP>}} {single} braces")
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == []


@responses.activate
def test_bcc_mode_refuses_any_placeholder_however_written(xlsx: Path) -> None:
    for body in ("Dear {{First-Name}}", "Dear {{ anything at all }}"):
        with pytest.raises(ValueError, match="does not support placeholders"):
            run(xlsx, "Hi", body, bcc_blast=True, bcc_blast_to="list@example.com")
    assert len(responses.calls) == 0


def test_column_with_a_brace_in_its_name_is_reported(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    path = tmp_path / "braces.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["email", "score {max}"])
    ws.append(["a@example.com", "5"])
    wb.save(path)
    with caplog.at_level(logging.WARNING):
        send_merge(spreadsheet=path, subject="Hi", body_text="Body", email_column="email")
    assert any("score {max}" in r.getMessage() and "placeholders" in r.getMessage() for r in caplog.records)


def test_cli_dry_run_reports_the_unknown_placeholder(xlsx: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    body = tmp_path / "body.txt"
    body.write_text("Dear {{Firstname}}", encoding="utf-8")
    with caplog.at_level(logging.ERROR):
        code = main(["--spreadsheet", str(xlsx), "--body", str(body), "--subject", "Hi", "--email-column", "E-mail"])
    assert code == 1
    assert any("Unresolvable placeholders: Firstname" in r.getMessage() for r in caplog.records)
