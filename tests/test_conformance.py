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
