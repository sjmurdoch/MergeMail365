"""Server-side sessions: the cookie is only an id, so it stays small
whatever the wizard stores (docs/review-fixes-plan.md, F14, G8).

tests/conftest.py also fails any test in the suite whose response sets a
cookie over 2 KB, so going back to keeping data in the cookie is noticed
wherever it happens.
"""

import time
from pathlib import Path
from unittest.mock import patch

import openpyxl
import pytest

pytest.importorskip("flask")

from mail_merge.web.app import create_app  # noqa: E402
from mail_merge.web.sessions import MAX_SESSIONS, ServerSideSessions  # noqa: E402


@pytest.fixture
def app():
    application = create_app(startup_token="tok", port=5050, client_id="cid")
    application.config["TESTING"] = True
    return application


def signed_in_client(app):
    c = app.test_client()
    assert c.get("/?token=tok").status_code == 302
    c.get("/")
    with c.session_transaction() as sess:
        return c, {"X-CSRF-Token": sess["csrf_token"]}


def cookie_bytes(resp) -> int:
    return max((len(v) for v in resp.headers.getlist("Set-Cookie")), default=0)


@pytest.fixture
def wide_xlsx(tmp_path: Path) -> Path:
    """200 columns with 100-character headers and 50 sheets: about 25 KB of
    names, six times what a cookie can hold. A survey export looks like
    this, with each question's full text as its column header."""
    path = tmp_path / "survey.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Responses"
    headers = ["email"] + [f"Q{i:03d} " + "how strongly do you agree that ".ljust(95, "x") for i in range(199)]
    assert all(len(h) >= 5 for h in headers) and len(headers) == 200
    ws.append(headers)
    ws.append(["alice@example.com"] + ["agree"] * 199)
    ws.append(["bob@example.com"] + ["disagree"] * 199)
    for i in range(49):
        wb.create_sheet(f"Sheet with a long descriptive name {i:02d}")
    wb.save(path)
    return path


def test_wizard_works_with_a_very_wide_spreadsheet(app, wide_xlsx: Path) -> None:
    c, headers = signed_in_client(app)
    with wide_xlsx.open("rb") as f:
        resp = c.post("/api/upload-spreadsheet", data={"spreadsheet": (f, "survey.xlsx")}, headers=headers)
    assert resp.status_code == 200
    assert len(resp.get_json()["columns"]) == 200 and len(resp.get_json()["sheets"]) == 50
    assert 0 < cookie_bytes(resp) < 1024

    # Every later step still finds the session and the spreadsheet.
    config = c.get("/api/config")
    assert cookie_bytes(config) < 1024
    assert len(config.get_json()["spreadsheet"]["columns"]) == 200
    assert len(config.get_json()["spreadsheet"]["rows"]) == 2

    resp = c.post("/api/change-sheet", json={"sheet": "Responses"}, headers=headers)
    assert resp.status_code == 200 and cookie_bytes(resp) < 1024

    resp = c.post("/api/get-recipients", data={"email_column": "email"}, headers=headers)
    assert resp.status_code == 200
    assert [r["email"] for r in resp.get_json()["recipients"]] == ["alice@example.com", "bob@example.com"]

    resp = c.post("/api/start-job", data={
        "mode": "dry_run", "email_column": "email", "subject": "Hi", "body": "Hello",
    }, headers=headers)
    assert resp.status_code == 200 and cookie_bytes(resp) < 1024


def test_cookie_holds_an_id_and_nothing_else(app) -> None:
    c, headers = signed_in_client(app)
    with patch("mail_merge.auth.initiate_auth_code_flow") as flow:
        flow.return_value = {"auth_uri": "https://login.example/authorize", "state": "s",
                             "code_verifier": "PKCE-VERIFIER-SECRET", "nonce": "n"}
        resp = c.get("/auth/login?client_id=cid", base_url="http://localhost:5050/")
    assert resp.status_code == 302
    cookie = c.get_cookie("session")
    assert cookie is not None
    assert "PKCE-VERIFIER-SECRET" not in cookie.value
    assert len(cookie.value) < 100
    with c.session_transaction() as sess:
        assert sess["auth_flow"]["code_verifier"] == "PKCE-VERIFIER-SECRET"


def test_unknown_or_forged_cookie_is_not_a_session(app) -> None:
    c = app.test_client()
    c.set_cookie("session", "made-up-session-id")
    assert c.get("/").status_code == 403
    c.set_cookie("session", "")
    assert c.get("/api/config").status_code == 403


def test_requests_without_the_token_leave_nothing_in_the_store(app) -> None:
    store = app.session_interface._store
    for _ in range(5):
        fresh = app.test_client()
        assert fresh.get("/").status_code == 403
        assert fresh.get("/static/style.css").status_code == 200
        assert fresh.get("/auth/callback?code=x").status_code == 400
        assert fresh.get_cookie("session") is None
    assert store == {}


def test_session_cookie_attributes(app) -> None:
    resp = app.test_client().get("/?token=tok")
    cookie = resp.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie and "Path=/" in cookie
    assert "tok" not in cookie.split("=", 1)[1].split(";")[0]


def test_session_expires_after_its_lifetime(app, monkeypatch) -> None:
    c, _headers = signed_in_client(app)
    assert c.get("/").status_code == 200
    real = time.monotonic
    lifetime = app.permanent_session_lifetime.total_seconds()
    # Activity slides the window...
    monkeypatch.setattr("mail_merge.web.sessions.time.monotonic", lambda: real() + lifetime - 60)
    assert c.get("/").status_code == 200
    # ...and silence for the whole lifetime ends the session.
    monkeypatch.setattr("mail_merge.web.sessions.time.monotonic", lambda: real() + 2 * lifetime)
    assert c.get("/").status_code == 403


def test_a_read_only_request_does_not_overwrite_a_concurrent_write(app) -> None:
    """Two requests in flight: one only reads the session, the other stores
    the job id. Whichever finishes last, the job id must survive."""
    c, _headers = signed_in_client(app)
    sid = c.get_cookie("session").value
    interface: ServerSideSessions = app.session_interface

    with app.test_request_context("/api/config", headers={"Cookie": f"session={sid}"}):
        reader = interface.open_session(app, __import__("flask").request)
    with c.session_transaction() as writer:
        writer["job_id"] = "job-123"
    # The reader finishes after the writer.
    interface.save_session(app, reader, app.response_class())
    with c.session_transaction() as sess:
        assert sess.get("job_id") == "job-123"


def test_store_is_bounded(app) -> None:
    interface: ServerSideSessions = app.session_interface
    for _ in range(MAX_SESSIONS + 50):
        assert app.test_client().get("/?token=tok").status_code == 302
    assert len(interface._store) <= MAX_SESSIONS


def test_handoff_to_localhost_keeps_the_uploaded_spreadsheet(app, wide_xlsx: Path) -> None:
    """Opened at 127.0.0.1, uploaded, then signed in: the sign-in moves to
    localhost, and the session there is the same one."""
    c = app.test_client()
    c.get("/?token=tok", base_url="http://127.0.0.1:5050/")
    c.get("/", base_url="http://127.0.0.1:5050/")
    with c.session_transaction(base_url="http://127.0.0.1:5050/") as sess:
        headers = {"X-CSRF-Token": sess["csrf_token"]}
    with wide_xlsx.open("rb") as f:
        c.post("/api/upload-spreadsheet", data={"spreadsheet": (f, "survey.xlsx")}, headers=headers,
               base_url="http://127.0.0.1:5050/")

    handover = c.get("/auth/login?client_id=cid", base_url="http://127.0.0.1:5050/").headers["Location"]
    with patch("mail_merge.auth.initiate_auth_code_flow") as flow, \
         patch("mail_merge.auth.acquire_token_by_auth_code", return_value="tok"):
        flow.return_value = {"auth_uri": "https://login.example/authorize", "state": "s"}
        c.get(handover)
        c.get("/auth/callback?code=x&state=s", base_url="http://localhost:5050/")
    config = c.get("/api/config", base_url="http://localhost:5050/")
    assert config.status_code == 200
    assert config.get_json()["spreadsheet"]["file_name"] == "survey.xlsx"
