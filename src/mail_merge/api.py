"""Python API for MergeMail365 — mirrors the CLI in a single function call."""

from __future__ import annotations

import base64
import logging
import mimetypes
import os
import re
from collections.abc import Callable
from datetime import datetime, timezone
from email.utils import parseaddr
from pathlib import Path

from mail_merge import config as _config
from mail_merge.config import load_config
from mail_merge.excel import read_recipients
from mail_merge.template import extract_placeholders, render, validate_template
from mail_merge.sender import (
    EmailAddress,
    MAX_RECIPIENTS_PER_MESSAGE,
    MessageOptions,
    SendResult,
    send_all,
    send_bcc_blast,
    send_one,
)
from mail_merge.report import print_summary, read_csv, write_csv

logger = logging.getLogger(__name__)

_FULL_DOC_RE = re.compile(r"<!DOCTYPE|<html\b", re.IGNORECASE)
_STYLE_TAG_RE = re.compile(r"<style\b", re.IGNORECASE)

_EMAIL_HTML_WRAPPER_HEAD = """\
<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml"
      xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
    <meta charset="utf-8">
    <!--[if mso]>
    <noscript><xml><o:OfficeDocumentSettings>
    <o:PixelsPerInch>96</o:PixelsPerInch>
    </o:OfficeDocumentSettings></xml></noscript>
    <![endif]-->
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body, p, h1, h2, h3, ul, ol, li, blockquote {
            margin: 0;
            padding: 0;
        }
        p {
            margin: 0 0 0.75em 0;
        }
        h1 {
            font-size: 1.6em;
            margin: 0 0 0.5em 0;
        }
        h2 {
            font-size: 1.3em;
            margin: 0 0 0.5em 0;
        }
        h3 {
            font-size: 1.1em;
            margin: 0 0 0.5em 0;
        }
        ul, ol {
            margin: 0 0 0.75em 0;
            padding-left: 1.5em;
        }
        li {
            margin: 0 0 0.25em 0;
        }
        blockquote {
            margin: 0 0 0.75em 0;
            padding: 0.5em 0 0.5em 1em;
            border-left: 3px solid #ccc;
            color: #555;
        }
        a {
            color: #1a73e8;
        }
    </style>
</head>
<body style="margin: 0; padding: 16px; font-family: -apple-system, 'Segoe UI', \
Roboto, Arial, Helvetica, sans-serif; font-size: 14px; \
line-height: 1.5; color: #1a1a1a;">
"""

_EMAIL_HTML_WRAPPER_TAIL = """
</body>
</html>"""


def _wrap_html_for_email(body: str) -> str:
    """Wrap an HTML fragment in an email-compatible document structure.

    If the body already contains ``<!DOCTYPE`` or ``<html`` (case-insensitive),
    it is returned unchanged — the user provided a complete document.
    """
    if _FULL_DOC_RE.search(body):
        return body
    return _EMAIL_HTML_WRAPPER_HEAD + body + _EMAIL_HTML_WRAPPER_TAIL


def _format_addrs(entries: list[EmailAddress]) -> str:
    """Format a list of EmailAddress objects for human-readable display."""
    return ", ".join(str(e) for e in entries)


def _parse_one_addr(raw: str) -> EmailAddress:
    """Parse 'Display Name <email>' or plain email into an EmailAddress."""
    name, addr = parseaddr(raw.strip())
    return EmailAddress(address=addr or raw.strip(), name=name or None)


def _parse_address_entries(
    value: str | list[str] | None,
) -> list[EmailAddress] | None:
    """Parse addresses (supporting 'Display Name <email>' format) into EmailAddress objects.

    Accepts a comma-separated string or list. Returns ``None`` when empty.
    """
    if value is None:
        return None
    parts = value.split(",") if isinstance(value, str) else value
    items = [s for a in parts if (s := a.strip())]
    if not items:
        return None
    return [_parse_one_addr(raw) for raw in items]


def _normalize_column(
    column: str, recipients: list[dict[str, str]], label: str,
) -> str:
    """Resolve a column name case-insensitively against recipient headers.

    Raises ``ValueError`` if the column is not found.
    """
    match = next((k for k in recipients[0] if k.lower() == column.lower()), None)
    if match is None:
        raise ValueError(
            f"{label} {column!r} not found "
            f"(available: {', '.join(recipients[0].keys())})"
        )
    return match


def _process_attachments(
    paths: list[str | Path] | None,
) -> list[dict[str, str]] | None:
    if not paths:
        return None
    attachment_list: list[dict[str, str]] = []
    max_attachment_size = 3 * 1024 * 1024  # ~3 MB raw ≈ 4 MB base64
    for att_path_raw in paths:
        att_path = Path(att_path_raw)
        try:
            content_bytes = att_path.read_bytes()
        except FileNotFoundError:
            raise FileNotFoundError(f"Attachment not found: {att_path}")
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
    err = (
        f"Invalid filter syntax: {expr!r} "
        f"(expected 'column=value' or 'column!=value')"
    )
    for op in ("!=", "="):
        if op in expr:
            parts = expr.split(op, 1)
            if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
                raise ValueError(err)
            return parts[0].strip(), op, parts[1].strip()
    raise ValueError(err)


def validate_emails(
    recipients: list[dict[str, str]], email_column: str
) -> list[dict[str, str]]:
    """Remove recipients with invalid email addresses, logging each skip."""
    from email_validator import validate_email, EmailNotValidError

    result = []
    for row in recipients:
        addr = row.get(email_column, "")
        try:
            validate_email(addr, check_deliverability=False, allow_smtputf8=False)
        except EmailNotValidError as exc:
            logger.warning("⚠️  Skipping invalid email address: %s (%s)", addr, exc)
            continue
        result.append(row)
    if not result:
        raise ValueError(
            "No recipients remaining after removing invalid email addresses"
        )
    return result


def apply_filters(
    recipients: list[dict[str, str]], filters: list[str]
) -> list[dict[str, str]]:
    """Apply all filter expressions (AND logic) to recipients.

    Column names and values are compared case-insensitively.
    Raises ``ValueError`` for bad syntax or unknown columns.
    """
    parsed = [_parse_filter(f) for f in filters]

    if not recipients:
        return recipients

    # Validate and resolve column names once
    resolved = [
        (_normalize_column(col, recipients, "Filter column"), op, val.lower())
        for col, op, val in parsed
    ]

    result = []
    for row in recipients:
        match = True
        for actual_key, op, val_lower in resolved:
            cell = str(row.get(actual_key, "")).lower()
            if op == "=" and cell != val_lower:
                match = False
                break
            if op == "!=" and cell == val_lower:
                match = False
                break
        if match:
            result.append(row)
    return result


def send_merge(
    spreadsheet: str | Path,
    body: str | Path | None = None,
    subject: str = "",
    email_column: str = "",
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
    filters: list[str] | None = None,
    confirm: bool = True,
    resume: bool = True,
    batch_size: int | None = None,
    bcc_blast: bool = False,
    bcc_blast_to: str | None = None,
    name_column: str | None = None,
    body_text: str | None = None,
    token_provider: Callable[[], str] | None = None,
    device_code: bool = False,
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
            ``MERGEMAIL365_CLIENT_ID``, config file, if not provided.
        tenant_id: Azure AD tenant ID. Resolved from env var
            ``MERGEMAIL365_TENANT_ID``, config file, or defaults to ``"common"``.
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
        filters: Filter expressions to select recipients. Each expression is
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
        bcc_blast: If ``True``, send all recipients as BCC in batches rather
            than individually. Recipients cannot see each other's addresses.
            Incompatible with ``batch_size`` and templates containing
            ``{{placeholders}}``. When combined with ``test_email``, sends
            the blast to only that address instead of the full recipient list.
        bcc_blast_to: The ``To:`` address used in BCC blast mode. Required
            when ``bcc_blast=True``. Supports ``"Display Name <email>"`` format.
        name_column: Column name containing recipient display names. When set,
            each email's ``To:`` header includes the name (e.g.
            ``"Alice <alice@example.com>"``). In BCC blast mode this is
            ignored (use ``bcc_blast_to`` with display name format instead).
        body_text: Use directly as body template string. Takes precedence
            over ``body`` file path if both provided. At least one of
            ``body`` or ``body_text`` must be provided.
        token_provider: Callable that returns an access token string.
            When provided, skips the built-in auth block (device code flow).
        device_code: If ``True``, use device code flow for authentication
            (user copies a code to a browser). If ``False`` (the default),
            use interactive browser flow (opens system browser automatically).
            Falls back to device code flow if interactive fails.

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
        client_id = os.environ.get("MERGEMAIL365_CLIENT_ID") or config.get("client_id")

    if not tenant_id:
        tenant_id = (
            os.environ.get("MERGEMAIL365_TENANT_ID")
            or config.get("tenant_id")
            or "common"
        )

    # --- BCC blast conflict checks and To address parsing ---
    blast_to: EmailAddress | None = None
    if bcc_blast:
        if batch_size is not None:
            raise ValueError(
                "--batch-size is not supported with --bcc-blast; "
                "batches are sized automatically based on the recipient list"
            )
        if not bcc_blast_to:
            raise ValueError("bcc_blast_to is required when bcc_blast=True")
        # Support "Display Name <email>" format (RFC 2822)
        blast_to = _parse_one_addr(bcc_blast_to)

    # --- Read spreadsheet ---
    spreadsheet_path = Path(spreadsheet)
    recipients = read_recipients(spreadsheet_path, email_column, sheet)
    if not recipients:
        raise ValueError("No recipients found in spreadsheet")

    # Normalise column names to match the actual header keys (read_recipients
    # uses case-insensitive matching, so the dict key may differ in case).
    email_column = _normalize_column(email_column, recipients, "Email column")
    if name_column:
        name_column = _normalize_column(name_column, recipients, "Name column")

    # --- Validate email addresses ---
    recipients = validate_emails(recipients, email_column)

    # --- Apply filters ---
    if filters:
        total = len(recipients)
        recipients = apply_filters(recipients, filters)
        if not recipients:
            raise ValueError(
                f"No recipients match the filter(s): {', '.join(filters)}"
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
    if body_text is not None:
        body_template = body_text
    elif body is not None:
        body_path = Path(body)
        try:
            body_template = body_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise FileNotFoundError(f"Body template not found: {body_path}")
    else:
        raise ValueError("At least one of 'body' or 'body_text' must be provided")

    # --- Validate placeholders ---
    if bcc_blast:
        blast_ph = extract_placeholders(subject) | extract_placeholders(body_template)
        if blast_ph:
            raise ValueError(
                "--bcc-blast does not support placeholders (body and subject must be "
                f"static text); found: {', '.join(sorted(blast_ph))}"
            )
    else:
        columns = list(recipients[0].keys())
        bad_subject = validate_template(subject, columns)
        bad_body = validate_template(body_template, columns)
        bad = sorted(set(bad_subject + bad_body))
        if bad:
            raise ValueError(
                f"Unresolvable placeholders: {', '.join(bad)} "
                f"(available columns: {', '.join(columns)})"
            )

    # --- Validate importance ---
    if importance is not None and importance not in ("low", "normal", "high"):
        raise ValueError(
            f"Invalid importance {importance!r}; expected 'low', 'normal', or 'high'"
        )

    # --- Parse CC / BCC / reply-to ---
    cc_list = _parse_address_entries(cc)
    bcc_list = _parse_address_entries(bcc)
    reply_to_list = _parse_address_entries(reply_to)

    # --- Process attachments ---
    attachment_list = _process_attachments(attachment)

    # --- Bundle message options ---
    msg_opts = MessageOptions(
        max_retries=max_retries,
        importance=importance,
        cc=cc_list,
        bcc=bcc_list,
        html=html,
        save_to_sent_items=save_to_sent_items,
        attachments=attachment_list,
        reply_to=reply_to_list,
    )

    # --- Validate recipient count (skip for blast; each batch is validated internally) ---
    if not bcc_blast:
        recipient_count = 1 + len(msg_opts.cc or []) + len(msg_opts.bcc or [])
        if recipient_count > MAX_RECIPIENTS_PER_MESSAGE:
            raise ValueError(
                f"Too many recipients per message ({recipient_count}); "
                f"Microsoft Graph API limit is {MAX_RECIPIENTS_PER_MESSAGE} (to + cc + bcc)"
            )

    # --- Confirm before sending ---
    if not send or test_email:
        confirm = False

    if confirm:
        from mail_merge.console import console

        console.print()
        if bcc_blast:
            assert blast_to is not None
            reserved = 1 + len(msg_opts.cc or []) + len(msg_opts.bcc or [])
            max_per_batch = max(1, MAX_RECIPIENTS_PER_MESSAGE - reserved)
            blast_batch_count = max(1, (len(recipients) + max_per_batch - 1) // max_per_batch)
            console.print(f"[bold]Subject:[/bold]  {subject}")
            console.print(f"[bold]To:[/bold]       {blast_to.address}")
            console.print(f"[bold]BCC:[/bold]      {len(recipients)} recipients in {blast_batch_count} batch(es)")
        else:
            sample = recipients[0]
            console.print(f"[bold]Subject:[/bold]  {render(subject, sample)}")
            console.print(f"[bold]To:[/bold]       {len(recipients)} recipients")
        if msg_opts.cc:
            console.print(f"[bold]CC:[/bold]       {_format_addrs(msg_opts.cc)}")
        if not bcc_blast and msg_opts.bcc:
            console.print(f"[bold]BCC:[/bold]      {_format_addrs(msg_opts.bcc)}")
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
        if token_provider is not None:
            get_token = token_provider
        else:
            if not client_id:
                raise RuntimeError(
                    "--client-id is required (or set MERGEMAIL365_CLIENT_ID env var, "
                    f"or add to config file {_config.DEFAULT_PATH})"
                )
            from mail_merge.auth import (
                acquire_token,
                acquire_token_interactive_flow,
                token_expires_at,
            )

            try:
                if device_code:
                    token = acquire_token(client_id, tenant_id)
                else:
                    try:
                        token = acquire_token_interactive_flow(
                            client_id, tenant_id,
                        )
                    except Exception as interactive_exc:
                        logger.info(
                            "Interactive auth unavailable (%s), "
                            "falling back to device code flow",
                            interactive_exc,
                        )
                        token = acquire_token(client_id, tenant_id)
            except Exception as exc:
                raise RuntimeError(f"Authentication failed: {exc}") from exc

            # Subsequent calls will use silent acquisition (cached refresh token)
            def get_token() -> str:
                return acquire_token(client_id, tenant_id)

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

    # --- Wrap HTML body for email compatibility ---
    if html:
        body_template = _wrap_html_for_email(body_template)

    # --- Test email (always sends, regardless of --send flag) ---
    if test_email:
        if get_token is None:
            raise RuntimeError("Authentication is required to send a test email")
        if bcc_blast:
            assert blast_to is not None
            logger.info(
                "📧 BCC blast test: sending to %s via %s",
                test_email, blast_to.address,
            )
            return send_bcc_blast(
                get_token, [test_email], blast_to, subject, body_template,
                dry_run=False, opts=msg_opts,
            )

        sample = recipients[0]
        rendered_subject = render(subject, sample)
        rendered_body = render(body_template, sample)
        test_to_name = sample.get(name_column, "").strip() or None if name_column else None
        test_to = EmailAddress(address=test_email, name=test_to_name)
        logger.info(
            "📧 Sending test email to %s (using data from first recipient: %s)",
            test_email, sample.get(email_column, "?"),
        )
        result = send_one(
            get_token, test_to, rendered_subject, rendered_body, opts=msg_opts,
        )
        return [result]

    # --- Send emails ---
    if bcc_blast:
        assert blast_to is not None
        emails = [r[email_column] for r in recipients]
        results = send_bcc_blast(
            get_token=get_token,
            emails=emails,
            to=blast_to,
            subject=subject,
            body=body_template,
            dry_run=not send,
            opts=msg_opts,
        )
    else:
        results = send_all(
            get_token=get_token,
            recipients=recipients,
            email_column=email_column,
            subject_template=subject,
            body_template=body_template,
            name_column=name_column,
            dry_run=not send,
            delay=delay,
            opts=msg_opts,
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
