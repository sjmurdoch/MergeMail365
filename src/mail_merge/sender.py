import logging
import time
from collections.abc import Callable
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
    get_token: Callable[[], str],
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
    to_name: str | None = None,
) -> SendResult:
    """Send a single email via Microsoft Graph API.

    Handles 401 (token expired) with a single refresh attempt,
    429 (rate limit) with Retry-After, 5xx with exponential backoff,
    and 4xx (non-429/non-401) as immediate failures.
    """
    token = get_token()
    token_refreshed = False
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    content_type = "HTML" if html else "Text"
    message: dict[str, object] = {
        "subject": subject,
        "body": {"contentType": content_type, "content": body},
        "toRecipients": [{"emailAddress": {"address": to_email, **({"name": to_name} if to_name else {})}}],
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
            wait = min(2**retries, 60)
            logger.warning("⚠️ Network error sending to %s, retry %d in %ds: %s", to_email, retries, wait, exc)
            time.sleep(wait)
            continue

        if resp.status_code == 202:
            return SendResult(email=to_email, success=True, status_code=202, throttled=was_throttled)

        if resp.status_code == 401 and not token_refreshed:
            logger.warning("Token expired, refreshing...")
            token = get_token()
            token_refreshed = True
            headers["Authorization"] = f"Bearer {token}"
            continue

        if resp.status_code == 429:
            was_throttled = True
            rate_limit_retries += 1
            if rate_limit_retries > max_rate_limit_retries:
                return SendResult(
                    email=to_email, success=False, status_code=429,
                    error=f"Rate limited {max_rate_limit_retries} times, giving up",
                )
            try:
                retry_after = min(int(resp.headers.get("Retry-After", 10)), 120)
            except ValueError:
                retry_after = 10
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
            wait = min(2**retries, 60)
            logger.warning("⚠️ Server error %d for %s, retry %d in %ds", resp.status_code, to_email, retries, wait)
            time.sleep(wait)
            continue

        # 4xx (non-429) — no retry
        return SendResult(
            email=to_email, success=False, status_code=resp.status_code,
            error=resp.text[:500],
        )


def send_bcc_blast(
    get_token: Callable[[], str] | None,
    emails: list[str],
    to_email: str,
    subject: str,
    body: str,
    dry_run: bool = False,
    max_retries: int = 3,
    importance: str | None = None,
    cc: list[str] | None = None,
    bcc_extra: list[str] | None = None,
    html: bool = False,
    save_to_sent_items: bool = True,
    attachments: list[dict[str, str]] | None = None,
    reply_to: list[str] | None = None,
    to_name: str | None = None,
) -> list[SendResult]:
    """Send a single subject/body to all emails via BCC, in batches of up to 499.

    Recipients within each batch cannot see each other's addresses.
    Returns one SendResult per batch (not per recipient).
    """
    reserved = 1 + len(cc or []) + len(bcc_extra or [])
    max_per_batch = max(1, 500 - reserved)
    batches = [emails[i:i + max_per_batch] for i in range(0, len(emails), max_per_batch)]
    total = len(batches)
    results = []
    for i, batch in enumerate(batches):
        label = f"batch {i + 1}/{total} ({len(batch)} recipients)"
        if dry_run:
            logger.info("🔄 DRY RUN %s | Subject: %s", label, subject)
            results.append(SendResult(email=label, success=True, status_code=None))
            continue
        if get_token is None:
            raise RuntimeError("get_token is required when not in dry-run mode")
        logger.info("📧 Sending %s", label)
        bcc_all = list(bcc_extra or []) + batch
        result = send_one(
            get_token, to_email, subject, body,
            max_retries=max_retries, importance=importance,
            cc=cc, bcc=bcc_all, html=html,
            save_to_sent_items=save_to_sent_items,
            attachments=attachments, reply_to=reply_to,
            to_name=to_name,
        )
        results.append(SendResult(
            email=label,
            success=result.success,
            status_code=result.status_code,
            error=result.error,
            throttled=result.throttled,
        ))
    return results


def send_all(
    get_token: Callable[[], str] | None,
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
            if get_token is None:
                raise RuntimeError("get_token is required when not in dry-run mode")
            logger.info("📧 Sending [%d/%d] to %s", i + 1, len(recipients), to_email)
            result = send_one(
                get_token, to_email, rendered_subject, rendered_body,
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

        if not dry_run and current_delay > 0 and i < len(recipients) - 1:
            time.sleep(current_delay)

    return results
