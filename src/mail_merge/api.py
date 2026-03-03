"""Python API for mail-merge — mirrors the CLI in a single function call."""

from __future__ import annotations

import base64
import logging
import mimetypes
import os
from pathlib import Path

from mail_merge.config import load_config
from mail_merge.excel import read_recipients
from mail_merge.template import validate_template
from mail_merge.sender import SendResult, send_all, send_one
from mail_merge.report import print_summary, write_csv

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


def send_merge(
    spreadsheet: str | Path,
    body: str | Path,
    subject: str,
    email_column: str,
    client_id: str | None = None,
    tenant_id: str | None = None,
    sheet: str | None = None,
    test_email: str | None = None,
    dry_run: bool = False,
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
            then return.
        dry_run: Validate and render only; do not authenticate or send.
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

    logger.info("Loaded %d recipients", len(recipients))

    # --- Read body template ---
    body_path = Path(body)
    if not body_path.exists():
        raise FileNotFoundError(f"Body template not found: {body_path}")
    body_template = body_path.read_text()

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

    # --- Authenticate (skip for dry-run) ---
    token = None
    if not dry_run:
        if not client_id:
            raise RuntimeError(
                "--client-id is required (or set MAIL_MERGE_CLIENT_ID env var, "
                "or add to ~/.mail-merge.toml)"
            )
        from mail_merge.auth import acquire_token

        try:
            token = acquire_token(client_id, tenant_id)
        except Exception as exc:
            raise RuntimeError(f"Authentication failed: {exc}") from exc

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

    # --- Test email ---
    if test_email:
        from mail_merge.template import render

        sample = recipients[0]
        rendered_subject = render(subject, sample)
        rendered_body = render(body_template, sample)
        if dry_run:
            logger.info(
                "DRY RUN test email to %s | Subject: %s",
                test_email, rendered_subject,
            )
            logger.debug("Body:\n%s", rendered_body)
            return [SendResult(email=test_email, success=True, status_code=None)]

        logger.info(
            "Sending test email to %s (using data from first recipient: %s)",
            test_email, sample.get(email_column, "?"),
        )
        assert token is not None
        result = send_one(
            token, test_email, rendered_subject, rendered_body,
            max_retries=max_retries, importance=importance,
            cc=cc_list, bcc=bcc_list, html=html,
            save_to_sent_items=save_to_sent_items,
            attachments=attachment_list, reply_to=reply_to_list,
        )
        return [result]

    # --- Send emails ---
    results = send_all(
        token=token,
        recipients=recipients,
        email_column=email_column,
        subject_template=subject,
        body_template=body_template,
        dry_run=dry_run,
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

    # --- Report ---
    print_summary(results)
    if output:
        write_csv(results, output)

    return results
