# Formal model of the web UI wizard (Quint)

Status: steps 1 and 2 done (2026-10-02); step 3 next.

## Motivation

Many past web/desktop UI bugs were reachable states nobody tested: stale test/verify flags after Back navigation, a null recipient list after reload (`4f20d61`), Back from step 5 landing on an inactive step (`c15715b`), a source textarea left visible after toggling HTML mode (`1cdad8c`), and overlapping auth polls (`d8ea08c`). The abstract state space of the wizard is small enough for a model checker to explore exhaustively, which hand-written Playwright tests cannot do.

A model checked in isolation only checks our intentions. The plan therefore ends with conformance testing between the model and the real code, and moves `app.js` toward a shape that maps one-to-one onto the model.

## Bugs found

The first bug was spotted by reading the code while evaluating this idea; the model checker then reproduced it and found the others. Each has a scenario test in `spec/wizard.qnt` replaying the counterexample, and all six were reproduced in the real UI by `tests/test_web_e2e_workflow.py` (every test failed before the fixes) and fixed in step 2.

1. **Stale test completion marks edited content as tested** (`next4Honest`, `noUntestedSend`). On step 4, click "Send test email". While it runs, click Back to step 3, then Back to step 2. `confirmGoBack()` only prompts and resets when a flag is already `true`, so nothing invalidates the in-flight job. When it finishes, the `streamEvents` callback in `sendTestEmail()` sets `state.testPassed = true` and enables `btn-next-4` unconditionally. Edit the body, go forward: step 4 shows as passed, and the edited content can be dry-run and sent without ever being test-sent. Counterexample (16 steps): `upload next1 next2 next3 sendTestEmail back4 back3 edit complete next2 next3 next4 complete next5 typeSend startSend`.
2. **Stale dry-run completion** (`next5Honest`). Leave step 5 while dry run A is in flight, go back, edit, re-test, return to step 5 (starting dry run B). If A completes first it sets `verifyPassed = true` and enables `btn-next-5`, so Send is reachable without a dry run of the current content. Needs more than 16 steps, so only the scenario test covers it.
3. **Reload after any test or dry run jumps to the Send step** (`sendScreenHonest`). `session["job_id"]` is set for every job mode, and `/api/config` reports it as `active_job_id` whenever it is still in `_jobs`, whatever its mode or status (finished jobs are only evicted when a new job starts). `loadConfig()` then shows step 6 in "sending" mode and attaches the send callback to a test/dry-run job.
4. **Reload after a finished job hangs on "Sending"** (`sendScreenNotStuck`). Same path, but the job's event queue was already drained (including the `None` sentinel) by the previous page's SSE stream, so the new stream only gets keepalives. Back is disabled and the done navigation hidden, so there is no way out except New merge, which isn't shown. Applies after a real send too.
5. **Retesting leaves Next enabled while `testPassed` is false** (`buttonsMatchFlags`). `sendTestEmail()` clears `testPassed` but not `btn-next-4`; if the retest fails the button stays enabled and does nothing.
6. **Back on step 6 stays disabled after New merge** (`back6Usable`). `startSend()` disables `btn-back-6`; neither `prepareSend()` nor `newMerge()` re-enables it.

Browser-only enforcement is intended: `/api/start-job` does not check that a test email and dry run passed, and that is a deliberate decision (2026-10-02), not a bug. The checks guard against mistakes made in the wizard, not against a client that bypasses it, which would already hold the startup and CSRF tokens. So the fixes below are all about the browser getting its own state right, which is what the model checks.

Fixes (modelled by the `fixed` variant, where all invariants hold, and implemented in step 2):

- Per-kind generation counters (`state.testGen`, `state.verifyGen`) bumped by `resetTestAndVerify()`, `resetAll()` and when starting a job; `streamEvents()` takes an `isCurrent` guard, so a stale job's log lines and completion are ignored. `resetTestAndVerify()` also re-enables `btn-send-test`.
- `sendTestEmail()` disables `btn-next-4`.
- `prepareSend()` re-enables `btn-back-6`.
- `Job` records its `mode`; `/api/config` only reports send jobs as active. The SSE stream also ends when the job has finished and its queue is empty, so reconnecting to a finished send (or one whose sentinel an old stream took) shows the results.

Found outside the model while fixing: **"Stop sending" does nothing.** `/api/job/<id>/stop` sets `job.stop_requested`, but neither `send_merge()` nor `sender.py` reads it, so the send runs to completion. Not fixed yet.

## Step 1 results

- `spec/wizard.qnt`: one parameterised module, instantiated as `buggy` (code as of `fb28c33`) and `fixed`. State is a single record so actions use `{ ...s, field: v }`; ghost fields record what the server actually tested, dry-ran and sent.
- `spec/check.sh buggy|fixed`: runs `quint verify` (Apalache, bounded, default 16 steps) once per invariant. `buggy` violates `noUntestedSend`, `next4Honest`, `buttonsMatchFlags`, `sendScreenHonest` and `sendScreenNotStuck`; `next5Honest` and `back6Usable` hold up to 16 steps because their counterexamples are longer.
- Scenario tests (`quint test --main=buggy|fixed --max-samples=1`) replay all six bugs plus a happy path; each asserts the invariant fails in `buggy` and holds in `fixed`.
- Random simulation (`quint run`) missed bug 1 in 20,000 traces. The counterexamples need specific interleavings, so exhaustive checking (Apalache) and targeted scenarios are what make this useful; simulation is a smoke test only.

Environment notes:

- Quint's default `run`/`test` backend downloads a Rust evaluator from GitHub; `--backend=typescript` avoids that.
- `quint verify` downloads Apalache 0.56.1 (released 2026-03-26) into `$QUINT_HOME` (default `~/.quint`). Apalache runs as a gRPC server on local port 8822, so it needs local port binding; under the Claude Code sandbox that requires `sandbox.network.allowLocalBinding: true`. The Apalache launcher's `mktemp -t` uses the macOS per-user temp folder, which the sandbox also blocks.
- Homebrew's OpenJDK must come before `/usr/bin` on `PATH` (or set `JAVA_HOME`); `/usr/bin/java` is Apple's stub.

## Tooling

- Quint, pinned to **0.32.0** (released 2026-03-31). 0.33.0 was released 2026-09-28, inside the 7-day supply-chain cooldown; revisit after 2026-10-05 per `docs/upgrade-plan.md`.
- `quint typecheck`, `quint run` (random simulation with invariants), `quint test` (spec unit tests), `quint verify` (bounded model checking via Apalache, needs Java) for exhaustive checks.
- Spec lives in `spec/` at the repo root. Initially run via `npx @informalsystems/quint@0.32.0` (or `spec/check.sh --quint PATH`); step 4 adds a pinned `package.json` + lockfile for CI.

## Steps

### Step 1 — Wizard spec and invariants

Write `spec/wizard.qnt` modelling the workflow layer of `app.js` as it is today (bugs included), so the checker can reproduce known/suspected problems.

State:

- `step` (1..6), `dataLoaded`, `composeVersion` (incremented on any compose edit, which is only possible on step 2)
- `testPassed`, `verifyPassed` (the booleans the code actually uses), plus ghost variables `testedVersion` / `verifiedVersion` recording which content each passing job actually checked
- in-flight jobs: a set of `{kind, version}` records; completion is a separate action that may fire at any time
- `sendStarted`, `sendDone`, `signedIn`
- the UI projection: `btnNext4`, `btnNext5`, `btnDoSend` enabled flags, mirroring the `disabled` assignments in the code
- reload (wipes tier 1 state, keeps session/localStorage) and New merge

Actions mirror the handlers: upload, edit compose, `goToStep(n)`, `confirmGoBack(n)` (with confirm accepted or cancelled), `sendTestEmail`, job completion (success/failure), `startVerify` on entry to step 5, typing SEND, `startSend`, reload, New merge.

Invariants (the UI projection is what users see, so assert on it):

- `NoUntestedSend`: if a send job starts, the current `composeVersion` was test-sent and dry-run.
- `Next4Honest`: `btnNext4` enabled ⇒ a successful test exists for the current content.
- `Next5Honest`: `btnNext5` enabled ⇒ a completed dry run exists for the current content.
- `StepReachable`: `step ≥ 3` ⇒ `dataLoaded`.
- `ButtonsMatchFlags`: the button projection agrees with `testPassed` / `verifyPassed`.

Exit criteria: spec type-checks; the checker finds the stale-completion counterexample; a `fixed` variant passes all invariants under `quint verify`. Done — see "Step 1 results".

### Step 2 — Confirm and fix real bugs

Done.

- Reproduce each counterexample in the real UI with a Playwright (Python) regression test in `tests/test_web_e2e.py`, using a mocked Graph endpoint that delays the test job response.
- Fix in `app.js`: version/generation stamp on job completions; ignore stale ones.
- ~~Add server-side enforcement in `/api/start-job`~~: dropped. Enforcing the test email and dry run in the browser is sufficient (see "Bugs found").
- Update the spec to the fixed design and keep both variants (`buggy` as a regression record) or just the fixed one.

### Step 3 — Restructure `app.js` around a reducer

- Extract the workflow layer into a pure `reduce(state, event) → state` (no DOM, no fetch) with an explicit event list matching the Quint actions, and `render(state)` that sets panel visibility and button `disabled` state.
- Side effects (fetch, SSE, alerts/confirm) stay in thin handlers that dispatch events.
- Keep `window.state` and the legacy aliases for existing E2E tests.
- Biome lint and the existing test suites must stay green after each sub-step; do it incrementally, one event at a time.

### Step 4 — Model-based conformance testing

- `quint run --out-itf` generates traces (ITF JSON) from the spec.
- Fast tier: a Node test harness replays traces against `reduce()` and compares abstract state after each step. Runs in CI on every push.
- Slow tier: a Python Playwright driver replays a small number of traces against the real app (mocked Graph/MSAL, as in `test_web_e2e.py`), reading `window.state` and the DOM button/panel state after each action and comparing with the trace.
- Add `spec/package.json` + lockfile pinning Quint; CI job runs `quint typecheck`, `quint test`, the simulator with invariants, and conformance.

### Step 5 — Extend coverage

Candidates, in order of past bug density: auth (sign-in polling, desktop interactive flow, token expiry during send), reload with an active send job (SSE reconnect), sheet change invalidating column selections, HTML/source toggle view state.

## Out of scope

Trix and paste sanitisation, CSS/Pico layout, template rendering, SSE framing, Graph retry logic. These are either covered by existing tests or are not state-machine problems.

## Risks

- Model drift: mitigated only by step 4. Without it, treat the spec as design documentation.
- Second language to maintain: keep the spec small (target 200–300 lines) and limited to the workflow layer.
- Apalache requires Java; if unavailable in CI, rely on simulation and conformance.
