import argparse
import base64
import logging
import mimetypes
import os
import sys
from pathlib import Path

from mail_merge.config import load_config
from mail_merge.excel import read_recipients
from mail_merge.template import validate_template
from mail_merge.sender import send_all, send_one
from mail_merge.report import print_summary, write_csv


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mail-merge",
        description="Send personalised emails via Microsoft Graph API",
    )
    parser.add_argument("--spreadsheet", required=True, help="Path to .xlsx file with recipients")
    parser.add_argument("--body", required=True, help="Path to plain-text body template file")
    parser.add_argument("--subject", required=True, help="Email subject (supports {{placeholders}})")
    parser.add_argument("--email-column", required=True, help="Column name containing email addresses")
    parser.add_argument(
        "--client-id",
        default=None,
        help="Azure AD application (client) ID (or set MAIL_MERGE_CLIENT_ID env var, or ~/.mail-merge.toml)",
    )
    parser.add_argument(
        "--tenant-id",
        default=None,
        help="Azure AD tenant ID (or set MAIL_MERGE_TENANT_ID env var, or ~/.mail-merge.toml; default: 'common')",
    )
    parser.add_argument("--sheet", default=None, help="Sheet name (default: first sheet)")
    parser.add_argument("--test-email", default=None, help="Send a single test email to this address using the first recipient's data, then exit")
    parser.add_argument("--dry-run", action="store_true", help="Render and validate only, do not send")
    parser.add_argument("--output", default=None, help="Path to write CSV report")
    parser.add_argument("--delay", type=float, default=2.0, help="Base seconds between sends (default 2s; Exchange Online allows ~30 msgs/min; adaptive throttling increases this on rate limits)")
    parser.add_argument("--max-retries", type=int, default=3, help="Max retries per recipient for 5xx errors")
    parser.add_argument("--importance", choices=["low", "normal", "high"], default=None, help="Email importance level")
    parser.add_argument("--cc", default=None, help="Comma-separated CC addresses")
    parser.add_argument("--bcc", default=None, help="Comma-separated BCC addresses")
    parser.add_argument("--html", action="store_true", help="Treat body as HTML (default: plain text)")
    parser.add_argument("--no-save-to-sent", action="store_true", help="Do not save sent messages to Sent Items folder")
    parser.add_argument("--attachment", action="append", default=None, help="Path to file attachment (repeatable)")
    parser.add_argument("--reply-to", default=None, help="Comma-separated reply-to addresses")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    return parser.parse_args(argv)


def _resolve_args(args: argparse.Namespace) -> None:
    """Fill in client_id and tenant_id from env vars, config file, or defaults.

    Precedence (highest wins): CLI flag → env var → config file → hardcoded default.
    Mutates *args* in place.
    """
    config = load_config()

    if not args.client_id:
        args.client_id = (
            os.environ.get("MAIL_MERGE_CLIENT_ID")
            or config.get("client_id")
        )

    if not args.tenant_id:
        args.tenant_id = (
            os.environ.get("MAIL_MERGE_TENANT_ID")
            or config.get("tenant_id")
            or "common"
        )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _resolve_args(args)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )
    logger = logging.getLogger(__name__)

    # Read spreadsheet
    spreadsheet_path = Path(args.spreadsheet)
    if not spreadsheet_path.exists():
        logger.error("Spreadsheet not found: %s", spreadsheet_path)
        return 1

    try:
        recipients = read_recipients(spreadsheet_path, args.email_column, args.sheet)
    except Exception as exc:
        logger.error("Failed to read spreadsheet: %s", exc)
        return 1

    if not recipients:
        logger.error("No recipients found in spreadsheet")
        return 1

    logger.info("Loaded %d recipients", len(recipients))

    # Read body template
    body_path = Path(args.body)
    if not body_path.exists():
        logger.error("Body template not found: %s", body_path)
        return 1
    body_template = body_path.read_text()

    # Validate placeholders in both subject and body
    columns = list(recipients[0].keys())
    bad_subject = validate_template(args.subject, columns)
    bad_body = validate_template(body_template, columns)
    bad = sorted(set(bad_subject + bad_body))

    if bad:
        logger.error(
            "Unresolvable placeholders: %s (available columns: %s)",
            ", ".join(bad), ", ".join(columns),
        )
        return 1

    # Authenticate (skip for dry-run)
    token = None
    if not args.dry_run:
        if not args.client_id:
            logger.error("--client-id is required (or set MAIL_MERGE_CLIENT_ID env var, or add to ~/.mail-merge.toml)")
            return 1
        from mail_merge.auth import acquire_token
        try:
            token = acquire_token(args.client_id, args.tenant_id)
        except Exception as exc:
            logger.error("Authentication failed: %s", exc)
            return 1

    # Parse CC/BCC into lists
    cc_list = [a.strip() for a in args.cc.split(",") if a.strip()] if args.cc else None
    bcc_list = [a.strip() for a in args.bcc.split(",") if a.strip()] if args.bcc else None

    # Parse reply-to into list
    reply_to_list = [a.strip() for a in args.reply_to.split(",") if a.strip()] if args.reply_to else None

    # Validate recipient count (Graph API limit: 500 across to+cc+bcc)
    recipient_count = 1 + len(cc_list or []) + len(bcc_list or [])
    if recipient_count > 500:
        logger.error(
            "Too many recipients per message (%d); Microsoft Graph API limit is 500 (to + cc + bcc)",
            recipient_count,
        )
        return 1

    # Process attachments
    attachment_list: list[dict[str, str]] | None = None
    if args.attachment:
        attachment_list = []
        for att_path_str in args.attachment:
            att_path = Path(att_path_str)
            if not att_path.exists():
                logger.error("Attachment not found: %s", att_path)
                return 1
            content_bytes = att_path.read_bytes()
            max_attachment_size = 3 * 1024 * 1024  # 3 MB — Graph API limit is 4 MB base64-encoded (~3 MB raw)
            if len(content_bytes) > max_attachment_size:
                logger.error(
                    "Attachment too large: %s (%.1f MB); Graph API inline limit is ~3 MB",
                    att_path, len(content_bytes) / (1024 * 1024),
                )
                return 1
            mime_type = mimetypes.guess_type(att_path.name)[0] or "application/octet-stream"
            attachment_list.append({
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": att_path.name,
                "contentType": mime_type,
                "contentBytes": base64.b64encode(content_bytes).decode("ascii"),
            })

    # Test email: send one email using first recipient's data, then exit
    if args.test_email:
        from mail_merge.template import render
        sample = recipients[0]
        rendered_subject = render(args.subject, sample)
        rendered_body = render(body_template, sample)
        if args.dry_run:
            logger.info(
                "DRY RUN test email to %s | Subject: %s",
                args.test_email, rendered_subject,
            )
            logger.debug("Body:\n%s", rendered_body)
            return 0
        logger.info(
            "Sending test email to %s (using data from first recipient: %s)",
            args.test_email, sample.get(args.email_column, "?"),
        )
        assert token is not None
        result = send_one(
            token, args.test_email, rendered_subject, rendered_body,
            max_retries=args.max_retries, importance=args.importance,
            cc=cc_list, bcc=bcc_list, html=args.html,
            save_to_sent_items=not args.no_save_to_sent,
            attachments=attachment_list, reply_to=reply_to_list,
        )
        if result.success:
            logger.info("Test email sent successfully to %s", args.test_email)
            return 0
        else:
            logger.error("Test email failed: [%s] %s", result.status_code, result.error)
            return 1

    # Send emails
    results = send_all(
        token=token,
        recipients=recipients,
        email_column=args.email_column,
        subject_template=args.subject,
        body_template=body_template,
        dry_run=args.dry_run,
        delay=args.delay,
        max_retries=args.max_retries,
        importance=args.importance,
        cc=cc_list,
        bcc=bcc_list,
        html=args.html,
        save_to_sent_items=not args.no_save_to_sent,
        attachments=attachment_list,
        reply_to=reply_to_list,
    )

    # Report
    print_summary(results)
    if args.output:
        try:
            write_csv(results, args.output)
        except OSError as exc:
            logger.error("Failed to write report: %s", exc)

    has_failures = any(not r.success for r in results)
    return 1 if has_failures else 0


if __name__ == "__main__":
    sys.exit(main())
