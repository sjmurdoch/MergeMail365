import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from importlib.metadata import version

import requests

logger = logging.getLogger(__name__)

GRAPH_SEND_URL = "https://graph.microsoft.com/v1.0/me/sendMail"
MAX_RECIPIENTS_PER_MESSAGE = 500
X_MAILER = f"MergeMail365/{version('mergemail365')}"


@dataclass
class EmailAddress:
    """An email address with an optional display name."""
    address: str
    name: str | None = None

    def __str__(self) -> str:
        return f"{self.name} <{self.address}>" if self.name else self.address

    def to_graph(self) -> dict[str, object]:
        """Convert to Microsoft Graph API emailAddress format."""
        entry: dict[str, str] = {"address": self.address}
        if self.name:
            entry["name"] = self.name
        return {"emailAddress": entry}


@dataclass
class MessageOptions:
    """Shared message-formatting options passed through sender functions."""
    max_retries: int = 3
    importance: str | None = None
    cc: list[EmailAddress] | None = None
    bcc: list[EmailAddress] | None = None
    html: bool = False
    save_to_sent_items: bool = True
    attachments: list[dict[str, str]] | None = None
    reply_to: list[EmailAddress] | None = None


@dataclass
class SendResult:
    email: str
    success: bool
    status_code: int | None = None
    error: str = ""
    throttled: bool = False


def send_one(
    get_token: Callable[[], str],
    to: EmailAddress,
    subject: str,
    body: str,
    opts: MessageOptions | None = None,
) -> SendResult:
    """Send a single email via Microsoft Graph API.

    Handles 401 (token expired) with a single refresh attempt,
    429 (rate limit) with Retry-After, 5xx with exponential backoff,
    and 4xx (non-429/non-401) as immediate failures.
    """
    if opts is None:
        opts = MessageOptions()
    token = get_token()
    token_refreshed = False
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    content_type = "HTML" if opts.html else "Text"
    message: dict[str, object] = {
        "subject": subject,
        "body": {"contentType": content_type, "content": body},
        "toRecipients": [to.to_graph()],
        "internetMessageHeaders": [
            {"name": "X-Mailer", "value": X_MAILER},
        ],
    }
    if opts.importance:
        message["importance"] = opts.importance
    if opts.cc:
        message["ccRecipients"] = [a.to_graph() for a in opts.cc]
    if opts.bcc:
        message["bccRecipients"] = [a.to_graph() for a in opts.bcc]
    if opts.attachments:
        message["attachments"] = opts.attachments
    if opts.reply_to:
        message["replyTo"] = [a.to_graph() for a in opts.reply_to]
    payload: dict[str, object] = {"message": message}
    if not opts.save_to_sent_items:
        payload["saveToSentItems"] = False

    max_rate_limit_retries = 20
    retries = 0
    rate_limit_retries = 0
    was_throttled = False
    while True:
        try:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("POST to %s with headers %s and payload: %s",
                             GRAPH_SEND_URL,
                             json.dumps(headers, indent=2), json.dumps(payload, indent=2))
            resp = requests.post(GRAPH_SEND_URL, json=payload, headers=headers, timeout=30)
        except requests.RequestException as exc:
            retries += 1
            if retries > opts.max_retries:
                return SendResult(email=to.address, success=False, error=str(exc))
            wait = min(2**retries, 60)
            logger.warning("⚠️ Network error sending to %s, retry %d in %ds: %s", to.address, retries, wait, exc)
            time.sleep(wait)
            continue

        if resp.status_code == 202:
            return SendResult(email=to.address, success=True, status_code=202, throttled=was_throttled)

        if resp.status_code == 401 and not token_refreshed:
            logger.warning("⚠️ Token expired, refreshing...")
            token = get_token()
            token_refreshed = True
            headers["Authorization"] = f"Bearer {token}"
            continue

        if resp.status_code == 429:
            was_throttled = True
            rate_limit_retries += 1
            if rate_limit_retries > max_rate_limit_retries:
                return SendResult(
                    email=to.address, success=False, status_code=429,
                    error=f"Rate limited {max_rate_limit_retries} times, giving up",
                )
            try:
                retry_after = min(int(resp.headers.get("Retry-After", 10)), 120)
            except ValueError:
                retry_after = 10
            logger.warning("⚠️ Rate limited, waiting %ds before retrying %s", retry_after, to.address)
            time.sleep(retry_after)
            continue

        if 500 <= resp.status_code < 600:
            retries += 1
            if retries > opts.max_retries:
                return SendResult(
                    email=to.address, success=False, status_code=resp.status_code,
                    error=resp.text[:500],
                )
            wait = min(2**retries, 60)
            logger.warning("⚠️ Server error %d for %s, retry %d in %ds", resp.status_code, to.address, retries, wait)
            time.sleep(wait)
            continue

        # 4xx (non-429) — no retry
        return SendResult(
            email=to.address, success=False, status_code=resp.status_code,
            error=resp.text[:500],
        )


class SendAborted(RuntimeError):
    """Sending stopped part-way because of an error.

    ``results`` holds the results for the emails attempted before the
    error, so a caller can still report which went out.
    """

    def __init__(self, message: str, results: list[SendResult]) -> None:
        super().__init__(message)
        self.results = results


def send_bcc_blast(
    get_token: Callable[[], str] | None,
    emails: list[str],
    to: EmailAddress,
    subject: str,
    body: str,
    dry_run: bool = False,
    opts: MessageOptions | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> list[SendResult]:
    """Send a single subject/body to all emails via BCC, in batches of up to 499.

    Recipients within each batch cannot see each other's addresses.
    Returns one SendResult per recipient email: when a batch succeeds or
    fails, every recipient in that batch receives the same result.
    If ``should_stop`` returns ``True`` before a batch, no further batches
    are sent and only the results so far are returned.
    """
    if opts is None:
        opts = MessageOptions()
    reserved = 1 + len(opts.cc or []) + len(opts.bcc or [])
    max_per_batch = max(1, MAX_RECIPIENTS_PER_MESSAGE - reserved)
    batches = [emails[i:i + max_per_batch] for i in range(0, len(emails), max_per_batch)]
    total = len(batches)
    results: list[SendResult] = []
    bcc_extra = list(opts.bcc or [])
    for i, batch in enumerate(batches):
        if should_stop is not None and should_stop():
            logger.warning("⏹️ Stopped after %d of %d batches", i, total)
            break
        label = f"batch {i + 1}/{total} ({len(batch)} recipients)"
        if dry_run:
            logger.info("🔄 DRY RUN %s | Subject: %s", label, subject)
            results.extend(
                SendResult(email=addr, success=True, status_code=None)
                for addr in batch
            )
            continue
        if get_token is None:
            raise RuntimeError("get_token is required when not in dry-run mode")
        logger.info("📧 Sending %s", label)
        bcc_recipients = [EmailAddress(address=a) for a in batch]
        bcc_all = bcc_extra + bcc_recipients
        batch_opts = replace(opts, bcc=bcc_all)
        try:
            result = send_one(get_token, to, subject, body, opts=batch_opts)
        except Exception as exc:
            raise SendAborted(str(exc), results) from exc
        results.extend(
            SendResult(
                email=addr,
                success=result.success,
                status_code=result.status_code,
                error=result.error,
                throttled=result.throttled,
            )
            for addr in batch
        )
    return results


def send_all(
    get_token: Callable[[], str] | None,
    recipients: list[dict[str, str]],
    email_column: str,
    subject_template: str,
    body_template: str,
    name_column: str | None = None,
    dry_run: bool = False,
    delay: float = 0.0,
    opts: MessageOptions | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> list[SendResult]:
    """Send personalised emails to all recipients.

    In dry-run mode, renders and logs each email without sending.
    If ``name_column`` is set, the recipient's display name is included
    in the ``To:`` header (e.g. ``"Alice <alice@example.com>"``).
    ``should_stop`` is checked before each recipient; once it returns
    ``True``, no further emails are sent and only the results so far are
    returned.
    """
    from mail_merge.template import render

    if opts is None:
        opts = MessageOptions()
    results = []
    current_delay = delay
    max_delay = 30.0
    for i, recipient in enumerate(recipients):
        if should_stop is not None and should_stop():
            logger.warning("⏹️ Stopped after %d of %d emails", i, len(recipients))
            break
        to_name = recipient.get(name_column, "").strip() or None if name_column else None
        to = EmailAddress(address=recipient[email_column], name=to_name)
        rendered_subject = render(subject_template, recipient)
        rendered_body = render(body_template, recipient)

        if dry_run:
            logger.info(
                "🔄 DRY RUN [%d/%d] To: %s | Subject: %s",
                i + 1, len(recipients), to.address, rendered_subject,
            )
            logger.debug("Body:\n%s", rendered_body)
            results.append(SendResult(email=to.address, success=True, status_code=None))
        else:
            if get_token is None:
                raise RuntimeError("get_token is required when not in dry-run mode")
            logger.info("📧 Sending [%d/%d] to %s", i + 1, len(recipients), to.address)
            try:
                result = send_one(
                    get_token, to, rendered_subject, rendered_body, opts=opts,
                )
            except Exception as exc:
                raise SendAborted(str(exc), results) from exc
            results.append(result)
            if not result.success:
                logger.error("❌ Failed to send to %s: %s", to.address, result.error)

            # Adaptive delay: back off on throttling, recover when clear
            if result.throttled:
                current_delay = min(current_delay * 2, max_delay)
                logger.info("⏱️ Rate limit hit, increasing delay to %.1fs", current_delay)
            else:
                current_delay = max(current_delay / 2, delay)

        if not dry_run and current_delay > 0 and i < len(recipients) - 1:
            time.sleep(current_delay)

    return results
