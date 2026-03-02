import argparse
import logging
import os
import sys
from pathlib import Path

from mail_merge.excel import read_recipients
from mail_merge.template import validate_template, extract_placeholders
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
        default=os.environ.get("MAIL_MERGE_CLIENT_ID"),
        help="Azure AD application (client) ID (or set MAIL_MERGE_CLIENT_ID env var)",
    )
    parser.add_argument("--sheet", default=None, help="Sheet name (default: first sheet)")
    parser.add_argument("--test-email", default=None, help="Send a single test email to this address using the first recipient's data, then exit")
    parser.add_argument("--dry-run", action="store_true", help="Render and validate only, do not send")
    parser.add_argument("--output", default=None, help="Path to write CSV report")
    parser.add_argument("--delay", type=float, default=0.0, help="Seconds between sends")
    parser.add_argument("--max-retries", type=int, default=3, help="Max retries per recipient for 5xx errors")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )
    logger = logging.getLogger(__name__)

    # Validate client-id (not needed for dry-run but we still check)
    if not args.dry_run and not args.test_email and not args.client_id:
        logger.error("--client-id is required (or set MAIL_MERGE_CLIENT_ID env var)")
        return 1

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

    # Authenticate (skip for dry-run without test-email)
    token = None
    needs_auth = not args.dry_run or args.test_email
    if needs_auth:
        if not args.client_id:
            logger.error("--client-id is required (or set MAIL_MERGE_CLIENT_ID env var)")
            return 1
        from mail_merge.auth import acquire_token
        try:
            token = acquire_token(args.client_id)
        except Exception as exc:
            logger.error("Authentication failed: %s", exc)
            return 1

    # Test email: send one email using first recipient's data, then exit
    if args.test_email:
        from mail_merge.template import render
        sample = recipients[0]
        rendered_subject = render(args.subject, sample)
        rendered_body = render(body_template, sample)
        logger.info(
            "Sending test email to %s (using data from first recipient: %s)",
            args.test_email, sample.get(args.email_column, "?"),
        )
        result = send_one(token, args.test_email, rendered_subject, rendered_body, max_retries=args.max_retries)
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
    )

    # Report
    print_summary(results)
    if args.output:
        write_csv(results, args.output)

    has_failures = any(not r.success for r in results)
    return 1 if has_failures else 0


if __name__ == "__main__":
    sys.exit(main())
