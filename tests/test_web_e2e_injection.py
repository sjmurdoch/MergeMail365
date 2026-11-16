"""Untrusted text cannot become markup (docs/review-fixes-plan.md, F11, G7).

One walk through the whole wizard with an injection payload in every string
the page receives from somewhere else: the spreadsheet's file name, sheet
names, column headers and cells, the signed-in account, /auth/debug's
answer, error text from the server and from Microsoft, job log lines, the
send's results, an interrupted send's record, and the #auth-error fragment.

The payload is an <img> with a class. If any of it is ever parsed as markup,
an element with that class exists, whether or not its handler ran: the
Content Security Policy stops the handler, so "no script ran" alone would
prove nothing about the escaping. The walk therefore counts canary elements
after each step; tests/conftest.py also fails the test on any Content
Security Policy violation.

The second test seeds the bug (an escapeHtml() that escapes nothing) and
requires the walk to find canaries at every sink, so a walk that visits
nothing can't pass for a safe page.
"""

import io
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import quote

import openpyxl
import pytest
from playwright.sync_api import Page, expect

import mail_merge.api
from mail_merge.sender import SendAborted, SendResult
from tests.test_web_e2e_workflow import (  # noqa: F401  (fixtures)
    STARTUP_TOKEN,
    AuthStub,
    auth,
    workflow_server,
)


# Breaks out of a quoted attribute, then starts an element.
PAYLOAD = '"\'><img src=x class="xss-canary" onerror="window.__xss=1">'
# Sheet titles are limited to 31 characters and may not contain / : * ? [ ].
SHEET_PAYLOAD = "<img src=x class=xss-canary>"
SAFE_HTML_JS = Path(mail_merge.api.__file__).parent / "web" / "static" / "safe-html.js"


def poisoned_xlsx() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = SHEET_PAYLOAD
    ws.append(["email", PAYLOAD, "name"])
    ws.append(["alice@example.com", PAYLOAD, PAYLOAD])
    ws.append(["bob@example.com", "plain", "Bob"])
    ws.append([f"{SHEET_PAYLOAD}@example.com", "an invalid address", PAYLOAD])
    wb.create_sheet("<b class=xss-canary>two")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def poisoned_send_merge(**kwargs: Any) -> list[SendResult]:
    logging.getLogger("mail_merge.fake").info("log line %s", PAYLOAD)
    if kwargs.get("test_email"):
        if poisoned_send_merge.fail_test:  # type: ignore[attr-defined]
            poisoned_send_merge.fail_test = False  # type: ignore[attr-defined]
            raise RuntimeError(f"Graph said {PAYLOAD}")
        return [SendResult(email="me@example.com", success=True, status_code=202)]
    if kwargs.get("send"):
        results = [
            SendResult(email=PAYLOAD, success=True, status_code=202),
            SendResult(email=f"{PAYLOAD}@example.com", success=False, status_code=400, error=f"rejected: {PAYLOAD}"),
        ]
        raise SendAborted(f"stopped by {PAYLOAD}", results)
    return []


def canaries(page: Page) -> int:
    return int(page.evaluate("document.querySelectorAll('.xss-canary').length"))


def walk(page: Page, base_url: str) -> dict[str, int]:
    """Go through every step with the payload everywhere; return how many
    canary elements existed after each."""
    found: dict[str, int] = {}

    def check(place: str) -> None:
        page.wait_for_timeout(150)  # an injected <img> needs a moment to fail to load
        found[place] = canaries(page)

    def poisoned_config(route: Any) -> None:
        response = route.fetch()
        data = response.json()
        data["tenant_id"] = PAYLOAD
        data["interrupted_sends"] = [{
            "started": PAYLOAD,
            "results": [
                {"email": PAYLOAD, "success": True, "status_code": 202, "error": ""},
                {"email": "x@example.com", "success": False, "status_code": 400, "error": PAYLOAD},
            ],
        }]
        route.fulfill(response=response, json=data)

    page.route("**/api/config", poisoned_config)
    page.route("**/api/interrupted/dismiss", lambda route: route.fulfill(json={"success": True}))
    page.route("**/auth/status", lambda route: route.fulfill(
        json={"authenticated": True, "email": PAYLOAD, "token_expires_at": None}))
    page.route("**/auth/debug", lambda route: route.fulfill(json={
        "error": PAYLOAD, "cache_path": PAYLOAD, "accounts": [{"username": PAYLOAD, "home_account_id": PAYLOAD}],
        "token_valid": False, "authority_reachable": False,
    }))
    page.on("dialog", lambda d: d.accept())

    # --- Step 1: the #auth-error fragment, the account, an interrupted send.
    page.goto(f"{base_url}/?token={STARTUP_TOKEN}")
    page.wait_for_selector("text=Data")
    page.goto(f"{base_url}/#auth-error={quote(PAYLOAD, safe='')}")
    page.reload()
    page.wait_for_selector("#interrupted-send:not(.hidden)", timeout=5000)
    expect(page.locator("#auth-display")).to_contain_text("<img src=x")
    expect(page.locator("#interrupted-send-details")).to_contain_text("<img src=x")
    check("auth display and interrupted send")
    expect(page.locator("#auth-message")).to_contain_text("<img src=x")
    check("auth error fragment")

    page.evaluate("document.getElementById('btn-test-connection').click()")
    expect(page.locator("#auth-diag-content")).to_contain_text("<img src=x")
    check("test connection")

    # --- Step 1: the upload.
    page.set_input_files("#spreadsheet-file", {
        "name": f"{PAYLOAD}.xlsx".replace("/", ""), "mimeType": "application/octet-stream", "buffer": poisoned_xlsx(),
    })
    page.wait_for_selector("#spreadsheet-info:not(.hidden)", timeout=5000)
    expect(page.locator("#preview-table")).to_contain_text("<img src=x")
    check("upload: summary, sheet list, preview table, filter chips")

    # --- Step 2: column lists, chips, the unknown-placeholder message.
    page.click("#btn-next-1")
    page.wait_for_selector("#step-2.active", timeout=5000)
    page.select_option("#email-column", "email")
    # Selecting by value only works if the value attribute holds the whole name.
    page.select_option("#name-column", PAYLOAD)
    assert page.input_value("#name-column") == PAYLOAD
    page.fill("#subject-input", "Hello {{nope}}")
    page.fill("#body-input", "Body")
    page.wait_for_selector("#placeholder-errors:not(.hidden)", timeout=5000)
    expect(page.locator("#placeholder-errors")).to_contain_text("<img src=x")
    check("compose: column lists, chips, placeholder errors")
    page.fill("#subject-input", "Hello {{name}}")
    # The CC field is inside a collapsed "options" section.
    page.evaluate("""(value) => {
        const el = document.getElementById("cc-input");
        el.value = value;
        el.dispatchEvent(new Event("input"));
    }""", '"<b class=xss-canary>cc</b>" <cc@example.com>')

    # --- Step 3: preview, recipients table, skipped addresses.
    page.click("#btn-next-2")
    page.wait_for_selector("#step-3.active", timeout=5000)
    expect(page.locator("#recipients-table")).to_contain_text("<img src=x")
    expect(page.locator("#invalid-email-warning")).to_contain_text("<img src=x")
    expect(page.locator("#preview-subject")).to_contain_text("<img src=x")
    check("preview: headers, recipients table, invalid addresses")

    # --- Step 4: the test email fails with poisoned error text, then passes.
    page.click("#btn-next-3")
    page.wait_for_selector("#step-4.active", timeout=5000)
    page.fill("#test-email-input", "me@example.com")
    expect(page.locator("#test-preview-info")).to_contain_text("<img src=x")
    page.click("#btn-send-test")
    expect(page.locator("#test-result")).to_contain_text("<img src=x", timeout=10000)
    expect(page.locator("#test-log")).to_contain_text("<img src=x")
    check("test email: preview line, error, log")
    page.click("#btn-retry-test")
    expect(page.locator("#test-result")).to_contain_text("successfully", timeout=10000)

    # --- Step 5: the dry run's log.
    page.click("#btn-next-4")
    page.wait_for_selector("#step-5.active", timeout=5000)
    expect(page.locator("#verify-result")).to_contain_text("ready to send", timeout=10000)
    check("dry run: log and result")

    # --- Step 6: the confirmation details, then a send that fails part-way.
    page.click("#btn-next-5")
    page.wait_for_selector("#step-6.active", timeout=5000)
    expect(page.locator("#send-confirm-details")).to_contain_text("<img src=x")
    check("send: confirmation details")
    page.fill("#send-confirm-input", "SEND")
    page.click("#btn-do-send")
    expect(page.locator("#send-result")).to_contain_text("stopped by", timeout=10000)
    expect(page.locator("#send-result table")).to_contain_text("<img src=x")
    expect(page.locator("#send-log")).to_contain_text("<img src=x")
    check("send: error, results table, log")
    return found


@pytest.fixture
def poisoned_jobs(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    poisoned_send_merge.fail_test = True  # type: ignore[attr-defined]
    monkeypatch.setattr(mail_merge.api, "send_merge", poisoned_send_merge)
    # The log panel shows INFO lines; nothing has configured logging here.
    logger = logging.getLogger("mail_merge")
    level = logger.level
    logger.setLevel(logging.INFO)
    yield
    logger.setLevel(level)


def test_payload_everywhere_creates_no_element(page: Page, workflow_server: str, poisoned_jobs: None) -> None:  # noqa: F811
    found = walk(page, workflow_server)
    assert len(found) >= 10
    assert all(count == 0 for count in found.values()), f"injected markup became elements: {found}"
    assert page.evaluate("window.__xss") is None
    # The page fixture fails the test on any Content Security Policy violation.


def test_walk_finds_the_canary_when_escaping_is_broken(page: Page, workflow_server: str, poisoned_jobs: None) -> None:  # noqa: F811
    """The walk must notice an escapeHtml() that escapes nothing, at every
    place that writes markup."""
    source = SAFE_HTML_JS.read_text(encoding="utf-8")
    old = "return String(text).replace(/[&<>\"']/g, c => ESCAPES[c]);"
    assert source.count(old) == 1
    page.route("**/static/safe-html.js", lambda route: route.fulfill(
        body=source.replace(old, "return String(text);"), content_type="application/javascript"))
    page.expect_csp_violations = True  # type: ignore[attr-defined]

    try:
        found = walk(page, workflow_server)
    except Exception:
        # Injected markup may break the page before the walk ends (a column
        # list that can no longer be selected from): that is a finding too.
        found = {"walk broke": canaries(page)}
    assert any(count > 0 for count in found.values()), f"the walk found nothing: {found}"
    if "walk broke" not in found:
        clean = [place for place, count in found.items() if count == 0]
        assert not clean, f"places the walk visits without reaching a markup sink: {clean}"
    # Injected handlers were stopped by the policy, not by luck.
    assert page.evaluate("window.__xss") is None
    assert page.csp_violations, "the injected onerror handlers should have been refused by the policy"  # type: ignore[attr-defined]
