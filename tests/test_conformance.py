"""Model-based conformance (docs/quint-model-plan.md, step 4).

Random traces of spec/wizard.qnt are generated with Quint and replayed
against the code, comparing the model's state with the code's after every
step:

- client tier: tests/js/conformance.test.js replays each trace through
  WizardCore.reduce() and compares WizardCore.abstractPage();
- server tier: TestServerConformance (below) replays the server's side of
  each trace against JobStore and compares JobStore.abstract().

Traces come from two step relations: `cStep` in the `conformance` module
(biased so traces reach the send step) and the model's own `step` in `fixed`
(uniform, so resets on steps 1 to 3 are covered). Mutation tests check that
the client replay notices seeded bugs in wizard-core.js.

Needs Quint (spec/node_modules/.bin/quint after `npm ci --prefix spec`, or
QUINT, or `quint` on PATH) and Node; skipped otherwise. CONFORMANCE_TRACES
sets the number of biased traces (default 100).
"""

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "spec" / "wizard.qnt"
CORE = ROOT / "src" / "mail_merge" / "web" / "static" / "wizard-core.js"
CLIENT_REPLAY = ROOT / "tests" / "js" / "conformance.test.js"


def quint_command() -> str | None:
    if os.environ.get("QUINT"):
        return os.environ["QUINT"]
    local = ROOT / "spec" / "node_modules" / ".bin" / "quint"
    if local.exists():
        return str(local)
    return shutil.which("quint")


QUINT = quint_command()
pytestmark = pytest.mark.skipif(
    QUINT is None or shutil.which("node") is None, reason="Quint or Node.js is not installed",
)


def generate(out_dir: Path, main: str, n: int, steps: int, seed: str, extra: list[str]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    assert QUINT is not None
    subprocess.run(
        [QUINT, "run", str(SPEC), f"--main={main}", "--backend=typescript", "--mbt",
         f"--max-samples={n}", f"--n-traces={n}", f"--max-steps={steps}", f"--seed={seed}",
         f"--out-itf={out_dir / (main + '_{seq}.itf.json')}", *extra],
        check=True, capture_output=True, text=True, timeout=1800,
    )


@pytest.fixture(scope="session")
def traces(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("traces")
    n = int(os.environ.get("CONFORMANCE_TRACES", "100"))
    generate(out, "conformance", n, 120, "0x1", ["--init=cInit", "--step=cStep"])
    generate(out, "fixed", max(n // 2, 1), 30, "0x2", [])
    return out


def replay_client(traces: Path, core: Path = CORE) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["node", "--test", str(CLIENT_REPLAY)],
        env={**os.environ, "TRACES_DIR": str(traces), "WIZARD_CORE": str(core)},
        capture_output=True, text=True, timeout=600,
    )


def test_client_conformance(traces):
    result = replay_client(traces)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]


# Bugs seeded into wizard-core.js, each of which the client replay must
# notice: (name, text to replace, replacement). Mutants that the replay
# cannot notice by design are left out:
# - configLoaded keeping the passed flags: a reload starts from
#   initialState(), so the flags are already false;
# - previewResponse ignoring the step: any navigation already drops the
#   preview request;
# - authStatus applying stale answers: the model treats a sign-in check as
#   atomic (spec/requirements.md, R16), so answers never arrive out of order;
# - jobStarted recording a stale job id: the model's start-job response for
#   a test or dry run is atomic too;
# - entering step 5 without clearing the dry-run result: step 4 never holds
#   one (going back from step 5 always asks first, and resets it).
MUTANTS = [
    ("completion-after-reset",
     "requests: dropRequests(s, [\"test\", \"verify\"]).requests,",
     "requests: s.requests,"),
    ("back3-keeps-checks",
     "if (s.currentStep === 3 && event.to === 2) {",
     "if (false) {"),
    ("stop-not-queued",
     "if (stopQueued) effects.unshift",
     "if (false) effects.unshift"),
    ("failed-send-hides-results",
     "|| (Array.isArray(r.results) && r.results.length > 0)",
     ""),
    ("edit-keeps-preview",
     "state: Object.assign({}, s0, dropRequests(s0, [\"preview\"]), {",
     "state: Object.assign({}, s0, {"),
    ("failed-test-skips-auth",
     "event.ok ? { type: \"saveState\" } : { type: \"checkAuth\" }",
     "{ type: \"saveState\" }"),
    ("upload-keeps-recipients",
     "s.recipientsVersion = null;",
     ""),
    ("next4-skips-dry-run",
     "effects.push({ type: \"startJob\", mode: \"dry_run\", id });",
     ""),
    ("send-test-twice",
     "return s.signedIn && !s.testRunning;",
     "return s.signedIn;"),
    ("back6-after-send",
     "return !s.sendStarted;\n    }\n\n    /** Which part",
     "return true;\n    }\n\n    /** Which part"),
]


@pytest.mark.parametrize(("name", "old", "new"), MUTANTS, ids=[m[0] for m in MUTANTS])
def test_client_replay_catches_mutant(traces, tmp_path, name, old, new):
    source = CORE.read_text(encoding="utf-8")
    assert source.count(old) == 1, f"mutant {name}: the text to replace is not in wizard-core.js once"
    mutant = tmp_path / f"{name}.js"
    mutant.write_text(source.replace(old, new), encoding="utf-8")
    result = replay_client(traces, mutant)
    assert result.returncode != 0, f"the client replay did not notice mutant {name}"


# ---------------------------------------------------------------------------
# Server tier
# ---------------------------------------------------------------------------

from tests.conformance_support import TOTAL, FakeSendMerge, Handle, load_trace  # noqa: E402

from typing import Any  # noqa: E402

class ServerReplay:
    """Replays the server's side of a trace through the Flask routes."""

    def __init__(self, monkeypatch, xlsx: Path) -> None:
        import mail_merge.web.app as web_app
        from mail_merge.auth import NotSignedInError

        self.web_app = web_app
        self.monkeypatch = monkeypatch
        self.xlsx = xlsx
        self.fake = FakeSendMerge()
        self.signed_in = False
        monkeypatch.setattr("mail_merge.api.send_merge", self.fake)

        def silent(_cid: str, _tid: str) -> str:
            if not self.signed_in:
                raise NotSignedInError("Not signed in")
            return "token"

        monkeypatch.setattr("mail_merge.auth.acquire_token_silent", silent)
        self.handles: list[Handle] = []
        self.restart()

    def restart(self) -> None:
        """A fresh process: new job store, new app, no session."""
        from mail_merge.web.app import create_app
        from mail_merge.web.jobs import JobStore

        for h in self.handles:
            h.commands.put("die")
        store = JobStore()
        self.monkeypatch.setattr(self.web_app, "_job_store", store)
        self.monkeypatch.setattr(self.web_app, "_jobs", store.jobs)
        self.monkeypatch.setattr(self.web_app, "_running_send_job", store.running_send)
        self.store = store
        app = create_app(startup_token="t", port=5050)
        app.config["TESTING"] = True
        self.client = app.test_client()
        assert self.client.get("/?token=t").status_code == 302
        self.client.get("/")
        with self.client.session_transaction() as sess:
            sess["client_id"] = "test-client-id"
            self.csrf = sess["csrf_token"]
        self.jobs: dict[int, tuple[str, Handle]] = {}  # model id -> (job id, handle)
        self.offset = 0

    def post(self, url: str, **kw: Any):
        return self.client.post(url, headers={"X-CSRF-Token": self.csrf}, **kw)

    def session_job(self) -> str | None:
        with self.client.session_transaction() as sess:
            return sess.get("job_id")

    def set_session_job(self, job_id: str | None) -> None:
        with self.client.session_transaction() as sess:
            if job_id is None:
                sess.pop("job_id", None)
            else:
                sess["job_id"] = job_id

    def upload(self) -> None:
        with self.xlsx.open("rb") as f:
            resp = self.post("/api/upload-spreadsheet", data={"spreadsheet": (f, "r.xlsx")},
                             content_type="multipart/form-data")
        assert resp.status_code == 200, resp.get_json()

    def start_job(self, model_id: int, mode: str) -> None:
        resp = self.post("/api/start-job", data={
            "mode": mode, "email_column": "email", "subject": "Hi", "body": "Hello",
            "test_email": "me@example.com" if mode == "test_email" else "",
        })
        assert resp.status_code == 200, resp.get_json()
        handle = self.fake.started.get(timeout=5)
        self.handles.append(handle)
        self.jobs[model_id] = (resp.get_json()["job_id"], handle)

    def command(self, model_id: int, cmd: str) -> None:
        """Send a command to a job's runner and wait until it has acted."""
        job_id, handle = self.jobs[model_id]
        job = self.store.jobs.get(job_id)
        handle.commands.put(cmd)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if not handle.acks.empty():
                handle.acks.get()
                return
            if job is None or job.status.value in ("completed", "failed", "stopped"):
                return
            time.sleep(0.001)
        raise AssertionError(f"job {model_id} did not act on {cmd!r}")

    def step(self, m: dict, nxt: dict, action: str, picks: dict) -> None:
        self.signed_in = nxt["signedIn"]
        if action == "serverRestart":
            self.restart()
            self.offset = nxt["nextJobId"]
            return
        if nxt["nextJobId"] > m["nextJobId"]:
            new = [sj["kind"] for sj in nxt["sessionJob"] if sj["id"] == m["nextJobId"]]
            mode = "send" if action == "startSend" else {"Test": "test_email", "Verify": "dry_run"}[new[0]]
            before = self.session_job()
            self.start_job(m["nextJobId"], mode)
            if mode == "send":
                # The session cookie naming the send arrives with the
                # response: startSendResponse.
                self.set_session_job(before)
        if action == "upload":
            self.upload()
        elif action == "newMerge":
            assert self.post("/api/reset").status_code == 200
        elif action == "startSendResponse":
            self.set_session_job(self.jobs[picks["id"]][0])
        elif action in ("completeJob", "completeOrphan"):
            model_id = picks["j"]["id"] if action == "completeJob" else picks["sj"]["id"]
            ok = picks.get("ok", True)
            self.command(model_id, "ok" if ok else "fail")
        elif action in ("sendNext", "sendWithoutToken"):
            self.command(picks["j"]["id"], "next")
        elif action == "finishSend":
            self.command(picks["j"]["id"], "fail" if picks["failed"] else "next")
        elif action in ("reload", "signIn") and (action == "reload" or not picks["desktop"]):
            self.check_reload(nxt)
        # Stop: the page posts it (stopSend, or startSendResponse for a
        # queued Stop; the client tier checks when).
        for j in nxt["sendJob"]:
            before = next((x for x in m["sendJob"] if x["id"] == j["id"]), None)
            if j["stopRequested"] and not (before and before["stopRequested"]) and j["id"] in self.jobs:
                assert self.post(f"/api/job/{self.jobs[j['id']][0]}/stop").status_code == 200

    def check_reload(self, nxt: dict) -> None:
        """/api/config names the send the reloaded model page reconnects to."""
        active = self.client.get("/api/config").get_json()["active_job_id"]
        if not (nxt["step"] == 6 and nxt["sendStarted"]):
            assert active is None, "config reports an active job the model doesn't reconnect to"
            return
        assert active is not None, "the model reconnects to a send that config doesn't report"
        listening = [p["id"] for p in nxt["pending"] if p["handler"] == "Send"]
        if listening:
            assert active == self.jobs[listening[0]][0]

    def compare(self, m: dict, where: str) -> None:
        session_job = self.session_job()
        actual = self.store.abstract(session_job)
        shift = self.offset
        # Creating a job evicts finished ones, so the session can name a
        # finished job the store no longer holds; the model keeps it as done.
        # /api/config treats both alike (only a send is reconnected, and the
        # model's single page can't start a job while its finished send is
        # still the session's).
        evicted = session_job is not None and session_job not in self.store.jobs
        expected = {
            "sessionJob": [{**sj, "id": sj["id"] - shift} for sj in m["sessionJob"]
                           if not (evicted and sj["done"])],
            "sendJob": [
                {"id": j["id"] - shift, "sent": j["sent"], "stopRequested": j["stopRequested"],
                 "status": j["status"]}
                # The model keeps the previous process's send (marked Killed if
                # it was running); a restarted server has no record of it.
                for j in m["sendJob"] if j["id"] >= shift
            ],
            "nextJobId": m["nextJobId"] - shift,
        }
        assert actual == expected, where


@pytest.fixture
def conformance_xlsx(tmp_path) -> Path:
    import openpyxl

    path = tmp_path / "r.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["email"])
    for i in range(TOTAL):
        ws.append([f"r{i}@example.com"])
    wb.save(path)
    return path


def replay_server(traces: Path, monkeypatch, xlsx: Path) -> None:
    files = sorted(traces.glob("*.itf.json"))
    assert files
    for path in files:
        trace = load_trace(path)
        replay = ServerReplay(monkeypatch, xlsx)
        replay.compare(trace[0]["s"], f"{path.name} init")
        for i in range(1, len(trace)):
            actions = " ".join(t["action"] for t in trace[1:i + 1])
            where = f"{path.name} step {i} ({actions})"
            replay.step(trace[i - 1]["s"], trace[i]["s"], trace[i]["action"], trace[i]["picks"])
            replay.compare(trace[i]["s"], where)
        replay.restart()  # release the runners still waiting


def test_server_conformance(traces, monkeypatch, conformance_xlsx):
    replay_server(traces, monkeypatch, conformance_xlsx)


def _ignore_stop(job):
    return False


def _count_nothing(job, result):
    pass


def _session_job_only(self, session_job_id):
    job = self.get(session_job_id)
    return job.id if job and job.mode == "send" else None


def _any_session_job(self, session_job_id):
    running = self.running_send()
    if running:
        return running.id
    job = self.get(session_job_id)
    return job.id if job else None


def _stop_without_flag(self, job_id):
    return job_id in self.jobs


# Bugs seeded into JobStore, each of which the server replay must notice.
SERVER_MUTANTS = {
    "stop-ignored": ("should_stop", staticmethod(_ignore_stop)),
    "sent-not-counted": ("record_sent", staticmethod(_count_nothing)),
    "reload-misses-unnamed-send": ("active_job_id", _session_job_only),
    "reload-resumes-dry-run": ("active_job_id", _any_session_job),
    "stop-not-recorded": ("request_stop", _stop_without_flag),
}


@pytest.mark.parametrize("name", list(SERVER_MUTANTS))
def test_server_replay_catches_mutant(traces, monkeypatch, conformance_xlsx, name):
    from mail_merge.web.jobs import JobStore

    attr, replacement = SERVER_MUTANTS[name]
    monkeypatch.setattr(JobStore, attr, replacement)
    with pytest.raises(AssertionError):
        replay_server(traces, monkeypatch, conformance_xlsx)
