# Plan: Web Interface for mail-merge

## Context

The mail-merge tool currently has a CLI and Python API but no browser-based interface. A web UI on localhost will make it more accessible — users can upload spreadsheets, compose templates with live preview, and monitor send progress visually, without memorising CLI flags.

## Approach: Flask + Vanilla JS Single-Page App

**Framework:** Flask (single new dependency, minimal overhead for a local tool).
**Frontend:** Single HTML page with vanilla JavaScript — no build step, no JS framework.
**Styling:** Pico CSS v2 served from a bundled local copy (`static/pico.min.css`). No CDN — for a localhost app, CDN adds network dependency with zero performance benefit, and complicates offline/PyInstaller use. Semantic HTML gets automatic styling (forms, tables, buttons, light/dark mode). Custom CSS only for wizard-specific elements (step indicator, progress panel, placeholder chips).
**Existing code:** Modified where it makes the integration cleaner.

## Authentication: Authorization Code Flow with PKCE

Since the user is already in a browser, use the OAuth 2.0 Authorization Code flow with PKCE instead of device code flow. This is the standard approach for browser-accessible apps.

**Flow:**
1. User clicks "Sign In" in the web UI
2. Flask calls `msal_app.initiate_auth_code_flow(scopes=SCOPES, redirect_uri="http://localhost:{port}/auth/callback")` and stores the flow dict in the Flask session
3. User is redirected to `login.microsoftonline.com` to authenticate
4. Microsoft redirects back to `/auth/callback` with an authorization code
5. Flask calls `msal_app.acquire_token_by_auth_code_flow(flow, request.args)` to exchange the code for a token
6. Token is cached in the same MSAL cache file (`~/.mail-merge-token-cache.json`)
7. When `send_merge()` later calls `acquire_token()`, silent acquisition succeeds from the shared cache

**Setup requirement:** The Azure AD app registration needs `http://localhost:5050/auth/callback` added as a redirect URI (under "Mobile and desktop applications" for public clients). This is a one-time setup step, documented in the UI. Note: Entra ignores the port for localhost URIs, so this works on any port — no re-registration needed if the port auto-increments.

## API Compatibility & Maintainability Review

**Constraint:** `send_merge()` is used by external callers. All changes must be backward-compatible — only add optional parameters with defaults that preserve existing behaviour. No removal or renaming of existing parameters.

Reviewed `api.py`:179-561, `sender.py`, `cli.py`:

1. **`body_text` parameter.** Add `body_text: str | None = None` to `send_merge()`. When provided, use directly as the body template string — no temp file needed. Make `body` optional (default `None`) with validation: at least one of `body` or `body_text` must be provided, otherwise raise `ValueError`. If both are provided, `body_text` takes precedence. Existing callers that pass `body` are unaffected (it still works as before).

2. **Token provider.** Add `token_provider: Callable[[], str] | None = None` to `send_merge()`. When provided, skip the entire auth block (lines 453-489). Named `token_provider` to avoid shadowing the existing `get_token` local variable (line 454/470 of `api.py`). Existing callers pass nothing, device code flow unchanged.

3. **Repeated work across wizard steps.** Each step calls `send_merge()` independently (re-reads spreadsheet, re-validates). Acceptable with 99-recipient cap. The web layer builds common kwargs once via a `_build_merge_kwargs(session_data)` helper, then each call overrides only the mode-specific flags (`send`, `test_email`, `confirm`). This avoids copy-paste across the 3 call sites.

4. **`print_summary()` and `write_csv()`.** `print_summary()` writes Rich-formatted output to server stderr — harmless but produces ANSI escape codes. Extract a `summarize()` data function from `report.py` that returns structured counts; both `print_summary()` and the web UI call it. `write_csv()` only runs when `send=True and output is set`. Web passes no `output`.

5. **`confirm` prompt.** Already disabled when `send=False`/`test_email` set. Web passes `confirm=False`. Note: if `confirm=True` is accidentally passed from the web layer, `send_merge()` would block on `console.input()` — a footgun. The web layer must always pass `confirm=False`.

## Changes to Existing Files

### `src/mail_merge/auth.py`

Add two new functions (existing `acquire_token()` unchanged):

```python
def initiate_auth_code_flow(
    client_id: str,
    tenant_id: str = "common",
    redirect_uri: str = "http://localhost:5050/auth/callback",
) -> dict[str, Any]:
    """Start an authorization code flow. Returns the flow dict to store in the session."""

def acquire_token_by_auth_code(
    client_id: str,
    tenant_id: str = "common",
    auth_code_flow: dict[str, Any],
    auth_response: dict[str, str],
) -> str:
    """Complete the authorization code flow. Returns the access token."""
```

Both use `_load_cache()` / `_save_cache()` so the token cache is shared with the CLI's device code flow.

Add a diagnostic function:

```python
def diagnose_auth(client_id: str, tenant_id: str = "common") -> dict[str, Any]:
    """Test Entra auth config and return diagnostic info."""
```

Returns a dict with:
- `cache_exists`: whether the token cache file exists
- `cache_path`: path to the cache file
- `accounts`: list of cached accounts (email/username, not tokens)
- `token_valid`: whether silent acquisition succeeds
- `token_expires_at`: expiry time of current token (if valid)
- `authority_reachable`: whether the Entra authority URL responds
- `client_id_valid`: whether the app registration exists (test via MSAL app creation)
- `error`: any error message if something fails

This powers the `GET /auth/debug` endpoint and is also useful for CLI troubleshooting.

### `src/mail_merge/api.py`

Two new optional parameters on `send_merge()`:

```python
def send_merge(
    ...
    body_text: str | None = None,
    token_provider: Callable[[], str] | None = None,
) -> list[SendResult]:
```

- `body_text`: Use directly as body template string. Takes precedence over `body` file path if both provided. Avoids writing to temp files. `body` becomes optional (default `None`); at least one of `body`/`body_text` must be provided. Existing callers pass `body` — unchanged.
- `token_provider`: Skip the entire auth block (lines 453-489) and use this callable instead. Named `token_provider` to avoid shadowing the existing `get_token` local variable. Existing callers pass nothing — device code flow unchanged.

### `src/mail_merge/report.py`

Extract a data-returning function from `print_summary()`:

```python
def summarize(results: list[SendResult]) -> dict[str, Any]:
    """Return structured summary: total, sent, failed counts + failed details."""
```

`print_summary()` calls `summarize()` internally. The web UI also calls `summarize()` to render the HTML summary. Single source of truth for summary logic.

### `src/mail_merge/excel.py`

Add a preview function that doesn't require `email_column`:

```python
def read_preview(path: str | Path, sheet_name: str | None = None, max_rows: int = 5) -> tuple[list[str], list[dict[str, str]]]:
    """Read column headers and first N rows. Returns (columns, rows)."""
```

Shares internal logic with `read_recipients()` (size check, header parsing, value stringification). Used by the web upload endpoint instead of calling openpyxl directly.

### `pyproject.toml`

1. Add optional dependencies:
   ```toml
   [project.optional-dependencies]
   web = ["flask>=3.0"]
   desktop = ["flask>=3.0", "pywebview>=5.0"]
   ```
2. Add entry point: `mail-merge-web = "mail_merge.web:main"`

## New Files

```
src/mail_merge/web/
    __init__.py          # Entry point: main() with --desktop flag support
    app.py               # Flask app factory, routes, background job logic
    templates/
        index.html       # Single-page wizard UI (Jinja2)
    static/
        pico.min.css     # Pico CSS v2 (bundled for offline/PyInstaller use)
        style.css        # Custom CSS for wizard elements (step indicator, chips, log panel)
        app.js           # Vanilla JS for wizard, uploads, preview, SSE
tests/test_web.py        # Web interface tests
mail_merge_web.spec      # PyInstaller spec for building standalone app
```

## Architecture

### Entry Point (`web/__init__.py`)

`main()` parses `--host` (default `127.0.0.1`), `--port` (default `5050`), and `--desktop` flag. Two modes:

- **Browser mode** (default): Binds the socket first (confirms port availability), opens the default browser via a short-delay Timer thread, then starts Flask on the pre-bound socket. This avoids the browser hitting a connection-refused page before Flask is ready.
- **Desktop mode** (`--desktop`): Uses `pywebview` to open a native OS window with the Flask app embedded. No external browser needed.

**Port conflict handling:** If the default port (5050) is in use, auto-increment and try the next port (5051, 5052, ...) up to 5099. Log the actual port being used. The auth callback redirect URI uses the actual port, but **Entra ignores the port component for localhost redirect URIs** — so a single registered `http://localhost:5050/auth/callback` (or `http://localhost/auth/callback`) will work on any port. No additional Entra configuration needed when the port changes.

Installed as `mail-merge-web` console script. The desktop mode is the intended path for non-CLI users — they double-click a packaged app that starts in desktop mode automatically.

### Backend Routes (`web/app.py`)

| Route | Method | Purpose |
|---|---|---|
| `GET /` | — | Serve the wizard UI |
| `GET /auth/login` | — | Start auth code flow, redirect to Microsoft login |
| `GET /auth/callback` | — | Handle redirect from Microsoft, exchange code for token |
| `GET /auth/status` | JSON | Check if user is authenticated (cached token valid?) |
| `POST /api/upload-spreadsheet` | multipart | Upload .xlsx, return columns + 5 preview rows |
| `POST /api/preview-template` | JSON | Render subject + body with sample row data |
| `POST /api/start-job` | multipart | Start `send_merge()` in background thread, return job ID |
| `GET /api/job/<id>/events` | SSE | Stream log messages and completion/failure events |
| `GET /api/job/<id>/status` | JSON | Poll fallback for job status + results |
| `POST /api/job/<id>/stop` | JSON | Request graceful stop of running job |
| `GET /api/config` | JSON | Return client_id/tenant_id from config file |
| `GET /auth/debug` | JSON | Test Entra auth config and return diagnostic info |

### Spreadsheet Upload

Call `excel.read_preview()` (new function, shares logic with `read_recipients()`). Save uploaded file to a temp dir. Return column names and preview data. Reuses existing size checks, header parsing, and value stringification from `excel.py`.

### Template Preview

Call `template.render()` and `template.validate_template()` from `src/mail_merge/template.py` with subject, body text, and sample data from the first spreadsheet row. CC/BCC/reply-to fields parsed via `_parse_address_entries()` from `api.py` — reuse existing address parsing, not re-implemented in the web layer.

### Background Jobs

```python
class JobStatus(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class Job:
    id: str
    status: JobStatus
    events: queue.Queue       # SSE log events (transient, drained by consumer)
    results: list[SendResult] | None  # Set atomically on completion
    error: str | None
```

- `events` carries log messages only (transient). `results` carries structured outcome (set once on completion). No duplication.
- In-memory dict. One job at a time.
- Custom `JobLogHandler(logging.Handler)` captures `mail_merge` logger output → event queue.
- Background thread calls `send_merge(confirm=False, token_provider=..., resume=False)` with no `output` path.
- The `token_provider` callable does silent acquisition from the shared MSAL cache.
- Temp files persist until job completes, then cleaned up. Abandoned sessions (user closes browser) cleaned up periodically (delete temp dirs older than 1 hour) or on session expiry.
- `atexit` handler cleans up any remaining temp dirs on server shutdown.

### SSE Implementation Details

- `queue.get(timeout=15)` with SSE comment keepalive (`: keepalive\n\n`) on timeout.
- Sentinel value `None` pushed to queue on job completion — SSE generator stops.
- On client disconnect, generator catches write exception and exits cleanly.
- `results` set via single dict assignment (GIL-safe) after `send_merge()` returns.
- `/auth/status` is a lightweight cache check (called frequently). `/auth/debug` does network I/O (called only on user action).

### Output Log & Resume

No output CSV is written during sending. Results are held in memory (the `list[SendResult]` returned by `send_merge()`). The Step 5 results table displays per-recipient success/failure, and a "Download CSV" button lets the user save the results. Resume is not supported in the web UI — with the 99-recipient cap this is acceptable. For large resumable sends, use the CLI.

### Frontend: Wizard-Style UI

A step indicator at the top shows: `Setup > Preview > Test > Verify > Send`. Each step has Back/Next buttons.

**Persistent header:** After sign-in, show "Sending as: user@example.com" at the top of every step. This is critical — sending from the wrong account is irreversible.

**Session awareness:** Show a session timer ("Session expires in 47m"). Warn at 10 minutes remaining. Auto-save form state to browser `localStorage` so the user can restore after re-authenticating or accidental page close.

**Safety limits:** The web UI enforces a maximum of 99 recipients and a fixed 2-second delay between sends. These are not configurable in the UI. For larger sends, use the CLI.

**Step 1: Setup**
- Auth: "Sign In with Microsoft" button → redirects to Microsoft login → returns authenticated. After sign-in, show account identity ("Signed in as user@example.com" with green checkmark). Sign-in not required for "Next" — only required before Step 3 (Test Email).
- Auth debug: "Test Connection" button next to sign-in. Calls `GET /auth/debug` and displays diagnostics: cache status, token validity, authority reachability, errors. Helps users diagnose misconfigured app registrations, expired tokens, or network issues before attempting sign-in.
- Config: client_id, tenant_id inputs (pre-filled from `GET /api/config`). Show "Loaded from config file" badge when pre-filled. If client_id is empty, show callout: "You need an Azure AD app registration before you can send emails. [Setup guide]". For tenant_id, hint: "Leave as 'common' if unsure."
- Spreadsheet: file upload → column preview table + dropdowns for email_column, name_column, sheet. Auto-detect email column by scanning headers for common patterns ("email", "e-mail", "email address"). After upload, show recipient breakdown: "45 rows found. 42 valid recipients. 3 skipped (empty email in rows 5, 12, 38)." Warn if name_column has empty cells: "3 recipients have empty name fields — their emails will show only the email address."
- Message: subject input, body textarea, HTML toggle. Available placeholders as clickable chips (appear after spreadsheet upload). Real-time placeholder validation — underline unrecognized placeholders in red with tooltip: "No column named 'company_name'. Did you mean 'company'?"
- Sending mode: Prominent toggle between "Individual emails" (default, supports `{{placeholders}}`) and "BCC blast" (one email, all recipients in BCC, requires a To: address). Not buried in collapsible options. When BCC blast selected: show bcc_blast_to field, disable placeholder chips, warn if body contains `{{...}}`.
- Options (collapsible): CC, BCC, reply-to, importance, attachments (show file size, validate 3MB limit inline), max_retries, filters, save-to-sent toggle. CC/BCC use placeholder text: "e.g., user@example.com or Display Name &lt;user@example.com&gt;"
- "Next" validates required fields. Blocks if recipient count exceeds 99 with message: "This web interface supports up to 99 recipients. For larger sends, use the command-line tool."

**Step 2: Preview**
- Rendered subject + body with recipient selector (dropdown or prev/next arrows): "Previewing recipient 1 of 42"
- Scrollable recipient table with email, name, rendered subject. Searchable. If filters applied: "Showing 37 of 42 recipients (filtered by: company=Acme)."
- Unresolved placeholder warnings are specific: "The placeholder `{{company_name}}` in your subject does not match any column. Available: name, email, company. Did you mean `{{company}}`?"

**Step 3: Test Email** (required)
- Prominent explanation: "This step sends one real email to verify your setup. The email is personalized with the first recipient's data but delivered only to the test address below. No emails are sent to your actual recipients."
- Test email address input (pre-populated with signed-in user's email if available)
- Show exactly what will be sent: rendered subject, To: address, body preview
- SSE log stream (filtered to user-meaningful events by default, "Show technical details" toggle for full log)
- On failure, categorised errors: 401/403 → "Permission denied. Check Mail.Send permission."; 400 → "Email rejected. Check addresses/attachments."; 429 → "Rate limited. Wait and retry."; 5xx → "Microsoft server error. Usually temporary. [Retry]"
- "Retry" button on failure; must succeed before proceeding

**Step 4: Verify** (required) — renamed from "Dry Run" for clarity
- Subheading: "No emails will be sent. This step verifies that all 42 emails can be composed correctly."
- Auto-runs `send_merge(send=False, confirm=False)` via background job
- SSE log stream shows validation progress
- Summary: "42 emails ready to send. Estimated time: ~84 seconds (2-second delay between sends)."
- Token expiry check: warn if token will expire before estimated send completion
- Must complete before proceeding

**Step 5: Send**
- Confirmation shows full context: "You are about to send 42 real emails. This cannot be undone." + From address, recipient count breakdown (To + CC + BCC), attachment list with sizes. Require typing "SEND" to confirm (not just clicking a button).
- SSE log stream with real-time progress
- **"Stop Sending" button** visible once sending starts — halts after current email completes, shows partial results: "Sending stopped. 10 of 42 sent. 32 remaining."
- `beforeunload` warning during active send: "Emails are currently being sent. Closing this tab will stop the process."
- Results table + CSV export. On failure, show human-readable errors: parse common Graph API error codes (ErrorSendAsDenied, ErrorRecipientNotFound, etc.) with "Technical details" expandable section.
- Back disabled once sending starts
- **After send completes (or is stopped):** No "Back" button. Instead show "New Merge" button + "Download CSV" button. See Navigation below.

**Navigation:**

*Pre-send (Steps 1-4):*
- Steps 1-2 freely navigable (Back/Next).
- Steps 3-4 cannot be skipped.
- Going back from Step 3+ shows confirmation: "Going back will discard your test and verification results. You will need to complete these steps again. [Go back] [Stay here]"
- Setup data (spreadsheet, body, options) is preserved when going back — only test/verify results are discarded.

*Post-send (Step 5 completed or stopped):*
- **No "Back" button** — prevents accidentally re-sending to the same recipients.
- **"New Merge" button** — clears the uploaded spreadsheet and resets wizard to Step 1. Auth session and config (client_id, tenant_id) are preserved. Message template (subject, body, options) may be restored from `localStorage` auto-save if the user wants to reuse it with a different spreadsheet.
- **"Download CSV"** — export results before starting a new merge.
- This structural separation makes it unambiguous: "Back" = fix something before sending, "New Merge" = start a fresh send operation.

### Logging

The CLI uses `RichHandler` with timestamps, emoji indicators, and colored output. The web UI provides comparable facilities:

**Log capture:** `JobLogHandler` (custom `logging.Handler`) captures all `mail_merge` logger output into the job's event queue. Each SSE event:
```json
{"type": "log", "data": {"message": "📧 Sending [1/50] to alice@example.com", "level": "INFO", "timestamp": "14:23:05"}}
```

**Log panel (Steps 3-5):**
- Auto-scrolling monospace panel
- Each line: `[timestamp] message`
- Level-based styling: INFO = default, WARNING = amber, ERROR = red bold
- Emoji indicators pass through (📋 📧 🔄 ❌ ⚠️ ✅ 🔑 ⏱️ — already in log messages)
- New entries animate in subtly

**Summary (Step 5, after send):**
Replicates `print_summary()` from `report.py` in HTML:
- Total / Sent (green) / Failed (red) counts
- Failed recipients listed with status code + error
- Built from `list[SendResult]`, not log parsing

**Server-side logging:**
- Flask also logs to stderr using `RichHandler` (same as CLI)
- Logs: startup, port, auth events, job lifecycle, errors
- Provides debugging fallback and audit trail independent of the browser

## Entra (Azure AD) App Registration Changes

The existing app registration uses the device code flow (CLI). The web UI uses the Authorization Code flow with PKCE, which requires adding a redirect URI.

### Steps to reconfigure

1. Go to [Azure Portal](https://portal.azure.com) → **Microsoft Entra ID** → **App registrations** → select your app.
2. Go to **Authentication** in the left sidebar.
3. Under **Platform configurations**, click **Add a platform** → select **Web**.
4. Set **Redirect URI** to `http://localhost:5050/auth/callback` (adjust port if using a custom `--port`).
5. Leave **Implicit grant** checkboxes unchecked (not needed — PKCE is used instead).
6. Click **Configure**.
7. Verify under **Advanced settings** that **Allow public client flows** is still set to **Yes** (needed for the CLI's device code flow to continue working).

Both flows (device code for CLI, authorization code for web) will work with the same app registration and the same client ID. They share the same token cache, so authenticating via the web UI also enables the CLI (and vice versa).

### If creating a new app registration

1. **Microsoft Entra ID** → **App registrations** → **New registration**.
2. Name: e.g. `Mail Merge`.
3. Supported account types: choose based on your organisation (single tenant or multi-tenant).
4. Redirect URI: platform **Web**, URI `http://localhost:5050/auth/callback`.
5. Click **Register**.
6. Note the **Application (client) ID** and **Directory (tenant) ID**.
7. Go to **Authentication** → **Advanced settings** → set **Allow public client flows** to **Yes** (enables device code flow for CLI).
8. Go to **API permissions** → **Add a permission** → **Microsoft Graph** → **Delegated permissions** → add `Mail.Send`.
9. (Optional) **Grant admin consent** if required by your organisation.

## Platform Compatibility

Target platforms: **macOS** (recent versions, both Intel and Apple Silicon) and **Windows** (10/11).

### Cross-platform considerations

| Concern | macOS | Windows |
|---|---|---|
| Port 5000 | Conflicts with AirPlay Receiver (macOS 12+). Default port changed to **5050** to avoid this. | No common conflict. |
| Token cache path | `~/.mail-merge-token-cache.json` | `%LOCALAPPDATA%/mail-merge/token-cache.json` (existing `_paths.py` logic) |
| Config path | `~/.mail-merge.toml` | `%LOCALAPPDATA%/mail-merge/config.toml` (existing) |
| Temp file permissions | `0o700` via `os.chmod` | ACLs differ; `tempfile.mkdtemp()` is user-restricted by default |
| Browser auto-open | `webbrowser.open()` works | `webbrowser.open()` works |
| pywebview backend | Uses WebKit (built-in) | Uses EdgeChromium (WebView2, built into Windows 10+) |
| PyInstaller output | `.app` bundle (universal2 for Intel + ARM) | `.exe` (64-bit) |
| Line endings | LF | CRLF in some contexts; use `encoding="utf-8"` consistently |

### Default port: 5050

Changed from 5000 to **5050** to avoid the macOS AirPlay Receiver conflict (port 5000 is used by `ControlCe` on macOS 12+). The Entra redirect URI documentation is updated accordingly to `http://localhost:5050/auth/callback`.

## Packaging as Standalone App

A `mail_merge_web.spec` PyInstaller spec file bundles the Flask app + pywebview into a standalone application:

- **macOS**: Produces a `.app` bundle with `--target-arch universal2` for Intel + Apple Silicon
- **Windows**: Produces a `.exe` (64-bit)

The spec file:
- Includes `src/mail_merge/web/templates/` and `src/mail_merge/web/static/` as data files
- Sets the entry point to `main(["--desktop"])` so it opens in a native window
- Bundles Flask, pywebview, msal, openpyxl, and all other dependencies

Build commands:
- macOS: `uv run pyinstaller mail_merge_web.spec`
- Windows: `uv run pyinstaller mail_merge_web.spec`

The packaged app requires no Python installation, no CLI usage — user just double-clicks to start.

## Security Assessment

### Threat Model

The web app runs on localhost on potentially shared machines, handling PII (recipient email addresses, names) and holding delegated Microsoft Graph API credentials (Mail.Send scope). Threats to consider:

1. **Other local users accessing the server** — Any user on the machine can connect to `http://localhost:5050`.
2. **PII exposure** — Spreadsheet data in temp files, in-memory state, logs, and SSE streams.
3. **Credential theft** — MSAL token cache and Flask session cookies.
4. **Cross-site attacks** — CSRF and XSS via malicious spreadsheet content.
5. **Accidental mass emailing** — Sending to wrong recipients or too many.

### Mitigations

#### Local access control: startup token (like Jupyter)

On startup, generate a cryptographically random token and include it in the auto-opened URL: `http://localhost:5050/?token=<random>`. The server:
- On first request with a valid `?token=`, sets a signed session cookie and redirects to `/`.
- All subsequent requests require the session cookie.
- Requests without a valid session or token get a 403 page explaining how to get the URL.
- Token is logged to the server console so the user who started the process can find it.

This prevents other local users from accessing the server — they don't know the token. This is the same approach used by Jupyter Notebook.

#### Flask session security

- **Secret key**: Generated via `secrets.token_hex(32)` on each startup. Not persisted. Sessions are invalidated on restart.
- **Cookie flags**: `Secure=False` (localhost doesn't use HTTPS), `HttpOnly=True`, `SameSite=Lax`.
- **Session lifetime**: 1 hour. User must re-authenticate after that.

#### CSRF protection

- All state-mutating API endpoints (`POST /api/*`) require a CSRF token.
- Use Flask's `flask.g` + a per-session CSRF token sent as a header (`X-CSRF-Token`) from JavaScript.
- The token is rendered into the HTML page and included in all `fetch()` calls.
- SSE (`GET /api/job/<id>/events`) and other GET endpoints are safe (read-only).

#### PII handling

- **Temp files**: Created with `tempfile.mkdtemp()` with `0o700` permissions (owner-only). Cleaned up immediately after job completion. `atexit` handler catches server shutdown.
- **In-memory data**: Job results and uploaded spreadsheet data held in Python dicts. Cleared when the user starts a new session or after 1 hour.
- **Log stream**: SSE events contain email addresses (necessary for showing progress). The SSE endpoint requires session authentication (see above).
- **No disk logging**: The web server does not write log files. Log output goes to stderr only (the terminal where the server was started).

#### Credential protection

- **MSAL token cache**: Already protected with `0o600` permissions (existing code in `auth.py`).
- **Flask session**: Contains only the session ID and CSRF token, not the access token. Access tokens are held in the MSAL cache, not in the Flask session.
- **Auth code flow**: Uses PKCE (Proof Key for Code Exchange), preventing authorization code interception.

#### XSS prevention

- **Spreadsheet data**: All data from the spreadsheet is rendered via Jinja2's auto-escaping (enabled by default in Flask). The preview panel, results table, and column names are all escaped.
- **Template preview**: When rendering the user's email template with `template.render()`, the output is displayed in a `<pre>` or text-content element, not injected as raw HTML — even in HTML mode, a sandboxed `<iframe srcdoc>` with `sandbox=""` (no scripts) is used for the preview.
- **SSE events**: Log messages in SSE are JSON-encoded and inserted into the DOM via `textContent`, not `innerHTML`.

#### Protection against accidental mass emailing

- **99 recipient cap**: Hard limit in the web UI, enforced server-side.
- **Fixed 2s delay**: Not configurable, prevents rate-limit issues.
- **Mandatory test email**: Must send and verify a test email before proceeding.
- **Mandatory dry run**: Must complete a dry run before the Send step.
- **Confirmation dialog**: Step 5 requires explicit confirmation with recipient count.
- **No auto-send**: The wizard requires deliberate progression through all steps.

### Residual risks (accepted)

- **localhost HTTP (not HTTPS)**: Traffic is not encrypted. On a shared machine, another user could theoretically sniff localhost traffic. Mitigated by: (a) the startup token prevents unauthorized access, (b) TLS on localhost requires self-signed certs which cause browser warnings and UX friction, (c) the MSAL token cache is the higher-value target and it's already on disk with file permissions.
- **Terminal access**: The user who started the server can see the startup token in their terminal. On a shared machine with shared terminal access, this is inherent. Users should not leave the terminal unattended.
- **Flask dev server**: Not a production WSGI server. Acceptable for a local single-user tool. Not exposed to the network (bound to `127.0.0.1`).

## Implementation Sequence

1. **Auth additions** — Add `initiate_auth_code_flow()` and `acquire_token_by_auth_code()` to `auth.py`. Add `token_provider` param to `send_merge()`. Run existing tests.

2. **Dependencies + skeleton** — Update `pyproject.toml`, create web module with `GET /` and auth routes. `uv sync`. Verify server starts and auth flow works.

3. **Spreadsheet upload + config** — Upload endpoint, config endpoint, file picker + preview table in UI. Tests.

4. **Template preview** — Preview endpoint + live preview panel. Tests.

5. **Background job + SSE + wizard steps 3-5** — Job class, start-job/events endpoints, dry run / test email / send wizard steps. Tests.

6. **Polish** — CSS (system fonts, light/dark), error handling, edge cases.

## Testing Strategy

### Patterns to follow

Existing tests use `responses` library for HTTP mocks, monkeypatch `mail_merge.auth.acquire_token` for auth. Fixtures in `conftest.py`: `sample_xlsx` (3 recipients), `body_template_file`. CLI tests call `main([...])` directly.

### `tests/test_web.py` — Web interface tests

Use Flask `test_client()` — no server needed.

**Access control & CSRF:**
- `test_index_requires_auth_token` — GET `/` without startup token → 403
- `test_auth_token_sets_session` — GET `/?token=<valid>` sets cookie, redirects
- `test_invalid_auth_token_rejected` — GET `/?token=<wrong>` → 403
- `test_post_without_csrf_rejected` — POST without `X-CSRF-Token` → 403

**Config & upload:**
- `test_config_returns_client_tenant` — GET `/api/config` returns JSON
- `test_upload_xlsx_returns_columns_and_preview` — verify columns + first 5 rows
- `test_upload_non_xlsx_rejected` — 400 for non-.xlsx
- `test_upload_empty_xlsx_rejected` — error for empty spreadsheet

**Template preview:**
- `test_preview_renders_placeholders` — verify rendered output
- `test_preview_reports_unresolved_placeholders` — unknown `{{missing}}` reported
- `test_preview_escapes_html` — XSS in sample data is escaped

**Auth endpoints:**
- `test_auth_login_redirects` — redirects to Microsoft login
- `test_auth_callback_exchanges_code` — mock MSAL, token acquired
- `test_auth_callback_handles_error` — error params → error handling
- `test_auth_status_authenticated` / `test_auth_status_not_authenticated`
- `test_auth_debug_returns_diagnostics` — mock MSAL, verify all diagnostic fields

**Job lifecycle (dry run, test email, send):**
- `test_dry_run_job_completes` — poll status until completed, verify results
- `test_dry_run_sse_events` — consume SSE, verify log + completion events
- `test_dry_run_validates_placeholders` — bad placeholders → job failure
- `test_test_email_job` — mock Graph API, verify single email sent
- `test_send_job_completes` — mock Graph API, verify all results
- `test_send_sse_progress` — verify per-recipient events
- `test_send_with_failures` — mock 4xx for one recipient, partial failure
- `test_send_rejects_over_99` — 100+ rows → 400 error
- `test_send_enforces_fixed_delay` — verify delay=2.0 is not overridable

**Options pass-through:**
- `test_cc_bcc_passed_through`, `test_html_mode`, `test_attachments_uploaded`, `test_importance`

### `tests/test_auth_additions.py` — New auth functions

- `test_initiate_auth_code_flow` — verify flow dict has `auth_uri`
- `test_acquire_token_by_auth_code` — mock MSAL, token returned, cache saved
- `test_acquire_token_by_auth_code_error` — error → RuntimeError
- `test_diagnose_auth_no_cache` / `_valid_token` / `_expired_token`

### `tests/test_api_additions.py` — New `send_merge()` parameters

- `test_body_text_used` — pass `body_text`, verify rendering without file
- `test_body_text_precedence` — `body_text` takes precedence over `body` path
- `test_token_provider_skips_auth_block` — auth module not imported when `token_provider` provided
- `test_token_provider_used_for_send` — verify token from callable used in requests

### Type checking

- All new code fully type-annotated (strict mypy enabled)
- Add `flask` to mypy `ignore_missing_imports` overrides
- `Callable` from `collections.abc` (consistent with `sender.py`)
- `uv run mypy` run after each implementation step

### `tests/test_web_e2e.py` — Playwright end-to-end tests

Uses the Playwright Python API (per project convention) to test the full wizard flow in a real browser. The Flask server runs in a background thread with mocked Graph API (`responses`) and mocked MSAL.

**Wizard flow tests:**
- `test_full_wizard_flow` — Upload spreadsheet → fill in subject/body → preview renders → send test email → dry run completes → confirm send → results appear
- `test_wizard_navigation_back` — Navigate forward to Preview, go back to Setup, change subject, verify preview updates
- `test_wizard_blocks_on_missing_fields` — Try to advance from Setup with no spreadsheet → Next button disabled or error shown
- `test_wizard_blocks_unresolved_placeholders` — Preview step shows warning and blocks Next when `{{missing}}` placeholder used

**Upload & preview tests:**
- `test_spreadsheet_upload_shows_columns` — Upload .xlsx, verify column dropdown populated and preview table visible
- `test_template_live_preview` — Type in body textarea, verify preview panel updates (debounced)
- `test_placeholder_chips_insert_text` — Click a placeholder chip, verify `{{column}}` inserted into textarea

**Auth flow tests:**
- `test_sign_in_button_redirects` — Click "Sign In", verify redirect to Microsoft login URL (mocked to return immediately)
- `test_auth_status_shown` — After mock auth, verify "Authenticated" indicator visible
- `test_test_connection_shows_diagnostics` — Click "Test Connection", verify diagnostic panel appears with results

**Safety tests:**
- `test_over_99_recipients_blocked` — Upload 100-row spreadsheet, verify error shown, Next blocked
- `test_test_email_required` — Try to skip test email step, verify Next disabled
- `test_dry_run_required` — Try to skip dry run step, verify Send step not accessible
- `test_send_confirmation_dialog` — Click Send, verify confirmation dialog appears with recipient count

**SSE & progress tests:**
- `test_dry_run_log_stream` — Start dry run, verify log messages appear in real-time in the progress panel
- `test_send_results_table` — Complete send, verify results table shows per-recipient status
- `test_download_csv_button` — After send, click "Download CSV", verify file downloads

**Responsive/a11y basics:**
- `test_page_loads_without_js_errors` — No console errors on load
- `test_keyboard_navigation` — Tab through wizard, verify focus order makes sense

### Playwright setup

Add to `pyproject.toml`:
```toml
[dependency-groups]
dev = [
    ...
    "playwright>=1.40",
    "pytest-playwright>=0.4",
]
```

After adding dependencies: `uv run playwright install chromium` to install the browser binary.

Fixture `live_server` starts Flask in a background thread on a random port, with `responses` activated for Graph API mocking and MSAL monkeypatched. Yields the base URL. Tears down after test.

### Test fixtures (add to `conftest.py`)

- `web_client` — Flask test client with startup token pre-authenticated
- `sample_xlsx_100` — spreadsheet with 100 rows for testing 99-recipient cap

## Verification

1. `uv run pytest` — full suite passes including all new tests
2. `uv run mypy` — no type errors across all modules
3. `uv run pytest --cov=mail_merge` — verify coverage of web module
4. `uv run mail-merge-web` starts on `http://127.0.0.1:5050`
5. Upload spreadsheet → columns and preview rows appear
6. Template preview renders correctly
7. Wizard flow: setup → preview → test email → dry run → send
8. SSE streams real-time progress in test/dry-run/send steps
