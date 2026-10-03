"""Flask application for MergeMail365 web UI."""

import atexit
import hashlib
import json
import logging
import os
import queue
import re
import secrets
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

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
from mail_merge.web.jobs import FINISHED_STATUSES, JobStore
from mail_merge.web.sendlog import SendLog

logger = logging.getLogger(__name__)

MAX_WEB_RECIPIENTS = 99
WEB_SEND_DELAY = 2.0

_HTML_TAG_RE = re.compile(r"<[a-zA-Z][^>]*>")
_BLOCK_OR_BR_RE = re.compile(
    r"<(br|p|div|table|tr|td|li|ul|ol|h[1-6])\b", re.IGNORECASE,
)
_STRIPPED_TAGS_RE = re.compile(
    r"<(script|iframe|form|embed|object)\b", re.IGNORECASE,
)
_EXT_STYLESHEET_RE = re.compile(
    r"""<link\b[^>]*rel\s*=\s*["']stylesheet["'][^>]*>""", re.IGNORECASE,
)
_STYLE_BLOCK_RE = re.compile(r"<style\b", re.IGNORECASE)
_FULL_HTML_DOC_RE = re.compile(r"<!DOCTYPE|<html\b", re.IGNORECASE)
_GMAIL_CLIP_BYTES = 102 * 1024  # ~102 KB

# Strip full-document tags so the app's email wrapper is always applied.
_STRIP_DOC_RE = re.compile(
    r"<!DOCTYPE[^>]*>|</?html[^>]*>|<head\b[^>]*>.*?</head>|</?body[^>]*>",
    re.IGNORECASE | re.DOTALL,
)


# ---------------------------------------------------------------------------
# Job management
# ---------------------------------------------------------------------------


# The job lifecycle lives in web/jobs.py. One store per process: the app
# has one user. _jobs and _running_send_job stay importable for tests.
_job_store = JobStore()
_jobs = _job_store.jobs
_running_send_job = _job_store.running_send

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
# Pure helpers (no Flask app/session dependency)
# ---------------------------------------------------------------------------


def _strip_html_doc_tags(body: str) -> str:
    """Remove full-document tags so the app's email wrapper is always applied."""
    if _FULL_HTML_DOC_RE.search(body):
        return _STRIP_DOC_RE.sub("", body).strip()
    return body


# Approximate size of the email wrapper added by _wrap_html_for_email.
_EMAIL_WRAPPER_BYTES = 1500


def _validate_html_body(body: str) -> list[str]:
    """Return a list of warning strings for HTML email body content.

    Expects body content only (no <!DOCTYPE>, <html>, <head>, or <body>
    tags).  Call ``_strip_html_doc_tags`` first if needed.
    """
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
            if re.search(rf"<{tag}\b", body, re.IGNORECASE)
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

    if _STYLE_BLOCK_RE.search(body):
        warnings.append(
            "Inline <style> blocks may be stripped by email clients "
            "(Gmail, Outlook.com). Use inline style attributes on each "
            "element for reliable rendering."
        )

    body_bytes = len(body.encode("utf-8")) + _EMAIL_WRAPPER_BYTES
    if body_bytes > _GMAIL_CLIP_BYTES:
        size_kb = body_bytes // 1024
        warnings.append(
            f"Large body (~{size_kb} KB with email wrapper): Gmail clips "
            "emails over ~102 KB. Recipients may see a truncated message."
        )

    return warnings


def _attachment_basename(filename: str) -> str | None:
    """Return the final path component of an uploaded attachment's filename.

    The multipart filename is client-controlled and Werkzeug passes it
    through unchanged, so it may contain ``../``, an absolute path, or
    Windows separators.  Strip everything up to the last ``/`` or ``\\``,
    which keeps the name as the user sees it (spaces, punctuation,
    non-ASCII) unlike ``secure_filename``.  Returns ``None`` when nothing
    usable is left.
    """
    name = re.split(r"[/\\]", filename)[-1].strip()
    if name in ("", ".", "..") or "\x00" in name:
        return None
    return name


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


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

_LOOPBACK_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1"})
_WILDCARD_HOSTS = frozenset({"", "0.0.0.0", "::"})


def _allowed_hostnames(bind_host: str) -> frozenset[str] | None:
    """Hostnames the Host header may name, or None to allow any.

    Rejecting other names blocks DNS rebinding, where a web page on an
    attacker's domain re-resolves it to 127.0.0.1 to reach this server.
    A wildcard bind can be reached under any of the machine's names, so
    the check is skipped there and the startup token is the only guard.
    """
    if bind_host in _WILDCARD_HOSTS:
        return None
    return _LOOPBACK_HOSTNAMES | {bind_host.strip("[]").lower()}


def _request_hostname() -> str:
    return (urlsplit("//" + request.host).hostname or "").lower()



def create_app(
    startup_token: str = "",
    port: int = 5050,
    client_id: str = "",
    tenant_id: str = "",
    desktop_mode: bool = False,
    host: str = "localhost",
    send_log_dir: Path | None = None,
) -> Flask:
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "templates"),
        static_folder=os.path.join(os.path.dirname(__file__), "static"),
    )
    # Use a stable secret key based on the startup token so that restarting
    # the server doesn't invalidate the user's session.
    app.secret_key = hashlib.sha256(startup_token.encode()).hexdigest()

    # Keep running sends' results on disk, and report the sends an earlier
    # process didn't finish (spec/requirements.md, R15). Only the
    # mergemail365-web entry point passes a directory.
    if send_log_dir is not None:
        _job_store.attach_send_log(SendLog(send_log_dir))
    
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["PERMANENT_SESSION_LIFETIME"] = 86400  # 24 hours
    app.config["STARTUP_TOKEN"] = startup_token
    app.config["PORT"] = port
    app.config["FIXED_CLIENT_ID"] = client_id
    app.config["FIXED_TENANT_ID"] = tenant_id
    app.config["DESKTOP_MODE"] = desktop_mode

    # ----- Auth middleware -----
    # Desktop mode is served over a localhost port too (the native window
    # opens the same token URL a browser would), so both modes share these
    # checks.

    allowed_hostnames = _allowed_hostnames(host)

    @app.before_request
    def _check_host() -> Response | None:
        if allowed_hostnames is None or _request_hostname() in allowed_hostnames:
            return None
        return Response(
            "Forbidden -- unexpected Host header.\n",
            status=403,
            content_type="text/plain; charset=utf-8",
        )

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
        if request.endpoint in ("auth_login", "auth_callback"):
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

    @app.route("/auth/logout", methods=["POST"])
    def auth_logout() -> Response:
        client_id, tenant_id = _get_client_tenant()
        if client_id:
            from mail_merge.auth import sign_out
            sign_out(client_id, tenant_id)
        session.pop("ms_authenticated", None)
        return jsonify({"success": True})

    @app.route("/auth/debug")
    def auth_debug() -> Response:
        client_id, tenant_id = _get_client_tenant()
        if not client_id:
            return jsonify({"error": "client_id is required"})

        from mail_merge.auth import diagnose_auth
        return jsonify(diagnose_auth(client_id, tenant_id))

    @app.route("/auth/interactive", methods=["POST"])
    def auth_interactive() -> Response:
        if not app.config["DESKTOP_MODE"]:
            return jsonify({"error": "Interactive auth is only available in desktop mode"}), 400  # type: ignore[return-value]

        data = request.get_json() or {}
        fallback_cid, fallback_tid = _get_client_tenant()
        cid = data.get("client_id") or fallback_cid
        tid = data.get("tenant_id") or fallback_tid

        if not cid:
            return jsonify({"error": "client_id is required"}), 400  # type: ignore[return-value]

        session["client_id"] = cid
        session["tenant_id"] = tid

        def _run_interactive() -> None:
            try:
                from mail_merge.auth import acquire_token_interactive_flow
                acquire_token_interactive_flow(cid, tid, timeout=300)
            except Exception as exc:
                logger.warning("Interactive auth failed: %s", exc)

        thread = threading.Thread(target=_run_interactive, name="interactive-auth", daemon=True)
        thread.start()
        return jsonify({"status": "started"})

    # ----- Config route -----

    @app.route("/api/config")
    def api_config() -> Response:
        # Check if there is an active job still running for this session
        # Only a send is resumed after reload; test emails and dry runs are
        # re-run by the user (see spec/wizard.qnt, sendScreenHonest).
        # A running send is resumed even if the session doesn't name it: a
        # reload before the start-job response arrived never got the cookie
        # (spec/wizard.qnt, runningSendVisible).
        active_job_id = _job_store.active_job_id(session.get("job_id"))

        fixed_cid = app.config["FIXED_CLIENT_ID"]
        fixed_tid = app.config["FIXED_TENANT_ID"]

        # Re-read preview rows from the saved file if restoring session
        spreadsheet_info = session.get("spreadsheet_info")
        if spreadsheet_info and session.get("spreadsheet_path"):
            filepath = session["spreadsheet_path"]
            if os.path.exists(filepath):
                try:
                    from mail_merge.excel import read_preview
                    saved_sheet = spreadsheet_info.get("active_sheet")
                    _cols, rows, _sheets, _total, _active = read_preview(
                        filepath, sheet_name=saved_sheet,
                    )
                    spreadsheet_info = {**spreadsheet_info, "rows": rows}
                except Exception:
                    pass

        from mail_merge.api import _EMAIL_HTML_HEAD, _EMAIL_HTML_TAIL

        return jsonify({
            "client_id": fixed_cid or _get_config_value("client_id") or "",
            "tenant_id": fixed_tid or _get_config_value("tenant_id") or "",
            "client_id_locked": bool(fixed_cid),
            "tenant_id_locked": bool(fixed_tid),
            "desktop_mode": app.config["DESKTOP_MODE"],
            "email_wrapper": {
                "head": _EMAIL_HTML_HEAD,
                "tail": _EMAIL_HTML_TAIL,
            },
            "spreadsheet": spreadsheet_info,
            "current_step": session.get("current_step", 1),
            "test_passed": session.get("test_passed", False),
            "verify_passed": session.get("verify_passed", False),
            "active_job_id": active_job_id,
            # Sends an earlier process didn't finish, until dismissed.
            "interrupted_sends": [
                {"started": s["started"], "results": s["results"]} for s in _job_store.interrupted
            ],
        })

    @app.route("/api/interrupted/dismiss", methods=["POST"])
    def api_dismiss_interrupted() -> Response:
        """The user has seen the interrupted sends: delete their logs."""
        _job_store.dismiss_interrupted()
        return jsonify({"success": True})

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

    # ----- Session cleanup -----

    def _cleanup_session_temp() -> None:
        """Remove temp files associated with the current session."""
        tmp_dir = session.get("spreadsheet_tmp_dir")
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            _unregister_temp_dir(tmp_dir)
        session.pop("spreadsheet_tmp_dir", None)
        session.pop("spreadsheet_path", None)
        session.pop("spreadsheet_info", None)

    @app.route("/api/reset", methods=["POST"])
    def api_reset() -> Response:
        """Clean up temp files and reset session state for a new merge."""
        _cleanup_session_temp()
        session.pop("current_step", None)
        session.pop("test_passed", None)
        session.pop("verify_passed", None)
        session.pop("job_id", None)
        return jsonify({"success": True})

    # ----- Spreadsheet upload -----

    @app.route("/api/upload-spreadsheet", methods=["POST"])
    def api_upload_spreadsheet() -> Response:
        file = request.files.get("spreadsheet")
        if not file or not file.filename:
            return jsonify({"error": "No file uploaded"}), 400  # type: ignore[return-value]

        if not file.filename.endswith(".xlsx"):
            return jsonify({"error": "Only .xlsx files are supported"}), 400  # type: ignore[return-value]

        # Clean up previous upload if re-uploading
        _cleanup_session_temp()

        tmp_dir = tempfile.mkdtemp()
        os.chmod(tmp_dir, 0o700)
        _register_temp_dir(tmp_dir)

        filepath = os.path.join(tmp_dir, "upload.xlsx")
        file.save(filepath)

        from mail_merge.excel import read_preview

        try:
            columns, rows, sheets, total_rows, active_sheet = read_preview(filepath)
        except Exception as exc:
            logger.debug("upload-spreadsheet: read_preview failed", exc_info=True)
            shutil.rmtree(tmp_dir, ignore_errors=True)
            _unregister_temp_dir(tmp_dir)
            return jsonify({"error": str(exc)}), 400  # type: ignore[return-value]

        session["spreadsheet_path"] = filepath
        session["spreadsheet_tmp_dir"] = tmp_dir
        # Store only lightweight metadata in the session cookie — preview
        # rows can be large and would blow the 4 KB cookie size limit,
        # causing the session to be silently dropped by the browser.
        session["spreadsheet_info"] = {
            "columns": columns,
            "sheets": sheets,
            "total_rows": total_rows,
            "file_name": file.filename,
            "active_sheet": active_sheet,
        }

        return jsonify({**session["spreadsheet_info"], "rows": rows})

    @app.route("/api/change-sheet", methods=["POST"])
    def api_change_sheet() -> Response:
        filepath = session.get("spreadsheet_path")
        if not filepath or not os.path.exists(filepath):
            return jsonify({"error": "No spreadsheet uploaded"}), 400  # type: ignore[return-value]

        data = request.get_json()
        sheet_name = data.get("sheet") if data else None

        from mail_merge.excel import read_preview

        try:
            columns, rows, sheets, total_rows, active_sheet = read_preview(
                filepath, sheet_name=sheet_name,
            )
        except Exception as exc:
            logger.debug("change-sheet: read_preview failed", exc_info=True)
            return jsonify({"error": str(exc)}), 400  # type: ignore[return-value]

        # Update session metadata (preserve file_name from original upload)
        info = session.get("spreadsheet_info") or {}
        session["spreadsheet_info"] = {
            "columns": columns,
            "sheets": sheets,
            "total_rows": total_rows,
            "file_name": info.get("file_name", "upload.xlsx"),
            "active_sheet": active_sheet,
        }

        return jsonify({**session["spreadsheet_info"], "rows": rows})

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
            logger.debug("get-recipients failed", exc_info=True)
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
            html_warnings = _validate_html_body(
                _strip_html_doc_tags(rendered_body),
            )

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
        if data.get("html"):
            body_text_val = _strip_html_doc_tags(body_text_val)
        test_email_addr = data.get("test_email", "")

        if not email_column or not subject:
            return jsonify({"error": "email_column and subject are required"}), 400  # type: ignore[return-value]

        # One send at a time, for example from a second tab
        # (spec/wizard.qnt, noConcurrentSends).
        if mode == "send" and _running_send_job():
            return jsonify({"error": "A send is already in progress"}), 409  # type: ignore[return-value]

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
            logger.debug("start-job: recipient validation failed", exc_info=True)
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
        attachments = [a for a in request.files.getlist("attachments") if a.filename]
        att_names: list[str] = []
        for att in attachments:
            name = _attachment_basename(att.filename or "")
            if name is None:
                return jsonify({"error": f"Invalid attachment filename: {att.filename!r}"}), 400  # type: ignore[return-value]
            att_names.append(name)
        if attachments:
            tmp_dir = session.get("spreadsheet_tmp_dir")
            if not tmp_dir:
                tmp_dir = tempfile.mkdtemp()
                os.chmod(tmp_dir, 0o700)
                _register_temp_dir(tmp_dir)
                session["spreadsheet_tmp_dir"] = tmp_dir
            # Each file gets its own subdirectory so the original name (which
            # becomes the attachment name in the email) can be kept, and two
            # attachments with the same name don't overwrite each other.
            att_paths: list[str] = []
            for att, name in zip(attachments, att_names):
                att_dir = tempfile.mkdtemp(dir=tmp_dir)
                att_path = os.path.join(att_dir, name)
                # On Windows a drive-relative name ("C:x.txt") makes join
                # discard att_dir, so check where the path actually lands.
                if os.path.dirname(os.path.abspath(att_path)) != os.path.abspath(att_dir):
                    return jsonify({"error": f"Invalid attachment filename: {att.filename!r}"}), 400  # type: ignore[return-value]
                att.save(att_path)
                att_paths.append(att_path)
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

            # Silent only: a job has nobody to answer a sign-in prompt, so
            # without a cached token it fails at once rather than waiting in
            # the device-code flow (spec/wizard.qnt, noInteractiveAuthInJob).
            def _make_token_provider(cid: str, tid: str) -> Any:
                def provider() -> str:
                    from mail_merge.auth import acquire_token_silent
                    return acquire_token_silent(cid, tid)
                return provider

            kwargs["token_provider"] = _make_token_provider(client_id, tenant_id)

        # Checked again here: two requests can pass the early check.
        job = _job_store.create(mode)
        if job is None:
            return jsonify({"error": "A send is already in progress"}), 409  # type: ignore[return-value]
        # The job's runner adds should_stop (checked before each email,
        # stopHonoured) and on_result (counts emails sent).
        _job_store.start(job, kwargs)

        session["job_id"] = job.id
        return jsonify({"job_id": job.id})

    @app.route("/api/job/<job_id>/events")
    def api_job_events(job_id: str) -> Response:
        job = _jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404  # type: ignore[return-value]

        def generate() -> Any:
            idle = 0
            while True:
                try:
                    event = job.events.get(timeout=1)
                except queue.Empty:
                    # A stream from a page that has since been reloaded may
                    # already have taken the end-of-job sentinel, so a
                    # finished job with nothing queued ends the stream here
                    # (spec/wizard.qnt, sendScreenNotStuck).
                    if job.status in FINISHED_STATUSES:
                        yield "data: {\"type\": \"done\"}\n\n"
                        break
                    idle += 1
                    if idle >= 15:
                        idle = 0
                        yield ": keepalive\n\n"
                    continue
                idle = 0
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
        if not _job_store.request_stop(job_id):
            return jsonify({"error": "Job not found"}), 404  # type: ignore[return-value]
        return jsonify({"message": "Stop requested"})

    # ----- Diagnostics -----

    @app.route("/api/log-path")
    def api_log_path() -> Response:
        from mail_merge._paths import log_dir
        log_file = log_dir() / "mergemail365.log"
        return jsonify({
            "path": str(log_file),
            "exists": log_file.exists(),
        })

    # ----- Helpers -----

    _cached_config: dict[str, str] | None = None

    def _get_config_value(key: str) -> str | None:
        # Fixed values (from --client-id / --tenant-id) take highest priority
        fixed_key = f"FIXED_{key.upper()}"
        if app.config.get(fixed_key):
            return str(app.config[fixed_key])
        nonlocal _cached_config
        if _cached_config is None:
            _cached_config = load_config()
        return os.environ.get(f"MERGEMAIL365_{key.upper()}") or _cached_config.get(key)

    def _get_client_tenant() -> tuple[str | None, str]:
        client_id = session.get("client_id") or _get_config_value("client_id")
        tenant_id = session.get("tenant_id") or _get_config_value("tenant_id") or "common"
        return client_id, tenant_id

    return app
