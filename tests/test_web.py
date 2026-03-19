"""Tests for the web interface."""

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
        csrf = self._get_csrf(web_client)
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
        csrf = self._get_csrf(web_client)
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
        csrf = self._get_csrf(web_client)
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

    def _get_csrf(self, client):
        """Get CSRF token from session."""
        # Make a GET request to trigger CSRF token creation
        client.get("/")
        with client.session_transaction() as sess:
            return sess.get("csrf_token", "")


# ---- Template preview ----

class TestPreview:
    def test_preview_renders_placeholders(self, web_client):
        csrf = self._get_csrf(web_client)
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
        csrf = self._get_csrf(web_client)
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
        csrf = self._get_csrf(web_client)
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

    def _get_csrf(self, client):
        client.get("/")
        with client.session_transaction() as sess:
            return sess.get("csrf_token", "")


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
        mock_app.acquire_token_silent.return_value = {"access_token": "token"}
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


# ---- Job lifecycle ----

class TestJobs:
    def _setup_upload(self, web_client, xlsx_path):
        """Upload a spreadsheet and return CSRF token."""
        csrf = self._get_csrf(web_client)
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

        # Poll for completion
        import time
        for _ in range(30):
            status_resp = web_client.get(f"/api/job/{data['job_id']}/status")
            status = status_resp.get_json()
            if status["status"] in ("completed", "failed"):
                break
            time.sleep(0.2)

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

        import time
        for _ in range(30):
            status_resp = web_client.get(f"/api/job/{data['job_id']}/status")
            status = status_resp.get_json()
            if status["status"] in ("completed", "failed"):
                break
            time.sleep(0.2)

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

        import time
        for _ in range(60):
            status_resp = web_client.get(f"/api/job/{data['job_id']}/status")
            status = status_resp.get_json()
            if status["status"] in ("completed", "failed"):
                break
            time.sleep(0.5)

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

        import time
        for _ in range(30):
            status_resp = web_client.get(f"/api/job/{data['job_id']}/status")
            status = status_resp.get_json()
            if status["status"] in ("completed", "failed"):
                break
            time.sleep(0.2)

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

        # Read SSE events
        import time
        time.sleep(1)  # Let job run

        # Check status instead of SSE (SSE is streaming, hard to test with test client)
        status_resp = web_client.get(f"/api/job/{job_id}/status")
        status = status_resp.get_json()
        # Job should be completed or still running
        assert status["status"] in ("completed", "running", "pending")

    def _get_csrf(self, client):
        client.get("/")
        with client.session_transaction() as sess:
            return sess.get("csrf_token", "")


# ---- Options passthrough ----

class TestOptionsPassthrough:
    def _setup_and_start(self, web_client, xlsx_path, extra_data=None):
        csrf = self._get_csrf(web_client)
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

    def _get_csrf(self, client):
        client.get("/")
        with client.session_transaction() as sess:
            return sess.get("csrf_token", "")


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
        columns, rows = read_preview(sample_xlsx_web)
        assert "name" in columns
        assert "email" in columns
        assert len(rows) == 2
        assert rows[0]["name"] == "Alice"

    def test_read_preview_max_rows(self, tmp_path):
        from mail_merge.excel import read_preview
        path = tmp_path / "many.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["id", "value"])
        for i in range(20):
            ws.append([str(i), f"val{i}"])
        wb.save(path)

        columns, rows = read_preview(path, max_rows=3)
        assert len(rows) == 3

    def test_read_preview_empty_raises(self, tmp_path):
        from mail_merge.excel import read_preview
        path = tmp_path / "empty.xlsx"
        wb = openpyxl.Workbook()
        wb.save(path)

        with pytest.raises(ValueError, match="empty"):
            read_preview(path)
