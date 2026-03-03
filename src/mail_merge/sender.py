import logging
import time
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

GRAPH_SEND_URL = "https://graph.microsoft.com/v1.0/me/sendMail"


@dataclass
class SendResult:
    email: str
    success: bool
    status_code: int | None = None
    error: str = ""
    throttled: bool = False


def send_one(
    token: str,
    to_email: str,
    subject: str,
    body: str,
    max_retries: int = 3,
    importance: str | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    html: bool = False,
    save_to_sent_items: bool = True,
    attachments: list[dict[str, str]] | None = None,
    reply_to: list[str] | None = None,
) -> SendResult:
    """Send a single email via Microsoft Graph API.

    Handles 429 (rate limit) with Retry-After, 5xx with exponential backoff,
    and 4xx (non-429) as immediate failures.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    content_type = "HTML" if html else "Text"
    message: dict[str, object] = {
        "subject": subject,
        "body": {"contentType": content_type, "content": body},
        "toRecipients": [{"emailAddress": {"address": to_email}}],
    }
    if importance:
        message["importance"] = importance
    if cc:
        message["ccRecipients"] = [{"emailAddress": {"address": a}} for a in cc]
    if bcc:
        message["bccRecipients"] = [{"emailAddress": {"address": a}} for a in bcc]
    if attachments:
        message["attachments"] = attachments
    if reply_to:
        message["replyTo"] = [{"emailAddress": {"address": a}} for a in reply_to]
    payload: dict[str, object] = {"message": message}
    if not save_to_sent_items:
        payload["saveToSentItems"] = False

    max_rate_limit_retries = 20
    retries = 0
    rate_limit_retries = 0
    was_throttled = False
    while True:
        try:
            resp = requests.post(GRAPH_SEND_URL, json=payload, headers=headers, timeout=30)
        except requests.RequestException as exc:
            retries += 1
            if retries > max_retries:
                return SendResult(email=to_email, success=False, error=str(exc))
            wait = 2**retries
            logger.warning("⚠️ Network error sending to %s, retry %d in %ds: %s", to_email, retries, wait, exc)
            time.sleep(wait)
            continue

        if resp.status_code == 202:
            return SendResult(email=to_email, success=True, status_code=202, throttled=was_throttled)

        if resp.status_code == 429:
            was_throttled = True
            rate_limit_retries += 1
            if rate_limit_retries > max_rate_limit_retries:
                return SendResult(
                    email=to_email, success=False, status_code=429,
                    error=f"Rate limited {max_rate_limit_retries} times, giving up",
                )
            retry_after = int(resp.headers.get("Retry-After", 10))
            logger.warning("⚠️ Rate limited, waiting %ds before retrying %s", retry_after, to_email)
            time.sleep(retry_after)
            continue

        if 500 <= resp.status_code < 600:
            retries += 1
            if retries > max_retries:
                return SendResult(
                    email=to_email, success=False, status_code=resp.status_code,
                    error=resp.text[:500],
                )
            wait = 2**retries
            logger.warning("⚠️ Server error %d for %s, retry %d in %ds", resp.status_code, to_email, retries, wait)
            time.sleep(wait)
            continue

        # 4xx (non-429) — no retry
        return SendResult(
            email=to_email, success=False, status_code=resp.status_code,
            error=resp.text[:500],
        )


def send_all(
    token: str | None,
    recipients: list[dict[str, str]],
    email_column: str,
    subject_template: str,
    body_template: str,
    dry_run: bool = False,
    delay: float = 0.0,
    max_retries: int = 3,
    importance: str | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    html: bool = False,
    save_to_sent_items: bool = True,
    attachments: list[dict[str, str]] | None = None,
    reply_to: list[str] | None = None,
) -> list[SendResult]:
    """Send personalised emails to all recipients.

    In dry-run mode, renders and logs each email without sending.
    """
    from mail_merge.template import render

    results = []
    current_delay = delay
    max_delay = 30.0
    for i, recipient in enumerate(recipients):
        to_email = recipient[email_column]
        rendered_subject = render(subject_template, recipient)
        rendered_body = render(body_template, recipient)

        if dry_run:
            logger.info(
                "🔄 DRY RUN [%d/%d] To: %s | Subject: %s",
                i + 1, len(recipients), to_email, rendered_subject,
            )
            logger.debug("Body:\n%s", rendered_body)
            results.append(SendResult(email=to_email, success=True, status_code=None))
        else:
            assert token is not None
            logger.info("📧 Sending [%d/%d] to %s", i + 1, len(recipients), to_email)
            result = send_one(
                token, to_email, rendered_subject, rendered_body,
                max_retries=max_retries, importance=importance, cc=cc, bcc=bcc,
                html=html, save_to_sent_items=save_to_sent_items,
                attachments=attachments, reply_to=reply_to,
            )
            results.append(result)
            if not result.success:
                logger.error("❌ Failed to send to %s: %s", to_email, result.error)

            # Adaptive delay: back off on throttling, recover when clear
            if result.throttled:
                current_delay = min(current_delay * 2, max_delay)
                logger.info("⏱️ Rate limit hit, increasing delay to %.1fs", current_delay)
            else:
                current_delay = max(current_delay / 2, delay)

        if current_delay > 0 and i < len(recipients) - 1:
            time.sleep(current_delay)

    return results
