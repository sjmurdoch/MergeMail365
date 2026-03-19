# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A Python tool that sends personalised emails via Microsoft Graph API. Recipients come from an Excel spreadsheet, and the email body/subject use `{{column_name}}` placeholders. Has three interfaces: CLI (`mail-merge`), Python API (`send_merge()`), and a web UI (`mail-merge-web`).

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

# CLI usage (after install) — dry run by default, add --send to deliver
uv run mail-merge --spreadsheet recipients.xlsx --body body.txt --subject "Hello {{name}}" --email-column email
uv run mail-merge --spreadsheet recipients.xlsx --body body.txt --subject "Hello {{name}}" --email-column email --send

# Web UI — opens browser automatically
uv run mail-merge-web
uv run mail-merge-web --port 8080
uv run mail-merge-web --desktop  # native window (requires pywebview)
```

## Architecture

Source lives under `src/mail_merge/` (src layout). There are three entry points:

1. **CLI** (`cli.py:main()`) — parses args, sets up logging, delegates to `send_merge()`, converts exceptions to exit codes.
2. **Python API** (`api.py:send_merge()`) — single function mirroring all CLI flags. Raises exceptions (`FileNotFoundError`, `ValueError`, `RuntimeError`) instead of returning exit codes. Returns `list[SendResult]`.
3. **Web UI** (`web/__init__.py:main()`) — Flask app with a 5-step wizard (Setup → Preview → Test → Verify → Send). Runs on localhost, opens browser automatically. See "Web UI" section below.

The orchestration flow (in `api.py`) is strictly ordered: resolve config → read spreadsheet → validate emails → apply filters → resume (skip previous successes) → apply batch size → read body template → validate all placeholders (abort if any unresolvable) → parse CC/BCC/reply-to → validate recipient count → process attachments → confirm → authenticate (MSAL device code) → send → merge results → report. All validation happens before any sending. Resume and batch size are skipped for `--test-email` (which only needs one recipient's data for rendering). Resume works for both individual sends and BCC blast mode.

Key design decisions:
- **`config.py`** reads `~/.mail-merge.toml` for persistent `client-id` / `tenant-id`. Precedence: CLI flag → env var → config file → default (`"common"` for tenant-id).
- **`EmailAddress`** dataclass (in `sender.py`) is the unified internal representation for email addresses throughout the codebase. It holds `address: str` and `name: str | None`, and provides `to_graph()` to convert to the Microsoft Graph API wire format (`{"emailAddress": {"address": ..., "name": ...}}`). Three representation layers are used consistently: user-facing strings (`"Display Name <email>"`) at the CLI/API boundary, `EmailAddress` objects internally, and Graph API dicts only at the point of HTTP serialisation in `send_one`.
- **`api.py`** contains `send_merge()`, the shared orchestration function used by both CLI and Python callers. Accepts `str | Path` for file args, `str | list[str]` for address lists. `_parse_one_addr()` parses a single RFC 2822 address string into an `EmailAddress`. `_parse_address_entries()` normalises all address inputs (cc/bcc/reply-to) into `list[EmailAddress]`; parsed values are bundled into a `MessageOptions` dataclass and passed to sender functions. `sender.py` functions (`send_one`, `send_bcc_blast`, `send_all`) accept `opts: MessageOptions` for shared message-formatting parameters (max_retries, importance, cc, bcc, html, save_to_sent_items, attachments, reply_to). The primary recipient is passed as an `EmailAddress` parameter `to` (bundling address and display name together). `send_all` accepts `name_column` to look up per-recipient names from the spreadsheet and construct an `EmailAddress` per recipient.
- **`auth.py`** uses lazy import in `api.py` — only imported when authentication is actually needed (skipped for dry runs)
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
- **`--filter`** (repeatable) filters recipients by column values (`column=value` or `column!=value`, AND logic, case-insensitive)
- **`--no-resume`** disables automatic resume; by default with `--output`, previous successes in the CSV are automatically skipped
- **`--batch-size N`** limits how many emails are sent per invocation
- **`--name-column`** specifies a spreadsheet column containing recipient display names; each email's `To:` header includes the name (e.g. `"Alice <alice@example.com>"`). In BCC blast mode, use `--bcc-blast-to "Display Name <email>"` instead.
- Recipient count validation: errors if to + cc + bcc exceeds the Graph API limit of 500

## Web UI

The web interface lives under `src/mail_merge/web/` and is installed as `mail-merge-web`. Flask backend (`web/app.py`) + vanilla JS single-page app (`web/static/app.js`) + Pico CSS. No build step, no JS framework.

**Dependencies:** `flask>=3.0` (optional `web` extra), `pywebview>=5.0` (optional `desktop` extra). Install with `uv sync --extra web`.

**Key files:**
- `web/__init__.py` — entry point: port discovery, startup token, browser launch
- `web/app.py` — Flask app factory, all routes, background job management
- `web/templates/index.html` — single Jinja2 template with all 5 wizard steps
- `web/static/app.js` — wizard navigation, SSE streaming, client-side template preview
- `web/static/style.css` — custom styles (step indicator, chips, log panel, callouts)
- `web/static/pico.min.css` — bundled Pico CSS v2 (no CDN)

**Architecture:**
- **Auth:** OAuth 2.0 Authorization Code flow with PKCE (browser-native), vs device code flow for CLI. Both share the same MSAL token cache. Auth functions in `auth.py`: `initiate_auth_code_flow()`, `acquire_token_by_auth_code()`, `diagnose_auth()`, `token_expires_at()`.
- **`send_merge()` integration:** The web UI calls `send_merge()` with two web-specific parameters: `body_text` (inline string, no temp file) and `token_provider` (callable for silent token acquisition, bypasses device code flow). Always passes `confirm=False`, `resume=False`.
- **Background jobs:** `send_merge()` runs in a daemon thread. `JobLogHandler` captures `mail_merge` logger output into an event queue. SSE (`/api/job/<id>/events`) streams log entries to the browser. Job results are fetched via `/api/job/<id>/status` which calls `report.summarize()`.
- **Safety limits:** 99-recipient cap (enforced server-side), fixed 2s send delay, mandatory test email and dry run steps, "SEND" confirmation typing.
- **Session:** Startup token (like Jupyter) for access control. CSRF token on all POST routes. 24-hour session lifetime with sliding window. Server-side state persistence (`/api/state`) + client-side localStorage auto-save.
- **Preview:** Client-side template rendering in JS for immediate feedback. Server-side `/api/get-recipients` handles email validation and filtering. Server-side `/api/preview-template` available for placeholder validation.

**Routes:**

| Route | Method | Purpose |
|---|---|---|
| `/` | GET | Serve wizard UI |
| `/auth/login` | GET | Start auth code flow → redirect to Microsoft |
| `/auth/callback` | GET | Exchange auth code for token |
| `/auth/status` | GET | Check if authenticated, return email + token expiry |
| `/auth/debug` | GET | Auth diagnostics (cache, token, authority) |
| `/api/config` | GET | Config + full session state for recovery |
| `/api/state` | POST | Save wizard step/validation state |
| `/api/upload-spreadsheet` | POST | Upload .xlsx, return columns + preview rows |
| `/api/get-recipients` | POST | Filtered, validated recipient list |
| `/api/preview-template` | POST | Server-side template render + placeholder validation |
| `/api/start-job` | POST | Start background send_merge(), return job ID |
| `/api/job/<id>/events` | GET | SSE stream of log + completion events |
| `/api/job/<id>/status` | GET | Job status + results (poll fallback) |
| `/api/job/<id>/stop` | POST | Request graceful stop |

**Design plan:** `docs/web-ui-plan.md` contains the full design document with implementation status, security assessment, and deferred features.

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

## Testing

Tests use `responses` library to mock HTTP calls to Graph API. Auth (`mail_merge.auth.acquire_token`) is monkeypatched in CLI tests that need authentication. The `sample_xlsx` and `body_template_file` fixtures in `conftest.py` create temporary test files.

**Web UI tests** span four files:
- `test_web.py` — Flask test client tests for all routes, CSRF, auth, job lifecycle, options pass-through. Uses `web_client` fixture (pre-authenticated test client).
- `test_web_e2e.py` — Playwright browser tests for the full wizard flow. Flask runs in a background thread with mocked Graph API and MSAL. Uses module-scoped `live_server` fixture.
- `test_web_cli.py` — entry point and argument parsing for `mail-merge-web`.
- `test_web_robustness.py` — edge cases (empty uploads, malformed requests).
- `test_auth_additions.py` — auth code flow, `diagnose_auth()`, `token_expires_at()`.
- `test_api_additions.py` — `body_text` and `token_provider` parameters on `send_merge()`.
