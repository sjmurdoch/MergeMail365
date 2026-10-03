# Formal model of the web UI wizard (Quint)

## Current status (2026-10-03)

Steps 1, 2, 2b and 2c are done, and so is a second round of web UI modelling (bugs 10–15, see "Round 2: awaits, failed sends and restarts"). Step 3 (re-architecting the web UI so the model maps onto it, revised for the richer model) is next, then steps 4 and 5. Nothing is in progress.

### Bugs fixed

All nine were found by the model or while modelling, reproduced by tests that failed before the fix, and fixed. Details under "Bugs found".

| # | Bug | Fix commit | Regression tests |
|---|---|---|---|
| 1 | Test email finishing after Back + edit marks the edited content as tested | `a456535` | `test_late_test_email_does_not_pass_edited_content` |
| 2 | Old dry run finishing during a newer one enables Next on step 5 | `a456535` | `test_late_dry_run_does_not_pass_edited_content` |
| 5 | Re-sending a test leaves Next enabled while it runs | `a456535` | `test_resending_test_disables_next` |
| 6 | Back on step 6 stays disabled after New merge | `f58faca` | `test_back_enabled_on_step6_after_new_merge` |
| 3 | Reload after a test email or dry run jumps to the Send step | `b56e713` | `test_reload_during_test_email_stays_off_send_step`, `test_config_does_not_resume_test_or_dry_run` |
| 4 | Reload after a finished job hangs on "Sending…" | `b56e713` | `test_reload_after_test_email_stays_off_send_step`, `test_reload_after_send_shows_results`, `test_events_end_for_finished_job_on_reconnect` |
| 7 | "Stop sending" does nothing: `job.stop_requested` is set but never read | `5c0c4de` | `test_stop_ends_send_early`, `TestShouldStop` (sender, API) |
| 8 | A signed-out user reaches step 4 (and 6) with no way to sign in there, and the send buttons stay enabled | step 2c commit | `TestSignInGate` (`test_web_e2e_workflow.py`) |
| 9 | A signed-out web job falls into the CLI device-code flow and blocks | `b491f78` | `test_test_email_when_signed_out_fails_at_once` (the inverted characterisation test), `test_send_when_token_lost_fails_at_once`, `TestAcquireTokenSilent` |
| 10 | Back, an edit or a re-upload while the recipient preview loads is overridden: the page jumps to step 3 with a list for the old content | `5aa1f52` | `test_back_while_preview_loads_stays_on_step1`, `test_edit_while_preview_loads_stays_on_step2` |
| 11 | A reload before the start-job response arrives leaves the send running unseen (the session cookie naming it never arrived) | `5aa1f52` | `test_config_resumes_running_send_the_session_does_not_name`, `test_second_send_refused_while_one_runs` |
| 12 | "Stop sending" pressed before the start-job response goes to the dry run's job | `5aa1f52` | `test_stop_before_start_response_reaches_the_send` |
| 13 | A send that fails part-way keeps no results; the page shows only the error | `5aa1f52` | `test_failed_send_keeps_emails_already_sent`, `test_failed_send_lists_emails_already_sent`, `TestSendAborted` |
| 14 | A second send starts with the first send's progress text | `5aa1f52` | `test_second_send_starts_with_fresh_progress` |
| 15 | New merge keeps the BCC To address | `5aa1f52` | `test_new_merge_clears_bcc_to` |
| — | The preview ignores non-ASCII placeholder names that the email substitutes (not a model bug: a regex difference) | `8bfb88c` | `test_render_template_matches_server` |

Playwright regressions are in `tests/test_web_e2e_workflow.py`; Flask ones in `tests/test_web.py` (`TestJobs`).

### Bugs remaining

| Bug | Found by | Status | Plan step |
|---|---|---|---|
| A server restart (app quit or crash) mid-send loses the record of which emails went out | Round 2 model (`spec/requirements.md`, R15; witness `restartLostSend`) | By design of the in-memory job store; needs a send log on disk | Not planned yet |
| CLI: Ctrl-C or an error mid-send writes no CSV, so `--resume` re-sends emails already sent | Commit-history review (2026-10-03), reproduced with a script | Not modelled (the model covers the web UI only); `SendAborted` now carries the partial results, so the CLI could write them | Not planned yet |

Possible link, unverified: the 0.4.1 changelog entry describes a Windows report that "sending a test email sometimes did nothing for several minutes until the user clicked Back". A test email waiting in the device-code flow (silent token acquisition failing, so the job blocks) would look like that. Bug 9 is now fixed; if the report recurs, the stall logs will show whether it was something else.

Decided, not a bug: the test email and dry run are enforced in the browser only (2026-10-02).

Decided: steps 4 and 6 can be entered signed out, because they offer sign-in themselves (`spec/requirements.md`, R2). This replaces the planned `step4NeedsSignIn`.

### Next actions

1. Step 3: re-architect the web UI so the model maps onto it (client core with one event per model action, `render()` from selectors, request ids, a server `JobStore`, abstraction functions), and split the spec into modules. Revised plan below.
2. Step 4: conformance, replaying `quint run --mbt` traces in client, server and end-to-end tiers.
3. Decide whether to persist send results (R15) and fix CLI resume after an interrupted run (step 5).

### Resuming: how to run the model

Quint is not installed in the repo yet (a pinned `spec/package.json` is part of step 4). Use Quint 0.32.0; 0.33.0 (2026-09-28) is out of the 7-day cooldown from 2026-10-05, so check its changelog before bumping.

```sh
# Type check and scenario tests (no Java needed; the TypeScript backend avoids downloading the Rust evaluator)
npx -y @informalsystems/quint@0.32.0 typecheck spec/wizard.qnt
npx -y @informalsystems/quint@0.32.0 test spec/wizard.qnt --main=buggy --max-samples=1 --backend=typescript
npx -y @informalsystems/quint@0.32.0 test spec/wizard.qnt --main=fixed --max-samples=1 --backend=typescript

# Bounded model checking (Apalache, needs Java); several minutes per invariant.
# check.sh takes a single executable, so install Quint into a directory first.
npm install --prefix "$TMPDIR/quint" @informalsystems/quint@0.32.0
JAVA_HOME=/opt/homebrew/opt/openjdk PATH="/opt/homebrew/opt/openjdk/bin:$PATH" \
  spec/check.sh --quint "$TMPDIR/quint/node_modules/.bin/quint" buggy
```

`spec/check.sh --all fixed` checks `allInvariants` in one run, which takes about as long as a single invariant; use it to confirm `fixed`, and the per-invariant run for `buggy`, where each violation needs its own trace.

Expected results: `fixed` holds every invariant; `buggy` violates ten of the 14 at 16 steps (see the table under "Steps 2b and 2c results"). All 15 scenario tests pass in both variants.

Running in a Claude Code cloud container (Linux, 4 cores, Java 21 and Node 22 preinstalled) needed:

- uv: the preinstalled uv (0.8.17) can't parse `exclude-newer = "7 days"` and silently re-resolved `uv.lock`, pulling Werkzeug 3.1.9, which fails two attachment tests. Install the version CI pins (`pip install --user uv==0.12.18`) and use `uv sync --locked --all-extras`.
- Playwright: the container's Chromium is older than the one pytest-playwright 1.63 expects, and `playwright install` is not allowed. Linking the expected headless-shell path to it works: `ln -s /opt/pw-browsers/chromium-1194/chrome-linux/chrome /opt/pw-browsers/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell`. One paste test was timing-sensitive under load.
- Apalache: `quint verify` downloads it into `$QUINT_HOME` without help. To run checks in parallel, start extra servers (`$QUINT_HOME/apalache-dist-0.56.1/apalache/bin/apalache-mc server --port=8823`) and pass `--server-endpoint=localhost:8823` to `quint verify`; `check.sh` always uses the default port. Run checks against a copy of the spec if you are still editing it: each `quint verify` reads the file afresh.
- Biome: `npm install --prefix <dir> @biomejs/biome@2.5.14` (the CI pin).

Running under the Claude Code sandbox on macOS needed these workarounds:

- npm's default cache had root-owned files and wasn't writable: set `npm_config_cache` to a directory under `$TMPDIR`.
- Set `QUINT_HOME` under `$TMPDIR`. Quint's own Apalache download produced an empty directory; download `https://github.com/apalache-mc/apalache/releases/download/v0.56.1/apalache.tgz` with curl and unpack it into `$QUINT_HOME/apalache-dist-0.56.1/`.
- The Apalache launcher's `mktemp -d -t` uses the macOS per-user temp folder, which the sandbox blocks: edit line 56 of `apalache/bin/apalache-mc` to `mktemp -d "${TMPDIR}/SANYXXXXXXXXXX"`.
- Apalache listens on local port 8822, so `quint verify` must run outside the sandbox (or with `sandbox.network.allowLocalBinding: true`).
- `uv run` needs to run outside the sandbox (its cache in `~/.cache/uv` isn't writable), as do the Playwright tests.
- `/usr/bin/java` is Apple's stub and comes first on the sandbox's `PATH`; use Homebrew's OpenJDK as above.

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

Found outside the model while fixing: **"Stop sending" does nothing** (bug 7). `/api/job/<id>/stop` sets `job.stop_requested`, but neither `send_merge()` nor `sender.py` reads it, so the send runs to completion. Fixed in step 2b.

Reported by the user (2026-10-03): **a signed-out user can go on to the Test step** (bug 8). `goToStep(4)` only calls `checkAuthForStep4()`, which refreshes the auth display; nothing gates the step, the "Send test email" button or the send on being signed in, and the only sign-in button is on step 1. Fixed in step 2c.

Found while checking that report, confirmed by `test_test_email_when_signed_out_waits_in_device_flow` in `tests/test_web.py`: **a signed-out web job falls into the CLI device-code flow.** The job's `token_provider` calls `auth.acquire_token()`, which falls back to `initiate_device_flow()` when the cache has no account. The device-code prompt (URL and code) is posted to the test log and the job thread blocks in `acquire_token_by_device_flow()` until the code is used or expires (Entra device codes typically last 15 minutes), with the job shown as running. A user who notices the code can sign in this way, so it is an undesigned second sign-in path rather than a hard failure. The same applies to a real send. Bug 9; fixed in step 2c, which inverted the test.

## Why the model missed "Stop sending", and how the plan closes the gap

The checker can only find bugs in behaviour the model describes. Stop was missed for three separate reasons, each of which would hide other bugs too:

1. **Missing action.** The model has no Stop action. Nothing checked that every control in the UI has a counterpart in the model, so the gap was invisible. Similar risk: any button, event handler or route added without a model action (Prev/Next on the preview, send mode toggle, sheet change, sign-in/out, Test connection).
2. **Server side too abstract.** A send is one opaque job that completes nondeterministically. With no count of emails sent and no stop flag, "stop has no effect" and "stop works" are the same behaviour in the model. Similar risk: anything inside `send_merge()` or the job thread that the UI relies on (progress reporting, partial failure, results after stop, retry and throttling as seen by the UI).
3. **Modelled from intent, not code.** Even with a Stop action, the natural way to write it ("stop sets a flag, the job ends as stopped") encodes the intended behaviour, and every check passes. The bug only appears if the action's guards and effects are copied from what the code does: the send loop's guard never reads `stop_requested`. Similar risk: any action written from documentation or memory rather than the handler.

The changes below address these in turn: step 2b makes the model complete and code-faithful, and step 4 checks it against the real code, which catches intent-vs-code mistakes that careful modelling misses.

## Why the model missed the signed-out Test step

Two reasons. The first is reason 2 again: sign-in is not in the model at all (step 1 planned a `signedIn` variable, but it was dropped and auth deferred to step 5), so a test email failing for lack of sign-in is folded into "the job may fail". The second is new:

4. **Missing requirement.** Even with sign-in modelled, no invariant says the state is wrong. All current invariants are safety properties of the form "nothing false is claimed or sent", and entering step 4 signed out breaks none of them: the test fails, Next stays disabled, nothing bad is sent. The bug is a dead end, a step the user can enter but never complete, and nobody had written down "don't let the user into a step they cannot finish". Stop had an intended behaviour the code fell short of; this requirement was never stated anywhere, so the checker had nothing to check against.

The general property ("from every reachable state there is still a way to finish") is a possibility property that LTL, and so `quint verify --temporal`, cannot express. Step 2c therefore approximates it three ways: an explicit requirements list turned into invariants, a computed "can make progress" invariant, and witnesses that flag suspicious states for review.

## Step 1 results

- `spec/wizard.qnt`: one parameterised module, instantiated as `buggy` (code as of `fb28c33`) and `fixed`. State is a single record so actions use `{ ...s, field: v }`; ghost fields record what the server actually tested, dry-ran and sent.
- `spec/check.sh buggy|fixed`: runs `quint verify` (Apalache, bounded, default 16 steps) once per invariant. `buggy` violates `noUntestedSend`, `next4Honest`, `buttonsMatchFlags`, `sendScreenHonest` and `sendScreenNotStuck`; `next5Honest` and `back6Usable` hold up to 16 steps because their counterexamples are longer.
- Scenario tests (`quint test --main=buggy|fixed --max-samples=1`) replay all six bugs plus a happy path; each asserts the invariant fails in `buggy` and holds in `fixed`.
- Random simulation (`quint run`) missed bug 1 in 20,000 traces. The counterexamples need specific interleavings, so exhaustive checking (Apalache) and targeted scenarios are what make this useful; simulation is a smoke test only.

Environment notes:

- Quint's default `run`/`test` backend downloads a Rust evaluator from GitHub; `--backend=typescript` avoids that.
- `quint verify` downloads Apalache 0.56.1 (released 2026-03-26) into `$QUINT_HOME` (default `~/.quint`). Apalache runs as a gRPC server on local port 8822, so it needs local port binding; under the Claude Code sandbox that requires `sandbox.network.allowLocalBinding: true`. The Apalache launcher's `mktemp -t` uses the macOS per-user temp folder, which the sandbox also blocks.
- Homebrew's OpenJDK must come before `/usr/bin` on `PATH` (or set `JAVA_HOME`); `/usr/bin/java` is Apple's stub.

## Steps 2b and 2c results

Model (`spec/wizard.qnt`, now about 700 lines; still one module):

- **Send loop and Stop.** A send is a `SendJob` record (`sent`, `stopRequested`, `status`) over `TOTAL = 3` recipients. `sendNext` is one loop iteration, `finishSend` the job thread ending, `stopSend` the button. Ghosts `sentAfterStop` and `stopEarly`. Invariants `stopHonoured` and `stoppedReported`. `buggy` transcribes the loop as it was (no stop check, and the job can only end as Completed or Failed).
- **Auth.** `signedIn` (the token cache) is separate from `authShown` (what the page last fetched), so the model can express a stale display. Actions `signIn(desktop)` (browser mode reloads the page), `signOut`, `tokenExpires` (any time, including mid-step and mid-send), `sendWithoutToken`; test-job completion consults `signedIn`. Ghost `interactiveAuthInJob`. Invariants `testNeedsSignIn`, `sendNeedsSignIn`, `noInteractiveAuthInJob` and `canProgress`. The guards `signInOffered`, `sendTestEnabled` and `doSendEnabled` are shared by the actions and the invariants, so the dead-end check can't drift from them. Sign-in polling (`signInPending`) is folded into `signIn`: only the successful outcome is modelled, because a failed or cancelled sign-in leaves the state unchanged.
- **Code-faithful actions.** Every action in `step` has a comment naming the code it transcribes; `tests/test_spec_coverage.py` fails without one.
- **Coverage inventory.** `spec/coverage.toml` lists all 70 entry points (inline handlers, listeners, EventSource callbacks, timers, routes), each mapped to actions or excluded with a reason. The test also fails on a listener the extractor can't key, a stale entry, an unknown action, or an action in `step` that no entry point or `[environment]` entry reaches.
- **Requirements.** `spec/requirements.md`, R1 to R10; the test checks every named check exists, every invariant has a requirement, and `check.sh` runs every invariant.
- **Scenarios.** 15 in each variant, including one (`remainingActionsTest`) that reaches the actions no other scenario takes, as the vacuity check. `completeOrphan` is only reachable in `fixed`, because the buggy reload reattaches every unfinished job.
- **Witnesses** (`quint run --witnesses`, random simulation, 5,000 traces of 25 steps): `staleSignIn` 180, `orphanJob` 88, `partialFailedSend` 0 (reached by a scenario instead). See `spec/requirements.md`.

Deviations from the plan:

- `step4NeedsSignIn` was dropped: steps 4 and 6 offer sign-in themselves instead of refusing entry (R2).
- `progressMonotone` was not added (R10): the progress bar is display only and a reload legitimately resets it.
- `stopHonoured` is `sentAfterStop == 0`, stricter than the planned `<= 1`: `sendNext` is atomic, so an email already being sent when Stop is pressed counts as sent before it.
- The Stop liveness property (`--temporal`) was not tried; `stoppedReported` and the scenario tests cover the stop path, and `sendScreenNotStuck` covers the page.
- The plan's `canProgress` counted "go back" as a fixing action, which would make it hold trivially wherever Back is enabled. It now requires that steps 4 and 6 can be finished from the step itself; a failed dry run on step 5 is fixed upstream by design.

Model checking (Apalache, 16 steps, on a 4-core cloud container; about 3 to 8 minutes per invariant, and `--all` about 30 to 40 minutes):

- Step 2b model, `fixed`: `allInvariants` holds (29 min).
- Step 2c model, `fixed`: `allInvariants` holds (40 min).
- Step 2c model, `buggy`, per invariant:

| Invariant | Result | Shortest trace found |
|---|---|---|
| `noUntestedSend` | holds at 16, violated at 17 | `init upload signIn next1 next2 next3 sendTestEmail back4 back3 edit next2 next3 complete next4 complete next5 typeSend startSend` |
| `next4Honest` | violated | `init signIn upload next1 next2 next3 sendTestEmail back4 back3 edit next2 complete next3` |
| `next5Honest` | holds at 16 | scenario test only |
| `buttonsMatchFlags` | violated | `init upload signIn next1 next2 next3 sendTestEmail complete sendTestEmail` |
| `back6Usable` | holds at 16 | scenario test only |
| `sendScreenHonest` | violated | `init upload next1 next2 next3 sendTestEmail reload` |
| `sendScreenNotStuck` | violated | `init upload next1 next2 next3 sendTestEmail complete reload` |
| `stepNeedsData` | holds | (no bug) |
| `stopHonoured` | violated | `init upload signIn next1 next2 next3 sendTestEmail complete next4 complete next5 typeSend startSend stopSend sendNext` |
| `stoppedReported` | holds at 16 | scenario test only (needs a stop and three more emails) |
| `testNeedsSignIn` | violated | `init upload next1 next2 next3` |
| `sendNeedsSignIn` | violated | `init signIn upload next1 next2 next3 sendTestEmail back4 complete tokenExpires next3 next4 complete next5` |
| `noInteractiveAuthInJob` | violated | `init upload next1 next2 next3 sendTestEmail complete` |
| `canProgress` | violated | `init upload next1 next2 next3` |

`noUntestedSend` needed 16 steps before; starting signed out costs a `signIn` step, so its counterexample now needs 17.

Found while modelling, not fixed: a send that fails part-way keeps no results (R9).

## Round 2: awaits, failed sends and restarts

A review of the commit history for bug classes the model could catch but didn't found five that apply to the web UI:

1. **Clicks during an `await`.** The model treated every handler as atomic. `goToStep(3)` awaits `loadPreview()` and then sets the step wherever the page is; past instance `d8ea08c` (overlapping sign-in polls).
2. **Landing on a step whose entry action didn't run.** `canProgress` skipped step 5; past instances `c15715b`, `4f20d61`.
3. **What the page shows differs from what is sent.** The single `version` hid it; past instances `ea56ba1`, `a120b43`.
4. **New merge leaving state behind.** Hidden by `version + 1`; past instances `4f20d61`, `1cdad8c`, `4f1b9bb`.
5. **Server or session state disappearing.** The model assumed the session and job registry live forever; past instance `f21dea4`.

Changes to the model:

- `ROUND` replaces `FIXED`: `buggy` (0), `partial` (1, the code before this round) and `fixed` (2). Round 2 bugs are checked against `partial`, because the round 1 bugs in `buggy` can mask them: there, a reload before the start-job response reattaches the page to the finished dry run, so the unseen send never shows.
- Awaiting handlers whose answer changes the page are split into request and response actions: `next2`/`previewResponse` and `startSend`/`startSendResponse`. Splitting `startSend` also exposed bug 12 (Stop during the wait).
- New state: `recipientsVersion`, `previewGen`, `verifyShown`, `resultsShown`, `progressJob`, `bccToMerge` (with ghost `mergeId`), the pending requests, and `serverRestart`.
- New invariants `noStepJump`, `previewHonest`, `runningSendVisible`, `noConcurrentSends`, `failedSendReported`, `progressHonest`, `newMergeClears`; `canProgress` now covers step 5, `stopHonoured` covers an early Stop, and `sendScreenNotStuck` allows a pending start-job response. 21 invariants, 23 scenarios.
- Mapping the model's `edit` back to the code showed the filter-chip handler changed the filter text without calling `onTemplateChange()`; it does now.
- New requirements R11–R16 in `spec/requirements.md`.

Not modelled: out-of-order `/auth/status` answers (R16; harmless since bug 9's fix), a second tab (the server now refuses a second concurrent send), and session expiry (a 24-hour sliding window).

Model checking (Apalache, 16 steps), `partial`, per invariant:

| Invariant | Result | Shortest trace found |
|---|---|---|
| `noStepJump` | violated | `init upload next1 next2 back2 previewResponse` |
| `previewHonest` | violated | `init upload next1 next2 edit previewResponse` |
| `runningSendVisible` | violated | `init signIn upload next1 next2 previewResponse next3 sendTestEmail complete next4 complete next5 typeSend startSend reload` |
| `noConcurrentSends` | holds at 16 | needs bug 11 and then a full second test and dry run |
| `failedSendReported` | violated | `init upload next1 next2 previewResponse next3 signIn sendTestEmail complete next4 complete next5 typeSend startSend sendNext finishSend startSendResponse` |
| `progressHonest` | holds at 16 | needs two sends; scenario test only |
| `newMergeClears` | holds at 16 | needs a full send before New merge; scenario test only |
| `stopHonoured` | violated | `init upload next1 next2 previewResponse next3 signIn sendTestEmail complete next4 complete next5 typeSend startSend stopSend` |
| `canProgress` (now with step 5) | holds | (the code already met it) |
| `sendScreenNotStuck` (now allowing a pending response) | holds | (the code already met it) |

`fixed`: `allInvariants` (all 21) holds at 16 steps (58 min). All 23 scenario tests pass in all three variants, and 5,000 random traces of 30 steps found no violation in `fixed`.

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

### Step 2b — Coverage inventory and server-side job model

Done; see "Steps 2b and 2c results" for what was built and where it departs from this plan.

Goal: every user-reachable control and server route is either modelled or deliberately excluded, and the server's job lifecycle is modelled at the granularity the UI depends on.

**Coverage inventory (reason 1).**

- Add `spec/coverage.toml` listing every entry point: each `onclick` in `templates/index.html`, each `addEventListener` and timer (`setInterval`/`setTimeout`) in `app.js`, each Flask route in `web/app.py`, plus page reload and SSE/EventSource events. Each entry maps to a model action name, or to `out_of_scope = "<reason>"`.
- Add `tests/test_spec_coverage.py` (fast, no browser): extract the entry points from those files with regular expressions, and fail if any entry point is missing from `coverage.toml`, or if a listed model action doesn't exist in `spec/wizard.qnt`. A new button or route then fails CI until someone decides how it is modelled.
- First pass will put Stop, preview Prev/Next, send mode toggle, sheet change, sign-in/out and the session timer into the inventory, each either modelled or explicitly excluded.

**Code-faithful actions (reason 3).**

- Each action in `wizard.qnt` gets a comment naming the function(s) it models (`// app.js: stopSend(); web/app.py: api_job_stop`), and its guards and updates are transcribed from that code, including what the code fails to do. The `buggy` variant is the faithful transcription; intended behaviour goes only in `fixed`.
- Review rule: when a handler changes, the action citing it must be re-checked against it in the same commit. `CLAUDE.md` already says to update the model when wizard behaviour changes; extend that to "update the action that cites the function".

**Server-side job model (reason 2).**

- Model a send job as a loop over recipients rather than one completion: `sent: int`, `total: int` (small constant, e.g. 3), `stopRequested: bool`, `status` (`Running | Completed | Failed | Stopped`). One action sends the next email; its guard is transcribed from the `send_all` / `send_bcc_blast` loop (today: `sent < total`, no stop check). A separate action finishes the job.
- Add the Stop action: `stopSend` (UI, enabled while sending) → `api_job_stop` sets `stopRequested`.
- Ghost field `sentAfterStop: int`, incremented when an email is sent while `stopRequested` is true.
- Safety invariants: `stopHonoured` (`sentAfterStop <= 1`, allowing the email already in flight); `stoppedReported` (a job with `stopRequested` that finishes has status `Stopped` and the UI shows partial results); `progressMonotone` (the progress bar's `current` never exceeds `total` and never decreases).
- Liveness, as a temporal property via `quint verify --temporal` (supported by Quint 0.32.0; not yet tried here): `stopRequested` eventually leads to a finished job, under weak fairness of the job's actions.
- Expected result: `buggy` violates `stopHonoured` in about 10 steps (start send, stop, send two more). That counterexample is the acceptance test for this step.

**Vacuity checks.**

- For each action, a witness (`quint run --witnesses`) or a small `quint test` that reaches it, so an action whose guard can never be true (a modelling slip that silently hides behaviour) is caught. `stopSend` must be reachable in both variants.

Then fix Stop: pass a stop check (e.g. a `should_stop` callable) from the job into `send_merge()` and the sender loops, set `JobStatus.STOPPED`, and add a Flask test (start a multi-recipient send with a gated `send_one`, stop, assert fewer than all were sent and status is `stopped`) plus a scenario test in the spec.

### Step 2c — Requirements list, auth model and dead-end checks

Done; see "Steps 2b and 2c results" for what was built and where it departs from this plan.

Goal: invariants come from written requirements, including "can this step succeed?", not only from honesty properties, and auth is modelled. Brought forward from step 5.

**Requirements list (reason 4).**

- Add `spec/requirements.md`: one numbered line per user-facing requirement, each naming the invariant or witness that checks it, or saying why it is unchecked. `tests/test_spec_coverage.py` (step 2b) also checks that every named invariant exists in `wizard.qnt` and is run by `spec/check.sh`.
- For each step, write its gate as two requirements: what must be true to *enter* it, and what must be true for its main action to *succeed*. The entry gate must imply the success conditions that are under the app's control. Initial list:
  - R1: entering step 2 requires a spreadsheet (exists: `stepNeedsData`).
  - R2: entering step 4 requires being signed in (new: `step4NeedsSignIn`, checked on the transition, because a token can expire while on step 4).
  - R3: while on step 4 signed out, "Send test email" is disabled and the sign-in control is shown (new: `testNeedsSignIn`).
  - R4: "Send emails" on step 6 is only enabled while signed in (new: `sendNeedsSignIn`).
  - R5: no web job ever waits for interactive input: a job started without a usable token fails at once with a "sign in" error (new: `noInteractiveAuthInJob`; the job's token provider is modelled from `_make_token_provider` and `acquire_token`, including the device-code fallback).
  - R6: existing honesty invariants (`noUntestedSend`, `next4Honest`, `next5Honest`, `buttonsMatchFlags`, `sendScreenHonest`, `sendScreenNotStuck`, `back6Usable`) and the step 2b stop invariants.
- Adding a step, button or job mode means adding its entry and success requirements to this list in the same change.

**Auth in the model (reason 2).**

- State: `signedIn` (the token cache has an account with a usable token), `authShown` (what the page last displayed from `/auth/status`, which can be stale), `signInPending` (polling during desktop interactive sign-in).
- Actions, each citing its code: `signIn` (browser auth-code flow or desktop `POST /auth/interactive` + polling), `signOut` (`/auth/logout`), `tokenExpires` (any time, including mid-step and mid-send), `checkAuthStatus` (refreshes `authShown`, as `goToStep(4)` and the timer do).
- The token provider in the job model: with `signedIn` the job proceeds; without it, `buggy` follows `acquire_token()` into a `waitingForDeviceCode` job state (which `noInteractiveAuthInJob` rejects), and `fixed` fails the job immediately.
- Expected: `buggy` violates `step4NeedsSignIn` in about 5 steps (upload, next ×3 while signed out) and `noInteractiveAuthInJob` in about 6.

**Dead-end checks (cheap net for unstated requirements).**

- `canProgress`: an invariant computed from the actions' own guards: on every step, either a forward action is enabled and can succeed in the current state, or a fixing action is enabled (sign in, go back, edit). Written as a pure function of the state using the same guard definitions the actions use, so it can't drift from them. A signed-out step 4 with no way to sign in from that step fails it.
- Witnesses (`quint run --witnesses`, supported by Quint 0.32.0; not yet tried here) for states that are allowed but suspicious, reported as counts: on a step whose main action cannot currently succeed; a job running with no page listening; a button enabled whose handler would return early. A non-zero count is reviewed: either it becomes a requirement and an invariant, or it is noted as acceptable in `requirements.md`.

Then fix: gate step 4 (and "Send test email" / "Send emails") on sign-in, offering the sign-in control on step 4; make the web token provider silent-only (raise a "not signed in" error instead of the device-code fallback); add a Playwright regression for the step gate and invert the characterisation test.

### Step 3 — Re-architect the web UI so the model maps onto it

Revised 2026-10-03, after steps 2b, 2c and round 2 made the model much richer than when this step was first written. The original step 3 extracted a reducer from `app.js`; the model now also describes the server's job lifecycle, the send loop, Stop, sign-in and the token cache, in-flight requests, and server restarts, so the re-architecture has to cover both sides.

**Goal.** Each model action corresponds to one named event in the code, and each model state field is computed by an abstraction function from real state, on the client and on the server. Conformance (step 4) can then replay a model trace event by event and compare states, and a mismatch names the action and the field.

**Why the code doesn't map today.** Each gap below is something the model had to paper over, and most of bugs 1–15 lived in one:

| Gap | Where | Model workaround | Bugs that lived there |
|---|---|---|---|
| Button and panel state is set imperatively in many places, apart from the flags it should follow | `app.js`: `disabled` written in 20+ places | Separate `btn*` fields, plus invariants that they agree with the flags | 5, 6, 8, 14 |
| Async handlers change state after an `await`, with ad hoc staleness checks | `goToStep(3)`, `sendTestEmail()`, `startVerify()`, `startSend()`, `stopSend()` | Request/response split per handler; three generation counters | 1, 2, 10, 12 |
| "What gets sent" is the live DOM, with no version of it in the code | form fields read by `buildJobFormData()` | The abstract `version` counter | 1, 2, 10 |
| Server job state is spread through a Flask closure, a module dict, the session cookie and a thread | `web/app.py` `api_start_job._run_job`, `_jobs`, `session["job_id"]`, `api_config` | `sessionJob`, `sendJob`, `nextJobId` assembled by hand | 3, 4, 7, 11, 13 |
| Reload recovery is spread over `loadConfig()`, localStorage and DOM defaults | `loadConfig()`, `DOMContentLoaded` | `reloadState()` re-derives the page | 3, 4, 11 |
| Auth display and gates are separate imperative updates | `checkAuthStatus()`, `updateAuthGates()` | `authShown` separate from `signedIn` | 8 |

**Target architecture.**

1. **Client core, `web/static/wizard-core.js`.** A pure ES module, no DOM and no `fetch`, loadable in Node and the browser:
   - `initialState()` and `reduce(state, event) → { state, effects }`. Events are plain objects named after model actions, including the response events the model already has (`previewResponse`, `startSendResponse`, `jobCompleted`, `authStatus`). Effects are data (`{ type: "fetch", request: ... }`, `{ type: "stream", jobId }`, `{ type: "confirm", ... }`) that the shell performs.
   - Every request carries an id the reducer records in `state.requests`; a response for an id no longer recorded is dropped. This replaces `testGen`, `verifyGen`, `previewGen`, `stopQueued` and the `isCurrent` callbacks with one mechanism, so a new awaiting handler gets staleness handling by construction.
   - `state.contentVersion`, incremented by every content event (upload, sheet change, any compose edit). Jobs, the recipient list and test/dry-run passes record the version they were made for. The model's abstract `version` becomes a real field, and checks like `previewHonest` and `next4Honest` become comparisons the code itself can make.
   - Selectors for everything the UI enables or shows: `canSendTest(state)`, `canDoSend(state)`, `signInOffered(state)`, `nextEnabled(state, step)`. They have the same names and definitions as the model's `pure def`s (`sendTestEnabled`, `doSendEnabled`, `signInOffered`), so a mismatch between them is a one-line diff.
   - `EVENTS`: the exported list of event names.
   - Loaded as a classic script (`window.WizardCore`, and `module.exports` for Node) rather than an ES module; see Progress below.
2. **Client shell, `app.js`.** Wires DOM events to `dispatch(event)`, runs effects (fetch, `EventSource`, `confirm()`, localStorage), and calls `render(state)`. `render()` is the only code that sets `disabled`, `hidden` or panel visibility, and it reads only selectors. Compose fields stay in the DOM; `dispatch` reads them when building a job request and bumps `contentVersion` on input events.
3. **Server job store, `web/jobs.py`.** A `JobStore` class with no Flask and no threads: `start(mode, version, …)`, `record_sent(job_id, result)`, `request_stop(job_id)`, `finish(job_id, status)`, `running_send()`, `config_view(session_job_id)`. `web/app.py` routes become thin adapters, and `_run_job` drives the store. Sending, token acquisition and the clock are injected (`send_one`, `token_provider`, `sleep`), so a test can step the send loop one email at a time, expire the token, or kill the job.
4. **Abstraction functions.** `wizard-core.js` exports `abstractPage(state)` and `jobs.py` exports `abstract_server(store, session)`. Each returns the model's field names, ghost fields excluded. Each function is the one place that says how real state maps to the model: job UUIDs become creation order, `sent` is the number of recorded results, `signedIn` comes from the token-cache adapter.
5. **One event vocabulary.** `tests/test_spec_coverage.py` additionally checks that `EVENTS` and the action names in the model's `step` relation are the same set, apart from listed environment actions. The DOM-listener scan stays, now checking that every listener dispatches a listed event.

**Changes to the model in the same step.**

- Rename actions where needed so each matches its event name one-to-one, including the response events.
- Once `render()` derives buttons from selectors, replace `btnNext4`, `btnNext5`, `btnSendTest`, `btnDoSend`, `btnBack6` and `doneNav` with `pure def`s of the state. `buttonsMatchFlags` and `back6Usable` then hold by construction in `fixed`; keep them, and the `buggy` variant, as the record of bugs 5 and 6.
- Replace the generation counters with request ids, as in the code.
- Split `wizard.qnt` into `page.qnt` (client), `server.qnt` (job store, send loop, token cache) and `wizard.qnt` (composition, invariants, scenarios). At about 950 lines it is past what one file can hold readably.
- Freeze `buggy` and `partial`: they can't be replayed against current code, so they stay as regression documentation, checked by `quint test` but not by conformance. A future bug is transcribed into `fixed` as the code is (conformance will insist), shown to break an invariant, then fixed in code and model together, with a scenario test recording it. Adding a `ROUND` per bug fix doesn't scale.

**Sequencing.** One area at a time, each sub-step green on Biome, mypy and the full test suite, including the 17 Playwright workflow regressions, which pin the behaviour being moved:

1. `wizard-core.js` with the state object, `contentVersion`, selectors and `render()` for steps 4–6 (test, dry run, send, Stop), where most bugs were. `app.js` becomes `<script type="module">`; the `window.*` exports used by inline handlers and the E2E tests stay.
2. Requests and effects: move `sendTestEmail`, `startVerify`, `startSend`, `stopSend` and `streamEvents` onto request ids, and delete the generation counters.
3. Navigation and the recipient preview (`goToStep`, `confirmGoBack`, `loadPreview`).
4. Auth: `authStatus` events, `signInOffered`, the sign-in callouts.
5. Reload and New merge: `init(config)` replaces `loadConfig()`'s state handling; `newMerge` resets state through `initialState()`, so new fields are reset by default.
6. Server: extract `JobStore`, inject the sender, token provider and clock, and add `abstract_server`.
7. Model: renames, derived buttons, request ids, split into modules; rerun `spec/check.sh --all fixed` and the scenario tests.

**Progress.**

- 3.1 done: `web/static/wizard-core.js` holds the workflow state, its reset rules (`resetTestAndVerify`, `newMergeState`) and selectors named after the model's pure defs; `contentVersion` counts content changes; `render()` in `app.js` is the only writer of the step 4–6 buttons and panels (enforced by `TestRenderOwnsControls` in `tests/test_spec_coverage.py`); `tests/js/wizard-core.test.js` runs under `node --test` via `tests/test_wizard_core_js.py`. Deviation: the core is a classic script exposing `window.WizardCore` (and `module.exports` for Node), not an ES module, because the E2E tests drive the page through globals (`state`, `_auth`, `goToStep`, `newMerge`, …) that a module would hide; this also avoids the desktop WebView question until it matters.
- 3.3 done: navigation and the recipient preview go through `reduce()`: events `goTo`, `back` and `previewResponse`, with `WizardCore.ACTIONS` mapping the model's `next1`…`next5`, `back2`…`back6` and `previewResponse` onto them, and effects as data run by `dispatch()`/`runEffect()` in `app.js`. `recipientsVersion` records the content version the preview was fetched for. Entering step 4 now always refreshes the sign-in display, as the model has it (the code skipped it when the test had passed, which can't happen arriving from step 3).
- 3.4 done: the page's sign-in state is `state.signedIn` (the model's `authShown`; `_auth.isSignedIn` is an alias for the tests), selectors read it from state, and each `/auth/status` check is a request answered by an `authStatus` event, so out-of-order answers are dropped (R16 now holds by construction).
- 3.5 done: page load dispatches `configLoaded` (the model's `reload`): the reducer restores the spreadsheet, clears the passed flags and handles reconnecting to a send; `newMerge` is an event whose state comes from `newMergeState()` (so new fields reset by default) with `resetServer` and `clearForm` effects for the server and the DOM.
- 3.6 done: `web/jobs.py` holds the job lifecycle (`JobStore`: create with the one-send rule, run with an injectable runner, Stop, `active_job_id`, `abstract()`); routes in `web/app.py` are thin adapters. `send_merge()` and both send loops take `on_result`, so a job counts emails as they go (the model's `sent`). `tests/test_web_jobs.py` steps a send one email at a time with `SteppedRunner` and checks `abstract()`. The token provider was already injectable (`token_provider`); the clock was not injected, because `mail_merge.sender.time.sleep` is easy to patch.
- 3.2 done for requests: `state.requests` (request ids from `WizardCore.startRequest`) replaces `testGen`, `verifyGen`, `previewGen`, `stopQueued` and the generation comparisons, for the test email, dry run, recipient preview and start-job requests. Effects as data followed in 3.3–3.7.
- 3.7 done, with deviations from the plan above:
  - The rest of the page is events: `contentChanged` and `spreadsheetLoaded` for edits and uploads; `sendTestEmail`, `jobStarted` and `jobCompleted` for steps 4 and 5; `startSend`, `startSendResponse`, `stopSend`, `sendCompleted`, `sendResults` and `sendError` for step 6. `app.js` keeps only the fetches, the SSE stream and the DOM content, as effects. `jobStarted`, `sendResults` and `sendError` are shell-only steps that leave the model's state alone (a Node test checks that every other event is named by a model action).
  - Actions were not renamed. `WizardCore.ACTIONS` maps each model action to its event instead (`finishSend` → `sendCompleted`, `reload` → `configLoaded`, …), which gives conformance the same one-to-one table without churning the model, its scenarios and the requirements.
  - `spec/coverage.toml` `[implementation]` says how each action in `step` is carried out: a `WizardCore` event, a `JobStore` method (`sendNext` → `record_sent`, `finishSend` → `run`, …), render-only (`typeSend`: `render()` reads the SEND input) or environment-only (`tokenExpires`, `serverRestart`). `tests/test_spec_coverage.py` checks that every action is in exactly one place and that the methods exist.
  - `abstractPage(state)` in the core and `JobStore.abstract()` on the server return the model's field names; `[abstraction]` in `coverage.toml` lists the non-ghost fields they leave out and why (the generation counters, DOM-only text, `#btn-next-2`, the token cache), and the coverage test checks the rest are all returned.
  - The generation counters stay in the model. In `fixed` they behave as the code's request ids (a bumped counter is a dropped request); the new `isCurrentJob` def says so, and `abstractPage` reports the current requests rather than counter values. Replacing them with request-id sets would change every scenario for no change in what is checked.
  - The `btn*` fields stay too, as the record of bugs 5, 6 and 14 in `buggy` and `partial`. The new invariant `buttonsDerived` (R17) checks that in `fixed` they equal the functions of state that the code's selectors compute.
  - The module split (`page.qnt`, `server.qnt`) was not done: the model's actions read and write client and server fields together (a start-job request creates the job and the page's pending request in one step), so a split would mostly move cross-module references around. Revisit if conformance (step 4) wants the server tier to import the server half alone.
  - `spec/check.sh --all fixed` holds with 22 invariants (Apalache, 16 steps, about 1 h 43 min on 4 cores).

Exit criteria: every model action is an event (checked by the coverage test); `abstractPage` and `abstract_server` cover every non-ghost model field; nothing outside `render()` writes `disabled` or visibility (a grep check in the coverage test); all existing tests pass.

### Step 4 — Model-based conformance testing

Revised 2026-10-03 for the richer model. Conformance runs against `fixed` only.

**Traces.** `quint run --mbt --out-itf=… --n-traces=N` (checked with Quint 0.32.0) records, for every state, `mbt::actionTaken` (the action name) and `mbt::nondetPicks` (the values chosen for `ok`, `failed`, `accept`, `desktop`, `bcc` and which pending job or request `j`, `r`, `id` was picked). That is enough to replay a trace without inventing anything. Job ids in picks are mapped to real ids by creation order.

**Drivers.** Every action needs a driver in every tier that covers it; a trace action with no driver fails the run, so the inventory and conformance can't drift apart. Environment actions are driven through the injection points from step 3:

| Model action | Driver |
|---|---|
| `completeJob(ok)` | release the held test or dry-run job, succeeding or raising |
| `sendNext` | let the injected `send_one` complete one email |
| `finishSend(failed)` / `sendWithoutToken` | end the loop, or make the token provider raise |
| `previewResponse(ok)` / `startSendResponse` | release the held response (client tier: dispatch the response event) |
| `tokenExpires`, `signIn`, `signOut` | flip the fake token cache; in the browser, answer `/auth/status` as `AuthStub` does |
| `reload` | client tier: `init(config)` from the server's `config_view`; browser: `page.reload()` |
| `serverRestart` | discard the `JobStore` and session and start a fresh client |
| `completeOrphan` | finish a job the page has no callback for |

**Tiers.**

- **Client tier (fast, Node, every push).** `node --test` (built in, no dependencies) replays traces against `reduce()`. Server answers come from the next trace state's server fields, so this tier checks the client alone; it compares `abstractPage(state)` with the trace after every step. Hundreds of traces in seconds.
- **Server tier (fast, pytest, every push).** Replays the server-side actions against `JobStore` and the Flask test client with the injected sender, token provider and clock; compares `abstract_server` after every step. This is the tier that catches a model action written from intent (reason 3): the trace says the job stops, the real loop keeps sending, and the replay fails.
- **End-to-end tier (slow, Playwright, a handful of traces).** Full stack with `JobGate`-style holds, comparing both abstractions and the rendered DOM (button `disabled`, visible panels and callouts) with the selectors.

**Ghost fields** are not compared directly; the fakes record what was really sent and with which `contentVersion`, and the harness recomputes `testedVersions`, `verifiedVersions`, `sentAfterStop` and the rest from that record and checks them against the trace.

**CI.** Add `spec/package.json` and a lockfile pinning Quint 0.32.0 (subject to the supply-chain cooldown). On every push: `quint typecheck`, `quint test` for all three variants, simulation of `fixed` with `allInvariants`, the coverage test, and the client and server conformance tiers. Apalache is too slow for every push (about an hour for `--all fixed` at 16 steps on 4 cores): run it when `spec/` changes, at a lower bound (12 steps) in CI and at 16 steps before merging, or nightly.

**Progress.**

- All three tiers done: client (`tests/js/conformance.test.js`), server (`tests/test_conformance.py`) and browser (`tests/test_conformance_e2e.py`). CI runs them in a new `spec` job with the scenario tests and a short simulation.
- Traces: uniform random traces of `step` almost never pass step 3, because reloads, restarts, Back and failures keep returning the page to the start. A `conformance` module in `wizard.qnt` adds `cStep`: the same actions, but a move that undoes progress is only taken after `GAP` (8) steps that didn't (Back moves don't reset the count, so they can chain). A hundred traces of 120 steps reach steps 5 and 6 thousands of times. Biasing with a `nondet` coin flip does not work: the simulator retries picks until an action is enabled. Half as many uniform traces of `step` (30 steps) are added for resets on steps 1 to 3.
- Client tier: replays each trace through `WizardCore` events, answering effects from the trace (start-job responses at once, `/auth/status` with the model's `signedIn`, a finished send's stream ending at once). After every step it compares `abstractPage()`, the action guards (`sendTestEnabled`, `doSendEnabled`, `signInOffered`) with the selectors, the number of jobs the page started with the model's `nextJobId`, and that every Stop the model records was posted. Versions are compared as a one-to-one correspondence, since the page's counter restarts on reload. `btnBack6` is compared on step 6 only (`buttonsDerived`).
- Server tier: replays the server's side through the Flask routes with a fake `send_merge()` and a fake token cache; the fake send loop takes one command per `sendNext`/`finishSend`/`sendWithoutToken`, and the real `should_stop`, token provider and `on_result` decide what happens. Compares `JobStore.abstract()` after every step and checks `/api/config` on reload. Documented gaps: a finished session job evicted by the next job's creation (the model keeps it as done), and jobs from before a server restart.
- Browser tier: replays traces of `eStep` (`cStep` with a pending preview or start-job response answered before any other action, and no server restart) in Chromium: clicks, typed values, reloads, and job events through the fake `send_merge()`. After each action it polls until `abstractPage()`, the selectors and the rendered controls (button `disabled`, callouts, panels, the results heading) match the model, failing with the differing fields after 5 s. It doesn't hold HTTP responses; those windows are covered by the client tier and `tests/test_web_e2e_workflow.py`. Things the replay had to respect: choosing the file already chosen fires no `change` event (alternate two copies), and a page must be left before clearing cookies or a late response restores the session. Four traces (80 steps) by default, `CONFORMANCE_E2E_TRACES` for more; 15 ran clean three times in a row.
- Mutation tests keep the harness honest: ten bugs seeded into `wizard-core.js`, five into `JobStore` and four into `app.js` (served to the browser through a route) must each make a replay fail. Mutants the replay can't notice by design (a reload already starts from `initialState()`, auth answers and test start-job responses are atomic in the model, step 4 never holds a passed dry run) are listed in `tests/test_conformance.py` with the reason.
- Found so far: `spreadsheetLoaded` kept `recipientsVersion` after a new upload, claiming a fetched recipient list the page no longer had (fixed). One harness bug was fixed along the way: the fake send loop checked Stop after the last email, which the real loop does not.
- Quint is pinned in `spec/package.json` with a lockfile resolved with `npm --before` 7 days back, installed with `npm ci --prefix spec --ignore-scripts`. `npm audit` reports `adm-zip` (high): Quint uses it only to unpack the Apalache release it downloads, which neither CI nor the conformance tests do. `tests/test_conformance.py` uses `spec/node_modules/.bin/quint` (or `QUINT`, or `quint` on `PATH`) and is skipped without it, so the cross-platform test job doesn't need Node packages.

### Step 5 — Extend coverage

Candidates, roughly in order of risk:

- Persisting send results so a restart mid-send can report what went out (R15), and the CLI resume bug after an interrupted run, which would bring the CLI's run/CSV protocol into the model.
- Out-of-order `/auth/status` answers (R16): falls out of step 3's request ids, then needs only invariants.
- A second tab: two pages sharing one session and job store.
- Session expiry (24-hour sliding window) and a lost session cookie.
- Sheet change invalidating column selections, and the HTML/source toggle view state (the last two original candidates; reload with an active send is done).

## Out of scope

Trix and paste sanitisation, CSS/Pico layout, SSE framing, Graph retry logic inside `send_one`, and template rendering (the JS and Python placeholder rules are kept in line by `test_render_template_matches_server`, not by the model). These are either covered by tests or are not state-machine problems. The send loop's control flow (next email, stop, finish, token failure, status) is modelled; anything else excluded must be listed in `spec/coverage.toml` with a reason.

## Risks

- **Model drift.** The coverage test catches missing actions and invariants without requirements; conformance (step 4) catches actions that don't match the code. Until step 4 runs in CI, treat the spec as design documentation backed by scenario tests.
- **Intent leaking into the model.** An action written from what the code should do passes every check. The citation rule helps; the server conformance tier is the real defence.
- **The re-architecture itself introducing bugs.** It touches every handler. Mitigations: one area at a time, the Playwright workflow regressions (one per model bug), the 600+ existing tests, and keeping `window.state` and the legacy aliases until the E2E tests no longer need them.
- **Over-engineering a single-user local tool.** A reducer, an effects runner and a job store are more structure than ~1,900 lines of JS strictly need. The justification is conformance: without one event per model action and an abstraction function, the model can only be checked by hand, which is how bugs 7, 11 and 12 were missed. If step 4 is dropped, steps 3.2 (request ids) and 3.6 (job store) are still worth doing on their own.
- **ES modules in the desktop app.** `<script type="module">` needs a reasonably current WebView2 (Windows) or WKWebView (macOS); both bundled pywebview backends support it, but check the release bundles before relying on it.
- **Second language to maintain.** Splitting the spec into modules (step 3.7) keeps it readable; conformance keeps it honest.
- **Apalache needs Java and is slow.** If it isn't available in CI, rely on simulation, scenarios and conformance, and run Apalache locally on spec changes.
