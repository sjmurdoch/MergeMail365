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


def send_one(
    token: str,
    to_email: str,
    subject: str,
    body: str,
    max_retries: int = 3,
) -> SendResult:
    """Send a single email via Microsoft Graph API.

    Handles 429 (rate limit) with Retry-After, 5xx with exponential backoff,
    and 4xx (non-429) as immediate failures.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": to_email}}],
        }
    }

    retries = 0
    while True:
        try:
            resp = requests.post(GRAPH_SEND_URL, json=payload, headers=headers, timeout=30)
        except requests.RequestException as exc:
            retries += 1
            if retries > max_retries:
                return SendResult(email=to_email, success=False, error=str(exc))
            wait = 2**retries
            logger.warning("Network error sending to %s, retry %d in %ds: %s", to_email, retries, wait, exc)
            time.sleep(wait)
            continue

        if resp.status_code == 202:
            return SendResult(email=to_email, success=True, status_code=202)

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 10))
            logger.warning("Rate limited, waiting %ds before retrying %s", retry_after, to_email)
            time.sleep(retry_after)
            continue  # unlimited retries for 429

        if 500 <= resp.status_code < 600:
            retries += 1
            if retries > max_retries:
                return SendResult(
                    email=to_email, success=False, status_code=resp.status_code,
                    error=resp.text[:500],
                )
            wait = 2**retries
            logger.warning("Server error %d for %s, retry %d in %ds", resp.status_code, to_email, retries, wait)
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
) -> list[SendResult]:
    """Send personalised emails to all recipients.

    In dry-run mode, renders and logs each email without sending.
    """
    from mail_merge.template import render

    results = []
    for i, recipient in enumerate(recipients):
        to_email = recipient[email_column]
        rendered_subject = render(subject_template, recipient)
        rendered_body = render(body_template, recipient)

        if dry_run:
            logger.info(
                "DRY RUN [%d/%d] To: %s | Subject: %s",
                i + 1, len(recipients), to_email, rendered_subject,
            )
            logger.debug("Body:\n%s", rendered_body)
            results.append(SendResult(email=to_email, success=True, status_code=None))
        else:
            logger.info("Sending [%d/%d] to %s", i + 1, len(recipients), to_email)
            result = send_one(token, to_email, rendered_subject, rendered_body, max_retries=max_retries)
            results.append(result)
            if not result.success:
                logger.error("Failed to send to %s: %s", to_email, result.error)

        if delay > 0 and i < len(recipients) - 1:
            time.sleep(delay)

    return results
