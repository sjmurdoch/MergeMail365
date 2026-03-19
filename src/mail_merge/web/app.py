"""Flask application for mail-merge web UI."""

from __future__ import annotations

import atexit
import enum
import hashlib
import json
import logging
import os
import queue
import secrets
import shutil
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import werkzeug
werkzeug.serving._log_add_style = False
from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from mail_merge.config import load_config
from mail_merge.sender import SendResult

logger = logging.getLogger(__name__)

MAX_WEB_RECIPIENTS = 99
WEB_SEND_DELAY = 2.0


# ---------------------------------------------------------------------------
# Job management
# ---------------------------------------------------------------------------


class JobStatus(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class Job:
    id: str
    status: JobStatus = JobStatus.PENDING
    events: queue.Queue[dict[str, Any] | None] = field(default_factory=queue.Queue)
    results: list[SendResult] | None = None
    error: str | None = None
    stop_requested: bool = False


class JobLogHandler(logging.Handler):
    """Captures mail_merge logger output into a job's event queue."""

    def __init__(self, job: Job) -> None:
        super().__init__()
        self.job = job

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.job.events.put({
                "type": "log",
                "data": {
                    "message": self.format(record),
                    "level": record.levelname,
                    "timestamp": time.strftime("%H:%M:%S", time.localtime(record.created)),
                },
            })
        except Exception:
            pass


# In-memory job store (single job at a time)
_jobs: dict[str, Job] = {}

# Track temp directories for cleanup
_temp_dirs: list[str] = []
_temp_dirs_lock = threading.Lock()


def _cleanup_temp_dirs() -> None:
    """Clean up all temp directories on shutdown."""
    with _temp_dirs_lock:
        for d in _temp_dirs:
            try:
                shutil.rmtree(d, ignore_errors=True)
            except Exception:
                pass
        _temp_dirs.clear()


atexit.register(_cleanup_temp_dirs)


def _register_temp_dir(path: str) -> None:
    with _temp_dirs_lock:
        _temp_dirs.append(path)


def _unregister_temp_dir(path: str) -> None:
    with _temp_dirs_lock:
        try:
            _temp_dirs.remove(path)
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    startup_token: str = "",
    port: int = 5050,
    client_id: str = "",
    tenant_id: str = "",
) -> Flask:
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "templates"),
        static_folder=os.path.join(os.path.dirname(__file__), "static"),
    )
    # Use a stable secret key based on the startup token so that restarting
    # the server doesn't invalidate the user's session.
    app.secret_key = hashlib.sha256(startup_token.encode()).hexdigest()
    
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["PERMANENT_SESSION_LIFETIME"] = 86400  # 24 hours
    app.config["STARTUP_TOKEN"] = startup_token
    app.config["PORT"] = port
    app.config["FIXED_CLIENT_ID"] = client_id
    app.config["FIXED_TENANT_ID"] = tenant_id

    # ----- Auth middleware -----

    @app.before_request
    def _check_auth() -> Any:
        # Allow static files and auth routes without session auth
        if request.endpoint == "static":
            return None
        if request.endpoint in ("auth_callback", "auth_login"):
            return None

        # Check for startup token in query string
        token = request.args.get("token")
        if token and token == app.config["STARTUP_TOKEN"]:
            session["authenticated"] = True
            session.permanent = True
            # Strip the token from URL and redirect
            return redirect(url_for("index"))

        # Check session
        if not session.get("authenticated"):
            return Response(
                "Forbidden -- use the URL printed in the terminal to access this app.\n"
                "Look for the line starting with 'Access URL:' in the server output.\n",
                status=403,
                content_type="text/plain; charset=utf-8",
            )

        # Refresh sliding window
        session.permanent = True
        return None

    # ----- CSRF protection -----

    @app.before_request
    def _ensure_csrf_token() -> None:
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_hex(32)

    @app.before_request
    def _check_csrf() -> Response | None:
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return None
        if request.endpoint and request.endpoint.startswith("auth_"):
            return None
        csrf_token = request.headers.get("X-CSRF-Token") or ""
        if not csrf_token or csrf_token != session.get("csrf_token"):
            return jsonify({"error": "CSRF token invalid"}), 403  # type: ignore[return-value]
        return None

    # ----- Routes -----

    @app.route("/")
    def index() -> str:
        csrf_token = session.get("csrf_token", "")
        return render_template("index.html", csrf_token=csrf_token)

    # ----- Auth routes -----

    @app.route("/auth/login")
    def auth_login() -> Any:
        # If the user is on 127.0.0.1, redirect them to localhost so the
        # session cookie is set on the domain that matches the redirect_uri.
        if request.host.startswith("127.0.0.1"):
            new_url = request.url.replace("127.0.0.1", "localhost", 1)
            return redirect(new_url)

        # Read client_id/tenant_id from query params (sent by JS), falling
        # back to session/config.  Store in session for later use.
        client_id = (
            request.args.get("client_id")
            or session.get("client_id")
            or _get_config_value("client_id")
        )
        tenant_id = (
            request.args.get("tenant_id")
            or session.get("tenant_id")
            or _get_config_value("tenant_id")
            or "common"
        )
        if not client_id:
            return jsonify({"error": "client_id is required"}), 400

        from mail_merge.auth import initiate_auth_code_flow

        redirect_uri = f"http://localhost:{app.config['PORT']}/auth/callback"
        flow = initiate_auth_code_flow(client_id, tenant_id, redirect_uri)
        session["auth_flow"] = flow
        session["client_id"] = client_id
        session["tenant_id"] = tenant_id
        return redirect(flow["auth_uri"])

    @app.route("/auth/callback")
    def auth_callback() -> Any:
        flow = session.get("auth_flow")
        if not flow:
            return Response("No auth flow in session", status=400)

        if "error" in request.args:
            error = request.args.get("error_description", request.args.get("error", "Unknown error"))
            return redirect(url_for("index") + f"#auth-error={error}")

        client_id = session.get("client_id", "")
        tenant_id = session.get("tenant_id", "common")

        from mail_merge.auth import acquire_token_by_auth_code

        try:
            acquire_token_by_auth_code(
                client_id=client_id,
                tenant_id=tenant_id,
                auth_code_flow=flow,
                auth_response=dict(request.args),
            )
        except RuntimeError as exc:
            return redirect(url_for("index") + f"#auth-error={exc}")

        session["ms_authenticated"] = True
        session.pop("auth_flow", None)
        return redirect(url_for("index") + "#auth-success")

    @app.route("/auth/status")
    def auth_status() -> Response:
        client_id, tenant_id = _get_client_tenant()
        if not client_id:
            return jsonify({"authenticated": False, "email": None})

        from mail_merge.auth import SCOPES, _build_msal_app, token_expires_at

        try:
            msal_app, _cache = _build_msal_app(client_id, tenant_id)
            accounts = msal_app.get_accounts()
            if accounts:
                result = msal_app.acquire_token_silent(SCOPES, account=accounts[0])
                if result and "access_token" in result:
                    expires = token_expires_at(result["access_token"])
                    return jsonify({
                        "authenticated": True,
                        "email": accounts[0].get("username", ""),
                        "token_expires_at": expires.isoformat() if expires else None,
                    })
        except Exception:
            pass
        return jsonify({"authenticated": False, "email": None})

    @app.route("/auth/debug")
    def auth_debug() -> Response:
        client_id, tenant_id = _get_client_tenant()
        if not client_id:
            return jsonify({"error": "client_id is required"})

        from mail_merge.auth import diagnose_auth
        return jsonify(diagnose_auth(client_id, tenant_id))

    # ----- Config route -----

    @app.route("/api/config")
    def api_config() -> Response:
        # Check if there is an active job still running for this session
        active_job_id = None
        job_id = session.get("job_id")
        if job_id and job_id in _jobs:
            active_job_id = job_id

        fixed_cid = app.config["FIXED_CLIENT_ID"]
        fixed_tid = app.config["FIXED_TENANT_ID"]

        return jsonify({
            "client_id": fixed_cid or _get_config_value("client_id") or "",
            "tenant_id": fixed_tid or _get_config_value("tenant_id") or "",
            "client_id_locked": bool(fixed_cid),
            "tenant_id_locked": bool(fixed_tid),
            "spreadsheet": session.get("spreadsheet_info"),
            "current_step": session.get("current_step", 1),
            "test_passed": session.get("test_passed", False),
            "verify_passed": session.get("verify_passed", False),
            "active_job_id": active_job_id,
        })

    @app.route("/api/state", methods=["POST"])
    def api_save_state() -> Response:
        data = request.get_json()
        if "current_step" in data:
            session["current_step"] = data["current_step"]
        if "test_passed" in data:
            session["test_passed"] = data["test_passed"]
        if "verify_passed" in data:
            session["verify_passed"] = data["verify_passed"]
        return jsonify({"success": True})

    # ----- Spreadsheet upload -----

    @app.route("/api/upload-spreadsheet", methods=["POST"])
    def api_upload_spreadsheet() -> Response:
        file = request.files.get("spreadsheet")
        if not file or not file.filename:
            return jsonify({"error": "No file uploaded"}), 400  # type: ignore[return-value]

        if not file.filename.endswith(".xlsx"):
            return jsonify({"error": "Only .xlsx files are supported"}), 400  # type: ignore[return-value]

        tmp_dir = tempfile.mkdtemp()
        os.chmod(tmp_dir, 0o700)
        _register_temp_dir(tmp_dir)

        filepath = os.path.join(tmp_dir, "upload.xlsx")
        file.save(filepath)

        from mail_merge.excel import read_preview

        try:
            columns, rows, sheets, total_rows = read_preview(filepath)
        except Exception as exc:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            _unregister_temp_dir(tmp_dir)
            return jsonify({"error": str(exc)}), 400  # type: ignore[return-value]

        session["spreadsheet_path"] = filepath
        session["spreadsheet_tmp_dir"] = tmp_dir
        session["spreadsheet_info"] = {
            "columns": columns,
            "rows": rows,
            "sheets": sheets,
            "total_rows": total_rows,
            "file_name": file.filename,
        }

        return jsonify(session["spreadsheet_info"])

    @app.route("/api/get-recipients", methods=["POST"])
    def api_get_recipients() -> Response:
        filepath = session.get("spreadsheet_path")
        if not filepath or not os.path.exists(filepath):
            return jsonify({"error": "No spreadsheet uploaded"}), 400  # type: ignore[return-value]

        email_column = request.form.get("email_column", "")
        filters_raw = request.form.get("filters", "")
        sheet = request.form.get("sheet")

        filters = [f.strip() for f in filters_raw.split("\n") if f.strip()]

        from mail_merge.api import apply_filters
        from mail_merge.excel import read_recipients

        try:
            recipients = read_recipients(filepath, email_column, sheet_name=sheet)
            total_before = len(recipients)
            valid, invalid = _partition_emails(recipients, email_column)
            recipients = valid
            if filters:
                recipients = apply_filters(recipients, filters)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400  # type: ignore[return-value]

        if not recipients:
            return jsonify({
                "error": "No recipients remaining after removing invalid email addresses"
            }), 400  # type: ignore[return-value]

        if len(recipients) > MAX_WEB_RECIPIENTS:
            return jsonify({
                "error": f"Too many recipients: {len(recipients)} found after filtering. "
                         f"The web UI supports a maximum of {MAX_WEB_RECIPIENTS} recipients. "
                         "Please use more restrictive filters or the CLI."
            }), 400  # type: ignore[return-value]

        return jsonify({
            "recipients": recipients,
            "invalid_emails": invalid,
            "total_before_validation": total_before,
        })

    # ----- Template preview -----

    @app.route("/api/preview-template", methods=["POST"])
    def api_preview_template() -> Response:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400  # type: ignore[return-value]

        subject = data.get("subject", "")
        body_text = data.get("body", "")
        sample_data = data.get("sample_data", {})
        columns = data.get("columns", [])

        from mail_merge.template import render, validate_template

        bad_subject = validate_template(subject, columns)
        bad_body = validate_template(body_text, columns)
        bad = sorted(set(bad_subject + bad_body))

        rendered_subject = render(subject, sample_data)
        rendered_body = render(body_text, sample_data)

        html_warnings: list[str] = []
        if data.get("html"):
            html_warnings = _validate_html_body(rendered_body)

        return jsonify({
            "subject": rendered_subject,
            "body": rendered_body,
            "unresolved_placeholders": bad,
            "html_warnings": html_warnings,
        })

    # ----- Job management -----

    @app.route("/api/start-job", methods=["POST"])
    def api_start_job() -> Response:
        data = request.form.to_dict()
        spreadsheet_path = session.get("spreadsheet_path")
        if not spreadsheet_path:
            return jsonify({"error": "No spreadsheet uploaded"}), 400  # type: ignore[return-value]

        mode = data.get("mode", "dry_run")  # dry_run, test_email, send
        email_column = data.get("email_column", "")
        subject = data.get("subject", "")
        body_text_val = data.get("body", "")
        test_email_addr = data.get("test_email", "")

        if not email_column or not subject:
            return jsonify({"error": "email_column and subject are required"}), 400  # type: ignore[return-value]

        # Enforce recipient cap (defense-in-depth: api_get_recipients checks
        # this during the wizard, but api_start_job must not trust the client
        # flow).  Uses the same read → validate → filter pipeline.
        filters_list = data["filters"].split("\n") if data.get("filters") else None
        try:
            count = _validated_recipient_count(
                spreadsheet_path, email_column,
                sheet=data.get("sheet"), filters=filters_list,
            )
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400  # type: ignore[return-value]
        if count > MAX_WEB_RECIPIENTS:
            return jsonify({
                "error": f"Too many recipients ({count}). "
                         f"The web UI supports up to {MAX_WEB_RECIPIENTS}. "
                         "Use the CLI for larger sends."
            }), 400  # type: ignore[return-value]

        # Build kwargs
        client_id, tenant_id = _get_client_tenant()

        kwargs: dict[str, Any] = {
            "spreadsheet": spreadsheet_path,
            "body_text": body_text_val,
            "subject": subject,
            "email_column": email_column,
            "client_id": client_id,
            "tenant_id": tenant_id,
            "confirm": False,
            "resume": False,
            "delay": WEB_SEND_DELAY,
        }

        # Optional fields
        if data.get("name_column"):
            kwargs["name_column"] = data["name_column"]
        if data.get("sheet"):
            kwargs["sheet"] = data["sheet"]
        if data.get("importance"):
            kwargs["importance"] = data["importance"]
        if data.get("cc"):
            kwargs["cc"] = data["cc"]
        if data.get("bcc"):
            kwargs["bcc"] = data["bcc"]
        if data.get("reply_to"):
            kwargs["reply_to"] = data["reply_to"]
        if data.get("html") == "true":
            kwargs["html"] = True
        if data.get("save_to_sent_items") == "false":
            kwargs["save_to_sent_items"] = False
        if data.get("filters"):
            kwargs["filters"] = data["filters"].split("\n")
        if data.get("bcc_blast") == "true":
            kwargs["bcc_blast"] = True
            kwargs["bcc_blast_to"] = data.get("bcc_blast_to", "")

        # Handle attachments
        attachments = request.files.getlist("attachments")
        if attachments:
            tmp_dir = session.get("spreadsheet_tmp_dir", tempfile.mkdtemp())
            att_paths: list[str] = []
            for att in attachments:
                if att.filename:
                    att_path = os.path.join(tmp_dir, att.filename)
                    att.save(att_path)
                    att_paths.append(att_path)
            if att_paths:
                kwargs["attachment"] = att_paths

        # Mode-specific config
        if mode == "dry_run":
            kwargs["send"] = False
        elif mode == "test_email":
            kwargs["test_email"] = test_email_addr
            kwargs["send"] = False  # test_email always sends, but needs token
        elif mode == "send":
            kwargs["send"] = True

        # Token provider for authenticated modes
        if mode in ("test_email", "send"):
            if not client_id:
                return jsonify({"error": "client_id is required for sending"}), 400  # type: ignore[return-value]

            def _make_token_provider(cid: str, tid: str) -> Any:
                def provider() -> str:
                    from mail_merge.auth import acquire_token
                    return acquire_token(cid, tid)
                return provider

            kwargs["token_provider"] = _make_token_provider(client_id, tenant_id)

        # Evict completed/failed jobs before creating a new one
        for jid in list(_jobs):
            if _jobs[jid].status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.STOPPED):
                del _jobs[jid]

        # Create and start job
        job = Job(id=str(uuid.uuid4()))
        _jobs[job.id] = job

        def _run_job() -> None:
            job.status = JobStatus.RUNNING
            handler = JobLogHandler(job)
            handler.setFormatter(logging.Formatter("%(message)s"))
            mm_logger = logging.getLogger("mail_merge")
            mm_logger.addHandler(handler)
            try:
                from mail_merge.api import send_merge
                results = send_merge(**kwargs)
                job.results = results
                job.status = JobStatus.COMPLETED
                job.events.put({
                    "type": "completed",
                    "data": {"message": "Job completed"},
                })
            except Exception as exc:
                job.error = str(exc)
                job.status = JobStatus.FAILED
                job.events.put({
                    "type": "error",
                    "data": {"message": str(exc)},
                })
            finally:
                mm_logger.removeHandler(handler)
                job.events.put(None)  # Sentinel

        thread = threading.Thread(target=_run_job, daemon=True)
        thread.start()

        session["job_id"] = job.id
        return jsonify({"job_id": job.id})

    @app.route("/api/job/<job_id>/events")
    def api_job_events(job_id: str) -> Response:
        job = _jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404  # type: ignore[return-value]

        def generate() -> Any:
            while True:
                try:
                    event = job.events.get(timeout=15)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                if event is None:
                    yield "data: {\"type\": \"done\"}\n\n"
                    break
                yield f"data: {json.dumps(event)}\n\n"

        return Response(generate(), mimetype="text/event-stream")

    @app.route("/api/job/<job_id>/status")
    def api_job_status(job_id: str) -> Response:
        job = _jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404  # type: ignore[return-value]

        result: dict[str, Any] = {
            "status": job.status.value,
            "error": job.error,
        }
        if job.results is not None:
            from mail_merge.report import summarize
            result["summary"] = summarize(job.results)
            result["results"] = [
                {
                    "email": r.email,
                    "success": r.success,
                    "status_code": r.status_code,
                    "error": r.error,
                }
                for r in job.results
            ]
        return jsonify(result)

    @app.route("/api/job/<job_id>/stop", methods=["POST"])
    def api_job_stop(job_id: str) -> Response:
        job = _jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404  # type: ignore[return-value]
        job.stop_requested = True
        return jsonify({"message": "Stop requested"})

    # ----- Helpers -----

    import re as _re

    _HTML_TAG_RE = _re.compile(r"<[a-zA-Z][^>]*>")
    _BLOCK_OR_BR_RE = _re.compile(
        r"<(br|p|div|table|tr|td|li|ul|ol|h[1-6])\b", _re.IGNORECASE,
    )
    _STRIPPED_TAGS_RE = _re.compile(
        r"<(script|iframe|form|embed|object)\b", _re.IGNORECASE,
    )
    _EXT_STYLESHEET_RE = _re.compile(
        r"""<link\b[^>]*rel\s*=\s*["']stylesheet["'][^>]*>""", _re.IGNORECASE,
    )
    _GMAIL_CLIP_BYTES = 102 * 1024  # ~102 KB

    def _validate_html_body(body: str) -> list[str]:
        """Return a list of warning strings for HTML email body content."""
        if not body.strip():
            return []
        warnings: list[str] = []

        if not _HTML_TAG_RE.search(body):
            warnings.append(
                "No HTML tags detected. The body appears to be plain text "
                "but will be sent as HTML. Line breaks will not be visible "
                "to recipients. Use <br> for line breaks or <p> for paragraphs."
            )
        elif "\n" in body and not _BLOCK_OR_BR_RE.search(body):
            warnings.append(
                "Line breaks may not render. The body contains newlines but "
                "no <br>, <p>, or <div> tags. Newlines are ignored in HTML."
            )

        m = _STRIPPED_TAGS_RE.search(body)
        if m:
            found = [
                tag for tag in ("script", "iframe", "form", "embed", "object")
                if _re.search(rf"<{tag}\b", body, _re.IGNORECASE)
            ]
            warnings.append(
                f"Unsupported tags: <{'>, <'.join(found)}> will be stripped "
                "by email clients."
            )

        if _EXT_STYLESHEET_RE.search(body):
            warnings.append(
                "External stylesheets (<link rel=\"stylesheet\">) are not "
                "supported in email. Use inline style attributes instead."
            )

        body_bytes = len(body.encode("utf-8"))
        if body_bytes > _GMAIL_CLIP_BYTES:
            size_kb = body_bytes // 1024
            warnings.append(
                f"Large body ({size_kb} KB): Gmail clips emails over ~102 KB. "
                "Recipients may see a truncated message."
            )

        return warnings

    def _partition_emails(
        recipients: list[dict[str, str]], email_column: str,
    ) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        """Split recipients into (valid, invalid) based on email validation."""
        from email_validator import EmailNotValidError, validate_email

        valid: list[dict[str, str]] = []
        invalid: list[dict[str, str]] = []
        for row in recipients:
            addr = row.get(email_column, "")
            try:
                validate_email(addr, check_deliverability=False, allow_smtputf8=False)
                valid.append(row)
            except EmailNotValidError as exc:
                invalid.append({"address": addr, "reason": str(exc)})
        return valid, invalid

    def _validated_recipient_count(
        filepath: str, email_column: str,
        sheet: str | None = None, filters: list[str] | None = None,
    ) -> int:
        """Read, validate, and filter recipients — return the count.

        Used by both api_get_recipients (full results) and api_start_job
        (defense-in-depth cap check) to ensure consistent counting.
        """
        from mail_merge.api import apply_filters
        from mail_merge.excel import read_recipients

        recipients = read_recipients(filepath, email_column, sheet_name=sheet)
        valid, _invalid = _partition_emails(recipients, email_column)
        if filters:
            valid = apply_filters(valid, filters)
        return len(valid)

    _cached_config: dict[str, str] | None = None

    def _get_config_value(key: str) -> str | None:
        # Fixed values (from --client-id / --tenant-id) take highest priority
        fixed_key = f"FIXED_{key.upper()}"
        if app.config.get(fixed_key):
            return app.config[fixed_key]
        nonlocal _cached_config
        if _cached_config is None:
            _cached_config = load_config()
        return os.environ.get(f"MAIL_MERGE_{key.upper()}") or _cached_config.get(key)

    def _get_client_tenant() -> tuple[str | None, str]:
        client_id = session.get("client_id") or _get_config_value("client_id")
        tenant_id = session.get("tenant_id") or _get_config_value("tenant_id") or "common"
        return client_id, tenant_id

    return app
