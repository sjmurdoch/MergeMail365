# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A Python tool that sends personalised emails via Microsoft Graph API. Recipients come from an Excel spreadsheet, and the email body/subject use `{{column_name}}` placeholders. Has three interfaces: CLI (`mergemail365`), Python API (`send_merge()`), and a web UI (`mergemail365-web`).

## Commands

```bash
# Setup
uv sync

# Run all tests
uv run pytest

# Run a single test file or test
uv run pytest tests/test_template.py
uv run pytest tests/test_cli.py::TestTestEmail::test_test_email_sends_to_correct_address

# Run with coverage
uv run pytest --cov=mail_merge

# Type checking
uv run mypy

# JS linting (requires Biome — brew install biome; CI pins the version in .github/workflows/test.yml)
biome lint src/mail_merge/web/static/app.js src/mail_merge/web/static/wizard-core.js

# CLI usage (after install) — dry run by default, add --send to deliver
uv run mergemail365 --spreadsheet recipients.xlsx --body body.txt --subject "Hello {{name}}" --email-column email
uv run mergemail365 --spreadsheet recipients.xlsx --body body.txt --subject "Hello {{name}}" --email-column email --send

# Web UI — opens browser automatically
uv run mergemail365-web
uv run mergemail365-web --port 8080
uv run mergemail365-web --desktop  # native window (requires pywebview)
```

## Architecture

Source lives under `src/mail_merge/` (src layout). There are three entry points:

1. **CLI** (`cli.py:main()`) — parses args, sets up logging, delegates to `send_merge()`, converts exceptions to exit codes.
2. **Python API** (`api.py:send_merge()`) — single function mirroring all CLI flags. Raises exceptions (`FileNotFoundError`, `ValueError`, `RuntimeError`) instead of returning exit codes. Returns `list[SendResult]`.
3. **Web UI** (`web/__init__.py:main()`) — Flask app with a 6-step wizard (Data → Compose → Preview → Test → Verify → Send). Runs on localhost, opens browser automatically. See "Web UI" section below.

The orchestration flow (in `api.py`) is strictly ordered: resolve config → read spreadsheet → validate emails → apply filters → resume (skip previous successes) → apply batch size → read body template → validate all placeholders (abort if any unresolvable) → parse CC/BCC/reply-to → validate recipient count → process attachments → confirm → authenticate → send → merge results → report. All validation happens before any sending. Resume and batch size are skipped for `--test-email` (which only needs one recipient's data for rendering). Resume works for both individual sends and BCC blast mode.

Key design decisions:
- **`config.py`** reads `~/.mergemail365.toml` for persistent `client-id` / `tenant-id`. Precedence: CLI flag → env var → config file → default (`"common"` for tenant-id).
- **`EmailAddress`** dataclass (in `sender.py`) is the unified internal representation for email addresses throughout the codebase. It holds `address: str` and `name: str | None`, and provides `to_graph()` to convert to the Microsoft Graph API wire format (`{"emailAddress": {"address": ..., "name": ...}}`). Three representation layers are used consistently: user-facing strings (`"Display Name <email>"`) at the CLI/API boundary, `EmailAddress` objects internally, and Graph API dicts only at the point of HTTP serialisation in `send_one`.
- **`api.py`** contains `send_merge()`, the shared orchestration function used by both CLI and Python callers. Accepts `str | Path` for file args, `str | list[str]` for address lists. `_parse_one_addr()` parses a single RFC 2822 address string into an `EmailAddress`. `_parse_address_entries()` normalises all address inputs (cc/bcc/reply-to) into `list[EmailAddress]`; parsed values are bundled into a `MessageOptions` dataclass and passed to sender functions. `sender.py` functions (`send_one`, `send_bcc_blast`, `send_all`) accept `opts: MessageOptions` for shared message-formatting parameters (max_retries, importance, cc, bcc, html, save_to_sent_items, attachments, reply_to). The primary recipient is passed as an `EmailAddress` parameter `to` (bundling address and display name together). `send_all` accepts `name_column` to look up per-recipient names from the spreadsheet and construct an `EmailAddress` per recipient.
- **`auth.py`** uses lazy import in `api.py` — only imported when authentication is actually needed (skipped for dry runs). Three auth flows: **interactive browser** (default for CLI — opens system browser via `acquire_token_interactive_flow()`), **device code** (opt-in via `--device-code` — user copies a code to a browser, for headless/SSH), and **auth code with PKCE** (web UI — redirect to Microsoft and back). All flows share the same MSAL token cache file. If interactive flow fails (e.g. no display), it falls back to device code automatically. Web jobs use a fourth, `acquire_token_silent()`: cache only, raising `NotSignedInError` (a `RuntimeError`) instead of prompting, because a background job has nobody to answer a prompt.
- **`sender.py`** has two retry strategies: 429 (rate limit) honours `Retry-After` with a cap of 20 attempts; 5xx retries use exponential backoff capped at `--max-retries`. 4xx errors (non-429) fail immediately. `--delay` defaults to 2s (Exchange Online limit: ~30 msgs/min) with adaptive throttling: delay doubles (up to 30s) on 429s and halves back to the base when clear.
- **Email validation** uses `email-validator` (`_validate_emails` in `api.py`) to reject malformed and non-ASCII addresses before sending. Invalid recipients are skipped with a warning; if none remain, a `ValueError` is raised.
- **`template.py`** uses case-insensitive matching — `{{Name}}` matches a column called `name`
- **`cli.py:main()`** accepts `argv` parameter for testability — all CLI tests call `main([...])` directly
- **`--test-email`** always sends one email to a specified address using first recipient's data, then exits (no `--send` needed; resume and batch size are ignored)
- **`--importance`** sets email importance (`low`, `normal`, `high`); omitted from API by default
- **`--cc`** / **`--bcc`** accept comma-separated addresses (plain `email@example.com` or `"Display Name <email>"`) for CC/BCC recipients
- **`--html`** sends the body as HTML instead of plain text
- **`--no-save-to-sent`** sets `saveToSentItems: false` so sent messages skip the Sent Items folder
- **`--attachment`** (repeatable) attaches files as base64-encoded `#microsoft.graph.fileAttachment` objects
- **`--reply-to`** comma-separated reply-to addresses (plain or `"Display Name <email>"`) added to the message `replyTo` field
- **Safe defaults** — `send=False`, `confirm=True`, `resume=True` in the API; CLI requires `--send` to actually deliver. Resume silently skips when `--output` is not set.
- **`--send`** opts into actual sending (default is dry run)
- **`--log-file`** enables file logging at DEBUG level (available on both `mergemail365` and `mergemail365-web`; always on in PyInstaller bundles)
- **`--device-code`** uses device code flow for authentication (headless/SSH environments). Default behaviour opens the system browser via `acquire_token_interactive_flow()`
- **`--filter`** (repeatable) filters recipients by column values (`column=value` or `column!=value`, AND logic, case-insensitive)
- **`--no-resume`** disables automatic resume; by default with `--output`, previous successes in the CSV are automatically skipped
- **`--batch-size N`** limits how many emails are sent per invocation
- **`--name-column`** specifies a spreadsheet column containing recipient display names; each email's `To:` header includes the name (e.g. `"Alice <alice@example.com>"`). In BCC blast mode, use `--bcc-blast-to "Display Name <email>"` instead.
- Recipient count validation: errors if to + cc + bcc exceeds the Graph API limit of 500

## Web UI

The web interface lives under `src/mail_merge/web/` and is installed as `mergemail365-web`. Flask backend (`web/app.py`) + vanilla JS single-page app (`web/static/app.js`) + Pico CSS. No build step, no JS framework.

**Dependencies:** `flask>=3.0` (optional `web` extra), `pywebview>=5.0` (optional `desktop` extra). Install with `uv sync --extra web`.

**Key files:**
- `web/__init__.py` — entry point: port discovery, startup token, browser launch
- `web/app.py` — Flask app factory, all routes, background job management. Pure helper functions (`_validate_html_body`, `_partition_emails`, `_validated_recipient_count`) and job infrastructure (`Job`, `JobLogHandler`, `_jobs`) are at module level; only routes and session-dependent helpers live inside `create_app()`.
- `web/templates/index.html` — single Jinja2 template with all 6 wizard steps
- `web/static/wizard-core.js` — the wizard's workflow state (`initialState()`, reset rules) and selectors, with no DOM or `fetch`. Loaded as a classic script before `app.js` (`window.WizardCore`) and with `require()` by the Node tests in `tests/js/`. Selector names follow the model's pure defs (`sendTestEnabled`, `doSendEnabled`, `signInOffered`).
- `web/static/app.js` — wizard navigation, SSE streaming, client-side template preview. Wizard state centralised in `state` object (`window.state`, built from `WizardCore.initialState()`), auth state in `_auth`. `render()` is the only code that sets the step 4–6 buttons' `disabled` state and which parts of steps 4–6 are shown; it reads only `WizardCore` selectors, and handlers change `state` and call `render()` (`tests/test_spec_coverage.py` enforces this for the controls in `RENDERED_CONTROLS`).
- `web/static/style.css` — custom styles (step indicator, chips, log panel, callouts)
- `web/static/pico.min.css` — bundled Pico CSS v2 (no CDN)

**Architecture:**
- **Auth:** Three flows, all sharing the same MSAL token cache. **Browser mode:** OAuth 2.0 Authorization Code flow with PKCE (redirect to Microsoft and back). **Desktop mode (pywebview):** `acquire_token_interactive_flow()` opens the system browser (not the embedded webview) via `POST /auth/interactive`; JS polls `/auth/status` until authenticated. **CLI:** Interactive browser flow by default, device code via `--device-code`. Auth functions in `auth.py`: `acquire_token_interactive_flow()`, `initiate_auth_code_flow()`, `acquire_token_by_auth_code()`, `acquire_token_silent()`, `diagnose_auth()`, `token_expires_at()`. **Sign-in gate:** the test email and the send go out from the signed-in account, so while the page shows signed out (`_auth.isSignedIn`), `render()` disables "Send test email", Retry and "Send emails" and shows a sign-in callout on steps 4 and 6 (`#signin-callout-4`, `#signin-callout-6`, whose buttons share `onSignInClick()` with `#btn-sign-in`). Steps 4 and 6 can be entered signed out; the callout removes the dead end (`spec/requirements.md`, R2). `checkAuthStatus()` runs on load, on entering steps 4 and 6, and after a failed test email.
- **`send_merge()` integration:** The web UI calls `send_merge()` with three web-specific parameters: `body_text` (inline string, no temp file), `token_provider` (callable that replaces `send_merge()`'s own authentication step; it calls `auth.acquire_token_silent()`, so a job with no usable cached token fails at once with "Not signed in" instead of falling into the device-code flow), and `should_stop` (checked by the send loops before each email or BCC batch). Always passes `confirm=False`, `resume=False`.
- **Background jobs:** `send_merge()` runs in a daemon thread. `JobLogHandler` captures `mail_merge` logger output into an event queue. SSE (`/api/job/<id>/events`) streams log entries to the browser; the stream also ends when the job has finished and its queue is empty, because a stream from a page that was since reloaded may already have taken the end-of-job sentinel. Each `Job` records its `mode`. **Stop:** `/api/job/<id>/stop` sets `job.stop_requested`; the job's `should_stop()` reports it to the send loop, which stops before the next email and returns the results so far, and the job ends as `stopped` (only if the loop actually stopped early). Job results are fetched via `/api/job/<id>/status` which calls `report.summarize()`. A send that fails part-way raises `sender.SendAborted` (a `RuntimeError`) carrying the results so far; the job keeps them and the page lists them under the error. Only one send runs at a time: `/api/start-job` answers 409 while `_running_send_job()` finds one (checked again under `_jobs_lock` when the job is created).
- **Safety limits:** 99-recipient cap (enforced server-side), fixed 2s send delay, mandatory test email and dry run steps, "SEND" confirmation typing. The mandatory test email and dry run are enforced in the browser only, by design: they guard against mistakes made while using the wizard, not against a client that bypasses it (anything that can call `/api/start-job` directly already holds the startup token and CSRF token and can send as the user). `/api/start-job` does not check them, and the `test_passed` / `verify_passed` values stored via `/api/state` are only for display, not authorisation.
- **Session:** Startup token (like Jupyter) for access control. CSRF token on all POST routes. `Host` header allowlist (loopback names + `--host`, skipped for wildcard binds) against DNS rebinding. Identical in both modes: desktop mode serves the app on a localhost port via werkzeug `make_server` in a thread and opens the pywebview window at the same `?token=` URL. Never pass the Flask app itself to `webview.create_window()`, because pywebview then serves it on its own untokened localhost port. 24-hour session lifetime with sliding window. Server-side state persistence (`/api/state`) + client-side localStorage auto-save.
- **Untrusted content:** Spreadsheet cells (including column headers), the uploaded file's name and pasted clipboard HTML all come from outside the app, and script injected into the page could send email as the signed-in user. In `app.js`, never put them into `innerHTML` unescaped: use `escapeHtml()` or `textContent`. The `trix-before-paste` handler parses clipboard HTML in an inert document (`document.implementation.createHTMLDocument`), because an element of the live document would load images and fire `onerror` before Trix sanitises the paste. The HTML preview iframe uses `sandbox=""`. There is no CSP yet, so these rules are the only defence. On the server, attachment filenames are client-controlled: `_attachment_basename()` keeps only the last path component (rejecting `.`, `..` and empty names), and `api_start_job` saves each attachment to its own `mkdtemp` subdirectory under the session temp dir and checks the result stays there. This keeps the original name for the email without letting `../` or absolute paths escape. Tests: `TestAttachmentSaving` (traversal) and `TestAttachmentDelivery` (names and bytes reach the Graph request) in `test_web.py`; in `test_web_e2e.py`, the XSS tests, `SPECIAL_COLUMNS` (legitimate column names containing `&`, `<`, quotes), `TestAttachmentsFromBrowser`, and exact paste output (`test_trix_paste_cleanup_exact_output`, plus real clipboard pastes checked against `PASTE_EXPECTED`, recorded before the inert-document change). If a change alters `PASTE_EXPECTED`, treat it as a behaviour change, not a fixture to refresh.
- **Preview:** Client-side template rendering in JS for immediate feedback. Server-side `/api/get-recipients` handles email validation and filtering. Server-side `/api/preview-template` available for placeholder validation.
- **Logging:** Three independent destinations, each with its own level: (1) **Console** via RichHandler on stderr (`--log-level`, default INFO), (2) **File** via `RotatingFileHandler` (5 MB, 3 backups) always at DEBUG — enabled by `--log-file` or automatically in PyInstaller bundles, (3) **Browser panel** via `JobLogHandler` at INFO (web UI only, during send jobs). Both `mergemail365` and `mergemail365-web` support `--log-level` and `--log-file`. Enabling file logging never affects console verbosity (each handler has its own `setLevel()`). Log file location is platform-specific: `~/Library/Logs/mergemail365/mergemail365.log` on macOS, `%LOCALAPPDATA%/mergemail365/logs/mergemail365.log` on Windows. All API error paths (`upload-spreadsheet`, `get-recipients`, `start-job`, background job) log exceptions at DEBUG with full tracebacks via `logger.debug(..., exc_info=True)`. `GET /api/log-path` returns the log file path for discoverability. Setup in `console.py:setup_logging()` and `setup_file_logging()`, path resolution in `_paths.py:log_dir()`. The file format includes `[%(threadName)s]`; job threads are named `job-<id prefix>`. When file logging is on, `mergemail365-web` also calls `diagnostics.py:start_diagnostics()`, which logs package versions and runs a `StallWatchdog`: a heartbeat thread that logs a WARNING when it wakes ≥10s late and re-arms `faulthandler.dump_traceback_later` each second, so a ≥30s stall dumps every thread's stack to `mergemail365-stalls.log` (the C timer doesn't need the GIL). Added to diagnose a v0.3.1 Windows desktop report where network requests stalled for minutes until the user clicked in the window.

**Routes:**

| Route | Method | Purpose |
|---|---|---|
| `/` | GET | Serve wizard UI |
| `/auth/login` | GET | Start auth code flow → redirect to Microsoft |
| `/auth/callback` | GET | Exchange auth code for token |
| `/auth/status` | GET | Check if authenticated, return email + token expiry |
| `/auth/debug` | GET | Auth diagnostics (cache, token, authority) |
| `/auth/interactive` | POST | Start interactive auth via system browser (desktop mode only) |
| `/api/config` | GET | Config + full session state for recovery (includes `desktop_mode`) |
| `/api/state` | POST | Save wizard step/validation state |
| `/api/upload-spreadsheet` | POST | Upload .xlsx, return columns + preview rows |
| `/api/change-sheet` | POST | Re-read preview for a different sheet |
| `/api/get-recipients` | POST | Filtered, validated recipient list |
| `/api/preview-template` | POST | Server-side template render + placeholder validation |
| `/api/start-job` | POST | Start background send_merge(), return job ID |
| `/api/job/<id>/events` | GET | SSE stream of log + completion events |
| `/api/job/<id>/status` | GET | Job status + results (poll fallback) |
| `/api/job/<id>/stop` | POST | Stop a send before its next email |
| `/api/log-path` | GET | Log file path + exists flag (for troubleshooting) |

**Design plan:** `docs/web-ui-plan.md` contains the full design document with implementation status, security assessment, and deferred features.

### Web UI state management

State lives in three tiers, each with different lifetimes and sync characteristics.

**Tier 1 — JS memory (ephemeral, lost on reload):** Wizard workflow state is centralised in a `state` object (`window.state`): `currentStep`, `spreadsheetData`, `previewIndex`, `sendMode`, `contentVersion` (counts changes to what would be sent: the model's `version`), `testPassed`, `testRunning`, `testFailed`, `testResult`, `verifyPassed`, `verifyResult`, `sendStarted`, `sendOutcome`, `currentJobId`, `sendResults`, `requests`, `nextRequestId`, `formDirty`, `trixEditor`. `requests` records what the page is waiting for, by request id (`WizardCore.startRequest(state, kind)` with kind `"test"`, `"verify"`, `"preview"` or `"send"`, through `beginRequest()` in `app.js`); a response or job completion (and its log lines) is applied only while `requestIsCurrent(id)`. A new request replaces the previous one of its kind, `resetTestAndVerify()` drops test and dry-run requests, and any navigation, edit, sheet change or upload drops the preview request (`dropPreview()`), so a job that finishes after the user has gone back and edited can't mark the new content as tested, and a late recipient preview can't move the page to step 3. A "Stop sending" pressed before the start-job response named the job is kept as `stopQueued` on the send request and posted once the id arrives. Auth state is grouped in `_auth`: `isSignedIn`, `desktopMode`, `signInPoll`, `tokenExpiresAt`. Legacy global aliases (`window.testPassed`, `window.verifyPassed`, `window.spreadsheetData`) are defined as property accessors for E2E test compatibility. The DOM form elements (`subject-input`, `body-input`, `email-column`, `name-column`, `html-toggle`, `filter-input`, `cc-input`, etc.) are the source of truth for compose data — JS reads them directly when building form submissions rather than caching copies.

**Tier 2 — localStorage (survives reload, per-browser):** Six keys auto-saved: `mm_subject`, `mm_body`, `mm_email_col`, `mm_name_col`, `mm_html` (every 5 seconds when `state.formDirty` is true), and `mm_sheet` (on sheet change). On page load, these fill form fields that are still empty (server-restored values take precedence). Sheet selection triggers a `/api/change-sheet` call if the saved sheet differs from the server's default. Cleared by `newMerge()`. Filters, CC/BCC, reply-to, importance, attachments, and send mode are intentionally not persisted — they are considered step-specific and not worth carrying across sessions.

**Tier 3 — Flask session (cookie-based, survives reload):** Auth state (`authenticated`, `ms_authenticated`, `client_id`, `tenant_id`, `auth_flow`, `csrf_token`), spreadsheet metadata (`spreadsheet_path`, `spreadsheet_tmp_dir`, `spreadsheet_info` — columns/sheets/total_rows/file_name but not row data, which would exceed the 4 KB cookie limit), and wizard progress (`current_step`, `test_passed`, `verify_passed`, `job_id`). The MSAL token cache is a separate file on disk shared with CLI auth.

**Tier 4 — Server memory (ephemeral, lost on restart):** `_jobs` dict holds active/completed `Job` objects with their event queues and results. These are not persisted — server restart loses all job state.

**Tier 5 — Temp files on disk:** Uploaded spreadsheet saved to a `tempfile.mkdtemp()` directory, tracked by `spreadsheet_tmp_dir` in the session. Cleaned up on re-upload, reset, or process exit (`atexit`).

#### Data flow and sync points

The tiers sync at specific moments, not continuously:

- **Upload/sheet change → server → JS:** `POST /api/upload-spreadsheet` and `POST /api/change-sheet` write metadata to the session and return full row data in the response. JS stores this as `spreadsheetData`. The session stores only metadata (no rows).
- **Step navigation → server:** `saveState()` POSTs `{current_step, test_passed, verify_passed}` to `/api/state` on every step change. This is a one-way push.
- **Page load → JS:** `loadConfig()` GETs `/api/config` which returns session metadata + re-reads preview rows from the temp file. JS restores `spreadsheetData` from this. Separately, localStorage restores compose fields into empty form inputs.
- **Job lifecycle → server → JS:** `POST /api/start-job` creates a server-side `Job`, stores its ID in the session, and returns it. JS connects via SSE for live events. On completion, the `testPassed`/`verifyPassed` flags are set in JS and pushed to the session.
- **Active job reconnection:** On reload after starting a send, `/api/config` returns the `active_job_id`: any send job still running (even if the session doesn't name it, because a reload before the start-job response arrived never got the session cookie), otherwise the session's job if it is a send (`session["job_id"]` is set for every job). JS reconnects to the SSE stream and resumes the send UI at step 6; if the send already finished, the stream ends at once and the results are shown. Test/verify jobs are not reconnected: reload returns to step 1.

#### What is and is not recoverable after page reload

| State | Recovered? | Source |
|---|---|---|
| Auth status | Yes | MSAL token cache on disk, checked via `/auth/status` |
| Uploaded spreadsheet | Yes | Temp file on disk, path in session |
| Sheet selection | Yes | localStorage (`mm_sheet`); triggers `/api/change-sheet` on reload if different from default |
| Spreadsheet preview rows | Yes | Re-read from temp file by `/api/config` |
| Column selections | Partially | localStorage has `mm_email_col`/`mm_name_col`, restored if columns still match |
| Subject / body / HTML mode | Yes | localStorage (`mm_subject`, `mm_body`, `mm_html`) |
| Filtered recipient list | No | Only in JS memory; must re-run `/api/get-recipients` |
| Test/verify passed flags | No | Session has them, but JS always resets to `false` on load (by design — results are transient) |
| Active send job | Yes | `session["job_id"]` + `_jobs` dict; JS reconnects to SSE stream |
| Send results | No | In-memory `Job.results`, lost if not fetched before server restart |
| Filters, CC/BCC, reply-to, importance, attachments | No | DOM-only, not persisted |

#### Dependency graph: what invalidates what

The wizard is a pipeline — upstream changes invalidate downstream state. The invalidation rules:

```
Spreadsheet upload / sheet change (Step 1)
  └→ columns, rows, preview table, total_rows
      └→ Column selections may become invalid (Step 2)
          └→ Placeholder chips refresh
          └→ Filtered recipients invalid (Step 3)
              └→ Test results invalid (Step 4)
                  └→ Verify results invalid (Step 5)
                      └→ Send confirmation invalid (Step 6)
```

In the current implementation:
- **Step 1 → Step 2:** `initComposeStep()` re-populates column dropdowns when entering Step 2. Previous selections are preserved if the column name still exists in the new data; otherwise reset to empty.
- **Step 2 → Step 3:** `loadPreview()` always re-fetches filtered recipients from the server when advancing to Step 3. No caching of the recipient list across step transitions.
- **Step 3 → Steps 4–6:** `confirmGoBack()` warns the user and resets `testPassed`/`verifyPassed` when navigating backward from any step ≥ 3.
- **Sheet change on Step 1:** Calls `/api/change-sheet`, replaces `spreadsheetData` entirely. If the user had already advanced to Step 2 and goes back, re-entering Step 2 will refresh dropdowns from the new column list.

There is no automatic cascade — invalidation happens lazily when the user navigates forward again.

#### MVVM suitability analysis

The current architecture is **imperative DOM manipulation** — JS functions directly read/write DOM elements and manage visibility. State is scattered across JS variables, DOM `.value` properties, and the server session with ad-hoc sync. This works for the current scale but creates several structural tensions:

**What MVVM would improve:**
- **Single source of truth.** Currently, compose data lives simultaneously in DOM form fields, localStorage (backup), and is re-read from the DOM when building form submissions. A ViewModel would be the one canonical location, with DOM bindings as a projection. This eliminates the "which is current?" question.
- **Declarative invalidation.** The dependency graph above (sheet change → columns → placeholders → recipients → test → verify → send) maps directly to reactive computed properties. Currently this cascade is handled by imperative function calls (`initComposeStep()`, `resetTestAndVerify()`, `showPlaceholderChips()`) spread across navigation handlers. A reactive ViewModel would make "spreadsheet columns changed" automatically propagate to dependent UI without explicit wiring.
- **Consistent state on reload.** A ViewModel serialised to/from a single persistence layer (instead of the current three-tier split) would make recovery deterministic. Currently, reload recovery involves merging data from `/api/config`, localStorage, and DOM defaults with priority rules scattered across `loadConfig()` and `DOMContentLoaded`.
- **Testability.** ViewModel logic (validation rules, navigation guards, state transitions) could be unit-tested in isolation from the DOM. Currently, testing wizard behaviour requires Playwright E2E tests.

**What MVVM would not improve (or would complicate):**
- **Server-side jobs and SSE.** The background job lifecycle (start → stream events → poll status → show results) is inherently async and event-driven. MVVM doesn't simplify this — it would still need imperative event handlers that update the ViewModel.
- **File upload and temp files.** Binary file handling is inherently imperative and tightly coupled to the server. No ViewModel pattern helps here.
- **Framework weight.** The app currently has zero JS build step and zero dependencies (vanilla JS + Pico CSS). Adopting MVVM properly would require either a framework (Vue, Svelte, Preact) or a hand-rolled reactive system. For a single-page, single-user, local-only tool, this may not be worth the added complexity. The current codebase is ~1500 lines of JS.

**Current approach (partial MVVM):** The first step has been taken: a `state` object centralises wizard workflow state (step, spreadsheet data, progress flags, job tracking) and an `_auth` object groups auth state. DOM form fields remain the source of truth for compose data, with `state` owning only workflow/progress state. This gives single-source-of-truth for navigation and invalidation without a full reactive framework. `state.resetTestAndVerify()` and `state.resetAll()` centralise invalidation logic. Legacy global property aliases (`window.testPassed` etc.) maintain backward compatibility for E2E tests.

A further step toward full MVVM would add computed getters (e.g. `canAdvanceToPreview`) and a `render()` function that projects state to DOM, replacing the manual `show()`/`hide()`/`updateStepUI()` calls. For the current scale (~1600 lines of JS, single-user local tool), the partial extraction is sufficient.

#### Current consistency guarantees and gaps

**Consistent by design:**
- The server re-validates recipients on `/api/start-job` (defense-in-depth — doesn't trust the client's filtered list).
- `buildJobFormData()` reads directly from DOM at submission time, so stale JS variables can't cause a wrong send.
- Auth tokens are always acquired via `token_provider()` at send time, not cached in JS state.

**Known inconsistency gaps:**
- `testPassed`/`verifyPassed` are saved to the server session but intentionally not restored on reload — the user must re-run these steps. This is a deliberate UX choice (results are transient), not a bug.
- `sendMode`, filters, CC/BCC, reply-to, importance, and attachments are DOM-only and lost on reload. For a local single-session app this is acceptable.

## Email address pipeline

Addresses enter the system in different forms and are normalised into `EmailAddress` before being serialised for the Graph API.

**Input sources:**
- **Primary recipients** (`--email-column`): bare addresses from the spreadsheet. Display name comes from a separate `--name-column` (if set); empty/whitespace cells yield `name=None`.
- **CC / BCC / reply-to / bcc-blast-to**: accept RFC 2822 `"Display Name <email>"` or bare `email@example.com`. CC/BCC/reply-to are comma-separated (CLI) or `str | list[str]` (Python API).
- **Test email** (`--test-email`): bare address; display name taken from the first row's `name_column` if set.
- **BCC blast batch recipients**: constructed with `name=None` (bare addresses only).

**Parsing** (`api.py`): `_parse_one_addr()` uses `email.utils.parseaddr` to split name and address; empty name becomes `None`, empty address falls back to the raw string. `_parse_address_entries()` splits comma-separated strings and calls `_parse_one_addr` on each.

**Construction in `send_all`** (`sender.py`): `EmailAddress` is built directly from the spreadsheet row — `name` is looked up via `name_column` and set to `None` if the column isn't specified or the cell is blank.

**`to_graph()` serialisation** (`sender.py`): produces `{"emailAddress": {"address": "..."}}`. The `"name"` key is **only included when `name` is not `None`** — omitting it entirely when there is no display name. This applies uniformly to `toRecipients`, `ccRecipients`, `bccRecipients`, and `replyTo`.

**`__str__` display**: with name → `"Alice <alice@example.com>"`; without → `"alice@example.com"`. Used in logging and confirmation prompts.

## Graph API quirks

Tested empirically via `examples/test_empty_to.py` (results in `out.txt`):

- **`toRecipients: []`** (empty array) — accepted (HTTP 202). The email is delivered with no visible To header.
- **`toRecipients` omitted entirely** — accepted (HTTP 202). Same behaviour as empty array.
- **`toRecipients` with a normal address** — accepted (HTTP 202). Standard behaviour.
- **`undisclosed-recipients:;`** as a To address — rejected (HTTP 400). The Graph API does not resolve this RFC 2822 group syntax and returns "Recipient is not resolved".

Implication for BCC blast: it is safe to send with `toRecipients: []` or omit the field, but `--bcc-blast-to` uses a real address in the To field to avoid surprising recipients with a blank To header.

## Supply-chain policy

Never adopt a package, tool, action or vendored file version that has been public for less than 7 days. Python packages are enforced by `exclude-newer = "7 days"` in `pyproject.toml` — don't remove or shorten it. Vendored JS/CSS go through `scripts/update-vendor.sh` (pinned versions, npm-date check). GitHub Actions are pinned to commit SHAs with a version comment, and uv/Biome versions are pinned in the workflows; check release dates before bumping any of them. See `docs/upgrade-plan.md`.

## Formal model of the wizard

`spec/wizard.qnt` is a Quint model of the web UI workflow layer: steps, test/verify flags, Next/Back button state, background job completions (as separate actions that can interleave with navigation), reload and New merge, the send loop and Stop, and sign-in (token cache vs what the page shows, token expiry, the job token provider). Three variants: `buggy` (`ROUND = 0`) is the code before any fixes in `docs/quint-model-plan.md`, `partial` (`ROUND = 1`) has the round 1 fixes (bugs 1–9) only, and `fixed` (`ROUND = 2`) is the current code; `FIXED` and `FIXED2` gate the two rounds. Handlers that `await` a request whose answer changes the page (the recipient preview, starting a send) are split into a request action and a response action, so clicks can land in between; do the same for any new awaiting handler. Each action cites the code it transcribes (`// app.js: ...`, `// environment: ...`): copy guards and effects from the code, faults included, not from intent. `spec/coverage.toml` maps every UI and server entry point to model actions or excludes it with a reason, and `spec/requirements.md` lists the requirements and the invariant or witness that checks each; `tests/test_spec_coverage.py` keeps both in step with the code and `spec/check.sh`. When changing wizard navigation, job handling, sign-in or reload behaviour in `app.js` or `web/app.py`, update the action that cites the changed function, `coverage.toml` and `requirements.md`, and rerun `spec/check.sh fixed` (Apalache bounded model checking; needs Java and local port 8822; several minutes per invariant) and `quint test --main=fixed --max-samples=1 --backend=typescript spec/wizard.qnt`. Quint is pinned to 0.32.0 (supply-chain cooldown). See `docs/quint-model-plan.md` for the plan, bugs found and tooling notes.

## Testing

Tests use `responses` library to mock HTTP calls to Graph API. An autouse fixture in `conftest.py` fails any test that makes a real HTTP request to a non-localhost host. MSAL mocks use `create_autospec` against the real `PublicClientApplication` so signature changes are caught; `test_msal_contract.py` runs real msal end to end against `responses`-mocked Entra endpoints. Auth (`mail_merge.auth.acquire_token` and `mail_merge.auth.acquire_token_interactive_flow`) is monkeypatched in CLI/API tests that need authentication. The `sample_xlsx` and `body_template_file` fixtures in `conftest.py` create temporary test files.

**Web UI tests** span four files:
- `test_web.py` — Flask test client tests for all routes, CSRF, auth, job lifecycle, options pass-through. Uses `web_client` fixture (pre-authenticated test client).
- `test_web_e2e.py` — Playwright browser tests for the full wizard flow. Flask runs in a background thread with mocked Graph API and MSAL. Uses module-scoped `live_server` fixture.
- `test_web_cli.py` — entry point and argument parsing for `mergemail365-web`.
- `test_web_robustness.py` — edge cases (empty uploads, malformed requests).
- `test_web_e2e_workflow.py` — Playwright regressions for workflow bugs found by the Quint model (stale job completions, button state, reload, sign-in gate). Replaces `send_merge` with a `JobGate` so each test controls when every job finishes, and answers `/auth/status` through an `AuthStub` (signed in by default; tests flip `signed_in`).
- `tests/js/*.test.js`, run by `test_wizard_core_js.py` — Node (`node --test`, no dependencies) unit tests for `wizard-core.js`; skipped if Node isn't installed.
- `test_spec_coverage.py` — keeps `spec/wizard.qnt`, `spec/coverage.toml`, `spec/requirements.md` and `spec/check.sh` in step with the code (no browser, no Quint).
- `test_auth_additions.py` — auth code flow, `acquire_token_silent()`, `diagnose_auth()`, `token_expires_at()`.
- `test_api_additions.py` — `body_text`, `token_provider`, `device_code` and `should_stop` parameters on `send_merge()`.
- `test_msal_contract.py` — real msal against mocked Entra endpoints (auth code, device code, token cache, sign-out).

Playwright tests cannot launch Chromium inside the Claude Code sandbox (mach-port permission error); run them outside it. CI (`.github/workflows/test.yml`) runs the full suite on Python 3.14 (the minimum supported version) across Linux, macOS and Windows.
