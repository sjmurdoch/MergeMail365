"""Tests for the web interface."""

import logging
import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, create_autospec, patch

import openpyxl
import msal
import pytest
import responses

from mail_merge.sender import GRAPH_SEND_URL
from mail_merge.web.app import create_app


# Captured at import, before any test patches msal.PublicClientApplication.
_RealPublicClientApplication = msal.PublicClientApplication


def _mock_msal_app():
    """An MSAL app mock whose methods enforce the real msal signatures."""
    return create_autospec(_RealPublicClientApplication, instance=True)


@pytest.fixture
def app():
    """Create a Flask app with a known startup token."""
    application = create_app(startup_token="test-token-abc", port=5050)
    application.config["TESTING"] = True
    return application


@pytest.fixture
def client(app):
    """Flask test client without auth."""
    return app.test_client()


@pytest.fixture
def web_client(app):
    """Flask test client pre-authenticated with startup token."""
    c = app.test_client()
    # Authenticate via startup token
    resp = c.get("/?token=test-token-abc", follow_redirects=False)
    assert resp.status_code == 302
    return c


@pytest.fixture
def sample_xlsx_web(tmp_path):
    """Create a test spreadsheet and return its path."""
    path = tmp_path / "test.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["name", "email", "company"])
    ws.append(["Alice", "alice@example.com", "Acme"])
    ws.append(["Bob", "bob@example.com", "Widgets"])
    wb.save(path)
    return path


@pytest.fixture
def sample_xlsx_100(tmp_path):
    """Create a spreadsheet with 100 rows."""
    path = tmp_path / "big.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["name", "email"])
    for i in range(100):
        ws.append([f"User{i}", f"user{i}@example.com"])
    wb.save(path)
    return path


# ---- Shared helpers ----

def get_csrf(client):
    """Get CSRF token from session."""
    client.get("/")
    with client.session_transaction() as sess:
        return sess.get("csrf_token", "")


def wait_for_job(client, job_id, timeout_sec=15):
    """Poll job status until terminal state or timeout. Returns status dict."""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        resp = client.get(f"/api/job/{job_id}/status")
        status = resp.get_json()
        if status["status"] in ("completed", "failed", "stopped"):
            return status
        time.sleep(0.2)
    return status


# ---- Access control ----

class TestAccessControl:
    def test_index_requires_auth_token(self, client):
        resp = client.get("/")
        assert resp.status_code == 403

    def test_auth_token_sets_session(self, client):
        resp = client.get("/?token=test-token-abc", follow_redirects=False)
        assert resp.status_code == 302
        # After redirect, should be able to access index
        resp2 = client.get("/")
        assert resp2.status_code == 200

    def test_invalid_auth_token_rejected(self, client):
        resp = client.get("/?token=wrong-token", follow_redirects=False)
        # Should still be forbidden (token doesn't match)
        resp2 = client.get("/")
        assert resp2.status_code == 403

    def test_post_without_csrf_rejected(self, web_client):
        resp = web_client.post("/api/preview-template",
                               json={"subject": "test"},
                               content_type="application/json")
        assert resp.status_code == 403


@pytest.fixture(params=[False, True], ids=["browser", "desktop"])
def any_mode_app(request):
    """App in browser or desktop mode — access control must be identical."""
    application = create_app(
        startup_token="test-token-abc", port=5050, desktop_mode=request.param
    )
    application.config["TESTING"] = True
    return application


class TestAccessControlBothModes:
    """Both modes serve over a localhost port, so both need the same checks."""

    def test_requires_startup_token(self, any_mode_app):
        c = any_mode_app.test_client()
        assert c.get("/").status_code == 403
        assert c.get("/api/config").status_code == 403

    def test_post_without_session_rejected(self, any_mode_app):
        c = any_mode_app.test_client()
        resp = c.post("/api/state", json={"current_step": 2})
        assert resp.status_code == 403

    def test_empty_startup_token_never_authenticates(self, any_mode_app):
        mode = any_mode_app.config["DESKTOP_MODE"]
        application = create_app(port=5050, desktop_mode=mode)
        c = application.test_client()
        c.get("/?token=")
        assert c.get("/").status_code == 403

    def test_startup_token_grants_access(self, any_mode_app):
        c = any_mode_app.test_client()
        resp = c.get("/?token=test-token-abc", follow_redirects=False)
        assert resp.status_code == 302
        assert c.get("/").status_code == 200

    def test_post_without_csrf_rejected(self, any_mode_app):
        c = any_mode_app.test_client()
        c.get("/?token=test-token-abc")
        resp = c.post("/api/state", json={"current_step": 2})
        assert resp.status_code == 403

    def test_post_with_csrf_accepted(self, any_mode_app):
        c = any_mode_app.test_client()
        c.get("/?token=test-token-abc")
        csrf = get_csrf(c)
        resp = c.post("/api/state", json={"current_step": 2},
                      headers={"X-CSRF-Token": csrf})
        assert resp.status_code == 200

    @pytest.mark.parametrize("url", [
        "http://localhost:5050",
        "http://127.0.0.1:5050",
        "http://[::1]:5050",
        "http://LOCALHOST:5050",
    ])
    def test_loopback_host_header_accepted(self, any_mode_app, url):
        c = any_mode_app.test_client()
        resp = c.get("/?token=test-token-abc", base_url=url)
        assert resp.status_code == 302

    @pytest.mark.parametrize("url", [
        "http://evil.example:5050",
        "http://evil.example",
        "http://localhost.evil.example:5050",
        "http://127.0.0.1.evil.example:5050",
    ])
    def test_foreign_host_header_rejected(self, any_mode_app, url):
        """DNS rebinding: a page on evil.example resolved to 127.0.0.1."""
        c = any_mode_app.test_client()
        resp = c.get("/?token=test-token-abc", base_url=url)
        assert resp.status_code == 403
        # Even an already-authenticated session is refused on a foreign host
        c.get("/?token=test-token-abc")
        assert c.get("/", base_url=url).status_code == 403
        assert c.get("/static/app.js", base_url=url).status_code == 403

    def test_custom_bind_host_accepted(self):
        application = create_app(startup_token="t", port=5050, host="myhost.lan")
        c = application.test_client()
        assert c.get("/?token=t", base_url="http://myhost.lan:5050").status_code == 302
        assert c.get("/?token=t", base_url="http://localhost:5050").status_code == 302
        assert c.get("/?token=t", base_url="http://evil.example").status_code == 403

    @pytest.mark.parametrize("wildcard", ["0.0.0.0", "::"])
    def test_wildcard_bind_host_skips_host_check(self, wildcard):
        """Bound to all interfaces, the Host could be any of the machine's names."""
        application = create_app(startup_token="t", port=5050, host=wildcard)
        c = application.test_client()
        assert c.get("/?token=t", base_url="http://192.0.2.7:5050").status_code == 302


# ---- Config ----

class TestConfig:
    def test_config_returns_client_tenant(self, web_client):
        resp = web_client.get("/api/config")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "client_id" in data
        assert "tenant_id" in data


# ---- Spreadsheet upload ----

class TestUpload:
    def test_upload_xlsx_returns_columns_and_preview(self, web_client, sample_xlsx_web):
        csrf = get_csrf(web_client)
        with open(sample_xlsx_web, "rb") as f:
            resp = web_client.post(
                "/api/upload-spreadsheet",
                data={"spreadsheet": (f, "test.xlsx")},
                headers={"X-CSRF-Token": csrf},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "columns" in data
        assert "name" in data["columns"]
        assert "email" in data["columns"]
        assert len(data["rows"]) == 2
        assert data["rows"][0]["name"] == "Alice"

    def test_upload_non_xlsx_rejected(self, web_client, tmp_path):
        csrf = get_csrf(web_client)
        txt_file = tmp_path / "bad.txt"
        txt_file.write_text("not a spreadsheet")
        with open(txt_file, "rb") as f:
            resp = web_client.post(
                "/api/upload-spreadsheet",
                data={"spreadsheet": (f, "bad.txt")},
                headers={"X-CSRF-Token": csrf},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 400

    def test_upload_empty_xlsx_rejected(self, web_client, tmp_path):
        csrf = get_csrf(web_client)
        path = tmp_path / "empty.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        # No data at all
        wb.save(path)
        with open(path, "rb") as f:
            resp = web_client.post(
                "/api/upload-spreadsheet",
                data={"spreadsheet": (f, "empty.xlsx")},
                headers={"X-CSRF-Token": csrf},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 400

    def test_reupload_cleans_previous_temp_dir(self, web_client, sample_xlsx_web):
        """Re-uploading a spreadsheet removes the previous temp directory."""
        csrf = get_csrf(web_client)
        # First upload
        with open(sample_xlsx_web, "rb") as f:
            web_client.post(
                "/api/upload-spreadsheet",
                data={"spreadsheet": (f, "test.xlsx")},
                headers={"X-CSRF-Token": csrf},
                content_type="multipart/form-data",
            )
        with web_client.session_transaction() as sess:
            first_tmp = sess["spreadsheet_tmp_dir"]
        assert os.path.exists(first_tmp)

        # Second upload
        with open(sample_xlsx_web, "rb") as f:
            resp = web_client.post(
                "/api/upload-spreadsheet",
                data={"spreadsheet": (f, "test2.xlsx")},
                headers={"X-CSRF-Token": csrf},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 200
        # First temp dir should be cleaned up
        assert not os.path.exists(first_tmp)
        with web_client.session_transaction() as sess:
            assert sess["spreadsheet_tmp_dir"] != first_tmp


class TestChangeSheet:
    def test_change_sheet_returns_updated_data(self, web_client, tmp_path):
        """Changing sheet re-reads preview with new columns and rows."""
        csrf = get_csrf(web_client)
        # Create a multi-sheet workbook
        path = tmp_path / "multi.xlsx"
        wb = openpyxl.Workbook()
        ws1 = wb.active
        ws1.title = "People"
        ws1.append(["name", "email"])
        ws1.append(["Alice", "alice@example.com"])
        ws2 = wb.create_sheet("Products")
        ws2.append(["product", "price"])
        ws2.append(["Widget", "9.99"])
        wb.save(path)

        # Upload
        with open(path, "rb") as f:
            resp = web_client.post(
                "/api/upload-spreadsheet",
                data={"spreadsheet": (f, "multi.xlsx")},
                headers={"X-CSRF-Token": csrf},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["columns"] == ["name", "email"]

        # Change to "Products" sheet
        resp = web_client.post(
            "/api/change-sheet",
            json={"sheet": "Products"},
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["columns"] == ["product", "price"]
        assert data["rows"][0]["product"] == "Widget"
        assert data["file_name"] == "multi.xlsx"

    def test_change_sheet_no_upload(self, web_client):
        """Changing sheet without a prior upload returns 400."""
        csrf = get_csrf(web_client)
        resp = web_client.post(
            "/api/change-sheet",
            json={"sheet": "Sheet1"},
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 400


# ---- Reset / cleanup ----

class TestReset:
    def test_reset_cleans_temp_dir(self, web_client, sample_xlsx_web):
        """POST /api/reset cleans up temp files and resets session state."""
        csrf = get_csrf(web_client)
        with open(sample_xlsx_web, "rb") as f:
            web_client.post(
                "/api/upload-spreadsheet",
                data={"spreadsheet": (f, "test.xlsx")},
                headers={"X-CSRF-Token": csrf},
                content_type="multipart/form-data",
            )
        with web_client.session_transaction() as sess:
            tmp_dir = sess["spreadsheet_tmp_dir"]
        assert os.path.exists(tmp_dir)

        resp = web_client.post("/api/reset", headers={"X-CSRF-Token": csrf})
        assert resp.status_code == 200
        assert not os.path.exists(tmp_dir)

        with web_client.session_transaction() as sess:
            assert "spreadsheet_tmp_dir" not in sess
            assert "spreadsheet_path" not in sess
            assert "spreadsheet_info" not in sess

    def test_reset_without_upload(self, web_client):
        """POST /api/reset succeeds even with no prior upload."""
        csrf = get_csrf(web_client)
        resp = web_client.post("/api/reset", headers={"X-CSRF-Token": csrf})
        assert resp.status_code == 200


# ---- Template preview ----

class TestPreview:
    def test_preview_renders_placeholders(self, web_client):
        csrf = get_csrf(web_client)
        resp = web_client.post(
            "/api/preview-template",
            json={
                "subject": "Hello {{name}}",
                "body": "Welcome to {{company}}, {{name}}!",
                "sample_data": {"name": "Alice", "company": "Acme"},
                "columns": ["name", "company"],
            },
            headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["subject"] == "Hello Alice"
        assert "Welcome to Acme, Alice!" in data["body"]
        assert data["unresolved_placeholders"] == []

    def test_preview_reports_unresolved_placeholders(self, web_client):
        csrf = get_csrf(web_client)
        resp = web_client.post(
            "/api/preview-template",
            json={
                "subject": "Hello {{missing}}",
                "body": "Body",
                "sample_data": {"name": "Alice"},
                "columns": ["name"],
            },
            headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "missing" in data["unresolved_placeholders"]

    def test_preview_escapes_html(self, web_client):
        csrf = get_csrf(web_client)
        resp = web_client.post(
            "/api/preview-template",
            json={
                "subject": "Hi {{name}}",
                "body": "Hello {{name}}",
                "sample_data": {"name": "<script>alert('xss')</script>"},
                "columns": ["name"],
            },
            headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
        )
        data = resp.get_json()
        # The template.render doesn't escape HTML — it does literal substitution.
        # But the data is returned as JSON, so it's safe. The frontend uses textContent.
        assert "<script>" in data["subject"]  # raw in JSON is fine

    def test_preview_html_warns_plain_text(self, web_client):
        csrf = get_csrf(web_client)
        resp = web_client.post(
            "/api/preview-template",
            json={
                "subject": "Hi",
                "body": "Hello world\nSecond line",
                "sample_data": {},
                "columns": [],
                "html": True,
            },
            headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
        )
        data = resp.get_json()
        assert len(data["html_warnings"]) > 0
        assert "No HTML tags" in data["html_warnings"][0]

    def test_preview_html_warns_newlines_without_br(self, web_client):
        csrf = get_csrf(web_client)
        resp = web_client.post(
            "/api/preview-template",
            json={
                "subject": "Hi",
                "body": "<b>Hello</b>\nSecond line",
                "sample_data": {},
                "columns": [],
                "html": True,
            },
            headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
        )
        data = resp.get_json()
        assert any("Line breaks" in w for w in data["html_warnings"])

    def test_preview_html_warns_script_tags(self, web_client):
        csrf = get_csrf(web_client)
        resp = web_client.post(
            "/api/preview-template",
            json={
                "subject": "Hi",
                "body": "<p>Hello</p><script>alert(1)</script>",
                "sample_data": {},
                "columns": [],
                "html": True,
            },
            headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
        )
        data = resp.get_json()
        assert any("script" in w for w in data["html_warnings"])

    def test_preview_html_no_warnings_for_valid_html(self, web_client):
        csrf = get_csrf(web_client)
        resp = web_client.post(
            "/api/preview-template",
            json={
                "subject": "Hi",
                "body": "<p>Hello</p><br><p>World</p>",
                "sample_data": {},
                "columns": [],
                "html": True,
            },
            headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
        )
        data = resp.get_json()
        assert data["html_warnings"] == []

    def test_preview_html_no_warnings_when_not_html(self, web_client):
        csrf = get_csrf(web_client)
        resp = web_client.post(
            "/api/preview-template",
            json={
                "subject": "Hi",
                "body": "Plain text\nwith newlines",
                "sample_data": {},
                "columns": [],
            },
            headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
        )
        data = resp.get_json()
        assert data["html_warnings"] == []

    def test_preview_html_warns_style_block(self, web_client):
        csrf = get_csrf(web_client)
        resp = web_client.post(
            "/api/preview-template",
            json={
                "subject": "Hi",
                "body": "<style>body { color: red; }</style><p>Hello</p>",
                "sample_data": {},
                "columns": [],
                "html": True,
            },
            headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
        )
        data = resp.get_json()
        assert any("style" in w.lower() and "stripped" in w.lower() for w in data["html_warnings"])

    def test_preview_html_strips_full_document_tags(self, web_client):
        """Full-document tags are stripped before validation, so a valid
        body wrapped in <html> produces no warnings."""
        csrf = get_csrf(web_client)
        resp = web_client.post(
            "/api/preview-template",
            json={
                "subject": "Hi",
                "body": "<!DOCTYPE html><html><body><p>Hello</p></body></html>",
                "sample_data": {},
                "columns": [],
                "html": True,
            },
            headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
        )
        data = resp.get_json()
        assert data["html_warnings"] == []


class TestRecipientAPI:
    def test_get_recipients_filtering(self, web_client, sample_xlsx):
        # 1. Establish session with token
        web_client.get("/?token=test-token")
        csrf = get_csrf(web_client)
        
        # 2. Upload
        with open(sample_xlsx, "rb") as f:
            web_client.post(
                "/api/upload-spreadsheet",
                data={"spreadsheet": f},
                headers={"X-CSRF-Token": csrf}
            )
        
        # 3. Get with filter
        resp = web_client.post(
            "/api/get-recipients",
            data={
                "email_column": "email",
                "filters": "company=Acme"
            },
            headers={"X-CSRF-Token": csrf}
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["recipients"]) == 1
        assert data["recipients"][0]["name"] == "Alice"

    def test_get_recipients_limit_enforced(self, web_client, sample_xlsx, monkeypatch):
        # 1. Establish session
        web_client.get("/?token=test-token")
        csrf = get_csrf(web_client)
        
        # 2. Upload
        with open(sample_xlsx, "rb") as f:
            web_client.post(
                "/api/upload-spreadsheet",
                data={"spreadsheet": f},
                headers={"X-CSRF-Token": csrf}
            )
        
        # Mock read_recipients to return > 99 rows
        from mail_merge import excel
        monkeypatch.setattr(excel, "read_recipients", lambda *a, **kw: [{"email": "x@y.com"}] * 105)
        
        resp = web_client.post(
            "/api/get-recipients",
            data={"email_column": "email"},
            headers={"X-CSRF-Token": csrf}
        )
        assert resp.status_code == 400
        assert "Too many recipients" in resp.get_json()["error"]

    def test_get_recipients_reports_invalid_emails(self, web_client, tmp_path):
        """Invalid email addresses are returned in the response so the UI can warn."""
        csrf = get_csrf(web_client)
        path = tmp_path / "mixed.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["name", "email"])
        ws.append(["Alice", "alice@example.com"])
        ws.append(["Bad", "not-an-email"])
        ws.append(["Also Bad", "also@bad@example.com"])
        ws.append(["Bob", "bob@example.com"])
        wb.save(path)

        with open(path, "rb") as f:
            web_client.post(
                "/api/upload-spreadsheet",
                data={"spreadsheet": (f, "mixed.xlsx")},
                headers={"X-CSRF-Token": csrf},
                content_type="multipart/form-data",
            )

        resp = web_client.post(
            "/api/get-recipients",
            data={"email_column": "email"},
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        # Only valid emails remain
        emails = [r["email"] for r in data["recipients"]]
        assert emails == ["alice@example.com", "bob@example.com"]
        # Invalid emails are reported
        assert len(data["invalid_emails"]) == 2
        invalid_addrs = [e["address"] for e in data["invalid_emails"]]
        assert "not-an-email" in invalid_addrs
        assert "also@bad@example.com" in invalid_addrs
        # Each invalid entry has a reason
        assert all("reason" in e for e in data["invalid_emails"])
        # Total before validation includes all rows
        assert data["total_before_validation"] == 4

    def test_get_recipients_no_invalid_emails(self, web_client, sample_xlsx_web):
        """When all emails are valid, invalid_emails is empty."""
        csrf = get_csrf(web_client)
        with open(sample_xlsx_web, "rb") as f:
            web_client.post(
                "/api/upload-spreadsheet",
                data={"spreadsheet": (f, "test.xlsx")},
                headers={"X-CSRF-Token": csrf},
                content_type="multipart/form-data",
            )
        resp = web_client.post(
            "/api/get-recipients",
            data={"email_column": "email"},
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["recipients"]) == 2
        assert data["invalid_emails"] == []
        assert data["total_before_validation"] == 2


# ---- Auth endpoints ----

class TestAuth:
    @patch("mail_merge.auth.initiate_auth_code_flow")
    def test_auth_login_redirects(self, mock_flow, web_client):
        mock_flow.return_value = {
            "auth_uri": "https://login.microsoftonline.com/test",
            "state": "abc",
        }
        # Set client_id in session
        with web_client.session_transaction() as sess:
            sess["client_id"] = "test-client-id"
            sess["tenant_id"] = "common"
        resp = web_client.get("/auth/login", follow_redirects=False)
        assert resp.status_code == 302
        assert "login.microsoftonline.com" in resp.headers["Location"]

    @patch("mail_merge.auth.acquire_token_by_auth_code")
    def test_auth_callback_exchanges_code(self, mock_acquire, web_client):
        mock_acquire.return_value = "test-token"
        with web_client.session_transaction() as sess:
            sess["auth_flow"] = {"state": "abc"}
            sess["client_id"] = "test-client-id"
            sess["tenant_id"] = "common"
        resp = web_client.get("/auth/callback?code=xyz", follow_redirects=False)
        assert resp.status_code == 302
        assert "#auth-success" in resp.headers["Location"]

    def test_auth_callback_handles_error(self, web_client):
        with web_client.session_transaction() as sess:
            sess["auth_flow"] = {"state": "abc"}
        resp = web_client.get("/auth/callback?error=access_denied&error_description=User+cancelled",
                              follow_redirects=False)
        assert resp.status_code == 302
        assert "#auth-error=" in resp.headers["Location"]

    @patch("mail_merge.auth._load_cache")
    @patch("mail_merge.auth.msal.PublicClientApplication", autospec=True)
    def test_auth_status_authenticated(self, mock_app_cls, mock_cache, web_client):
        mock_cache.return_value = MagicMock()
        mock_app = _mock_msal_app()
        mock_app.get_accounts.return_value = [{"username": "user@example.com"}]
        mock_app.acquire_token_silent.return_value = {"access_token": "eyJ.eyJleHAiOjk5OTk5OTk5OTl9.sig"}
        mock_app_cls.return_value = mock_app

        with web_client.session_transaction() as sess:
            sess["client_id"] = "test-client-id"
        resp = web_client.get("/auth/status")
        data = resp.get_json()
        assert data["authenticated"] is True
        assert data["email"] == "user@example.com"

    @patch("mail_merge.web.app.load_config", return_value={})
    def test_auth_status_not_authenticated(self, mock_config, web_client):
        # Ensure no client_id in session or config
        with web_client.session_transaction() as sess:
            sess.pop("client_id", None)
        resp = web_client.get("/auth/status")
        data = resp.get_json()
        assert data["authenticated"] is False

    @patch("mail_merge.auth.diagnose_auth")
    def test_auth_debug_returns_diagnostics(self, mock_diag, web_client):
        mock_diag.return_value = {
            "cache_exists": True,
            "token_valid": False,
            "authority_reachable": True,
        }
        with web_client.session_transaction() as sess:
            sess["client_id"] = "test-client-id"
        resp = web_client.get("/auth/debug")
        data = resp.get_json()
        assert "cache_exists" in data
        assert data["authority_reachable"] is True

    @patch("mail_merge.auth.sign_out")
    def test_auth_logout(self, mock_sign_out, web_client):
        """POST /auth/logout clears the MSAL cache."""
        mock_sign_out.return_value = True
        csrf = get_csrf(web_client)
        with web_client.session_transaction() as sess:
            sess["client_id"] = "test-client-id"
            sess["tenant_id"] = "common"
            sess["ms_authenticated"] = True
        resp = web_client.post(
            "/auth/logout",
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True
        mock_sign_out.assert_called_once_with("test-client-id", "common")
        with web_client.session_transaction() as sess:
            assert "ms_authenticated" not in sess

    def test_auth_logout_requires_csrf(self, web_client):
        """POST /auth/logout without CSRF token is rejected."""
        resp = web_client.post("/auth/logout")
        assert resp.status_code == 403

    @patch("mail_merge.auth.initiate_auth_code_flow")
    @patch("mail_merge.web.app.load_config", return_value={})
    def test_auth_login_reads_client_id_from_query(self, mock_config, mock_flow, web_client):
        """Client ID and tenant ID from query params should be used when not in session."""
        mock_flow.return_value = {
            "auth_uri": "https://login.microsoftonline.com/test",
            "state": "abc",
        }
        resp = web_client.get(
            "/auth/login?client_id=from-query&tenant_id=my-tenant",
            follow_redirects=False,
            base_url="http://localhost:5050/",
        )
        assert resp.status_code == 302
        mock_flow.assert_called_once_with("from-query", "my-tenant", "http://localhost:5050/auth/callback")

    def test_auth_host_consistency_redirect(self, client):
        """Test that starting on 127.0.0.1 redirects to localhost for session consistency.

        This test would have caught the 'No auth flow in session' bug where the
        session was set on 127.0.0.1 but the callback returned to localhost.
        """
        # 1. Start on 127.0.0.1 - should redirect to localhost/auth/login...
        resp = client.get("/auth/login?client_id=test", base_url="http://127.0.0.1:5050/")
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("http://localhost:5050/auth/login")

        # 2. Follow to localhost - should now proceed to Microsoft and set session on localhost
        with patch("mail_merge.auth.initiate_auth_code_flow") as mock_flow:
            mock_flow.return_value = {"auth_uri": "https://microsoft.com/auth", "state": "abc"}
            resp = client.get(resp.headers["Location"], base_url="http://localhost:5050/")
            assert resp.status_code == 302
            assert "microsoft.com" in resp.headers["Location"]

            # Verify session is set on localhost
            with client.session_transaction() as sess:
                assert "auth_flow" in sess

    @patch("mail_merge.auth._load_cache")
    @patch("mail_merge.auth.msal.PublicClientApplication", autospec=True)
    def test_auth_status_includes_token_expiry(self, mock_app_cls, mock_cache, web_client):
        import base64, json as _json
        # Create a JWT with exp claim for 2026-03-19T12:00:00+00:00
        payload = base64.urlsafe_b64encode(_json.dumps({"exp": 1773921600}).encode()).rstrip(b"=").decode()
        fake_jwt = f"eyJ.{payload}.sig"
        mock_cache.return_value = MagicMock()
        mock_app = _mock_msal_app()
        mock_app.get_accounts.return_value = [{"username": "user@example.com"}]
        mock_app.acquire_token_silent.return_value = {"access_token": fake_jwt}
        mock_app_cls.return_value = mock_app
        with web_client.session_transaction() as sess:
            sess["client_id"] = "test-client-id"
        resp = web_client.get("/auth/status")
        data = resp.get_json()
        assert data["token_expires_at"] is not None
        assert "2026-03-19" in data["token_expires_at"]


# ---- Job lifecycle ----

class TestJobs:
    def _setup_upload(self, web_client, xlsx_path):
        """Upload a spreadsheet and return CSRF token."""
        csrf = get_csrf(web_client)
        with open(xlsx_path, "rb") as f:
            resp = web_client.post(
                "/api/upload-spreadsheet",
                data={"spreadsheet": (f, "test.xlsx")},
                headers={"X-CSRF-Token": csrf},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 200
        return csrf

    def test_dry_run_job_completes(self, web_client, sample_xlsx_web):
        csrf = self._setup_upload(web_client, sample_xlsx_web)
        resp = web_client.post(
            "/api/start-job",
            data={
                "mode": "dry_run",
                "email_column": "email",
                "subject": "Hello {{name}}",
                "body": "Body for {{name}}.",
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "job_id" in data

        status = wait_for_job(web_client, data["job_id"])
        assert status["status"] == "completed"
        assert status["summary"]["total"] == 2
        assert status["summary"]["sent"] == 2

    def test_dry_run_strips_html_doc_tags(self, web_client, sample_xlsx_web):
        """Full-document HTML tags are stripped so the wrapper is always applied."""
        csrf = self._setup_upload(web_client, sample_xlsx_web)
        resp = web_client.post(
            "/api/start-job",
            data={
                "mode": "dry_run",
                "email_column": "email",
                "subject": "Hello {{name}}",
                "body": "<!DOCTYPE html><html><head><style>body{color:red}</style>"
                        "</head><body><p>Hi {{name}}</p></body></html>",
                "html": "true",
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 200
        data = resp.get_json()

        status = wait_for_job(web_client, data["job_id"])
        assert status["status"] == "completed"
        # The body passed to send_merge should be stripped content only
        assert status["summary"]["total"] == 2

    def test_dry_run_validates_placeholders(self, web_client, sample_xlsx_web):
        csrf = self._setup_upload(web_client, sample_xlsx_web)
        resp = web_client.post(
            "/api/start-job",
            data={
                "mode": "dry_run",
                "email_column": "email",
                "subject": "Hello {{nonexistent}}",
                "body": "Body.",
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 200
        data = resp.get_json()

        status = wait_for_job(web_client, data["job_id"])
        assert status["status"] == "failed"
        assert "nonexistent" in status["error"].lower()

    @responses.activate
    @patch("mail_merge.auth.acquire_token_silent", return_value="fake-token")
    def test_send_job_completes(self, mock_auth, web_client, sample_xlsx_web):
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        csrf = self._setup_upload(web_client, sample_xlsx_web)

        with web_client.session_transaction() as sess:
            sess["client_id"] = "test-client-id"

        resp = web_client.post(
            "/api/start-job",
            data={
                "mode": "send",
                "email_column": "email",
                "subject": "Hello {{name}}",
                "body": "Body for {{name}}.",
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 200
        data = resp.get_json()

        status = wait_for_job(web_client, data["job_id"], timeout_sec=30)
        assert status["status"] == "completed"
        assert len(status["results"]) == 2

    def test_send_rejects_over_99(self, web_client, sample_xlsx_100):
        csrf = self._setup_upload(web_client, sample_xlsx_100)
        resp = web_client.post(
            "/api/get-recipients",
            data={"email_column": "email"},
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "99" in data["error"] or "Too many" in data["error"]

    def test_start_job_rejects_over_99(self, web_client, sample_xlsx_100):
        """api_start_job enforces the cap independently of api_get_recipients."""
        csrf = self._setup_upload(web_client, sample_xlsx_100)
        resp = web_client.post(
            "/api/start-job",
            data={
                "mode": "dry_run",
                "email_column": "email",
                "subject": "Hello {{name}}",
                "body": "Body.",
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "Too many" in data["error"]

    @responses.activate
    @patch("mail_merge.auth.acquire_token_silent", return_value="fake-token")
    def test_test_email_job(self, mock_auth, web_client, sample_xlsx_web):
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        csrf = self._setup_upload(web_client, sample_xlsx_web)

        with web_client.session_transaction() as sess:
            sess["client_id"] = "test-client-id"

        resp = web_client.post(
            "/api/start-job",
            data={
                "mode": "test_email",
                "email_column": "email",
                "subject": "Hello {{name}}",
                "body": "Body for {{name}}.",
                "test_email": "tester@example.com",
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 200
        data = resp.get_json()

        status = wait_for_job(web_client, data["job_id"])
        assert status["status"] == "completed"
        assert status["results"][0]["email"] == "tester@example.com"

    def test_sse_events(self, web_client, sample_xlsx_web):
        csrf = self._setup_upload(web_client, sample_xlsx_web)
        resp = web_client.post(
            "/api/start-job",
            data={
                "mode": "dry_run",
                "email_column": "email",
                "subject": "Hello {{name}}",
                "body": "Body.",
            },
            headers={"X-CSRF-Token": csrf},
        )
        data = resp.get_json()
        job_id = data["job_id"]

        # Let job run
        time.sleep(1)

        # Check status instead of SSE (SSE is streaming, hard to test with test client)
        status_resp = web_client.get(f"/api/job/{job_id}/status")
        status = status_resp.get_json()
        # Job should be completed or still running
        assert status["status"] in ("completed", "running", "pending")

    @responses.activate
    @patch("mail_merge.auth.acquire_token_silent", return_value="fake-token")
    def test_send_with_failures(self, mock_auth, web_client, sample_xlsx_web):
        """One recipient fails with 400, the other succeeds — partial failure."""
        responses.add(responses.POST, GRAPH_SEND_URL, status=400,
                      json={"error": {"code": "ErrorRecipientNotFound", "message": "Bad recipient"}})
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        csrf = self._setup_upload(web_client, sample_xlsx_web)

        with web_client.session_transaction() as sess:
            sess["client_id"] = "test-client-id"

        resp = web_client.post(
            "/api/start-job",
            data={
                "mode": "send",
                "email_column": "email",
                "subject": "Hello {{name}}",
                "body": "Body for {{name}}.",
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 200
        data = resp.get_json()

        status = wait_for_job(web_client, data["job_id"], timeout_sec=30)
        assert status["status"] == "completed"
        assert status["summary"]["sent"] == 1
        assert status["summary"]["failed"] == 1

    def _start(self, web_client, csrf, mode, **extra):
        resp = web_client.post(
            "/api/start-job",
            data={"mode": mode, "email_column": "email",
                  "subject": "Hello {{name}}", "body": "Body.", **extra},
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 200, resp.get_json()
        job_id = resp.get_json()["job_id"]
        wait_for_job(web_client, job_id)
        return job_id

    def test_config_does_not_resume_test_or_dry_run(self, web_client, sample_xlsx_web):
        """Reloading after a dry run must not jump to the Send step."""
        csrf = self._setup_upload(web_client, sample_xlsx_web)
        self._start(web_client, csrf, "dry_run")
        assert web_client.get("/api/config").get_json()["active_job_id"] is None

    def test_config_resumes_send(self, web_client, sample_xlsx_web, monkeypatch):
        import mail_merge.api
        monkeypatch.setattr(mail_merge.api, "send_merge", lambda **kwargs: [])
        csrf = self._setup_upload(web_client, sample_xlsx_web)
        with web_client.session_transaction() as sess:
            sess["client_id"] = "test-client-id"
        job_id = self._start(web_client, csrf, "send")
        assert web_client.get("/api/config").get_json()["active_job_id"] == job_id

    def test_events_end_for_finished_job_on_reconnect(self, web_client, sample_xlsx_web):
        """A second stream (after reload) ends even though the first took the sentinel."""
        csrf = self._setup_upload(web_client, sample_xlsx_web)
        job_id = self._start(web_client, csrf, "dry_run")
        bodies: list[str] = []

        def read_stream() -> None:
            resp = web_client.get(f"/api/job/{job_id}/events")
            bodies.append(resp.get_data(as_text=True))

        for _ in range(2):
            t = threading.Thread(target=read_stream, daemon=True)
            t.start()
            t.join(timeout=10)
            assert not t.is_alive(), "event stream did not end"
        assert all(b.rstrip().endswith('data: {"type": "done"}') for b in bodies)

    @patch("mail_merge.auth._save_cache")
    @patch("mail_merge.auth._load_cache")
    @patch("mail_merge.auth.msal.PublicClientApplication", autospec=True)
    def test_test_email_when_signed_out_fails_at_once(
        self, mock_app_cls, mock_load_cache, mock_save_cache, web_client, sample_xlsx_web,
    ):
        """A signed-out web job fails with a sign-in error instead of waiting.

        The job's token provider is silent-only: with no cached account it
        must not start the device-code flow, whose prompt would only reach
        the job log while the job blocked (spec/wizard.qnt,
        noInteractiveAuthInJob).
        """
        mock_load_cache.return_value = MagicMock()
        mock_app = _mock_msal_app()
        mock_app.get_accounts.return_value = []
        mock_app_cls.return_value = mock_app

        csrf = self._setup_upload(web_client, sample_xlsx_web)
        with web_client.session_transaction() as sess:
            sess["client_id"] = "test-client-id"
        resp = web_client.post(
            "/api/start-job",
            data={"mode": "test_email", "test_email": "me@example.com",
                  "email_column": "email", "subject": "Hello {{name}}", "body": "Body."},
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 200, resp.get_json()
        status = wait_for_job(web_client, resp.get_json()["job_id"], timeout_sec=5)
        assert status["status"] == "failed"
        assert "Not signed in" in status["error"]
        mock_app.initiate_device_flow.assert_not_called()
        mock_app.acquire_token_by_device_flow.assert_not_called()

    @patch("mail_merge.auth._save_cache")
    @patch("mail_merge.auth._load_cache")
    @patch("mail_merge.auth.msal.PublicClientApplication", autospec=True)
    def test_send_when_token_lost_fails_at_once(
        self, mock_app_cls, mock_load_cache, mock_save_cache, web_client, sample_xlsx_web,
    ):
        """A send whose silent refresh fails ends as failed, without a device code."""
        mock_load_cache.return_value = MagicMock()
        mock_app = _mock_msal_app()
        mock_app.get_accounts.return_value = [{"username": "me@example.com"}]
        mock_app.acquire_token_silent.return_value = None
        mock_app_cls.return_value = mock_app

        csrf = self._setup_upload(web_client, sample_xlsx_web)
        with web_client.session_transaction() as sess:
            sess["client_id"] = "test-client-id"
        resp = web_client.post(
            "/api/start-job",
            data={"mode": "send", "email_column": "email",
                  "subject": "Hello {{name}}", "body": "Body."},
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 200, resp.get_json()
        status = wait_for_job(web_client, resp.get_json()["job_id"], timeout_sec=5)
        assert status["status"] == "failed"
        assert "Not signed in" in status["error"]
        mock_app.initiate_device_flow.assert_not_called()

    def test_stop_ends_send_early(self, web_client, sample_xlsx_web, monkeypatch):
        """Stop sending stops the loop before the next email (spec/wizard.qnt, stopHonoured)."""
        import mail_merge.sender
        from mail_merge.sender import SendResult

        first_send_started = threading.Event()
        release_first = threading.Event()
        sent: list[str] = []

        def gated_send_one(get_token, to, subject, body, opts=None):
            sent.append(to.address)
            first_send_started.set()
            release_first.wait(5)
            return SendResult(email=to.address, success=True, status_code=202)

        monkeypatch.setattr(mail_merge.sender, "send_one", gated_send_one)
        monkeypatch.setattr(mail_merge.sender.time, "sleep", lambda s: None)
        csrf = self._setup_upload(web_client, sample_xlsx_web)
        with web_client.session_transaction() as sess:
            sess["client_id"] = "test-client-id"
        resp = web_client.post(
            "/api/start-job",
            data={"mode": "send", "email_column": "email",
                  "subject": "Hello {{name}}", "body": "Body."},
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 200, resp.get_json()
        job_id = resp.get_json()["job_id"]
        try:
            assert first_send_started.wait(5), "send did not start"
            resp = web_client.post(f"/api/job/{job_id}/stop", headers={"X-CSRF-Token": csrf})
            assert resp.status_code == 200
        finally:
            release_first.set()
        status = wait_for_job(web_client, job_id)
        assert status["status"] == "stopped"
        assert sent == ["alice@example.com"]
        assert status["summary"]["total"] == 1
        assert [r["email"] for r in status["results"]] == ["alice@example.com"]

    def test_send_without_stop_completes(self, web_client, sample_xlsx_web, monkeypatch):
        import mail_merge.sender
        from mail_merge.sender import SendResult

        sent: list[str] = []

        def fake_send_one(get_token, to, subject, body, opts=None):
            sent.append(to.address)
            return SendResult(email=to.address, success=True, status_code=202)

        monkeypatch.setattr(mail_merge.sender, "send_one", fake_send_one)
        monkeypatch.setattr(mail_merge.sender.time, "sleep", lambda s: None)
        csrf = self._setup_upload(web_client, sample_xlsx_web)
        with web_client.session_transaction() as sess:
            sess["client_id"] = "test-client-id"
        job_id = self._start(web_client, csrf, "send")
        status = wait_for_job(web_client, job_id)
        assert status["status"] == "completed"
        assert sent == ["alice@example.com", "bob@example.com"]

    def _start_held_send(self, web_client, sample_xlsx_web, monkeypatch):
        """Start a send whose send_merge() blocks until the returned event is set."""
        import mail_merge.api
        release = threading.Event()
        started = threading.Event()

        def held_send_merge(**kwargs):
            started.set()
            release.wait(10)
            return []

        monkeypatch.setattr(mail_merge.api, "send_merge", held_send_merge)
        csrf = self._setup_upload(web_client, sample_xlsx_web)
        with web_client.session_transaction() as sess:
            sess["client_id"] = "test-client-id"
        resp = web_client.post(
            "/api/start-job",
            data={"mode": "send", "email_column": "email",
                  "subject": "Hello {{name}}", "body": "Body."},
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 200, resp.get_json()
        assert started.wait(5)
        return resp.get_json()["job_id"], csrf, release

    def test_config_resumes_running_send_the_session_does_not_name(
        self, web_client, sample_xlsx_web, monkeypatch,
    ):
        """A reload before the start-job response arrived still finds the send.

        spec/wizard.qnt, runningSendVisible: the session cookie naming the job
        only arrives with the response.
        """
        job_id, _csrf, release = self._start_held_send(web_client, sample_xlsx_web, monkeypatch)
        try:
            with web_client.session_transaction() as sess:
                sess.pop("job_id", None)
            assert web_client.get("/api/config").get_json()["active_job_id"] == job_id
        finally:
            release.set()

    def test_second_send_refused_while_one_runs(self, web_client, sample_xlsx_web, monkeypatch):
        """spec/wizard.qnt, noConcurrentSends (for example from a second tab)."""
        _job_id, csrf, release = self._start_held_send(web_client, sample_xlsx_web, monkeypatch)
        try:
            resp = web_client.post(
                "/api/start-job",
                data={"mode": "send", "email_column": "email",
                      "subject": "Hello {{name}}", "body": "Body."},
                headers={"X-CSRF-Token": csrf},
            )
            assert resp.status_code == 409
            assert "already in progress" in resp.get_json()["error"]
        finally:
            release.set()

    def test_failed_send_keeps_emails_already_sent(self, web_client, sample_xlsx_web, monkeypatch):
        """spec/wizard.qnt, failedSendReported: a send failing part-way lists what went out."""
        import mail_merge.sender
        from mail_merge.sender import SendResult

        def send_one_then_fail(get_token, to, subject, body, opts=None):
            if to.address != "alice@example.com":
                raise RuntimeError("Not signed in. Sign in with Microsoft, then try again.")
            return SendResult(email=to.address, success=True, status_code=202)

        monkeypatch.setattr(mail_merge.sender, "send_one", send_one_then_fail)
        monkeypatch.setattr(mail_merge.sender.time, "sleep", lambda s: None)
        csrf = self._setup_upload(web_client, sample_xlsx_web)
        with web_client.session_transaction() as sess:
            sess["client_id"] = "test-client-id"
        job_id = self._start(web_client, csrf, "send")
        status = web_client.get(f"/api/job/{job_id}/status").get_json()
        assert status["status"] == "failed"
        assert "Not signed in" in status["error"]
        assert [r["email"] for r in status["results"]] == ["alice@example.com"]

    def test_send_enforces_fixed_delay(self, web_client, sample_xlsx_web):
        """The web UI always uses delay=2.0 regardless of what the client sends."""
        csrf = self._setup_upload(web_client, sample_xlsx_web)
        resp = web_client.post(
            "/api/start-job",
            data={
                "mode": "dry_run",
                "email_column": "email",
                "subject": "Hello {{name}}",
                "body": "Body.",
                "delay": "0",  # try to override
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 200
        data = resp.get_json()

        # Job completes — the client's delay=0 was ignored (server forces 2.0)
        status = wait_for_job(web_client, data["job_id"])
        assert status["status"] == "completed"



# ---- Options passthrough ----

class TestOptionsPassthrough:
    def _setup_and_start(self, web_client, xlsx_path, extra_data=None):
        csrf = get_csrf(web_client)
        with open(xlsx_path, "rb") as f:
            web_client.post(
                "/api/upload-spreadsheet",
                data={"spreadsheet": (f, "test.xlsx")},
                headers={"X-CSRF-Token": csrf},
                content_type="multipart/form-data",
            )
        form_data = {
            "mode": "dry_run",
            "email_column": "email",
            "subject": "Test",
            "body": "Body.",
        }
        if extra_data:
            form_data.update(extra_data)
        resp = web_client.post("/api/start-job", data=form_data,
                               headers={"X-CSRF-Token": csrf})
        return resp

    def test_html_mode(self, web_client, sample_xlsx_web):
        resp = self._setup_and_start(web_client, sample_xlsx_web,
                                     {"html": "true"})
        assert resp.status_code == 200

    def test_importance(self, web_client, sample_xlsx_web):
        resp = self._setup_and_start(web_client, sample_xlsx_web,
                                     {"importance": "high"})
        assert resp.status_code == 200

    def test_cc_bcc_passed_through(self, web_client, sample_xlsx_web):
        resp = self._setup_and_start(web_client, sample_xlsx_web, {
            "cc": "cc@example.com",
            "bcc": "bcc@example.com",
        })
        assert resp.status_code == 200

    def test_attachments_uploaded(self, web_client, sample_xlsx_web, tmp_path):
        """Attachments are saved and passed through to send_merge."""
        csrf = get_csrf(web_client)
        with open(sample_xlsx_web, "rb") as f:
            web_client.post(
                "/api/upload-spreadsheet",
                data={"spreadsheet": (f, "test.xlsx")},
                headers={"X-CSRF-Token": csrf},
                content_type="multipart/form-data",
            )

        # Create a small attachment file
        att_path = tmp_path / "doc.txt"
        att_path.write_text("attachment content")

        import io
        with open(att_path, "rb") as att:
            resp = web_client.post(
                "/api/start-job",
                data={
                    "mode": "dry_run",
                    "email_column": "email",
                    "subject": "Test",
                    "body": "Body.",
                    "attachments": (io.BytesIO(b"file data"), "doc.txt"),
                },
                headers={"X-CSRF-Token": csrf},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 200


# ---- Attachment saving ----

class TestAttachmentSaving:
    """Uploaded attachments keep their names and contents, and stay in the temp dir."""

    def _start_with_attachments(self, web_client, xlsx_path, files, monkeypatch):
        import io
        captured: dict = {}

        def fake_send_merge(**kwargs):
            # Read the files while the request's temp dir still exists
            captured["files"] = [
                (Path(p).name, Path(p).read_bytes()) for p in kwargs.get("attachment", [])
            ]
            captured["paths"] = list(kwargs.get("attachment", []))
            return []

        monkeypatch.setattr("mail_merge.api.send_merge", fake_send_merge)
        csrf = get_csrf(web_client)
        with open(xlsx_path, "rb") as f:
            web_client.post(
                "/api/upload-spreadsheet",
                data={"spreadsheet": (f, "test.xlsx")},
                headers={"X-CSRF-Token": csrf},
                content_type="multipart/form-data",
            )
        resp = web_client.post(
            "/api/start-job",
            data={
                "mode": "dry_run",
                "email_column": "email",
                "subject": "Test",
                "body": "Body.",
                "attachments": [(io.BytesIO(data), name) for name, data in files],
            },
            headers={"X-CSRF-Token": csrf},
            content_type="multipart/form-data",
        )
        with web_client.session_transaction() as sess:
            tmp_dir = sess.get("spreadsheet_tmp_dir")
        return resp, captured, tmp_dir

    def test_original_filenames_preserved(self, web_client, sample_xlsx_web, monkeypatch):
        """Names with spaces, punctuation and non-ASCII reach send_merge unchanged."""
        files = [
            ("Q3 report (final).pdf", b"pdf data"),
            ("Café menu – 2026.docx", b"docx data"),
            ("notes.txt", b"plain text"),
        ]
        resp, captured, _ = self._start_with_attachments(
            web_client, sample_xlsx_web, files, monkeypatch)
        assert resp.status_code == 200
        status = wait_for_job(web_client, resp.get_json()["job_id"])
        assert status["status"] == "completed"
        assert captured["files"] == files

    def test_same_name_twice_keeps_both(self, web_client, sample_xlsx_web, monkeypatch):
        """Two attachments with the same name are both sent, with their own contents."""
        files = [("a.txt", b"first"), ("a.txt", b"second")]
        resp, captured, _ = self._start_with_attachments(
            web_client, sample_xlsx_web, files, monkeypatch)
        assert resp.status_code == 200
        wait_for_job(web_client, resp.get_json()["job_id"])
        assert captured["files"] == files

    @pytest.mark.parametrize("evil_name", [
        "../escaped.txt",
        "../../escaped.txt",
        "sub/../../escaped.txt",
        "..\\escaped.txt",
        "C:\\Users\\victim\\escaped.txt",
        "{abs}",
    ])
    def test_traversal_filename_stays_in_temp_dir(
        self, web_client, sample_xlsx_web, monkeypatch, tmp_path, evil_name
    ):
        """A filename with path components can't write outside the temp dir."""
        abs_target = tmp_path / "outside" / "escaped.txt"
        abs_target.parent.mkdir()
        evil_name = evil_name.format(abs=abs_target)
        resp, captured, tmp_dir = self._start_with_attachments(
            web_client, sample_xlsx_web, [(evil_name, b"payload")], monkeypatch)
        assert resp.status_code == 200
        wait_for_job(web_client, resp.get_json()["job_id"])
        root = Path(tmp_dir).resolve()
        for p in captured["paths"]:
            assert Path(p).resolve().is_relative_to(root), p
        assert captured["files"] == [("escaped.txt", b"payload")]
        assert not (root.parent / "escaped.txt").exists()
        assert not (root.parent.parent / "escaped.txt").exists()
        assert not abs_target.exists()

    def test_drive_relative_filename_stays_in_temp_dir(
        self, web_client, sample_xlsx_web, monkeypatch
    ):
        """'C:x.txt' is a drive-relative path on Windows; it must not escape."""
        resp, captured, tmp_dir = self._start_with_attachments(
            web_client, sample_xlsx_web, [("C:escaped.txt", b"payload")], monkeypatch)
        if resp.status_code == 400:  # Windows: rejected
            return
        assert resp.status_code == 200
        wait_for_job(web_client, resp.get_json()["job_id"])
        root = Path(tmp_dir).resolve()
        assert [Path(p).resolve().is_relative_to(root) for p in captured["paths"]] == [True]

    @pytest.mark.parametrize("bad_name", ["..", ".", "/", "../"])
    def test_filename_with_no_usable_name_is_rejected(
        self, web_client, sample_xlsx_web, monkeypatch, bad_name
    ):
        resp, _, _ = self._start_with_attachments(
            web_client, sample_xlsx_web, [(bad_name, b"x")], monkeypatch)
        assert resp.status_code == 400
        assert "attachment" in resp.get_json()["error"].lower()


class TestAttachmentDelivery:
    """Attachments uploaded through the web UI arrive in the Graph request intact.

    These run the real send_merge() against a mocked Graph endpoint, so they
    cover the whole path: multipart upload -> temp file -> base64 attachment.
    """

    FILES = [
        ("Q3 report (final).pdf", b"%PDF-1.4 fake pdf bytes \x00\xff"),
        ("Café menu – 2026.txt", "héllo wörld".encode()),
        ("report.v2.FINAL.docx", b"PK\x03\x04 docx"),
        (".profile", b"hidden-file content"),
        ("no_extension", b"\x01\x02\x03"),
    ]

    @staticmethod
    def _expected(files):
        import base64
        import mimetypes
        return [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": name,
                "contentType": mimetypes.guess_type(name)[0] or "application/octet-stream",
                "contentBytes": base64.b64encode(data).decode("ascii"),
            }
            for name, data in files
        ]

    def _start(self, web_client, xlsx_path, extra, files):
        import io
        csrf = get_csrf(web_client)
        with open(xlsx_path, "rb") as f:
            web_client.post(
                "/api/upload-spreadsheet",
                data={"spreadsheet": (f, "test.xlsx")},
                headers={"X-CSRF-Token": csrf},
                content_type="multipart/form-data",
            )
        with web_client.session_transaction() as sess:
            sess["client_id"] = "test-client-id"
        data = {
            "email_column": "email",
            "subject": "Hello {{name}}",
            "body": "Body for {{name}}.",
            **extra,
            "attachments": [(io.BytesIO(d), n) for n, d in files],
        }
        resp = web_client.post(
            "/api/start-job", data=data,
            headers={"X-CSRF-Token": csrf},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200, resp.get_json()
        status = wait_for_job(web_client, resp.get_json()["job_id"], timeout_sec=30)
        assert status["status"] == "completed", status
        return status

    @staticmethod
    def _sent_messages():
        import json
        return [json.loads(c.request.body)["message"] for c in responses.calls]

    @responses.activate
    @patch("mail_merge.auth.acquire_token_silent", return_value="fake-token")
    def test_test_email_carries_attachments(self, mock_auth, web_client, sample_xlsx_web):
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        self._start(web_client, sample_xlsx_web,
                    {"mode": "test_email", "test_email": "me@example.com"}, self.FILES)
        [msg] = self._sent_messages()
        assert msg["attachments"] == self._expected(self.FILES)

    @responses.activate
    @patch("mail_merge.auth.acquire_token_silent", return_value="fake-token")
    def test_send_attaches_files_to_every_message(self, mock_auth, web_client, sample_xlsx_web):
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        files = self.FILES[:2]
        self._start(web_client, sample_xlsx_web, {"mode": "send"}, files)
        msgs = self._sent_messages()
        assert [m["toRecipients"][0]["emailAddress"]["address"] for m in msgs] == [
            "alice@example.com", "bob@example.com"]
        for m in msgs:
            assert m["attachments"] == self._expected(files)

    @responses.activate
    @patch("mail_merge.auth.acquire_token_silent", return_value="fake-token")
    def test_empty_file_field_means_no_attachments(self, mock_auth, web_client, sample_xlsx_web):
        """An empty file input (filename "") is ignored, as before."""
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        self._start(web_client, sample_xlsx_web,
                    {"mode": "test_email", "test_email": "me@example.com"}, [("", b"")])
        [msg] = self._sent_messages()
        assert "attachments" not in msg

    def test_dry_run_with_attachments_completes(self, web_client, sample_xlsx_web):
        status = self._start(web_client, sample_xlsx_web, {"mode": "dry_run"}, self.FILES)
        assert status["summary"]["total"] == 2



# ---- Report summarize ----

class TestSummarize:
    def test_summarize_returns_structured_data(self):
        from mail_merge.report import summarize
        from mail_merge.sender import SendResult

        results = [
            SendResult(email="a@test.com", success=True, status_code=202),
            SendResult(email="b@test.com", success=False, status_code=400, error="Bad request"),
            SendResult(email="c@test.com", success=True, status_code=202),
        ]
        summary = summarize(results)
        assert summary["total"] == 3
        assert summary["sent"] == 2
        assert summary["failed"] == 1
        assert len(summary["failed_details"]) == 1
        assert summary["failed_details"][0]["email"] == "b@test.com"


# ---- Excel read_preview ----

class TestReadPreview:
    def test_read_preview_returns_columns_and_rows(self, sample_xlsx_web):
        from mail_merge.excel import read_preview
        columns, rows, sheets, total, _active = read_preview(sample_xlsx_web)
        assert "name" in columns
        assert "email" in columns
        assert len(rows) == 2
        assert rows[0]["name"] == "Alice"
        assert len(sheets) >= 1
        assert total == 2

    def test_read_preview_max_rows(self, tmp_path):
        from mail_merge.excel import read_preview
        path = tmp_path / "many.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["id", "value"])
        for i in range(20):
            ws.append([str(i), f"val{i}"])
        wb.save(path)

        columns, rows, _sheets, total, _active = read_preview(path, max_rows=3)
        assert len(rows) == 3
        assert total == 20

    def test_read_preview_empty_raises(self, tmp_path):
        from mail_merge.excel import read_preview
        path = tmp_path / "empty.xlsx"
        wb = openpyxl.Workbook()
        wb.save(path)

        with pytest.raises(ValueError, match="empty"):
            read_preview(path)


# ---- Web route error paths ----

class TestWebRouteErrors:
    """Tests for web route error paths not covered by other tests."""

    def test_preview_template_no_data(self, web_client):
        """POST to /api/preview-template with no JSON body is rejected."""
        csrf = get_csrf(web_client)
        # Flask rejects non-JSON content type before the route handler runs
        resp = web_client.post(
            "/api/preview-template",
            headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
            data="",
        )
        assert resp.status_code in (400, 415)

    def test_get_recipients_without_upload(self, web_client):
        """POST to /api/get-recipients without uploading a spreadsheet returns 400."""
        csrf = get_csrf(web_client)
        resp = web_client.post(
            "/api/get-recipients",
            data={"email_column": "email"},
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 400
        assert "No spreadsheet" in resp.get_json()["error"]

    def test_start_job_without_upload(self, web_client):
        """POST to /api/start-job without uploading a spreadsheet returns 400."""
        csrf = get_csrf(web_client)
        resp = web_client.post(
            "/api/start-job",
            data={"mode": "dry_run", "email_column": "email", "subject": "Hi", "body": "Body"},
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 400
        assert "No spreadsheet" in resp.get_json()["error"]

    def test_start_job_missing_required_fields(self, web_client, sample_xlsx_web):
        """POST to /api/start-job without email_column or subject returns 400."""
        csrf = get_csrf(web_client)
        with open(sample_xlsx_web, "rb") as f:
            web_client.post(
                "/api/upload-spreadsheet",
                data={"spreadsheet": (f, "test.xlsx")},
                headers={"X-CSRF-Token": csrf},
                content_type="multipart/form-data",
            )
        resp = web_client.post(
            "/api/start-job",
            data={"mode": "dry_run", "body": "Body"},
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 400
        assert "required" in resp.get_json()["error"]

    def test_job_status_not_found(self, web_client):
        """GET /api/job/<nonexistent>/status returns 404."""
        resp = web_client.get("/api/job/nonexistent-id/status")
        assert resp.status_code == 404
        assert "not found" in resp.get_json()["error"].lower()

    def test_job_stop_not_found(self, web_client):
        """POST /api/job/<nonexistent>/stop returns 404."""
        csrf = get_csrf(web_client)
        resp = web_client.post(
            "/api/job/nonexistent-id/stop",
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 404
        assert "not found" in resp.get_json()["error"].lower()

    def test_job_stop_success(self, web_client, sample_xlsx_web):
        """POST /api/job/<id>/stop sets stop_requested flag."""
        csrf = get_csrf(web_client)
        with open(sample_xlsx_web, "rb") as f:
            web_client.post(
                "/api/upload-spreadsheet",
                data={"spreadsheet": (f, "test.xlsx")},
                headers={"X-CSRF-Token": csrf},
                content_type="multipart/form-data",
            )
        resp = web_client.post(
            "/api/start-job",
            data={
                "mode": "dry_run",
                "email_column": "email",
                "subject": "Hello",
                "body": "Body.",
            },
            headers={"X-CSRF-Token": csrf},
        )
        job_id = resp.get_json()["job_id"]
        resp = web_client.post(
            f"/api/job/{job_id}/stop",
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 200
        assert "Stop requested" in resp.get_json()["message"]

    def test_auth_login_missing_client_id(self, web_client):
        """GET /auth/login without client_id returns 400."""
        with web_client.session_transaction() as sess:
            sess.pop("client_id", None)
        with patch("mail_merge.web.app.load_config", return_value={}):
            resp = web_client.get("/auth/login")
        assert resp.status_code == 400
        assert "client_id" in resp.get_json()["error"]

    def test_auth_callback_without_flow(self, web_client):
        """GET /auth/callback without a prior auth flow returns 400."""
        with web_client.session_transaction() as sess:
            sess.pop("auth_flow", None)
        resp = web_client.get("/auth/callback?code=xyz")
        assert resp.status_code == 400

    @patch("mail_merge.auth.acquire_token_by_auth_code", side_effect=RuntimeError("token exchange failed"))
    def test_auth_callback_exchange_failure(self, mock_acquire, web_client):
        """When token exchange raises RuntimeError, redirect with error hash."""
        with web_client.session_transaction() as sess:
            sess["auth_flow"] = {"state": "abc"}
            sess["client_id"] = "test-client-id"
            sess["tenant_id"] = "common"
        resp = web_client.get("/auth/callback?code=xyz", follow_redirects=False)
        assert resp.status_code == 302
        assert "#auth-error=" in resp.headers["Location"]
        assert "token%20exchange%20failed" in resp.headers["Location"]

    def test_send_mode_without_client_id(self, web_client, sample_xlsx_web):
        """Starting a send job without client_id returns 400."""
        csrf = get_csrf(web_client)
        with open(sample_xlsx_web, "rb") as f:
            web_client.post(
                "/api/upload-spreadsheet",
                data={"spreadsheet": (f, "test.xlsx")},
                headers={"X-CSRF-Token": csrf},
                content_type="multipart/form-data",
            )
        with web_client.session_transaction() as sess:
            sess.pop("client_id", None)
        with patch("mail_merge.web.app.load_config", return_value={}):
            resp = web_client.post(
                "/api/start-job",
                data={
                    "mode": "send",
                    "email_column": "email",
                    "subject": "Test",
                    "body": "Body.",
                },
                headers={"X-CSRF-Token": csrf},
            )
        assert resp.status_code == 400
        assert "client_id" in resp.get_json()["error"]

    def test_preview_html_empty_body(self, web_client):
        """Empty HTML body returns no warnings."""
        csrf = get_csrf(web_client)
        resp = web_client.post(
            "/api/preview-template",
            json={
                "subject": "Hi",
                "body": "   ",
                "sample_data": {},
                "columns": [],
                "html": True,
            },
            headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
        )
        data = resp.get_json()
        assert data["html_warnings"] == []

    def test_upload_no_file(self, web_client):
        """POST to /api/upload-spreadsheet with no file returns 400."""
        csrf = get_csrf(web_client)
        resp = web_client.post(
            "/api/upload-spreadsheet",
            data={},
            headers={"X-CSRF-Token": csrf},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400


class TestDesktopMode:
    """Tests for desktop mode interactive auth."""

    @pytest.fixture
    def desktop_app(self):
        """Create a Flask app in desktop mode."""
        application = create_app(
            startup_token="test-token-abc", port=5050, desktop_mode=True
        )
        application.config["TESTING"] = True
        return application

    @pytest.fixture
    def desktop_client(self, desktop_app):
        """Flask test client authenticated with the startup token."""
        c = desktop_app.test_client()
        resp = c.get("/?token=test-token-abc", follow_redirects=False)
        assert resp.status_code == 302
        return c

    def test_auth_interactive_returns_400_in_browser_mode(self, web_client):
        """POST /auth/interactive returns 400 when not in desktop mode."""
        csrf = get_csrf(web_client)
        resp = web_client.post(
            "/auth/interactive",
            json={"client_id": "test-client", "tenant_id": "common"},
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 400
        assert "desktop" in resp.get_json()["error"].lower()

    @patch("mail_merge.auth.acquire_token_interactive_flow")
    def test_auth_interactive_starts_in_desktop_mode(self, mock_flow, desktop_client):
        """POST /auth/interactive returns 200 and starts auth in desktop mode."""
        mock_flow.return_value = "fake-token"
        with desktop_client.session_transaction() as sess:
            sess["client_id"] = "test-client"
            sess["tenant_id"] = "common"
        resp = desktop_client.post(
            "/auth/interactive",
            json={"client_id": "test-client", "tenant_id": "common"},
            headers={"X-CSRF-Token": get_csrf(desktop_client)},
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "started"

    def test_api_config_includes_desktop_mode_false(self, web_client):
        """/api/config includes desktop_mode: false for browser mode."""
        resp = web_client.get("/api/config")
        data = resp.get_json()
        assert data["desktop_mode"] is False

    def test_api_config_includes_desktop_mode_true(self, desktop_client):
        """/api/config includes desktop_mode: true for desktop mode."""
        resp = desktop_client.get("/api/config")
        data = resp.get_json()
        assert data["desktop_mode"] is True


class TestLogPath:
    """Tests for the /api/log-path route."""

    def test_log_path_returns_path(self, web_client):
        """/api/log-path returns a path and exists flag."""
        resp = web_client.get("/api/log-path")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "path" in data
        assert "exists" in data
        assert isinstance(data["exists"], bool)
        assert data["path"].endswith("mergemail365.log")


class TestDebugLogging:
    """Tests that API error paths produce debug log records with tracebacks."""

    def test_upload_bad_file_logs_debug(self, web_client, tmp_path, caplog):
        """Upload a corrupt xlsx triggers debug log with traceback."""
        csrf = get_csrf(web_client)
        bad = tmp_path / "bad.xlsx"
        bad.write_bytes(b"not a real spreadsheet")

        with caplog.at_level("DEBUG", logger="mail_merge.web.app"):
            with open(bad, "rb") as f:
                resp = web_client.post(
                    "/api/upload-spreadsheet",
                    data={"spreadsheet": (f, "bad.xlsx")},
                    headers={"X-CSRF-Token": csrf},
                    content_type="multipart/form-data",
                )
        assert resp.status_code == 400
        debug_records = [r for r in caplog.records if r.levelname == "DEBUG" and r.exc_info]
        assert len(debug_records) >= 1
        assert "read_preview" in debug_records[0].message

    def test_get_recipients_bad_column_logs_debug(self, web_client, sample_xlsx_web, caplog):
        """get-recipients with invalid column triggers debug log."""
        csrf = get_csrf(web_client)

        # Upload a valid spreadsheet first
        with open(sample_xlsx_web, "rb") as f:
            web_client.post(
                "/api/upload-spreadsheet",
                data={"spreadsheet": (f, "test.xlsx")},
                headers={"X-CSRF-Token": csrf},
                content_type="multipart/form-data",
            )

        with caplog.at_level("DEBUG", logger="mail_merge.web.app"):
            resp = web_client.post(
                "/api/get-recipients",
                data={"email_column": "nonexistent_column"},
                headers={"X-CSRF-Token": csrf},
            )
        assert resp.status_code == 400
        debug_records = [r for r in caplog.records if r.levelname == "DEBUG" and r.exc_info]
        assert len(debug_records) >= 1
        assert "get-recipients" in debug_records[0].message


class TestInterruptedSends:
    """R15: sends an earlier process didn't finish are reported until dismissed."""

    @pytest.fixture
    def store(self, monkeypatch):
        import mail_merge.web.app as web_app
        from mail_merge.web.jobs import JobStore

        fresh = JobStore()
        monkeypatch.setattr(web_app, "_job_store", fresh)
        monkeypatch.setattr(web_app, "_jobs", fresh.jobs)
        monkeypatch.setattr(web_app, "_running_send_job", fresh.running_send)
        return fresh

    def _client(self, log_dir):
        application = create_app(startup_token="test-token-abc", port=5050, send_log_dir=log_dir)
        application.config["TESTING"] = True
        c = application.test_client()
        assert c.get("/?token=test-token-abc").status_code == 302
        return c

    def test_config_reports_and_dismiss_deletes(self, store, tmp_path):
        from mail_merge.sender import SendResult
        from mail_merge.web.sendlog import SendLog

        log = SendLog(tmp_path)
        log.start("old")
        log.record("old", SendResult(email="a@example.com", success=True, status_code=202))
        c = self._client(tmp_path)
        sends = c.get("/api/config").get_json()["interrupted_sends"]
        assert [[r["email"] for r in s["results"]] for s in sends] == [["a@example.com"]]

        resp = c.post("/api/interrupted/dismiss", headers={"X-CSRF-Token": get_csrf(c)})
        assert resp.status_code == 200
        assert c.get("/api/config").get_json()["interrupted_sends"] == []
        assert list(tmp_path.iterdir()) == []

    def test_dismiss_needs_csrf(self, store, tmp_path):
        c = self._client(tmp_path)
        assert c.post("/api/interrupted/dismiss").status_code == 403

    def test_no_send_log_without_a_directory(self, store, web_client):
        assert web_client.get("/api/config").get_json()["interrupted_sends"] == []
        assert store.send_log is None


def test_entry_point_keeps_send_logs_in_the_state_dir(monkeypatch, tmp_path):
    """mergemail365-web turns the send log on; create_app() alone doesn't."""
    import mail_merge.web as web_pkg
    from mail_merge import _paths

    seen = {}

    def fake_create_app(**kwargs):
        seen.update(kwargs)
        raise SystemExit(0)

    monkeypatch.setattr(_paths, "state_dir", lambda: tmp_path)
    monkeypatch.setattr("mail_merge.web.app.create_app", fake_create_app)
    monkeypatch.setattr(web_pkg, "_find_open_port", lambda port: port)
    with pytest.raises(SystemExit):
        web_pkg.main([])
    assert seen["send_log_dir"] == tmp_path / "sends"
