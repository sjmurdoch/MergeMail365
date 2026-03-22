import argparse
import logging
import sys

from mail_merge.api import send_merge
from mail_merge.console import setup_logging


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mergemail365",
        description="Send personalised emails via Microsoft Graph API",
    )
    parser.add_argument("--spreadsheet", required=True, help="Path to .xlsx file with recipients")
    parser.add_argument("--body", required=True, help="Path to body template file (plain text by default; use --html for HTML)")
    parser.add_argument("--subject", required=True, help="Email subject (supports {{placeholders}})")
    parser.add_argument("--email-column", required=True, help="Column name containing email addresses")
    parser.add_argument(
        "--client-id",
        default=None,
        help="Azure AD application (client) ID (or set MERGEMAIL365_CLIENT_ID env var, or config file)",
    )
    parser.add_argument(
        "--tenant-id",
        default=None,
        help="Azure AD tenant ID (or set MERGEMAIL365_TENANT_ID env var, or config file; default: 'common')",
    )
    parser.add_argument("--sheet", default=None, help="Sheet name (default: first sheet)")
    parser.add_argument("--name-column", default=None, help="Column name containing recipient display names (included in the To: header)")
    parser.add_argument("--test-email", default=None, help="Send a single test email to this address using the first recipient's data, then exit")
    parser.add_argument("--send", action="store_true", help="Actually send emails (default is dry-run)")
    parser.add_argument("--device-code", action="store_true", help="Use device code flow for headless/SSH environments (default: opens system browser)")
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
    parser.add_argument("--filter", dest="filters", action="append", default=None, help="Filter recipients: 'column=value' or 'column!=value' (repeatable, AND logic)")
    parser.add_argument("--no-resume", action="store_true", help="Send to all recipients even if --output CSV shows previous successes")
    parser.add_argument("--batch-size", type=int, default=None, help="Max emails to send per invocation (use with --output for resumable batching)")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    parser.add_argument(
        "--bcc-blast",
        action="store_true",
        help="Send all recipients via BCC in batches (recipients cannot see each other)",
    )
    parser.add_argument(
        "--bcc-blast-to",
        default=None,
        help="The To: address used in BCC blast mode (required with --bcc-blast)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    setup_logging(getattr(logging, args.log_level.upper(), logging.INFO))
    logger = logging.getLogger(__name__)

    try:
        results = send_merge(
            spreadsheet=args.spreadsheet,
            body=args.body,
            subject=args.subject,
            email_column=args.email_column,
            client_id=args.client_id,
            tenant_id=args.tenant_id,
            sheet=args.sheet,
            test_email=args.test_email,
            send=args.send,
            output=args.output,
            delay=args.delay,
            max_retries=args.max_retries,
            importance=args.importance,
            cc=args.cc,
            bcc=args.bcc,
            html=args.html,
            save_to_sent_items=not args.no_save_to_sent,
            attachment=args.attachment,
            reply_to=args.reply_to,
            filters=args.filters,
            confirm=not args.yes,
            resume=not args.no_resume,
            batch_size=args.batch_size,
            bcc_blast=args.bcc_blast,
            bcc_blast_to=args.bcc_blast_to,
            name_column=args.name_column,
            device_code=args.device_code,
        )
    except KeyboardInterrupt:
        logger.info("Aborted")
        return 130
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        logger.error("%s", exc)
        return 1
    except Exception as exc:
        logger.error("Unexpected error: %s", exc)
        return 1

    has_failures = any(not r.success for r in results)
    return 1 if has_failures else 0


if __name__ == "__main__":
    sys.exit(main())
