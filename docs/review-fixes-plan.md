# Plan: fixes from the November 2026 review

Written 2026-11-14 after a security, usability and correctness review of v0.6.0 (commit `ec3e8d3`). Finding numbers (F1–F16) are the ones used in the review. **If you are picking this work up, read [Handover](#handover-for-whoever-continues-this-work) first, then [Status](#status).** Parts 1 to 3 are the plan as first written; where the implementation differs, the notes in Status are what was built.

## How to read this plan

Each finding gets a fix and a regression test. Each *class* of finding also gets a guard: a test, lint rule, model change or structural change meant to catch the next bug of that kind, not only this one. The guards are listed first because several fixes depend on them.

Working rules for every step, from `CLAUDE.md`: write the failing test first, make one small change, run `uv run pytest` and `uv run mypy`, then commit. One commit per finding or guard. Playwright tests must be run outside the sandbox. New tools and packages are subject to the 7-day cooldown.

## Decisions needed

These change behaviour users may rely on. The plan assumes the recommended option; say so if you want another.

| # | Question | Decision |
|---|---|---|
| D1 | A `{{…}}` that matches no column: block the send, or warn? | Block, as unresolvable placeholders are blocked today. A stray unbalanced `{{` or `}}` only warns. |
| D2 | `{{ name }}` (spaces inside the braces) is sent literally today. Substitute it? | Yes. It is a behaviour change; note it in the changelog. |
| D3 | HTML mode: escape cell values? | Yes, always. Anyone who put markup in cells on purpose loses it; add a raw form later only if someone asks. |
| D4 | Date cells: what text? | ISO date (`2026-12-01`) when the time is midnight, otherwise `2026-12-01 14:30`. Apply `%` formats. Leave currency and custom formats as the raw number and say so in the preview. |
| D5 | Retries that may duplicate an email (read timeout, 5xx after the request was sent)? | Stop retrying read timeouts; record them as "outcome unknown, may have been delivered". Keep retrying connection errors, 429 and 5xx. |
| D6 | `--host` other than loopback? | Refuse unless `--allow-remote` is also given, and print a warning that the connection is unencrypted. |
| D7 | Token cache location? | Leave it in `~` (`~/.mergemail365-token-cache.json`) so existing sign-ins keep working; only stop touching the directory. |

## Part 1: guards against each class of bug

### G1. Outcome honesty: what the user is told matches what Graph said

Class: F1 (a failed test email shown as sent). The root cause is two notions of success, job status and per-email result, with each caller picking one.

- **Structure.** Give the job one derived answer: `Job.ok` is true only if the job completed *and* every result has `success=True`. `/api/job/<id>/status` returns `ok`, and the page uses it instead of `status === "completed"`. In `send_merge()`, the test-email path logs the failure and raises `SendAborted` with the result, so the CLI, the API and the web job all see a failure the same way.
- **Test: outcome matrix** (`tests/test_outcomes.py`). Parametrised over mode (test email, send, BCC blast) × Graph answer (202, 400, 401 twice, 403, 413, 429 until the cap, 500 until the cap, connection error, read timeout) × interface (API return or exception, CLI exit code and ERROR line, web `/status` `ok`). One table states the expected outcome for each cell; a new mode or interface without a row fails the test.
- **Quint.** See Part 3 (R19, `testPassHonest`).
- **Page tier.** A Node test for `jobCompleted` with a "completed but one failed" status, and a `test_web_e2e_workflow.py` test where the `JobGate` returns a failed result and step 4 must show the failure and keep Next disabled.

### G2. No secrets in logs

Class: F2, F13.

- **Structure.** Remove the header and payload dump in `sender.py`; log recipient, subject length, body size and attachment names and sizes at DEBUG. Add a `RedactingFilter` in `console.py`, attached to the file handler and the browser panel handler, which replaces `Bearer \S+`, JWT-shaped strings (`eyJ…\.…\.…`) and `token=\S+`. The filter is the second line of defence; the first is not logging these values.
- **Test: canary** (`tests/test_log_secrets.py`). Run a full CLI send, a full web send and a web sign-in with file logging on and the root logger at DEBUG, using distinctive canary strings for the access token, the refresh token in the cache, the startup token, the CSRF token and the session cookie value. Assert none appears in the log file, `caplog` or stderr. A second test asserts the email body and attachment bytes are absent.
- **Lint.** Add Ruff (pinned, cooldown applies) with `LOG`, `G` and `S` rule sets, run in the CI `lint` job. This also enforces the logging rules in the global instructions.
- **Files.** Create the log directory 0700 and log files 0600 (see G3).

### G3. The app only touches files it owns, and private files are private from creation

Class: F3, and the non-atomic cache write.

- **Structure.** One helper in `_paths.py`: `write_private(path, text)` creates a temporary file with `os.open(…, 0o600)` in the same directory, writes, and `os.replace()`s it; `private_dir(path)` creates the directory 0700 and only ever chmods a directory under `state_dir()`, `log_dir()` or Windows `data_dir()`, never `Path.home()`. The token cache, `SendLog` and log setup all use it. A corrupt cache file is treated as empty with a WARNING naming the file, instead of raising on every auth call.
- **Test: filesystem footprint** (`tests/test_fs_footprint.py`). With `HOME` set to a temp directory whose mode is 0755, run a CLI send with `--output` and `--log-file`, and a web send with a send log. Afterwards: the home directory's mode is unchanged; every file created is on an allowlist of expected paths; every file holding tokens, addresses or logs is 0600 and its app-owned parent is 0700. Skipped on Windows.
- **Test: atomicity.** `write_private` with a failing write leaves the previous file intact.

### G4. One template grammar, shared by Python and JavaScript

Class: F4, F8, and any preview/send mismatch.

- **Structure.** Define the grammar once: `{{` + any text without braces + `}}`, trimmed, matched case-insensitively against column names. Anything matching the pattern that is not a column is unresolved. Move the JS renderer and placeholder regex out of `app.js` into `wizard-core.js` (or a small `template-core.js`) so Node can test it. `render()` takes an `escape` function: `html.escape` in HTML mode, identity for plain text and always identity for the subject. Columns whose names contain `{` or `}` are reported at upload as unusable in placeholders.
- **Test: shared vectors** (`tests/data/template_vectors.json`). Each vector has a template, columns, a row, the HTML flag, and the expected unresolved list and rendered text. `tests/test_template.py` and `tests/js/template.test.js` both run every vector, so the two implementations cannot drift. Include: `{{ name }}`, `{{First-Name}}`, `{{Price <GBP>}}`, `{{Größe}}`, `{{name}`, `{name}}`, a value containing `{{other}}` (not re-expanded), and values containing `&`, `<`, `"` in both modes.
- **Test: every chip works.** For each column in `SPECIAL_COLUMNS` plus punctuation-heavy names, the text the chip inserts renders to the cell value in Python and JS. This is the property that failed for `{{First-Name}}`.
- **Check after render.** If `{{` or `}}` remains in a rendered subject or body, warn in the preview and the CLI (D1).

### G5. Every input is validated before the first email

Class: F7, F9.

- **Structure.** New `addresses.py` with `parse_addresses(value) -> list[EmailAddress]` using `email.utils.getaddresses` and the same `email-validator` call as the recipient column. Used for CC, BCC, reply-to, `bcc_blast_to` and `test_email`. Numeric options are checked in one place (`batch_size >= 1`, `delay >= 0`, `max_retries >= 0`), with argparse types giving the same messages on the CLI. Attachments are checked in total (base64 size plus body against Graph's request limit), not only one by one.
- **Test: invalid-input table** (`tests/test_input_validation.py`). One row per `send_merge()` parameter with an invalid value and the expected `ValueError`; each case runs with `send=True` under `responses` and asserts zero HTTP requests were made. The test reads `inspect.signature(send_merge)` and fails if a parameter has neither a row nor an entry in an explicit "no validation needed" list, so a new parameter cannot be added without deciding.
- **Web.** `/api/get-recipients` also validates CC, BCC, reply-to and the BCC-mode To address, so step 2 → 3 reports a bad address instead of the test email failing later.

### G6. Routes are protected by default

Class: F10.

- **Structure.** Replace the endpoint-name checks in `_check_auth` and `_check_csrf` with a `@public` decorator that sets an attribute on the view; the middleware reads it. Only `static` and `auth_callback` are public. `auth_login` requires the session. The `/?token=` handler redirects a `127.0.0.1` request to the same URL on `localhost` before setting the session, which fixes the 403 after sign-in from `127.0.0.1`. `auth_login` ignores the `client_id` and `tenant_id` query parameters when they were fixed on the command line, and `_get_client_tenant()` prefers the fixed values over the session.
- **Test: route table** (in `tests/test_web.py`). Iterate over `app.url_map`; for every rule and method, a request with no session must return 403 unless the endpoint is in the test's own allowlist of public endpoints, and every non-GET with a session but no CSRF token must return 403. A new route is covered without anyone remembering to add a test.
- **Test: sign-in from `127.0.0.1`** ends on a working page (the sequence run during the review, as a test).
- **Coverage file.** `spec/coverage.toml` already lists every server entry point; add `access = "session"` or `"public"` to each and have `test_spec_coverage.py` compare it with the decorator.

### G7. Untrusted text cannot become markup

Class: F11.

- **Structure.** Add an `html` tagged-template helper in `app.js` that escapes every interpolation unless wrapped in `raw()`, and convert each `innerHTML` assignment to it (or to `textContent`). Then add a Content Security Policy as a second layer: `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'`. That needs the two inline scripts in `index.html` moved (CSRF token into a `<meta>` tag, the Trix setting into `app.js`) and the `onclick=` attributes replaced by `addEventListener`. Also send `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and `Cache-Control: no-store` on API responses.
- **Test: sink check** (in `tests/test_spec_coverage.py`, which already reads `app.js`). Fail on any `.innerHTML =` or `.innerHTML +=` whose right-hand side is not a string literal or an `html\`…\`` template, and on any `insertAdjacentHTML` or `document.write`.
- **Test: canary payload** (extend the XSS tests in `test_web_e2e.py`). Put `<img src=x onerror="window.__xss=1">` into every string the page receives from elsewhere: tenant ID, `/auth/debug` error and account name, file name, sheet names, column names, cells, invalid-address reasons, Graph error text, job error, interrupted-send records, the `#auth-error=` fragment. Visit every step and assert `window.__xss` is unset and the console has no CSP violations.
- **Test: CSP present** on `/` and that the page works with it (the existing e2e suite, run with a console listener that fails on violations).

### G8. The session cookie stays small

Class: F14.

- **Structure.** Keep session data in server memory, keyed by a random session ID; the signed cookie holds only the ID. Spreadsheet metadata and the MSAL `auth_flow` (which includes the PKCE verifier) move out of the cookie. Nothing is lost by this: the cookie key already changes on every start, so sessions never survived a restart. Update the "Tier 3" description in `CLAUDE.md`.
- **Test.** Upload a sheet with 200 columns of 100-character headers and 50 sheet names; the wizard still works and `Set-Cookie` is under 1 KB. Add an `after_request` hook in the test app fixture that fails any test whose response sets a cookie over 2 KB.

### G9. Model assumptions are written down and pinned

Class: the gap that let F1 through the Quint work. The model's `completeJob(ok)` lets the environment choose `ok`, and the model treats it as "the email was accepted", but the code computed it from the job status. Every invariant about tested content held in the model and was false in the app.

- **Structure.** Add an `[assumptions]` table to `spec/coverage.toml`: one entry per parameter of an `// environment:` action, stating the fact in the code it stands for and the test that pins that fact (for `completeJob.ok`: "Graph accepted every email of the job", pinned by the outcome matrix in G1). `tests/test_spec_coverage.py` fails if an environment action parameter has no entry or names a test that does not exist. Add a short section to `docs/quint-model.md` explaining this.
- **Conformance.** The fake `send_merge()` in `conformance_support.py` currently only completes or raises. Extend it to return failed results, driven by the trace, so the server and browser tiers exercise "completed with failures".

## Part 2: fixes, in order

### Phase A: the three urgent fixes (release as 0.6.1)

| Step | Finding | Change | Guard |
|---|---|---|---|
| A1 | F1 | `Job.ok`; `/status` returns it; `runJob` uses it; test-email path in `api.py` logs the failure and raises; CLI prints the Graph error. | G1, G9, R19 |
| A2 | F2, F13 | Remove the header and payload log; add `RedactingFilter`; canary test. | G2 |
| A3 | F3 | `write_private` and `private_dir`; token cache, send log and log files use them; corrupt cache handled. | G3 |

After A3: run the full suite, `quint test`, and `spec/check.sh fixed` for the invariants touched by A1 (locally, not in CI). Update `CHANGELOG.md`. The changelog entry for A2 should tell users of 0.6.0 and earlier bundles that their log files may contain access tokens (expired within about an hour of being written) and email content, and where to delete them.

### Phase B: web security hardening

| Step | Finding | Change | Guard |
|---|---|---|---|
| B1 | F10 | `@public` decorator; `auth_login` needs the session; `127.0.0.1` redirect at token check; fixed client ID wins; README note corrected. | G6 |
| B2 | F14 | Server-side session store. | G8 |
| B3 | F11 | `html` helper, convert sinks, then CSP and headers. Do the helper and the sink test first, CSP second, since CSP needs the inline handlers removed. | G7 |
| B4 | F12 | `--allow-remote` (D6); bind the port probe to the host actually served. | A CLI test for refusal and for the warning. |
| B5 | Robustness seen in passing | `MAX_CONTENT_LENGTH`; `request.get_json(silent=True)` with a 400 on `/api/state` and `/api/change-sheet`; `running_send()` under the store lock; errors in `auth_login` redirect to `#auth-error=` instead of a 500; attachment temp directories removed when their job ends. | Cases added to `test_web_robustness.py`. |

### Phase C: what goes into the email (release as 0.7.0, behaviour changes)

| Step | Finding | Change | Guard |
|---|---|---|---|
| C1 | F4 | New grammar in `template.py` and the shared JS renderer; unresolved and leftover-brace checks (D1, D2). | G4 |
| C2 | F8 | Escaping in HTML mode in both renderers (D3). | G4 vectors |
| C3 | F6 | `_cell_str` handles `datetime`, `date`, `time`, `%` formats and large integers (D4); preview and send already share this function, so the preview shows the result. Confirm that openpyxl's read-only cells expose `number_format` before relying on it. | A vectors test for cell types; a note in the preview when a column holds formatted numbers. |
| C4 | F7 | `addresses.py`; web validation at step 2 → 3. | G5 |
| C5 | F9 (part) | Numeric option checks; total attachment size. | G5 |

`PASTE_EXPECTED` should not change in this phase. If it does, treat it as a behaviour change, as `CLAUDE.md` says.

### Phase D: the send engine

| Step | Finding | Change | Guard |
|---|---|---|---|
| D1 | F5 | Resume by occurrence: for each address, skip as many rows as there are recorded successes for it, instead of skipping all rows with that address. The merged report keeps one line per row. `read_csv` strips the formula guard tab. | `TestInterruptedSend` gains a duplicate-address case; a round-trip test `read_csv(write_csv(x)) == x` over addresses starting with `+`, `-`, `=`, `@`. |
| D2 | F9 (part) | Retry policy per D5; "outcome unknown" is a distinct result shown in the summary, the CSV and the web results table. | Rows in the outcome matrix (G1). |

### Phase E: usability

| Step | Finding | Change |
|---|---|---|
| E1 | F15 | The CLI logs "Sending as <account>" and the confirmation prompt has a From line; add `--sign-out`. |
| E2 | F16 | Case-insensitive `.xlsx` check. |
| E3 | F16 | `/status` returns each result's `status_code`; `categoriseError` uses the code, not a regex over the text. |
| E4 | F16 | `--log-level` uses `choices`; add `-v`; the CLI logs unexpected exceptions with the traceback at DEBUG. |
| E5 | F16 | Hidden rows: openpyxl's read-only mode cannot see them. Document it in the README and tutorial; revisit only if a user is caught by it. |

Each has a plain unit or CLI test; no class guard is needed.

### Phase F: documents

Update `CLAUDE.md` (session tiers, auth routes, logging, template grammar, new test files), `README.md` (the `127.0.0.1` note, `--allow-remote`, date formatting, placeholders), `docs/tutorial.md`, `CHANGELOG.md`, `spec/requirements.md`, `spec/coverage.toml` and `docs/quint-model.md`. Do this in the same commit as each change where the spec coverage test requires it, and the rest at the end of each phase.

### Phase G: is it safe to update the dependencies and vendored code?

Added 2026-11-15 at the user's request. The question comes first; updating follows only for what is found safe. Detail is in the Handover section.

| Step | What | Result |
|---|---|---|
| G1 | List everything pinned and what newer version exists: Python packages (`uv.lock`), vendored Trix and Pico CSS, Quint (`spec/package.json`), GitHub Actions, the uv and Biome versions pinned in the workflows, Playwright's browser, Python itself. | An inventory table in this file: current, latest, latest allowed by the 7-day cooldown, release date. |
| G2 | For each, decide whether it is safe: read the changelog between the two versions, check for security advisories against the current version, and name the tests that would notice a regression. Where this branch leans on a dependency's internals, say so. | A verdict per item (update, hold, or needs a test first) with the reason. |
| G3 | Report to the user and ask which to update. | The user's decision, recorded. |
| G4 | Update what was agreed, one group per commit, full suite before each, in the order used in `docs/upgrade-plan.md`. | `uv.lock` and vendored files updated; `docs/upgrade-plan.md` brought up to date. |

### Phase H: end-to-end test of the released build on a real system

Added 2026-11-15 at the user's request. Last, after every other phase. The thing tested is the bundle that `.github/workflows/release.yml` builds and attaches to a GitHub release, downloaded from that release, not a local build. Detail is in the Handover section.

| Step | What | Result |
|---|---|---|
| H1 | Get the branch through CI (`test.yml`) on Linux, macOS and Windows. It has never run there. | A green run, or fixes. |
| H2 | Build a release candidate with the release workflow (a pre-release tag), with the user's approval: this pushes, tags and publishes. | `MergeMail365-macOS.zip` and `MergeMail365-Windows.zip` attached to a pre-release. |
| H3 | Download each bundle from the release onto a real machine of that kind and work through the checklist with a real Microsoft 365 account, sending to mailboxes the user controls. | The checklist filled in for macOS and for Windows. |
| H4 | Fix what fails, rebuild as the next candidate, repeat H3 for what changed. | Every item passing, or the exceptions listed and accepted by the user. |
| H5 | Hand back to the user for the real release. | The user's decision. |

## Part 3: changes to the Quint model

Only one finding is a workflow bug of the kind the model exists for. The others are about data handling, files and HTTP access, where a table-driven test is cheaper and checks the real code; adding them to the model would lengthen Apalache runs (each extra step costs about 2½ times the last) for no extra assurance.

### R19: step 4 passes only if the test email was accepted

- **Model.** Add a third round (`ROUND = 3`, `FIXED3`). `completeJob` takes two environment choices instead of one: whether the job ran to the end, and whether Graph accepted the email. Before `FIXED3` the page's verdict is the first alone, as in the code today; with `FIXED3` it is both. `testedVersions` gains the version only when the email was accepted.
- **Invariant.** `testPassHonest`: `testPassed` implies the current version is in `testedVersions`. `next4Honest` and `noUntestedSend` already depend on `testedVersions`, so they become counterexamples in `buggy`, `partial` and round 2, which is the evidence that the model now sees the bug.
- **Scenario.** `rejectedTestEmailTest`: sign in, reach step 4, send a test, complete with "ran, not accepted"; expect `testPassed` false, Next disabled, Retry shown.
- **Files.** Update the action's `// app.js:` citation, `spec/coverage.toml` (`[implementation]`, `[assumptions]`), `spec/requirements.md` (R19), `spec/check.sh` (add the invariant) and `docs/quint-model.md`.
- **Conformance.** Map the new parameter to the fake `send_merge()` result (G9). Add a mutation test that puts back `ok = status === "completed"` in `wizard-core.js` and `Job.ok` in `JobStore`; each replay must notice.
- **Dry run.** Check whether `verifyPassed` has the same shape. A dry run makes no Graph call, so its results are always successes today; pin that with an entry in `[assumptions]` so a later change (for example, validating addresses during the dry run) cannot silently break it.

### Not modelled, with reasons

- **F10 (unauthenticated `/auth/login`)** is a property of the route table, not of interleavings. G6 checks every route against the real app.
- **F14 (lost session cookie)** is removed by construction in G8. The open item in `TODO.md`, "Session expiry and a lost session cookie", remains worth modelling for its own sake but is not needed for this fix.
- **Sign-in as request and response** (R16, already in `TODO.md`) is unrelated to these findings; leave it there.

### Running the checks

`quint test --main=fixed --max-samples=1 --backend=typescript spec/wizard.qnt` and the conformance tests after each model change; `spec/check.sh fixed` for the new and affected invariants locally before pushing. CI keeps to the scenario tests, a short simulation and conformance, as now.

## Order and size

| Phase | Depends on | Rough size |
|---|---|---|
| A (urgent) | G1, G2, G3, G9, R19 | 3 fixes, 4 new test files, 1 model round |
| B (web hardening) | G6, G7, G8 | The CSP step is the largest: every inline handler in `index.html` moves |
| C (content) | G4, G5 | Touches both renderers; behaviour changes need changelog entries |
| D (send engine) | G1 | Small code, careful tests |
| E (usability) | none | Small |
| F (documents) | A–E | Small |
| G (dependency updates) | A–E, so the suite that judges an update is the final one | Mostly reading; size depends on what is outdated |
| H (released build on a real system) | Everything, and the user: it needs a push, a pre-release, real accounts and a Windows machine | Half a day of supervised testing per round |

A can ship alone. B and C are independent of each other. D needs the outcome matrix from A. G comes after the code changes and before H, so that what is tested on a real system is what will be released; F can be done before or after G but must be finished before H2, since the release notes come from the changelog.

## Finished when

- Every finding F1–F16 has a test that failed before its fix.
- Each guard G1–G9 exists and fails when its bug is put back (check by reverting the fix locally).
- `uv run pytest`, `uv run mypy`, Biome, Ruff, `quint test` and the conformance tiers pass; `spec/check.sh fixed` passes locally for the invariants in `check.sh`.
- `CLAUDE.md`, `README.md`, the tutorial and the changelog describe the new behaviour.
- Every pinned dependency and vendored file has a recorded verdict (updated, or held with a reason), and `docs/upgrade-plan.md` reflects it.
- The bundles built by the release workflow have passed the phase H checklist on a real Mac and a real Windows PC, with real email sent and received, or the user has accepted the listed exceptions.

## Handover: for whoever continues this work

Written 2026-11-15, at the end of phase C, for an agent (or person) with no memory of the earlier work.

### Where things are

- **Branch:** `review-fixes`, branched from `master` at `ec3e8d3`; 15 commits, the last being this handover. Nothing is pushed. The working tree is clean. `git log --oneline master..review-fixes` lists the steps in order; each commit message says which finding and guard it covers.
- **Done:** phases A to F (findings F1–F16; guards G1–G9; requirement R19; documents).
- **Remaining:** phase G (whether the dependencies and vendored code can safely be updated), phase H (an end-to-end test of the bundle the GitHub release process builds, on real systems), and the loose ends listed below. G and H were added by the user after phase C.
- **Version and release:** the version is still 0.6.0 and nothing is tagged. All changelog entries are under "Unreleased" in `CHANGELOG.md`. Bumping the version and releasing are the user's call; ask, don't do it.
- **Last verified state** (commit `83cce54`): 1163 tests pass and 14 are skipped (Windows-only tests, on macOS); `mypy`, `ruff check .` and `biome lint` are clean; the Quint scenarios pass for `buggy`, `partial`, `round2` and `fixed`; Apalache reports `allInvariants` holds for `fixed` at 16 steps.

### How the user wants this run

- **Stop at each phase boundary.** Finish the phase to a tested commit, update the Status section of this file, summarise, and ask the user whether to continue. The user asked for this explicitly part-way through.
- **One commit per step**, test first, full suite before each commit, descriptive message naming the finding (see the existing commits for the style). Don't push.
- **Every user-visible change gets a `CHANGELOG.md` entry** under "Unreleased", written for users, and the matching `CLAUDE.md` text is updated in the same commit.
- **Markdown paragraphs are not hard-wrapped** (one line per paragraph).
- **Nothing newer than 7 days** may be added as a dependency, tool, action or vendored file (`CLAUDE.md`, "Supply-chain policy").
- **CI minutes cost money:** thorough model checking runs locally, not in CI.

### Running things here

| What | Command | Notes |
|---|---|---|
| Restore the environment | `uv sync --locked --all-extras` | **Plain `uv run …` re-syncs the virtualenv without the `web` and `desktop` extras and uninstalls Flask**, after which six web test files fail at collection. If that happens, run this again. |
| Tests | `.venv/bin/python -m pytest -q` | About 5½ minutes. Doesn't re-sync. |
| Tests without a browser | add `--ignore=tests/test_web_e2e.py --ignore=tests/test_web_e2e_workflow.py --ignore=tests/test_web_e2e_injection.py --ignore=tests/test_conformance_e2e.py --ignore=tests/test_web_state.py` | About 2 minutes. |
| Types, lint | `.venv/bin/python -m mypy`, `.venv/bin/ruff check .`, `biome lint` | `biome lint` with no arguments uses the file list in `biome.json`. |
| Node tests only | `node --test tests/js/*.test.js` | Also run by `tests/test_wizard_core_js.py`. |
| Quint scenarios | `for v in buggy partial round2 fixed; do spec/node_modules/.bin/quint test --main=$v --max-samples=1 --backend=typescript spec/wizard.qnt; done` | Seconds. |
| Quint simulation | `spec/node_modules/.bin/quint run spec/wizard.qnt --main=conformance --init=cInit --step=cStep --backend=typescript --invariant=allInvariants --max-samples=3000 --max-steps=60` | Under a minute. |
| Apalache | `PATH="/opt/homebrew/opt/openjdk/bin:$PATH" QUINT="$PWD/spec/node_modules/.bin/quint" spec/check.sh --all fixed` | About 2 hours according to `docs/quint-model.md` (the run in phase A was not timed); needs Java (the `/usr/bin/java` stub is not a JDK) and local port 8822. Only needed if `spec/wizard.qnt` changes. |

In a sandboxed session: `uv` cannot open its cache, Chromium cannot start, and nothing can bind a local port. So the Playwright tests, `tests/test_log_secrets.py::test_server_access_log_hides_startup_token_and_auth_code` and Apalache must run outside the sandbox.

### Guards that will stop you, and what each wants

Phases A to C added tests that fail when something new is added without a decision. Expect these when doing D, E and F:

| If you… | …this fails | Do this |
|---|---|---|
| add a Flask route | `TestRouteTable` (`tests/test_web.py`), `TestRouteAccess` and the inventory tests (`tests/test_spec_coverage.py`) | Add the route to `spec/coverage.toml` with `access = "session"` and its model actions or an `out_of_scope` reason. Only mark a view `@public` with a very good reason. |
| add a button or listener | the inventory tests in `tests/test_spec_coverage.py` | Buttons use `data-action="name(arg)"`; add the function to `CLICK_ACTIONS` in `app.js` and the entry to `spec/coverage.toml`. No `onclick=` and no inline `<script>`: the Content Security Policy forbids them and `TestNoInlineScript` checks. |
| write markup to the page | `TestHtmlSinks` | Build it with `` html`…` `` and `setHtml()` from `static/safe-html.js`, or use `textContent`. |
| show a new server-supplied string in the page | nothing automatically | Add it to the walk in `tests/test_web_e2e_injection.py`. |
| add a `send_merge()` parameter | `test_every_parameter_has_a_row_or_a_reason` (`tests/test_input_validation.py`) | Add a row to `INVALID` or an entry to `NO_VALIDATION`. |
| add a job mode or a way Graph can answer | `tests/test_outcomes.py` | Add to `SENDING_MODES` or `ANSWERS`. |
| make the app write a new file under the home directory | `tests/test_fs_footprint.py` | Create it with `write_private()`, `open_private_append()` or `private_dir()` (`_paths.py`) and add it to that test's allowlist. |
| log something new | `tests/test_log_secrets.py`, Ruff `LOG`/`G` | Lazy `%`-style arguments; never headers, payloads, tokens or message bodies. Message content that must reach the terminal is logged with `extra={sender.CONSOLE_ONLY: True}`. |
| change how placeholders or cell values are rendered | `tests/data/template_vectors.json` (run by `tests/test_template.py` and `tests/js/template.test.js`), `CELL_CASES` in `tests/test_excel.py` | Change `template.py` and `static/template-core.js` together and add a vector. |
| change the model | `tests/test_spec_coverage.py`, `tests/test_conformance.py` | Follow "When you change the code" in `docs/quint-model.md`. A new environment choice needs an entry in `[assumptions]` in `spec/coverage.toml`. |
| store anything in a cookie | the autouse `_cookies_stay_small` fixture in `tests/conftest.py` | Keep it in the server-side session (`web/sessions.py`). |

### Remaining work, in detail

#### D1. Resume must not skip rows that share an address (F5)

The bug: resume is keyed on the address alone. If two rows have the same address (one person, two personalised emails) and a run is interrupted after the first, the second is never sent.

- **Where:** `src/mail_merge/api.py`, the block under `# --- Resume and batch size (skip for test emails) ---` (builds `successful_emails`, a set, and filters `recipients` with it) and the block under `# --- Merge with previous results when resuming ---` (a dict keyed by lower-cased address, which also collapses duplicates in the final report).
- **Change, skipping:** count the recorded successes per lower-cased address (`collections.Counter`). Walk the recipients in spreadsheet order; for each row, if the count for its address is above zero, decrement it and skip the row, otherwise keep it. So two successes skip the first two rows with that address and no more.
- **Change, the final report:** one line per row attempted, never collapsed by address. A workable rule: keep every previous success, add this run's results, and keep a previous failure only if its row was not attempted again in this run (that happens with `--batch-size`, where later rows wait for the next run). Check the rule against the incremental CSV: with `--send`, the CSV is rewritten with the previous results before the first email, each result is appended as it arrives (`report.append_csv`), and it is rewritten at the end; an interrupted run must leave a file the next run reads correctly.
- **Change, the CSV round trip:** `report._sanitize_csv()` puts a tab before a value starting with `=`, `+`, `@`, `-`, tab or carriage return, and `report.read_csv()` does not take it off, so an address such as `+tag@example.com` never matches on resume. In `read_csv`, strip one leading tab when the next character is one of those. The web page's `saveCsv()` in `app.js` writes the same guard but nothing reads its files back.
- **Tests:** in `tests/test_api.py`, class `TestInterruptedSend` (line 1396 at the time of writing): add a duplicate-address case (three rows for one address, interrupted after one, resumed: exactly two more go out, and the report has three lines), the same with `--batch-size`, and the BCC-mode path (resume applies to it too). In `tests/test_report.py`: `read_csv(write_csv(x)) == x` for addresses and error texts starting with each guarded character.
- **Not affected:** the web UI always passes `resume=False`.
- **Docs:** the `--no-resume` bullet in `CLAUDE.md`, the resume section of `docs/tutorial.md`, the changelog.

#### D2. Don't retry when the email may already have gone (the rest of F9, decision D5)

`sender.send_one()` retries any `requests.RequestException` up to `max_retries` times. After a read timeout the request may have been accepted, so a retry can deliver the email twice; `sendMail` has no idempotency key.

- **Change in `src/mail_merge/sender.py`:** catch `requests.ReadTimeout` before the general `requests.RequestException` clause (`ConnectTimeout` is both a `ConnectionError` and a `Timeout`, and must keep being retried: nothing was sent). On a read timeout, do not retry; return a result that is not a success and is marked as unknown, with an error such as "No answer from Microsoft: the email may or may not have been delivered. Check Sent Items before sending again." Keep retrying connection errors, 429 and 5xx, as decision D5 says.
- **`SendResult`:** add a field, for example `unknown: bool = False` (`success` stays `False`). Everything that copies or serialises a result needs it: `send_bcc_blast()` (copies the batch's result to each recipient), `report.summarize()` and `print_summary()` (a third count, "Outcome unknown"), `report._row()`/`write_csv()`/`read_csv()` (a new CSV column; read old files, which lack it, with `row.get`), `/api/job/<id>/status` in `web/app.py`, `web/sendlog.py` (`record()` and `interrupted()`), and in `app.js` `showResults()`, `showInterrupted()` and `saveCsv()` (show "Unknown: may have been delivered", not "Failed").
- **Ask the user first:** what resume should do with a row recorded as unknown. Re-sending it automatically risks the duplicate this change exists to prevent; skipping it silently risks a missed email. Recommended: skip it on resume, with a warning naming the address and saying how to force a retry (remove its line from the CSV). The test email path should say "may have been delivered" in the `SendAborted` it raises.
- **Tests:** `tests/test_outcomes.py` already has a "read timeout" answer expected to report failure; keep that and add assertions that exactly one request was made and that the result is marked unknown in each interface. Check `tests/test_sender.py` (`TestNetworkErrors`) for tests that assume a timeout is retried. Add a row to `ANSWERS` for a connect timeout that then succeeds.
- **Model:** not affected. `finishSend(failed)` and `completeJob` do not distinguish kinds of failure, and `Job.ok` is already false for any result that is not a success.

#### E1. The command line says which account it sends from (F15)

- **Now:** `auth.acquire_token()` and `acquire_token_interactive_flow()` use `accounts[0]` from the token cache and log "Found cached account" without naming it. The confirmation prompt in `send_merge()` has no From line. Nothing on the command line signs out; `auth.sign_out()` exists but only the web UI calls it.
- **Change:** log `Sending as <username>` at INFO once the token is acquired. Add a From line to the confirmation prompt. Note the order in `send_merge()`: the prompt comes before authentication, so either read the account from the cache without the network (constructing `msal.PublicClientApplication` does instance discovery over HTTP, which the test suite's `_no_external_http` fixture will refuse; `msal.SerializableTokenCache` can be searched directly), showing "you will be asked to sign in" when there is none, or move authentication before the prompt and update the orchestration order in `CLAUDE.md`. If the cache holds more than one account, warn and name the one used.
- **`--sign-out`:** `cli.parse_args()` marks `--spreadsheet`, `--body`, `--subject` and `--email-column` as required, so handle `--sign-out` before they are demanded. It needs a client ID (flag, environment, config file) to call `auth.sign_out()`.
- **Tests:** `tests/test_msal_contract.py` has the fixtures for real msal against mocked Entra endpoints (`entra`, `_token_response`); `tests/test_cli.py` for the prompt and the flag. The prompt's From line must go through `rich.markup.escape` like the other lines.

#### E2. Accept `.XLSX` (F16)

`web/app.py`, `api_upload_spreadsheet`: `file.filename.endswith(".xlsx")` is case-sensitive. Compare lower-cased. Test in `tests/test_web.py`.

#### E3. Explain a failed test email from its status code, not by searching the text for digits (F16)

`categoriseError()` in `app.js` matches `/400|Bad Request/`, `/5\d\d/` and so on against the whole error text, so a request ID or an address containing those digits gets the wrong advice. Since A1, a rejected test email reaches the page with its results (`SendAborted` carries them, and `/api/job/<id>/status` returns each result's `status_code`), so choose the advice from the failed result's `status_code` (401/403, 400, 429, 5xx, none for a network failure) and show the error text unchanged when there is no result (for example "Not signed in…" or a validation message). Put the function in `wizard-core.js` so it has Node tests. `TestRejectedTestEmail` in `tests/test_web_e2e_workflow.py` expects "Permission denied" for a 403; `test_failed_test_email_offers_sign_in` expects the "Not signed in" text to be shown as it is.

#### E4. Logging options (F16)

`--log-level` in `cli.py` and `web/__init__.py` silently treats an unknown level as INFO: use `choices`. Add `-v`/`--verbose` for DEBUG. The user's standing preference is that a setting is available on the command line, as an environment variable and in the TOML config alike, so also read `MERGEMAIL365_LOG_LEVEL` and a `log-level` key (`config.py` only returns `client_id` and `tenant_id` today). In `cli.main()`, the final `except Exception` logs "Unexpected error" with no traceback: add the traceback at DEBUG (`exc_info=True`).

#### E5. Hidden rows (F16)

Rows hidden or filtered out in Excel are still read and sent to; openpyxl's read-only mode cannot see row visibility. Document it in `README.md` and `docs/tutorial.md` (the web UI's preview shows every row that will be sent). No code.

#### F. Documents

- `docs/tutorial.md` has not been touched by any phase. It needs: the new placeholder rules and the HTML escaping (C1, C2), how dates and numbers appear (C3), address lists and semicolons (C4), `--allow-remote` (B4), what the log file does and doesn't contain (A2), and whatever D and E change.
- `README.md`: the options listing near line 106 is a copy of `mergemail365 --help`; regenerate it after E1 and E4.
- `docs/web-ui-plan.md` has a security assessment that predates the Content Security Policy, server-side sessions and route protection.
- `TODO.md`: add what is left open (below).
- When everything is done, this plan moves to `archive/` like the earlier ones, with its Status section final.

#### G. Whether it is safe to update the dependencies and vendored code

Read `docs/upgrade-plan.md` first. It records the last round (2026-09-30): what was upgraded, the test gaps that were closed beforehand so that an upgrade's regressions would be noticed, and two items still open (a smoke test of the PyInstaller bundle, and manually launching a built app), which phase H now covers. Follow its method: one group per commit, the full suite and `mypy` before each.

**G1. Inventory.** Nothing may be adopted until it has been public for 7 days. `uv` enforces that for Python packages (`exclude-newer = "7 days"` in `pyproject.toml`); for everything else, check the release date by hand.

| What | Where it is pinned | Now | How to see what is newer |
|---|---|---|---|
| Python packages (runtime: msal, requests, openpyxl, email-validator, rich, flask, pywebview and what they pull in; tools: pytest, mypy, ruff, playwright, pyinstaller, responses) | `uv.lock` | msal 1.39.0, requests 2.34.2, openpyxl 3.1.5, email-validator 2.3.0, rich 15.0.0, flask 3.1.3, werkzeug 3.1.8, pywebview 6.2.1, pyinstaller 6.22.3, playwright 1.63.0, pytest 9.1.1, mypy 2.3.1, ruff 0.17.4 | `uv tree --outdated`, or `uv lock --upgrade` on a scratch branch and read `git diff uv.lock` (the cooldown is applied for you). Check `uv --help` for the current spelling. |
| Trix, Pico CSS (vendored) | `scripts/update-vendor.sh`; files in `src/mail_merge/web/static/` | Trix 2.1.19, Pico CSS 2.1.1 | The npm registry pages; the script itself refuses a version under 7 days old. |
| Quint | `spec/package.json` and its lockfile | 0.32.0 | npm. `TODO.md` notes an `npm audit` finding in its `adm-zip` dependency, used only to unpack Apalache. |
| GitHub Actions | commit SHAs in `.github/workflows/*.yml` | checkout v7.0.1, setup-python v7.0.0, setup-uv v10.2.0, setup-biome v2.7.1 | Each action's releases page; pin the new commit SHA, keep the version comment. |
| uv, Biome | versions in the workflows; schema URL in `biome.json` | uv 0.12.18, Biome 2.5.14 | Their release pages. The local `biome` comes from Homebrew and may already differ. |
| Python | `.python-version`, `requires-python`, the workflows, `mypy` `python_version` | 3.14 | Whether a newer stable release exists. Raising the minimum again is a decision for the user (see `docs/upgrade-plan.md`, "Minimum Python 3.14"), not part of this phase unless they ask. |

**G2. Is each one safe?** For every item with a newer version, record three things.

1. *What changed:* read the changelog or release notes between the two versions, looking for removed or renamed APIs, changed defaults and changed output.
2. *Known vulnerabilities:* check the current and the candidate version against a vulnerability database (GitHub's advisory database or osv.dev; `npm audit --prefix spec` for Quint). A fix for a vulnerability that affects how this app uses the package outweighs most risk of updating. Do not install a new auditing tool to do this without checking its age.
3. *Which tests would notice a regression*, and whether that is enough. This branch added code that leans on dependencies in ways the last round did not have:

| Dependency | What this branch relies on | What would notice a change |
|---|---|---|
| Flask, Werkzeug | `web/sessions.py` implements Flask's `SessionInterface` with Werkzeug's `CallbackDict`; `web/app.py` reaches the session object with `session._get_current_object()`; `tests/conftest.py` wraps `Flask.process_response`; `MAX_CONTENT_LENGTH` and the 413 handler; `after_request` headers | `tests/test_web_sessions.py`, `TestRouteTable`, `TestSecurityHeaders`, `tests/test_web_robustness.py` |
| msal | The file log drops msal's DEBUG records because they contain the OAuth code and PKCE verifier (`console._NoMsalDebug`). `tests/test_log_secrets.py::test_sign_in_logs_no_tokens` asserts that msal *does* log the code at DEBUG, on purpose: if an msal update stops doing so, that assertion fails, which means the filter may no longer be needed, not that something broke. Also the token cache format read and written through `write_private()`. | `tests/test_log_secrets.py`, `tests/test_msal_contract.py`, `tests/test_fs_footprint.py` |
| openpyxl | Read-only cells exposing `number_format`, and dates arriving as `datetime` objects (`excel.cell_text`) | `CELL_CASES` and the workbook tests in `tests/test_excel.py` |
| email-validator | Used for recipients and, now, every typed address (`addresses.py`). Tests match only the start of its messages. | `tests/test_addresses.py`, `tests/test_input_validation.py` |
| requests | `sender.py` tells `ReadTimeout` from other errors once D2 is done | `tests/test_outcomes.py` |
| rich | The confirmation prompt and console logging, as before | `tests/test_console.py`, `tests/test_cli.py` |
| Python's `logging` | `PrivateRotatingFileHandler` overrides `RotatingFileHandler._open`, a private method | `tests/test_fs_footprint.py`, `tests/test_log_secrets.py` |
| Trix | Must run under the Content Security Policy (no inline script; inline styles are allowed). `static/trix-config.js` sets `Trix.config.blockAttributes.default.tagName`. Placeholders in an HTML body depend on Trix writing `&amp;`, `&lt;` and `&nbsp;` as it does now. | `PASTE_EXPECTED` and the Trix tests in `tests/test_web_e2e.py` (a change to `PASTE_EXPECTED` is a behaviour change, not a fixture to refresh), `test_rich_text_editor_placeholder_for_a_column_with_markup_characters`, and the `page` fixture, which fails on any policy violation |
| Pico CSS | Styling only | Nothing automatic: look at each step of the wizard after updating |
| pywebview | The desktop window, `ALLOW_DOWNLOADS`. **No automated test runs the real web view**, so the Content Security Policy, the `data-action` buttons and the report download have never been exercised in WKWebView or WebView2. | `tests/test_web_cli.py` against an autospec only; really, phase H |
| PyInstaller | `mergemail365.spec` lists hidden imports by name and does not list the modules this branch added (`mail_merge.addresses`, `mail_merge.web.sessions`); they are imported at module level, so the analysis should find them, but no bundle has been built since. The whole `static/` directory is bundled, so the new script files come along. | Nothing automatic: phase H |
| Playwright | Test tooling; its browser version moves with it | The browser tests themselves |
| Quint | `tests/test_conformance.py` reads its trace format (`mbt::actionTaken`, `mbt::nondetPicks`) | The conformance tests and `spec/check.sh` |

Give each item a verdict: *update* (low risk, or a security fix, and covered by tests), *hold* (no benefit, or a risk the tests can't see), or *needs a test first* (write the test, as the last round did, then update).

**G3. Ask.** Put the inventory and verdicts in this file and ask the user which to update. Updating is not automatic.

**G4. Update what was agreed.** `uv lock --upgrade-package <name>` for one package at a time or by group, then `uv sync --locked --all-extras`; `scripts/update-vendor.sh --trix <version>` for vendored code, reviewing the diff. Run the full suite, `mypy`, Ruff and Biome before each commit. For Trix, Pico, pywebview and PyInstaller, the automated tests are not enough: note in Status that phase H must look at them. Bring `docs/upgrade-plan.md` up to date in the last commit.

#### H. End-to-end test of the released build, on real systems

The automated tests mock Microsoft Graph and Entra, and none runs the packaged app. This phase checks the real thing: the bundles that `.github/workflows/release.yml` builds, taken from the GitHub release as a user would get them, running on a real Mac and a real Windows PC, signed in to a real Microsoft 365 account, sending real email.

**What needs the user.** Pushing the branch, creating a tag and publishing a pre-release are outward-facing: get explicit approval for each, or have the user do them. The user must sign in (never ask for or handle their password), choose the mailboxes that receive the test emails, and provide or operate the Windows machine. An agent can prepare everything, drive the parts that don't need credentials, read the logs and record the results.

**H1. CI first.** `test.yml` runs on pushes to `master`, on pull requests and on manual dispatch, so open a pull request for `review-fixes` (or run the workflow manually on the branch). This is the first time the branch's tests run on Linux and Windows; expect to fix platform differences (see "Loose ends"). The `spec` job needs `round2` in its variant loop, which is already there.

**H2. Build a release candidate with the release workflow.** How the workflow behaves (read it before relying on this):

- It runs when a release is published, or by manual dispatch with a `tag` input. It builds on `macos-latest` and `windows-latest` in the `UCL` environment, which supplies the client and tenant IDs baked into the bundle and the Windows signing certificate.
- It rewrites the version in `pyproject.toml` and `mergemail365.spec` from the tag, builds with `uv run --frozen pyinstaller mergemail365.spec`, signs the Windows bundle, zips, and uploads with `gh release upload <tag>`. The upload needs a release for that tag to exist already.
- On manual dispatch it checks out the branch it was started from, not the tag; the tag is used only for the version number and the upload.

So: create a **pre-release** with a candidate tag (for example `v0.7.0rc1`; agree the version with the user) pointing at the commit to test, and let publishing it trigger the build, or dispatch the workflow for that tag. Mark it as a pre-release so that it is not offered to users as the latest version. Confirm both zip files are attached and note the commit they were built from.

**H3. The checklist.** Run it on macOS and on Windows. Download the zip from the release page in a browser, so that the operating system treats it as a downloaded file (Gatekeeper on macOS, SmartScreen on Windows; `docs/codesigning.md` describes what to expect). Use a machine that has no development copy of the project if possible. If an earlier version is installed and signed in, leave its token cache and log files in place: the upgrade is part of the test.

Prepare a spreadsheet for the test, with 6 to 10 rows addressed to mailboxes the user controls, containing: a column name with punctuation (`First-Name`) and one with spaces; a date column, a percentage column and a currency-formatted column; a cell containing `<`, `&` and a line break; two rows with the same address; one row with an invalid address; a second sheet; and about 60 columns with long headings (the session-cookie case).

| # | Do | Expect | Covers |
|---|---|---|---|
| 1 | Unzip and open the app. | It opens without a security block beyond what `docs/codesigning.md` describes. The window shows the wizard; the footer shows the candidate's version. | Build, signing, version injection |
| 2 | Click every button on step 1, including "Test connection". | Each responds. Nothing is dead. | The Content Security Policy and `data-action` buttons in the real web view, which no automated test runs |
| 3 | If an earlier version was signed in: check the header. Otherwise sign in (the system browser opens). | Still signed in after the upgrade, or sign-in completes and the header shows the account. | Token cache written by `write_private()`, read from the old location; desktop sign-in |
| 4 | Upload the spreadsheet. | It loads despite the wide headings. The note about unformatted numbers names the currency column. Dates show as `2026-12-01`, the percentage as `25%`. | F14, F6 |
| 5 | Change sheet and back. | The preview follows. | Sessions |
| 6 | Compose: use the chips for the punctuated columns, type `{{ First Name }}` by hand, add a CC as `"Surname, First" <address>`, attach a small file. Try Next with a misspelt placeholder, then with a bad CC address. | Each mistake is refused on this step with a message naming it. Corrected, Next works. | F4, F7 |
| 7 | Switch to HTML, use the editor's bold and a list, insert a chip, paste formatted text from Word or a web page. | The editor works; the preview shows the formatted email with the cell's `<` and `&` as text and the line break kept. | Trix under the policy, F8 |
| 8 | Step 3: page through the recipients. | The invalid address is listed as skipped; both rows with the shared address are present. | Preview |
| 9 | Step 4: send the test email to yourself. | "Sent successfully" appears and the email arrives, with the right subject, body, CC, attachment name and From. | The real Graph call |
| 10 | If an account or setting is available that makes Graph refuse the email (for example an account without a mailbox): send a test with it. | The step shows a failure and Next stays disabled. If no such account exists, note that this was not tested on a real system (the automated outcome matrix covers it). | F1 |
| 11 | Steps 5 and 6: dry run, then send. Press "Stop sending" after the second email. | The send stops; the results list exactly the emails that went out, and those arrived. | Stop, results |
| 12 | Send again to the rest; while it runs, quit the app. Reopen it. | Step 1 reports the interrupted send and which emails went out. "Download CSV" asks where to save and the file is correct. | Send log, download in the web view |
| 13 | Complete a send. "Download mail merge report". Then "New merge". | The report saves; every field is cleared. | Report, reset |
| 14 | Read the received emails in Outlook on the web and one other mail client. | Placeholders filled in everywhere, no `{{`; dates and percentages as in the preview; HTML renders; nothing from the cell was treated as markup. | F4, F6, F8 end to end |
| 15 | Open the log file (`~/Library/Logs/mergemail365/` or `%LOCALAPPDATA%\mergemail365\logs\`) and search it for `Bearer`, `eyJ`, `token=` followed by anything but `[redacted]`, and a distinctive phrase from the email body. | None found. The log still shows each send and its result. | F2, F13 |
| 16 | macOS only: `stat -f '%Lp %N' ~ ~/.mergemail365-token-cache.json ~/Library/Logs/mergemail365 ~/Library/Logs/mergemail365/*.log` before and after the session. | The home directory's mode is unchanged; the cache and logs are 600, the log directory 700; log files left by the earlier version are now 600. | F3 |
| 17 | Windows only: leave a send running with the window in the background for some minutes. | It keeps sending. If it stalls, keep `mergemail365.log` and `mergemail365-stalls.log`: this is the fault reported against 0.3.1 and 0.4.1 (`TODO.md`). | The open Windows report |
| 18 | Sign out, then sign in again. | Both work; the header follows. | Sign-in |

If phase G updated Trix, Pico CSS, pywebview or PyInstaller, items 1, 2, 7 and 12 are where a regression would show.

The command-line tool is not part of what the release workflow builds. If the user wants it covered, run steps 9, 11 and 14's equivalents with `mergemail365` from a clean checkout of the candidate's commit (`uv sync --locked`, then a dry run, `--test-email` and a small `--send --output`), and say in Status that this was a source install, not a release artefact.

**H4. Record and repeat.** Put the result of every item, per platform, in Status, with the candidate's tag and commit. Fix failures on the branch with tests where a test is possible, build the next candidate, and repeat the affected items. Remove candidate pre-releases only if the user asks.

**H5. Hand back.** The real release (version number, tag, release notes from the changelog) is the user's to make.

### Loose ends and things not verified

- **Not run on Windows or Linux.** CI has not run on this branch. The permission tests are skipped on Windows; `os.fchmod` and the `chmod` calls are guarded by platform checks, but that is untested there.
- **Guards checked against their bug:** `tests/test_outcomes.py` (fails without the `api.py` change), `tests/test_fs_footprint.py` (fails with the old `_save_cache`), the cookie guard and `tests/test_web_sessions.py` (fail with Flask's cookie session), the injection walk (its second test breaks the escaping), and the conformance mutants. **Not checked that way:** `test_running_send_lookup_survives_jobs_being_created_meanwhile` (may pass without the lock; the race is rare), `TestRouteTable` against a deliberately unprotected route, and `tests/test_log_secrets.py` against the original `sender.py` (the leak was confirmed by hand during the review; the test file did fail on the two leaks it found while being written).
- **Apalache** was run as `--all fixed` (one result for all invariants), not invariant by invariant, and for `round2` only at 12 steps for three invariants.
- **Browser conformance has no mutant for `jobSucceeded`.** The client and server tiers have one each; the page is covered by `TestRejectedTestEmail` instead, because the few random browser traces would not reliably include a rejected test email.
- **The 4 MB figure.** `_check_message_size()` and the older per-attachment check assume Microsoft Graph accepts about 4 MB per `sendMail` request. That is not stated in the copies of the documentation in `docs/`; verify it against Microsoft's documentation before relying on the exact limit.
- **Review findings not in this plan** (minor, left as they are): recipients' addresses are validated before filters are applied, so rows a filter would exclude can still produce "invalid address" warnings; a spreadsheet with two columns of the same name uses the last one's values; two `mergemail365-web` processes running at once each treat the other's running send log as interrupted; the token cache is a plain file rather than the system keychain.

### Questions waiting for the user

1. **`batch_size=0`.** It used to mean "send nothing this time" and an existing test said so; it is now an error, as the accepted plan specified (`batch_size >= 1`). The user was told and has not yet answered whether 0 should stay a no-op.
2. ~~Resume and "outcome unknown"~~: answered 2026-11-15, skip with a warning (done in D2).
3. **Releasing.** Whether phase A should go out on its own as 0.6.1 (it would have to be cherry-picked, since later commits change behaviour) or everything together as 0.7.0.
4. **Phase G:** which updates to make, once the verdicts are in; and whether to raise the minimum Python version if a newer stable release exists.
5. **Phase H:** approval to push the branch, open a pull request and publish a pre-release; the candidate's version number; which Microsoft 365 account and which recipient mailboxes to use; who operates the Windows machine.

## Status

Updated 2026-11-15 (end of phase F; last commit `734da86`). Work is on the `review-fixes` branch, one commit per step. At each phase boundary this section is updated and the user is asked whether to continue.

**Where things stand:** phases A to F are complete. Phases G and H have not been started (G and H were added to the plan on 2026-11-15, after phase C). Nothing has been pushed and the version has not been bumped; changelog entries are under "Unreleased".

**Checks at the last commit:** the full test suite passes (count in the commit message), mypy, Ruff and Biome are clean, the Quint scenarios pass for all four variants, and Apalache reports that `allInvariants` holds for `fixed` at 16 steps (run on the model as of A1; the model has not changed since).

### Phase A: urgent fixes — complete

| Step | State | Notes |
|---|---|---|
| A1 (F1, G1, G9, R19) | Done | `Job.ok`, `WizardCore.jobSucceeded()`, `send_merge()` raises for a rejected test email; `tests/test_outcomes.py`; model round 3 with `testPassHonest`; `[assumptions]` in `spec/coverage.toml`. Apalache at 12 steps: `testPassHonest` and `next4Honest` are violated in `round2` and hold in `fixed`. |
| A2 (F2, F13, G2) | Done | Implemented as a `RedactingFormatter` rather than a filter (a filter would rewrite records the console also prints). The canary tests found two leaks the review had missed: a DEBUG dry run logged every rendered body, and msal's DEBUG records include the OAuth code and PKCE verifier. Ruff added with `LOG`, `G`, `S`. |
| A3 (F3, G3) | Done | `write_private()`, `open_private_append()`, `private_dir()`; `tests/test_fs_footprint.py`. |

### Phase B: web security hardening — complete

| Step | State | Notes |
|---|---|---|
| B1 (F10, G6) | Done | `@public`, `TestRouteTable`, `access` in `spec/coverage.toml`. Changed from the plan: the `127.0.0.1` case is handled in `/auth/login` with a one-time handoff pass to `localhost`, not by redirecting the `/?token=` URL, which would have moved every `127.0.0.1` user (and the browser tests) to another origin on arrival. |
| B2 (F14, G8) | Done | `web/sessions.py`; `tests/test_web_sessions.py`; cookie-size guard in `tests/conftest.py`. The handoff pass carries the session id, so the upload survives the move to `localhost`. |
| B3 (F11, G7) | Done | `static/safe-html.js`, `TestHtmlSinks`, `TestNoInlineScript`, the CSP and headers, `tests/test_web_e2e_injection.py`. The injection walk counts elements created from the payload rather than checking whether script ran, because under the policy an injected handler never runs even when escaping is broken. Found on the way: the old `escapeHtml()` did not escape quotes, so a column name containing `"` broke out of the `value` attribute of its `<option>`. |
| B4 (F12) | Done | `--allow-remote`; `_find_open_port(host=...)`. |
| B5 | Done | `MAX_CONTENT_LENGTH` with a JSON 413, `_json_object()`, `running_send()` under a re-entrant lock, attachments deleted when their job ends. The `auth_login` error redirect was done with B1. |

### Phase C: what goes into the email — complete

| Step | State | Notes |
|---|---|---|
| C1 (F4, G4) | Done | New grammar in `template.py` and `static/template-core.js`; 36 shared vectors and 18 chip columns in `tests/data/template_vectors.json`; `tests/test_placeholders_end_to_end.py`; browser tests in `TestPlaceholderGrammarInThePage`. The web UI blocks Next on step 2 for a placeholder naming no column and warns about stray braces. Two decisions made while implementing: character references in an HTML placeholder name are limited to a fixed list (`&amp; &lt; &gt; &quot; &apos; &nbsp;` and numeric ones) so that Python and JavaScript can agree exactly; and a column whose name contains a brace gets no chip and is listed as unusable. |
| C2 (F8) | Done | Values are escaped in HTML bodies by both renderers; line breaks in a cell become `<br>`, which the plan did not mention. |
| C3 (F6) | Done | `excel.cell_text()` and `CELL_CASES`. openpyxl's read-only cells do expose `number_format`. Durations (`[hh]:mm`) and times are handled as well as dates. The note about unapplied formats is on the upload step (`#number-format-note`) and a warning in `send_merge()` when the message uses such a column. |
| C4 (F7) | Done | `addresses.py`, `tests/test_addresses.py`. Not an RFC 5322 parser, on purpose: a strict one refuses names people write unquoted, such as `[Team] Lead <x@y>`, which an existing test covers. Semicolons and newlines separate addresses as well as commas. `/api/get-recipients` checks the Compose step's addresses. |
| C5 (F9 part, G5) | Done | `_check_options()`, `_check_message_size()`, argparse types, `tests/test_input_validation.py` (34 rows). The table found one more: an unknown `--sheet` raised `KeyError`, reported as "Unexpected error". The total-size limit reuses the per-attachment limit's existing assumption (about 4 MB per request to Graph, 3 MB of files once base64-encoded); that figure was already in the code and is not stated in the copies of Microsoft's documentation kept in `docs/`. |

### Phase D: the send engine — complete

| Step | State | Notes |
|---|---|---|
| D1 (F5) | Done | `_skip_previously_sent()` and `_previous_results_to_keep()` in `api.py`; `report._unsanitize_csv()`. The rule for the report: the CSV written before the first email already leaves out the previous failures that this run will retry, so an interrupted run's file needs no further merging (the plan had left this open). Matching failures to rows is by count, earliest first, as for successes. |
| D2 (F9 rest) | Done | `SendResult.unknown`, `sender.NO_ANSWER`. The user chose: resume skips an unknown row, with a warning naming it and saying to delete its line from the report to send it anyway. `summarize()` counts unknown apart from failed (`failed` is now only emails known not to have gone) and adds `unknown_details`. The browser's CSV gained an `unknown` column, so `test_download_mail_merge_report`'s expected text changed. |

Checks at `a92d399`: 1206 passed, 14 skipped; mypy, Ruff and Biome clean. The model was not changed (as the plan expected), so Quint and Apalache were not rerun.

### Phase E: usability — complete

| Step | State | Notes |
|---|---|---|
| E1 (F15) | Done | `auth.cached_account_names()` reads the cache file without building an msal app; `auth.account_name()` prefers the token's `upn`/`preferred_username` and falls back to the cache (personal accounts get opaque tokens). Authentication stays after the prompt, so the order in `CLAUDE.md` is unchanged. `--sign-out` needs only a client ID; the four send arguments are now checked in `cli._parse()` instead of `required=True`. The per-email "Found cached account" INFO line is now DEBUG (it was logged once per email). Found on the way: tests read the developer's real token cache and config file; `tests/conftest.py` now isolates both and the `MERGEMAIL365_*` variables. The tutorial still described device-code sign-in as the default; corrected. |
| E2 (F16) | Done | Case-insensitive extension check. |
| E3 (F16) | Done | `WizardCore.testEmailFailure()` with Node tests; `categoriseError()` removed. A status code with no advice (413, say) is shown as `Microsoft refused the email (HTTP 413): …`. |
| E4 (F16) | Done | `console.add_log_level_arguments()`, `resolve_log_level()`, `configure_console_logging()`; `tests/test_log_options.py`. An invalid level from the environment or config file is a usage error (exit 2). Both expected and unexpected CLI errors now log the traceback at DEBUG. Not done: the global preference for timestamps and logger names in the format at DEBUG, which the plan did not ask for. |
| E5 (F16) | Done | README and tutorial. |

Checks at `feebd91` (E3, the last code change): 1237 passed, 14 skipped; mypy, Ruff and Biome clean. E5 is documentation only. The model was not changed.

### Phase F: documents — complete

| What | State | Notes |
|---|---|---|
| `README.md` | Done | Options listing regenerated from `--help`; feature list updated. `--help` itself changed: an explicit two-form usage line (a send, and `--sign-out`), since argparse's generated one showed the send arguments as optional; the address options' and `--max-retries`' help corrected. |
| `docs/tutorial.md` | Done | Placeholders, cell values, HTML escaping, address lists, the attachment total, what the log file holds, `--allow-remote`. D and E were documented as they were done. |
| `docs/web-ui-plan.md` | Done | Security assessment revised. |
| `TODO.md` | Done | The loose ends below, plus the web UI CSV's differences from `--output` reports. |
| `CLAUDE.md`, `CHANGELOG.md` | Done | Kept up to date in each step's commit. |
| `spec/*`, `docs/quint-model.md` | No change needed | The model did not change after A1, which updated them. |
| Move this plan to `archive/` | Not yet | After G and H. |

### Phases G, H — not started

What each step involves, file by file, is under [Remaining work, in detail](#remaining-work-in-detail) in the Handover section. Add a table here for each phase as it is done, in the style of the ones above.
