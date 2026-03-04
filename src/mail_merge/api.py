"""Python API for mail-merge — mirrors the CLI in a single function call."""

from __future__ import annotations

import base64
import logging
import mimetypes
import os
from datetime import datetime, timezone
from pathlib import Path

from mail_merge import config as _config
from mail_merge.config import load_config
from mail_merge.excel import read_recipients
from mail_merge.template import validate_template
from mail_merge.sender import SendResult, send_all, send_one
from mail_merge.report import print_summary, read_csv, write_csv

logger = logging.getLogger(__name__)


def _parse_address_list(value: str | list[str] | None) -> list[str] | None:
    """Normalise a comma-separated string or list into a list of addresses."""
    if value is None:
        return None
    if isinstance(value, str):
        return [a.strip() for a in value.split(",") if a.strip()] or None
    return list(value) or None


def _process_attachments(
    paths: list[str | Path] | None,
) -> list[dict[str, str]] | None:
    if not paths:
        return None
    attachment_list: list[dict[str, str]] = []
    max_attachment_size = 3 * 1024 * 1024  # ~3 MB raw ≈ 4 MB base64
    for att_path_raw in paths:
        att_path = Path(att_path_raw)
        if not att_path.exists():
            raise FileNotFoundError(f"Attachment not found: {att_path}")
        content_bytes = att_path.read_bytes()
        if len(content_bytes) > max_attachment_size:
            raise ValueError(
                f"Attachment too large: {att_path} "
                f"({len(content_bytes) / (1024 * 1024):.1f} MB); "
                f"Graph API inline limit is ~3 MB"
            )
        mime_type = mimetypes.guess_type(att_path.name)[0] or "application/octet-stream"
        attachment_list.append({
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": att_path.name,
            "contentType": mime_type,
            "contentBytes": base64.b64encode(content_bytes).decode("ascii"),
        })
    return attachment_list


def _parse_filter(expr: str) -> tuple[str, str, str]:
    """Parse a filter expression into (column, operator, value).

    Supported forms: ``"column=value"`` and ``"column!=value"``.
    Raises ``ValueError`` for malformed expressions.
    """
    if "!=" in expr:
        parts = expr.split("!=", 1)
        if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
            raise ValueError(
                f"Invalid filter syntax: {expr!r} "
                f"(expected 'column=value' or 'column!=value')"
            )
        return parts[0].strip(), "!=", parts[1].strip()
    if "=" in expr:
        parts = expr.split("=", 1)
        if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
            raise ValueError(
                f"Invalid filter syntax: {expr!r} "
                f"(expected 'column=value' or 'column!=value')"
            )
        return parts[0].strip(), "=", parts[1].strip()
    raise ValueError(
        f"Invalid filter syntax: {expr!r} "
        f"(expected 'column=value' or 'column!=value')"
    )


def _apply_filters(
    recipients: list[dict[str, str]], filters: list[str]
) -> list[dict[str, str]]:
    """Apply all filter expressions (AND logic) to recipients.

    Column names and values are compared case-insensitively.
    Raises ``ValueError`` for bad syntax or unknown columns.
    """
    parsed = [_parse_filter(f) for f in filters]

    # Build a case-insensitive column lookup from the first recipient
    if not recipients:
        return recipients
    col_lower = {k.lower(): k for k in recipients[0]}

    for col, _op, _val in parsed:
        if col.lower() not in col_lower:
            raise ValueError(
                f"Filter column {col!r} not found "
                f"(available: {', '.join(recipients[0].keys())})"
            )

    result = []
    for row in recipients:
        match = True
        for col, op, val in parsed:
            actual_key = col_lower[col.lower()]
            cell = str(row.get(actual_key, "")).lower()
            if op == "=" and cell != val.lower():
                match = False
                break
            if op == "!=" and cell == val.lower():
                match = False
                break
        if match:
            result.append(row)
    return result


def send_merge(
    spreadsheet: str | Path,
    body: str | Path,
    subject: str,
    email_column: str,
    client_id: str | None = None,
    tenant_id: str | None = None,
    sheet: str | None = None,
    test_email: str | None = None,
    send: bool = False,
    output: str | Path | None = None,
    delay: float = 2.0,
    max_retries: int = 3,
    importance: str | None = None,
    cc: str | list[str] | None = None,
    bcc: str | list[str] | None = None,
    html: bool = False,
    save_to_sent_items: bool = True,
    attachment: list[str | Path] | None = None,
    reply_to: str | list[str] | None = None,
    filter: list[str] | None = None,
    confirm: bool = True,
    resume: bool = True,
    batch_size: int | None = None,
) -> list[SendResult]:
    """Send personalised emails via Microsoft Graph API.

    This function mirrors the CLI orchestration: read spreadsheet, validate
    templates, authenticate, send, and report.

    Args:
        spreadsheet: Path to .xlsx file with recipients.
        body: Path to the body template file.
        subject: Email subject (supports ``{{placeholders}}``).
        email_column: Column name containing email addresses.
        client_id: Azure AD application (client) ID. Resolved from env var
            ``MAIL_MERGE_CLIENT_ID``, config file, if not provided.
        tenant_id: Azure AD tenant ID. Resolved from env var
            ``MAIL_MERGE_TENANT_ID``, config file, or defaults to ``"common"``.
        sheet: Worksheet name (default: first sheet).
        test_email: Send one email to this address using first recipient's data,
            then return. Always sends regardless of ``send`` flag.
        send: If ``True``, authenticate and send emails. If ``False``
            (the default), validate and render only (dry run).
        output: Path to write a CSV report of results.
        delay: Base seconds between sends (default 2.0).
        max_retries: Max retries per recipient for 5xx errors.
        importance: Email importance (``"low"``, ``"normal"``, or ``"high"``).
        cc: CC addresses — comma-separated string or list.
        bcc: BCC addresses — comma-separated string or list.
        html: If ``True``, send body as HTML.
        save_to_sent_items: If ``False``, skip saving to Sent Items.
        attachment: List of file paths to attach.
        reply_to: Reply-to addresses — comma-separated string or list.
        filter: Filter expressions to select recipients. Each expression is
            ``"column=value"`` (keep matching) or ``"column!=value"`` (exclude
            matching). Multiple filters use AND logic. Case-insensitive.
        confirm: If ``True`` (the default), display a summary and prompt for
            confirmation before sending. Automatically disabled when ``send``
            is ``False`` or ``test_email`` is set. Aborted sends raise
            ``KeyboardInterrupt``.
        resume: If ``True`` (the default), skip already-successful recipients
            when ``output`` CSV exists. Silently ignored if ``output`` is not
            set.
        batch_size: If set, only process this many recipients per invocation.
            Use with ``output`` for resumable batched rollout.

    Returns:
        List of :class:`~mail_merge.sender.SendResult` for each recipient.

    Raises:
        FileNotFoundError: If the spreadsheet, body file, or an attachment is
            missing.
        ValueError: If placeholders are unresolvable, recipients exceed Graph
            API limits, or an attachment is too large.
        RuntimeError: If authentication fails.
    """
    # --- Resolve client_id / tenant_id via config precedence ---
    config = load_config()

    if not client_id:
        client_id = os.environ.get("MAIL_MERGE_CLIENT_ID") or config.get("client_id")

    if not tenant_id:
        tenant_id = (
            os.environ.get("MAIL_MERGE_TENANT_ID")
            or config.get("tenant_id")
            or "common"
        )

    # --- Read spreadsheet ---
    spreadsheet_path = Path(spreadsheet)
    if not spreadsheet_path.exists():
        raise FileNotFoundError(f"Spreadsheet not found: {spreadsheet_path}")

    recipients = read_recipients(spreadsheet_path, email_column, sheet)
    if not recipients:
        raise ValueError("No recipients found in spreadsheet")

    # Normalise email_column to match the actual header key (read_recipients
    # uses case-insensitive matching, so the dict key may differ in case).
    email_column = next(k for k in recipients[0] if k.lower() == email_column.lower())

    # --- Apply filters ---
    if filter:
        total = len(recipients)
        recipients = _apply_filters(recipients, filter)
        if not recipients:
            raise ValueError(
                f"No recipients match the filter(s): {', '.join(filter)}"
            )
        logger.info("📋 Loaded %d recipients (filtered from %d)", len(recipients), total)
    else:
        logger.info("📋 Loaded %d recipients", len(recipients))

    # --- Resume and batch size (skip for test emails) ---
    previous_results: list[SendResult] = []
    if not test_email:
        if resume and output:
            output_path = Path(output)
            if output_path.exists():
                previous_results = read_csv(output_path)
                successful_emails = {
                    r.email.lower() for r in previous_results if r.success
                }
                total_before = len(recipients)
                recipients = [
                    r for r in recipients
                    if r[email_column].lower() not in successful_emails
                ]
                logger.info(
                    "📋 %d previously sent, %d remaining of %d total",
                    len(successful_emails),
                    len(recipients),
                    total_before,
                )
                if not recipients:
                    logger.info("✅ All emails already sent")
                    return previous_results

        if batch_size is not None:
            recipients = recipients[:batch_size]
            if not recipients:
                logger.info("✅ No recipients in this batch")
                return previous_results

    # --- Read body template ---
    body_path = Path(body)
    if not body_path.exists():
        raise FileNotFoundError(f"Body template not found: {body_path}")
    body_template = body_path.read_text(encoding="utf-8")

    # --- Validate placeholders ---
    columns = list(recipients[0].keys())
    bad_subject = validate_template(subject, columns)
    bad_body = validate_template(body_template, columns)
    bad = sorted(set(bad_subject + bad_body))
    if bad:
        raise ValueError(
            f"Unresolvable placeholders: {', '.join(bad)} "
            f"(available columns: {', '.join(columns)})"
        )

    # --- Parse CC / BCC / reply-to ---
    cc_list = _parse_address_list(cc)
    bcc_list = _parse_address_list(bcc)
    reply_to_list = _parse_address_list(reply_to)

    # --- Validate recipient count ---
    recipient_count = 1 + len(cc_list or []) + len(bcc_list or [])
    if recipient_count > 500:
        raise ValueError(
            f"Too many recipients per message ({recipient_count}); "
            f"Microsoft Graph API limit is 500 (to + cc + bcc)"
        )

    # --- Process attachments ---
    attachment_list = _process_attachments(attachment)

    # --- Confirm before sending ---
    if not send or test_email:
        confirm = False

    if confirm:
        from mail_merge.console import console
        from mail_merge.template import render

        sample = recipients[0]
        console.print()
        console.print(f"[bold]Subject:[/bold]  {render(subject, sample)}")
        console.print(f"[bold]To:[/bold]       {len(recipients)} recipients")
        if cc_list:
            console.print(f"[bold]CC:[/bold]       {', '.join(cc_list)}")
        if bcc_list:
            console.print(f"[bold]BCC:[/bold]      {', '.join(bcc_list)}")
        if attachment:
            names = [Path(a).name for a in attachment]
            console.print(f"[bold]Attach:[/bold]   {', '.join(names)}")
        console.print()
        try:
            answer = console.input("[bold]Send? [y/N][/bold] ")
        except EOFError:
            answer = ""
        if answer.lower() not in ("y", "yes"):
            raise KeyboardInterrupt("Send aborted by user")

    # --- Authenticate (skip for dry run, but always for test email) ---
    get_token = None
    if send or test_email:
        if not client_id:
            raise RuntimeError(
                "--client-id is required (or set MAIL_MERGE_CLIENT_ID env var, "
                f"or add to config file {_config.DEFAULT_PATH})"
            )
        from mail_merge.auth import acquire_token, token_expires_at

        try:
            # Eager call to trigger device-code flow if needed
            token = acquire_token(client_id, tenant_id)
        except Exception as exc:
            raise RuntimeError(f"Authentication failed: {exc}") from exc

        # Subsequent calls will use silent acquisition (cached refresh token)
        get_token = lambda: acquire_token(client_id, tenant_id)  # noqa: E731

        # --- Pre-flight token expiry check ---
        expires = token_expires_at(token)
        if expires:
            remaining = (expires - datetime.now(timezone.utc)).total_seconds()
            estimated = len(recipients) * delay
            min_token_lifetime = 5 * 60  # 5 minutes
            if estimated > remaining or remaining < min_token_lifetime:
                logger.warning(
                    "Token expires in %d min but send may take ~%d min; "
                    "refreshing token before sending",
                    remaining // 60,
                    estimated // 60,
                )
                try:
                    token = acquire_token(client_id, tenant_id)
                except Exception:
                    logger.warning("Token refresh failed, continuing with current token")

    # --- Test email (always sends, regardless of --send flag) ---
    if test_email:
        from mail_merge.template import render

        sample = recipients[0]
        rendered_subject = render(subject, sample)
        rendered_body = render(body_template, sample)
        logger.info(
            "📧 Sending test email to %s (using data from first recipient: %s)",
            test_email, sample.get(email_column, "?"),
        )
        assert get_token is not None
        result = send_one(
            get_token, test_email, rendered_subject, rendered_body,
            max_retries=max_retries, importance=importance,
            cc=cc_list, bcc=bcc_list, html=html,
            save_to_sent_items=save_to_sent_items,
            attachments=attachment_list, reply_to=reply_to_list,
        )
        return [result]

    # --- Send emails ---
    results = send_all(
        get_token=get_token,
        recipients=recipients,
        email_column=email_column,
        subject_template=subject,
        body_template=body_template,
        dry_run=not send,
        delay=delay,
        max_retries=max_retries,
        importance=importance,
        cc=cc_list,
        bcc=bcc_list,
        html=html,
        save_to_sent_items=save_to_sent_items,
        attachments=attachment_list,
        reply_to=reply_to_list,
    )

    # --- Merge with previous results when resuming ---
    if previous_results:
        merged: dict[str, SendResult] = {}
        for r in previous_results:
            merged[r.email.lower()] = r
        for r in results:
            merged[r.email.lower()] = r
        results = list(merged.values())

    # --- Report ---
    print_summary(results)
    if send and output:
        write_csv(results, output)

    return results
