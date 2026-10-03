"""Browser-tier conformance (docs/quint-model-plan.md, step 4).

Replays a handful of model traces against the real page in Chromium: each
model action becomes a click, a typed value, a reload or a server-side job
event, and after every step the page's state (WizardCore.abstractPage) and
its rendered controls must match the model. This is the tier that checks
app.js's effects and render() as well as the reducer.

Traces come from `eStep` in the `conformance` module of spec/wizard.qnt: a
recipient preview or start-job response is answered before any other action
and there is no server restart, so the browser never has to hold a response
(the client tier and tests/test_web_e2e_workflow.py cover those windows).

Needs Quint (see tests/test_conformance.py) and Playwright's Chromium.
CONFORMANCE_E2E_TRACES sets the number of traces (default 4).
"""

import os
import socket
import threading
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import openpyxl
import pytest
from playwright.sync_api import Page

import mail_merge.web.app as web_app
from mail_merge.web.app import create_app
from mail_merge.web.jobs import JobStore
from tests.conformance_support import TOTAL, FakeSendMerge, Handle, load_trace
from tests.test_conformance import QUINT, generate

pytestmark = pytest.mark.skipif(QUINT is None, reason="Quint is not installed")

STARTUP_TOKEN = "conformance-e2e"
SETTLE_S = 5.0


@pytest.fixture(scope="module")
def e2e_traces(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("e2e-traces")
    n = int(os.environ.get("CONFORMANCE_E2E_TRACES", "4"))
    generate(out, "conformance", n, 80, "0x3", ["--init=cInit", "--step=eStep"])
    return out


@pytest.fixture(scope="module")
def e2e_xlsx(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("e2e") / "recipients.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["email"])
    for i in range(TOTAL):
        ws.append([f"r{i}@example.com"])
    wb.save(path)
    return path


class TokenCache:
    """The fake token cache: /auth/status, job tokens and sign-in share it."""

    def __init__(self) -> None:
        self.signed_in = False

    def silent(self, _cid: str, _tid: str) -> str:
        from mail_merge.auth import NotSignedInError

        if not self.signed_in:
            raise NotSignedInError("Not signed in")
        return "token"


@pytest.fixture(scope="module")
def e2e_server() -> Iterator[tuple[str, FakeSendMerge, TokenCache]]:
    fake = FakeSendMerge()
    cache = TokenCache()
    # Its own job store: the module-level one is shared with every other
    # web test in the process.
    store = JobStore()
    with patch("mail_merge.auth._build_msal_app", side_effect=RuntimeError("no MSAL in tests")), \
            patch("mail_merge.api.send_merge", fake), \
            patch("mail_merge.auth.acquire_token_silent", cache.silent), \
            patch.object(web_app, "_job_store", store), \
            patch.object(web_app, "_jobs", store.jobs), \
            patch.object(web_app, "_running_send_job", store.running_send):
        app = create_app(startup_token=STARTUP_TOKEN, port=0, client_id="e2e-client")
        app.config["TESTING"] = True
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        threading.Thread(
            target=lambda: app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True),
            daemon=True,
        ).start()
        base_url = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                urllib.request.urlopen(f"{base_url}/?token={STARTUP_TOKEN}", timeout=1)
                break
            except Exception:
                time.sleep(0.1)
        try:
            yield base_url, fake, cache
        finally:
            fake.release_all()


# What the page shows, read in one evaluate: the abstraction, the selectors
# and the rendered controls (render() must project the selectors).
SNAPSHOT_JS = """() => {
    const C = WizardCore, s = window.state, $ = (id) => document.getElementById(id);
    const shown = (id) => !$(id).classList.contains("hidden");
    return {
        page: C.abstractPage(s, sendConfirmed()),
        guards: {
            sendTestEnabled: C.sendTestEnabled(s),
            doSendEnabled: C.doSendEnabled(s, sendConfirmed()),
            signInOffered: s.currentStep === 1 || C.signInOffered(s),
        },
        dom: {
            activeStep: Number(document.querySelector(".step-panel.active").id.replace("step-", "")),
            btnSendTest: !$("btn-send-test").disabled,
            btnNext4: !$("btn-next-4").disabled,
            btnNext5: !$("btn-next-5").disabled,
            btnDoSend: !$("btn-do-send").disabled,
            btnBack6: !$("btn-back-6").disabled,
            signin4: shown("signin-callout-4"),
            signin6: shown("signin-callout-6"),
            verifyShown: shown("verify-result"),
            sendConfirm: shown("send-confirm"),
            sendDone: shown("send-done-nav"),
            resultsShown: $("send-result").querySelector("h4") !== null,
        },
    };
}"""


def expected_view(m: dict) -> dict:
    """The model's page fields and the controls it implies."""
    step6 = m["step"] == 6
    offered = m["step"] == 1 or (not m["authShown"] and (m["step"] == 4 or (step6 and not m["sendStarted"])))
    return {
        "page": {
            "step": m["step"], "dataLoaded": m["dataLoaded"],
            "testPassed": m["testPassed"], "verifyPassed": m["verifyPassed"],
            "sendStarted": m["sendStarted"], "verifyShown": m["verifyShown"],
            "resultsShown": m["resultsShown"], "btnSendTest": m["btnSendTest"],
            "btnNext4": m["btnNext4"], "btnNext5": m["btnNext5"], "btnDoSend": m["btnDoSend"],
            "doneNav": m["doneNav"], "authShown": m["authShown"],
            "recipientsKnown": m["recipientsVersion"] != -1,
        },
        "guards": {
            "sendTestEnabled": m["btnSendTest"] and m["authShown"],
            "doSendEnabled": m["btnDoSend"] and m["authShown"],
            "signInOffered": offered,
        },
        "dom": {
            "activeStep": m["step"],
            "btnSendTest": m["btnSendTest"] and m["authShown"],
            "btnNext4": m["btnNext4"],
            "btnNext5": m["btnNext5"],
            "btnDoSend": m["btnDoSend"] and m["authShown"],
            "btnBack6": m["btnBack6"] if step6 else None,
            "signin4": offered and m["step"] == 4,
            "signin6": offered and step6,
            "verifyShown": m["verifyShown"],
            "sendConfirm": not m["sendStarted"],
            "sendDone": m["doneNav"],
            "resultsShown": m["resultsShown"],
        },
    }


def actual_view(snap: dict, step6: bool) -> dict:
    page = dict(snap["page"])
    page["recipientsKnown"] = page.pop("recipientsVersion") != -1
    for k in ("version", "pending", "previewReq", "sendReq", "stopQueued", "btnBack6"):
        page.pop(k)
    dom = dict(snap["dom"])
    if not step6:
        dom["btnBack6"] = None
    return {"page": page, "guards": snap["guards"], "dom": dom}


class BrowserReplay:
    def __init__(self, page: Page, base_url: str, fake: FakeSendMerge, cache: TokenCache, xlsx: Path) -> None:
        self.page = page
        self.base_url = base_url
        self.fake = fake
        self.cache = cache
        self.xlsx = xlsx
        self.jobs: dict[int, Handle] = {}
        self.dialog_accept = True
        self.fail_preview = False
        self.uploads = 0
        page.on("dialog", self._dialog)
        page.route("**/api/get-recipients", self._recipients)
        page.route("**/auth/status", self._auth_status)
        page.goto(f"{base_url}/?token={STARTUP_TOKEN}")
        self.loaded()

    def _dialog(self, dialog: Any) -> None:
        # confirm() is the back confirmation; alert() only needs closing.
        if dialog.type == "confirm" and not self.dialog_accept:
            dialog.dismiss()
        else:
            dialog.accept()

    def _recipients(self, route: Any) -> None:
        if self.fail_preview:
            route.fulfill(status=500, json={"error": "preview failed"})
        else:
            route.continue_()

    def _auth_status(self, route: Any) -> None:
        if self.cache.signed_in:
            route.fulfill(json={"authenticated": True, "email": "me@example.com", "token_expires_at": None})
        else:
            route.fulfill(json={"authenticated": False, "email": None})

    def js(self, script: str, arg: Any = None) -> Any:
        return self.page.evaluate(script, arg)

    def loaded(self) -> None:
        """Wait for a (re)loaded page to apply /api/config and /auth/status."""
        self.page.wait_for_function(
            "() => window.state && document.getElementById('client-id').value === 'e2e-client'"
            " && Object.keys(state.requests).length === 0", timeout=SETTLE_S * 1000)

    def compose(self) -> None:
        """Fill the compose fields without input events, so the page's
        content version doesn't move where the model's doesn't."""
        self.js("""() => {
            const $ = (id) => document.getElementById(id);
            if (!$("subject-input").value) $("subject-input").value = "Hello";
            if (!$("body-input").value) $("body-input").value = "Hi";
            if (!$("email-column").value) $("email-column").value = "email";
        }""")

    def new_job(self, model_id: int) -> None:
        self.jobs[model_id] = self.fake.started.get(timeout=SETTLE_S)

    def command(self, model_id: int, cmd: str) -> None:
        handle = self.jobs.get(model_id)
        if handle is None:
            return
        handle.commands.put(cmd)
        if cmd == "next":
            # Sent one email, or finished; the page catches up below.
            try:
                handle.acks.get(timeout=0.5)
            except Exception:
                pass

    def click(self, selector: str) -> None:
        self.page.click(selector, timeout=SETTLE_S * 1000)

    def step(self, m: dict, nxt: dict, action: str, picks: dict, following: dict | None) -> None:
        self.cache.signed_in = nxt["signedIn"]
        if action == "upload":
            # Choosing the file already chosen fires no change event (in a
            # real file picker too), so alternate between two copies.
            self.uploads += 1
            copy = self.xlsx.with_name(f"{self.xlsx.stem}-{self.uploads % 2}{self.xlsx.suffix}")
            if not copy.exists():
                copy.write_bytes(self.xlsx.read_bytes())
            with self.page.expect_response("**/api/upload-spreadsheet"):
                self.page.set_input_files("#spreadsheet-file", str(copy))
        elif action == "next1":
            self.js("goToStep(2)") if not m["dataLoaded"] else self.click("#btn-next-1")
        elif action == "edit":
            self.compose()
            value = self.js("document.getElementById('subject-input').value")
            self.page.fill("#subject-input", "Hello" if value.endswith("!") else value + "!")
        elif action == "back2":
            self.click("#step-2 button:has-text('Back')")
        elif action == "next2":
            # eStep answers the preview next: fail it now if the trace does.
            assert following and following["action"] == "previewResponse"
            self.fail_preview = not following["picks"]["ok"]
            self.compose()
            self.click("#btn-next-2")
        elif action == "previewResponse":
            pass  # answered by the server during next2
        elif action in ("back3", "back4", "back5", "back6"):
            self.dialog_accept = picks.get("a", True)
            step = int(action[-1])
            self.click(f"#step-{step} button:has-text('Back')")
        elif action == "next3":
            self.click("#btn-next-3")
        elif action == "sendTestEmail":
            self.js("""() => { const el = document.getElementById("test-email-input");
                if (!el.value) el.value = "me@example.com"; }""")
            self.click("#btn-send-test")
            self.new_job(m["nextJobId"])
        elif action == "next4":
            self.click("#btn-next-4")
            self.new_job(m["nextJobId"])
        elif action == "next5":
            self.click("#btn-next-5")
        elif action == "typeSend":
            self.page.fill("#send-confirm-input", "SEND")
        elif action == "startSend":
            self.click("#btn-do-send")
            self.new_job(m["nextJobId"])
        elif action == "startSendResponse":
            pass  # the start-job response arrives on its own
        elif action == "stopSend":
            self.click("#btn-stop-send")
        elif action == "completeJob":
            self.command(picks["j"]["id"], "ok" if picks["ok"] else "fail")
        elif action == "completeOrphan":
            self.command(picks["sj"]["id"], "ok")
        elif action in ("sendNext", "sendWithoutToken"):
            self.command(picks["j"]["id"], "next")
        elif action == "finishSend":
            self.command(picks["j"]["id"], "fail" if picks["failed"] else "next")
        elif action == "newMerge":
            self.click("#btn-new-merge")
        elif action == "signIn":
            if picks["desktop"]:
                self.js("checkAuthStatus()")
            else:
                self.page.reload()
                self.loaded()
        elif action == "signOut":
            self.js("checkAuthStatus()")
        elif action == "tokenExpires":
            pass  # the page isn't told
        elif action == "reload":
            self.page.reload()
            self.loaded()
        else:
            raise AssertionError(f"no browser driver for model action {action}")

    def settle(self, m: dict, where: str) -> None:
        """Wait until the page matches the model, or fail with the difference."""
        expected = expected_view(m)
        deadline = time.monotonic() + SETTLE_S
        while True:
            actual = actual_view(self.js(SNAPSHOT_JS), m["step"] == 6)
            if actual == expected or time.monotonic() > deadline:
                break
            time.sleep(0.02)
        diff = {
            f"{part}.{k}": {"page": actual[part].get(k), "model": v}
            for part in expected for k, v in expected[part].items() if actual[part].get(k) != v
        }
        assert not diff, f"{where}: {diff}"


def test_browser_conformance(page: Page, e2e_server, e2e_traces: Path, e2e_xlsx: Path):
    base_url, fake, cache = e2e_server
    files = sorted(e2e_traces.glob("*.itf.json"))
    assert files
    for path in files:
        trace = load_trace(path)
        cache.signed_in = trace[0]["s"]["signedIn"]
        # Leave the previous page first: a response still in flight would
        # set its session cookie again.
        page.goto("about:blank")
        page.context.clear_cookies()
        replay = BrowserReplay(page, base_url, fake, cache, e2e_xlsx)
        try:
            replay.settle(trace[0]["s"], f"{path.name} init")
            for i in range(1, len(trace)):
                t = trace[i]
                following = trace[i + 1] if i + 1 < len(trace) else None
                actions = " ".join(x["action"] for x in trace[1:i + 1])
                try:
                    replay.step(trace[i - 1]["s"], t["s"], t["action"], t["picks"], following)
                except Exception as exc:
                    raise AssertionError(f"{path.name} step {i} ({actions}): driving {t['action']} failed") from exc
                if t["action"] in ("next2", "startSend"):
                    continue  # compared after the response that eStep takes next
                replay.settle(t["s"], f"{path.name} step {i} ({actions})")
        finally:
            for handle in replay.jobs.values():
                handle.commands.put("die")
            page.unroute("**/api/get-recipients")
            page.unroute("**/auth/status")
            page.remove_listener("dialog", replay._dialog)
            page.evaluate("localStorage.clear()")
            # The next trace starts with no send running.
            deadline = time.monotonic() + SETTLE_S
            while web_app._running_send_job() and time.monotonic() < deadline:
                time.sleep(0.02)


APP_JS = Path(__file__).resolve().parent.parent / "src" / "mail_merge" / "web" / "static" / "app.js"

# Bugs seeded into app.js (rendering and effects, which the client tier
# doesn't run), each of which the browser replay must notice.
APP_MUTANTS = [
    ("next5-always-enabled",
     '$("btn-next-5").disabled = !C.nextEnabled(state, 5);',
     '$("btn-next-5").disabled = false;'),
    ("no-sign-in-on-step6",
     'toggle("signin-callout-6", offered && state.currentStep === 6);',
     'toggle("signin-callout-6", false);'),
    ("failed-test-keeps-stale-auth",
     'case "checkAuth":\n            checkAuthStatus();',
     'case "checkAuth":'),
    ("results-not-rendered",
     "let html = `<h4>Results</h4>`;",
     'let html = "";'),
]


@pytest.mark.parametrize(("name", "old", "new"), APP_MUTANTS, ids=[m[0] for m in APP_MUTANTS])
def test_browser_replay_catches_mutant(page: Page, e2e_server, e2e_traces: Path, e2e_xlsx: Path, name, old, new):
    source = APP_JS.read_text(encoding="utf-8")
    assert source.count(old) == 1, f"mutant {name}: the text to replace is not in app.js once"
    mutated = source.replace(old, new)
    page.route("**/static/app.js*", lambda route: route.fulfill(
        body=mutated, content_type="application/javascript"))
    with pytest.raises(AssertionError):
        test_browser_conformance(page, e2e_server, e2e_traces, e2e_xlsx)
