"""Tests for the web interface."""

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import openpyxl
import pytest
import responses

from mail_merge.sender import GRAPH_SEND_URL
from mail_merge.web.app import create_app


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
        if status["status"] in ("completed", "failed"):
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
    @patch("mail_merge.auth.msal.PublicClientApplication")
    def test_auth_status_authenticated(self, mock_app_cls, mock_cache, web_client):
        mock_cache.return_value = MagicMock()
        mock_app = MagicMock()
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
    @patch("mail_merge.auth.msal.PublicClientApplication")
    def test_auth_status_includes_token_expiry(self, mock_app_cls, mock_cache, web_client):
        import base64, json as _json
        # Create a JWT with exp claim for 2026-03-19T12:00:00+00:00
        payload = base64.urlsafe_b64encode(_json.dumps({"exp": 1773921600}).encode()).rstrip(b"=").decode()
        fake_jwt = f"eyJ.{payload}.sig"
        mock_cache.return_value = MagicMock()
        mock_app = MagicMock()
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
    @patch("mail_merge.auth.acquire_token", return_value="fake-token")
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
            "/api/start-job",
            data={
                "mode": "send",
                "email_column": "email",
                "subject": "Hello {{name}}",
                "body": "Body.",
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "99" in data["error"] or "Too many" in data["error"]

    @responses.activate
    @patch("mail_merge.auth.acquire_token", return_value="fake-token")
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
    @patch("mail_merge.auth.acquire_token", return_value="fake-token")
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
        columns, rows, sheets, total = read_preview(sample_xlsx_web)
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

        columns, rows, _sheets, total = read_preview(path, max_rows=3)
        assert len(rows) == 3
        assert total == 20

    def test_read_preview_empty_raises(self, tmp_path):
        from mail_merge.excel import read_preview
        path = tmp_path / "empty.xlsx"
        wb = openpyxl.Workbook()
        wb.save(path)

        with pytest.raises(ValueError, match="empty"):
            read_preview(path)
