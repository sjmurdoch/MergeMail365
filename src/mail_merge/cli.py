import argparse
import logging
import sys

from mail_merge.api import send_merge
from mail_merge.console import add_log_level_arguments, configure_console_logging


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, not {value}")
    return value


def _non_negative_int(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError(f"must not be negative, not {value}")
    return value


def _non_negative_float(text: str) -> float:
    value = float(text)
    if value < 0:
        raise argparse.ArgumentTypeError(f"must not be negative, not {value}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mergemail365",
        description="Send personalised emails via Microsoft Graph API",
        # The four send arguments are required unless --sign-out is given
        # (_parse), which argparse's generated usage line can't show.
        usage=(
            "%(prog)s --spreadsheet SPREADSHEET --body BODY --subject SUBJECT "
            "--email-column EMAIL_COLUMN [options]\n"
            "       %(prog)s --sign-out [--client-id CLIENT_ID] [--tenant-id TENANT_ID]"
        ),
    )
    parser.add_argument("--spreadsheet", default=None, help="Path to .xlsx file with recipients (required)")
    parser.add_argument("--body", default=None, help="Path to body template file (plain text by default; use --html for HTML) (required)")
    parser.add_argument("--subject", default=None, help="Email subject (supports {{placeholders}}) (required)")
    parser.add_argument("--email-column", default=None, help="Column name containing email addresses (required)")
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
    parser.add_argument("--delay", type=_non_negative_float, default=2.0, help="Base seconds between sends (default 2s; Exchange Online allows ~30 msgs/min; adaptive throttling increases this on rate limits)")
    parser.add_argument("--max-retries", type=_non_negative_int, default=3, help="Max retries per recipient for server (5xx) and connection errors (default 3; a timeout after sending is never retried)")
    parser.add_argument("--importance", choices=["low", "normal", "high"], default=None, help="Email importance level")
    parser.add_argument("--cc", default=None, help="CC addresses, separated by commas or semicolons; each 'Name <address>' or a bare address")
    parser.add_argument("--bcc", default=None, help="BCC addresses, as for --cc")
    parser.add_argument("--html", action="store_true", help="Treat body as HTML (default: plain text)")
    parser.add_argument("--no-save-to-sent", action="store_true", help="Do not save sent messages to Sent Items folder")
    parser.add_argument("--attachment", action="append", default=None, help="Path to file attachment (repeatable)")
    parser.add_argument("--reply-to", default=None, help="Reply-to addresses, as for --cc")
    parser.add_argument("--filter", dest="filters", action="append", default=None, help="Filter recipients: 'column=value' or 'column!=value' (repeatable, AND logic)")
    parser.add_argument("--no-resume", action="store_true", help="Send to all recipients even if --output CSV shows previous successes")
    parser.add_argument("--batch-size", type=_positive_int, default=None, help="Max emails to send per invocation (use with --output for resumable batching)")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")
    parser.add_argument("--sign-out", action="store_true", help="Sign out of every cached Microsoft account, then exit (needs only the client ID)")
    add_log_level_arguments(parser)
    parser.add_argument("--log-file", action="store_true", help="Enable debug logging to a file")
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
    return parser


# Required unless --sign-out is given (argparse's required=True can't say so).
_REQUIRED = ("spreadsheet", "body", "subject", "email_column")


def _parse(parser: argparse.ArgumentParser, argv: list[str] | None) -> argparse.Namespace:
    args = parser.parse_args(argv)
    if not args.sign_out:
        missing = [f"--{name.replace('_', '-')}" for name in _REQUIRED if getattr(args, name) is None]
        if missing:
            parser.error(f"the following arguments are required: {', '.join(missing)}")
    return args


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return _parse(build_parser(), argv)


def _sign_out(args: argparse.Namespace) -> int:
    from mail_merge import auth
    from mail_merge.api import resolve_ids

    logger = logging.getLogger(__name__)
    client_id, tenant_id = resolve_ids(args.client_id, args.tenant_id)
    if not client_id:
        logger.error("--sign-out needs the client ID: --client-id, MERGEMAIL365_CLIENT_ID or the config file")
        return 1
    names = auth.cached_account_names()
    if auth.sign_out(client_id, tenant_id):
        logger.info("Signed out of %s", ", ".join(names) or "the cached account")
    else:
        logger.info("Signed out: no account was signed in")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = _parse(parser, argv)

    configure_console_logging(parser, args)
    logger = logging.getLogger(__name__)

    if args.sign_out:
        return _sign_out(args)

    from mail_merge.console import maybe_enable_file_logging
    maybe_enable_file_logging(args.log_file)

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
        logger.debug("Traceback", exc_info=True)
        return 1
    except Exception as exc:
        logger.error("Unexpected error: %s", exc)
        logger.debug("Traceback of the unexpected error", exc_info=True)
        return 1

    has_failures = any(not r.success for r in results)
    return 1 if has_failures else 0


if __name__ == "__main__":
    sys.exit(main())
