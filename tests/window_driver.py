"""Runs `mergemail365-web --desktop` in its real window and drives the page
inside it (tests/test_window.py starts this as a separate process).

Everything is the app's own except three things: Microsoft sign-in (a token
cache holding one account), Graph (answers 202 and is counted) and a
function handed to `webview.start()`, which pywebview runs in a thread once
the window is up. That function works the page through
`window.evaluate_js()`, writes what it saw to a JSON file and closes the
window, which ends the app as closing it by hand does.

    python window_driver.py PHASE RESULT.json SPREADSHEET.xlsx [app options]

PHASE is `merge` (a whole merge, then leave the compose fields filled in)
or `reopen` (upload again and report what the page remembered).
"""

from __future__ import annotations

import base64
import json
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

ACCOUNT = "sender@example.com"
SUBJECT = "Hello {{First Name}}"
BODY = "<div>Dear <strong>{{First Name}}</strong>, see you soon.</div>"
EMAIL_COLUMN = "Work address"
NAME_COLUMN = "First Name"
SHEET = "Students"
AUTOSAVE_SECONDS = 5
ANSWER_PATH = "/window-test-answer/"

# What the page holds for each key it keeps in localStorage (as REMEMBERED
# in test_web_e2e_restart.py).
FIELDS_JS = """({
    mm_subject: $('subject-input').value,
    mm_body: $('html-toggle').checked ? $('trix-input').value : $('body-input').value,
    mm_html: $('html-toggle').checked,
    mm_email_col: $('email-column').value,
    mm_name_col: $('name-column').value,
    mm_sheet: $('sheet-select').value,
})"""


class FakeMsalApp:
    """A token cache with one signed-in account."""

    def get_accounts(self, username: str | None = None) -> list[dict[str, str]]:
        return [{"username": ACCOUNT}]

    def acquire_token_silent(self, scopes: Any, account: Any = None, **kwargs: Any) -> dict[str, str]:
        return {"access_token": "window-test-token"}


class Answers:
    """What the page posts back: a WSGI layer in front of the app that
    takes the requests to ANSWER_PATH and passes on the rest."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.count = 0
        self.waiting: dict[int, threading.Event] = {}
        self.arrived: dict[int, Any] = {}

    def expect(self) -> tuple[int, threading.Event]:
        with self.lock:
            self.count += 1
            self.waiting[self.count] = threading.Event()
            return self.count, self.waiting[self.count]

    def take(self, number: int) -> Any:
        with self.lock:
            del self.waiting[number]
            return self.arrived.pop(number)

    def in_front_of(self, app: Any) -> Any:
        def layer(environ: dict[str, Any], start_response: Any) -> Any:
            path = environ.get("PATH_INFO", "")
            if not path.startswith(ANSWER_PATH):
                return app(environ, start_response)
            body = environ["wsgi.input"].read(int(environ.get("CONTENT_LENGTH") or 0))
            number = int(path[len(ANSWER_PATH):])
            with self.lock:
                self.arrived[number] = json.loads(body)
                self.waiting[number].set()
            start_response("204 No Content", [])
            return [b""]
        return layer


class Page:
    """The page in the window, through pywebview."""

    def __init__(self, window: Any, answers: Answers) -> None:
        self.window = window
        self.answers = answers

    def js(self, expression: str) -> Any:
        """The value of a JavaScript expression (`$` is getElementById).

        pywebview's evaluate_js() wraps the script in eval(), which the
        app's Content Security Policy refuses, so the script is run as it
        is and posts its value back to the app's own port.
        """
        number, arrived = self.answers.expect()
        self.window.run_js(f"""(async () => {{
            const $ = (id) => document.getElementById(id);
            let answer;
            try {{ answer = {{value: await ({expression})}}; }} catch (e) {{ answer = {{error: String(e)}}; }}
            await fetch("{ANSWER_PATH}{number}", {{method: "POST", body: JSON.stringify(answer)}});
        }})();""")
        if not arrived.wait(10):
            raise TimeoutError(f"no answer from the page for: {expression[:200]}")
        answer = self.answers.take(number)
        if "error" in answer:
            raise RuntimeError(f"{answer['error']} in: {expression[:200]}")
        return answer.get("value")

    def wait(self, condition: str, what: str, seconds: float = 20) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                if self.js(f"!!({condition})"):
                    return
            except Exception:  # the page may be between documents
                pass
            time.sleep(0.1)
        raise AssertionError(f"timed out waiting for {what}; alerts: {self.js('window.__alerts || []')}")

    def ready(self) -> None:
        self.wait("document.readyState === 'complete' && window.state && $('step-1')", "the wizard to load")
        # A dialog would stop the page until someone answered it.
        self.js("(window.__alerts = [], window.alert = (m) => { window.__alerts.push(String(m)); }, "
                "window.confirm = () => true, true)")
        self.wait("$('step-1').classList.contains('active')", "step 1")

    def click(self, element_id: str) -> None:
        self.wait(f"$('{element_id}') && !$('{element_id}').disabled", f"#{element_id} to be enabled")
        self.js(f"($('{element_id}').click(), true)")

    def type(self, element_id: str, text: str) -> None:
        self.js(f"($('{element_id}').value = {json.dumps(text)}, "
                f"$('{element_id}').dispatchEvent(new Event('input', {{bubbles: true}})), true)")

    def choose(self, element_id: str, value: str) -> None:
        self.js(f"($('{element_id}').value = {json.dumps(value)}, "
                f"$('{element_id}').dispatchEvent(new Event('change', {{bubbles: true}})), true)")

    def step(self, number: int) -> None:
        self.wait(f"$('step-{number}').classList.contains('active')", f"step {number}")

    def upload(self, xlsx: Path) -> None:
        """Give the file input a file, as choosing one in the dialog does."""
        data = base64.b64encode(xlsx.read_bytes()).decode("ascii")
        self.js(f"""(() => {{
            const bytes = Uint8Array.from(atob("{data}"), (c) => c.charCodeAt(0));
            const transfer = new DataTransfer();
            transfer.items.add(new File([bytes], {json.dumps(xlsx.name)}));
            $('spreadsheet-file').files = transfer.files;
            $('spreadsheet-file').dispatchEvent(new Event('change', {{bubbles: true}}));
            return true;
        }})()""")
        self.wait("!$('spreadsheet-info').classList.contains('hidden')", "the spreadsheet to load")


def merge(page: Page, xlsx: Path, seen: dict[str, Any]) -> None:
    """A whole merge of one HTML email, start to finish."""
    page.ready()
    page.wait(f"$('auth-display').textContent.includes('{ACCOUNT}')", "the signed-in account")
    seen["desktop_mode"] = page.js("_auth.desktopMode")
    seen["origin"] = page.js("location.origin")
    seen["user_agent"] = page.js("navigator.userAgent")
    seen["stored_at_start"] = page.js("Object.keys(localStorage).filter((k) => k.startsWith('mm_'))")

    page.upload(xlsx)
    page.choose("sheet-select", SHEET)
    page.wait("JSON.stringify(window.state.spreadsheetData.rows).includes('bob@work.example')", "the second sheet")
    page.click("btn-next-1")
    page.step(2)
    page.choose("email-column", EMAIL_COLUMN)
    page.choose("name-column", NAME_COLUMN)
    page.type("subject-input", SUBJECT)
    page.click("html-toggle")
    page.wait("!$('html-editor-wrap').classList.contains('hidden') && window.state.trixEditor", "the HTML editor")
    page.click("source-toggle")
    page.type("html-source", BODY)
    page.click("source-toggle")
    page.wait("$('trix-input').value.includes('<strong>')", "the editor to take the HTML")
    seen["composed"] = page.js(FIELDS_JS)

    page.click("btn-next-2")
    page.step(3)
    seen["preview_subject"] = page.js("$('preview-subject').textContent")
    seen["preview_to"] = page.js("$('preview-to').textContent")
    seen["preview_frame"] = page.js(
        "(() => { const f = $('preview-body-html'); const r = f.getBoundingClientRect(); "
        "return {shown: !f.classList.contains('hidden'), width: r.width, height: r.height, "
        "srcdoc: f.srcdoc || ''}; })()")

    page.click("btn-next-3")
    page.step(4)
    seen["test_address"] = page.js("$('test-email-input').value")
    page.click("btn-send-test")
    page.wait("window.state.testPassed", "the test email")
    page.click("btn-next-4")
    page.step(5)
    page.wait("window.state.verifyPassed", "the dry run")
    page.click("btn-next-5")
    page.step(6)
    page.type("send-confirm-input", "SEND")
    page.click("btn-do-send")
    page.wait("!$('send-done-nav').classList.contains('hidden')", "the send to finish", seconds=30)
    seen["send_result"] = page.js("$('send-result').innerText")
    seen["scrolls_sideways"] = page.js("document.documentElement.scrollWidth > document.documentElement.clientWidth")
    seen["alerts"] = page.js("window.__alerts")

    # The page saves the compose fields every five seconds; then give the
    # window's own storage a moment to reach the disk before it is closed.
    page.wait("localStorage.getItem('mm_subject')", "the auto-save", seconds=AUTOSAVE_SECONDS + 5)
    seen["stored_at_end"] = page.js("Object.fromEntries(Object.entries(localStorage).filter(([k]) => k.startsWith('mm_')))")
    time.sleep(2)


def reopen(page: Page, xlsx: Path, seen: dict[str, Any]) -> None:
    """The app opened again: what does the page remember?"""
    page.ready()
    seen["origin"] = page.js("location.origin")
    seen["stored_at_start"] = page.js("Object.fromEntries(Object.entries(localStorage).filter(([k]) => k.startsWith('mm_')))")
    page.upload(xlsx)
    page.wait(f"$('sheet-select').value === '{SHEET}' && "
              "JSON.stringify(window.state.spreadsheetData.rows).includes('bob@work.example')", "the remembered sheet")
    page.click("btn-next-1")
    page.step(2)
    seen["composed"] = page.js(FIELDS_JS)
    seen["alerts"] = page.js("window.__alerts")
    # Leave nothing behind for the next run.
    page.js("(Object.keys(localStorage).forEach((k) => localStorage.removeItem(k)), true)")
    time.sleep(2)


PHASES = {"merge": merge, "reopen": reopen}


def main() -> None:
    phase, result_path, xlsx = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    app_args = sys.argv[4:]

    import responses
    import webview
    import werkzeug.serving

    import mail_merge.auth
    from mail_merge.sender import GRAPH_SEND_URL
    from mail_merge.web import main as app_main

    mail_merge.auth._build_msal_app = lambda *args, **kwargs: (FakeMsalApp(), None)  # type: ignore[assignment]
    mail_merge.auth.acquire_token_silent = lambda *args, **kwargs: "window-test-token"  # type: ignore[assignment]

    graph = responses.RequestsMock(assert_all_requests_are_fired=False)
    graph.add(responses.POST, GRAPH_SEND_URL, status=202)
    graph.start()

    seen: dict[str, Any] = {"phase": phase}
    answers = Answers()
    real_make_server = werkzeug.serving.make_server
    werkzeug.serving.make_server = (  # type: ignore[assignment]
        lambda host, port, app, **kwargs: real_make_server(host, port, answers.in_front_of(app), **kwargs))

    def drive(window: Any) -> None:
        try:
            PHASES[phase](Page(window, answers), xlsx, seen)
            seen["finished"] = True
        except BaseException:  # reported to the test, which fails on it
            seen["error"] = traceback.format_exc()
        finally:
            seen["graph_requests"] = [json.loads(call.request.body) for call in graph.calls]
            result_path.write_text(json.dumps(seen, indent=2), encoding="utf-8")
            window.destroy()

    real_start = webview.start

    def start(*args: Any, **kwargs: Any) -> None:
        seen["start_options"] = {k: str(v) for k, v in kwargs.items()}
        real_start(drive, webview.windows[0], *args, **kwargs)

    webview.start = start  # type: ignore[assignment]
    app_main(["--desktop", *app_args])


if __name__ == "__main__":
    main()
