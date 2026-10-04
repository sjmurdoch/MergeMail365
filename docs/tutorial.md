# Getting Started with MergeMail365

This tutorial walks you through setting up MergeMail365 and sending your first batch of personalised emails via Office 365.

## Prerequisites

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- An Azure AD app registration with **Mail.Send** delegated permission
- A Microsoft 365 account that can send email

## 1. Install

```bash
git clone <repo-url> && cd MergeMail365
uv sync
```

Verify it works:

```bash
uv run mergemail365 --help
```

## 2. Register an Azure AD application

1. Go to the [Azure portal](https://portal.azure.com/) > **App registrations** > **New registration**.
2. Set **Name** to something like `mergemail365`.
3. Under **Supported account types**, choose the option that matches your organisation (typically "Accounts in this organizational directory only").
4. Under **Redirect URI**, select **Public client/native (mobile & desktop)** and set the URI to `https://login.microsoftonline.com/common/oauth2/nativeclient`.
5. Click **Register**.
6. Copy the **Application (client) ID** — you'll need this as `--client-id`.
7. Go to **API permissions** > **Add a permission** > **Microsoft Graph** > **Delegated permissions** > search for `Mail.Send` > **Add**.
8. If your tenant requires it, click **Grant admin consent**.
9. Go to **Authentication** > **Advanced settings** > set **Allow public client flows** to **Yes** > **Save**. (Required for the device code flow used by this tool.)

## 3. Save your credentials (optional)

Instead of passing `--client-id` and `--tenant-id` on every run (or exporting environment variables), you can save them in `~/.mergemail365.toml`:

```toml
client-id = "YOUR_CLIENT_ID"
tenant-id = "YOUR_TENANT_ID"
```

Values are resolved in this order (highest wins):

1. CLI flags (`--client-id`, `--tenant-id`)
2. Environment variables (`MERGEMAIL365_CLIENT_ID`, `MERGEMAIL365_TENANT_ID`)
3. Config file (`~/.mergemail365.toml`)
4. Hardcoded default (`"common"` for tenant-id only)

## 4. Prepare your spreadsheet

Create an `.xlsx` file with a header row. One column must contain recipient email addresses. Other columns can be used as placeholders in your subject and body. Email addresses are validated before sending — malformed addresses (missing `@`, no domain, non-ASCII characters, etc.) are automatically skipped with a warning.

Example `recipients.xlsx`:

| name    | email             | company    |
|---------|-------------------|------------|
| Alice   | alice@example.com | Acme Corp  |
| Bob     | bob@example.com   | Widgets Co |

## 5. Write your email template

Create a plain-text file for the email body. Use `{{column_name}}` to insert per-recipient values. Placeholder names are case-insensitive (`{{Name}}` and `{{name}}` both work).

Example `body.txt`:

```
Hi {{name}},

I wanted to reach out from {{company}} about our upcoming event.

Best regards,
Your Name
```

## 6. Dry run (the default)

Running MergeMail365 performs a dry run by default — it checks the spreadsheet, resolves all placeholders, and logs what would be sent, without authenticating or making any API calls.

```bash
uv run mergemail365 \
  --spreadsheet recipients.xlsx \
  --body body.txt \
  --subject "Event invitation for {{name}}" \
  --email-column email
```

If a placeholder in your subject or body doesn't match any spreadsheet column, the tool will abort with an error listing the unresolvable placeholders and the available columns.

Use `--log-level DEBUG` to see the fully rendered body for each recipient.

## 7. Send a test email

Once the dry run looks good, send a single real email to yourself to verify delivery and formatting. `--test-email` renders the email using the first recipient's data but sends it to the address you specify. Unlike the full send, `--test-email` always sends — no `--send` flag needed:

```bash
uv run mergemail365 \
  --spreadsheet recipients.xlsx \
  --body body.txt \
  --subject "Event invitation for {{name}}" \
  --email-column email \
  --client-id YOUR_CLIENT_ID \
  --tenant-id YOUR_TENANT_ID \
  --test-email your.own@example.com
```

If your Azure AD app is registered as single-tenant (the most common setup), you must provide `--tenant-id` with your directory (tenant) ID. You can find this in the Azure portal under **App registrations** > your app > **Overview**. You can also set it via the `MERGEMAIL365_TENANT_ID` environment variable. Multi-tenant apps can omit this flag (it defaults to `common`).

On first run, you'll see a device code prompt like:

```
To sign in, use a web browser to open https://microsoft.com/devicelogin
and enter the code XXXXXXXXX to authenticate.
```

Open the URL, enter the code, and sign in with your Microsoft 365 account. The token is cached at `~/.mergemail365-token-cache.json` so subsequent runs won't require this step.

Check your inbox. If the email looks right, proceed to the full send.

## 8. Send to all recipients

Add `--send` to actually deliver emails. You'll see a confirmation prompt before anything is sent:

```bash
uv run mergemail365 \
  --spreadsheet recipients.xlsx \
  --body body.txt \
  --subject "Event invitation for {{name}}" \
  --email-column email \
  --client-id YOUR_CLIENT_ID \
  --tenant-id YOUR_TENANT_ID \
  --send
```

If you saved your credentials in `~/.mergemail365.toml` (step 3), you can omit `--client-id` and `--tenant-id`. You can also use environment variables:

```bash
export MERGEMAIL365_CLIENT_ID=YOUR_CLIENT_ID
export MERGEMAIL365_TENANT_ID=YOUR_TENANT_ID
```

After all emails are sent, you'll see a console summary:

```
========================================
Total:  2
Sent:   2
Failed: 0
========================================
```

The exit code is 0 if all emails succeeded, or 1 if any failed.

## 9. Optional features

### CSV report

Save detailed per-recipient results to a CSV file:

```bash
uv run mergemail365 \
  --spreadsheet recipients.xlsx \
  --body body.txt \
  --subject "Hello {{name}}" \
  --email-column email \
  --output report.csv
```

The CSV contains columns: `email`, `success`, `status_code`, `error`.

### Rate limiting

By default, MergeMail365 waits 2 seconds between sends (Exchange Online allows ~30 messages/minute) and uses adaptive throttling: if Microsoft Graph returns a 429 (rate limit) response, the delay doubles (up to 30s); once sends succeed without throttling, the delay halves back toward the base.

To change the base delay:

```bash
--delay 5.0     # 5 seconds base delay between each email
--delay 0       # no delay (not recommended for large sends)
```

### Retry control

Control how many times a failed send (5xx server error) is retried:

```bash
--max-retries 5  # default is 3
```

Rate-limit responses (HTTP 429) are retried automatically (up to 20 times), honouring the server's `Retry-After` header.

### Importance

Set the email importance flag (visible to recipients in most email clients):

```bash
--importance high    # low, normal, or high
```

When omitted, no importance field is sent and the email defaults to normal importance.

### CC and BCC

Add CC and/or BCC recipients to every email in the merge. Provide comma-separated addresses. Both plain addresses and `"Display Name <email>"` format are supported:

```bash
--cc "manager@example.com,team@example.com"
--cc "Manager <manager@example.com>, Team Inbox <team@example.com>"
--bcc "Archive <archive@example.com>"
```

These addresses are static (not templated per recipient).

### HTML emails

By default, the body is sent as plain text. To send HTML content instead:

```bash
--html
```

Your body template file should contain valid HTML when using this flag.

### Attachments

Attach files to every email in the merge. Specify `--attachment` once per file:

```bash
--attachment report.pdf --attachment logo.png
```

Files are base64-encoded inline. The Graph API limits inline attachments to ~3 MB per file.

### Reply-To

Set custom reply-to addresses (comma-separated) so replies go somewhere other than the sender. Plain addresses and `"Display Name <email>"` format are both accepted:

```bash
--reply-to "support@example.com,team@example.com"
--reply-to "Support Team <support@example.com>"
```

### Save to Sent Items

By default, sent messages appear in your Sent Items folder. To suppress this (useful for large bulk sends):

```bash
--no-save-to-sent
```

### Filter recipients

Send to a subset of your spreadsheet by filtering on column values. Use `--filter` (repeatable) with `column=value` or `column!=value` syntax. Multiple filters use AND logic. Matching is case-insensitive.

```bash
# Only send to people at Acme Corp
--filter "company=Acme Corp"

# Exclude a specific department
--filter "department!=Marketing"

# Combine filters (AND logic): PhD students in the Security group
--filter "role=PhD" --filter "group=Security"
```

### Interactive confirmation

When sending (`--send`), MergeMail365 shows a summary (subject, recipient count, CC/BCC, attachments) and asks for confirmation before proceeding. Type `y` to proceed or anything else to abort (exit code 130).

Confirmation is automatically skipped for dry runs (the default), `--test-email`, and when `--yes`/`-y` is passed:

```bash
# Skip the confirmation prompt
--yes
```

### Resume and batch size

When sending to large lists, runs can fail partway through (network issues, rate limits, auth expiry). Resume is automatic: when `--output` is set, MergeMail365 reads the existing CSV on each run, skips already-successful recipients, and retries failures. Just re-run the same command:

```bash
# First run — might fail partway through
uv run mergemail365 \
  --spreadsheet recipients.xlsx \
  --body body.txt \
  --subject "Hello {{name}}" \
  --email-column email \
  --output report.csv \
  --send

# Just re-run the same command — successes are skipped automatically
uv run mergemail365 \
  --spreadsheet recipients.xlsx \
  --body body.txt \
  --subject "Hello {{name}}" \
  --email-column email \
  --output report.csv \
  --send
```

Use `--batch-size N` to limit how many emails are sent per invocation. This is useful for controlled rollout — run the same command repeatedly until all emails are sent:

```bash
# Send in batches of 50 — re-run until done
uv run mergemail365 \
  --spreadsheet recipients.xlsx \
  --body body.txt \
  --subject "Hello {{name}}" \
  --email-column email \
  --output report.csv \
  --batch-size 50 \
  --send
```

When all recipients have succeeded, the tool logs "All emails already sent" and exits 0. Use `--no-resume` to disable automatic resume and send to all recipients fresh.

### BCC blast

When every recipient should receive the same email and must not be able to see other recipients' addresses, use BCC blast mode. Instead of sending one email per row, MergeMail365 groups all recipients into BCC batches (up to 499 addresses per email, respecting the Microsoft Graph API limit of 500 total recipients per message) and sends a small number of emails in total.

**When to use BCC blast:**
- Newsletters, announcements, or any message where the body is the same for everyone
- Situations where recipient privacy matters (no-one in the list can see who else received the email)
- Large lists where sending individual emails would hit Exchange Online's per-minute rate limit

**Constraints (combinations that abort with an error):**
- The subject and body must be **static text** — `{{placeholders}}` abort with an error (every recipient gets the same content)
- `--batch-size` aborts with an error (batch sizes are calculated automatically)
- `--bcc-blast-to` is required — omitting it aborts with an error

**Flags that are accepted but have no effect:**
- `--delay` — BCC blast sends batches one after another with no configurable inter-batch delay (this is not a concern in practice: a 50,000-recipient list becomes ~100 API calls, well within rate limits)

**Flags that work with modified semantics:**
- `--bcc` — the specified addresses are added as static extra BCC recipients on every batch, in addition to the blast recipients. They are not shown in the confirmation prompt (only the blast recipient count is shown).
- `--output` — a results CSV is written with one row per recipient email address (not per batch). When combined with resume (the default), re-running the same command skips already-successful recipients — the same behaviour as individual sends.

**Basic usage:**

```bash
uv run mergemail365 \
  --spreadsheet recipients.xlsx \
  --body announcement.txt \
  --subject "Upcoming event on Friday" \
  --email-column email \
  --bcc-blast \
  --bcc-blast-to noreply@example.com
```

`--bcc-blast-to` is the address that appears in the `To:` field of the outgoing message. Individual recipients are placed in BCC and cannot see each other's addresses.

Common choices for this address:

- `noreply@yourdomain.com` — signals to recipients that replies are not monitored
- Your own address — recipients can reply directly
- A shared mailbox alias (`announcements@yourdomain.com`) — replies go to a shared inbox

You can include a display name using standard `"Name <email>"` format. Passing `"Undisclosed recipients <noreply@yourdomain.com>"` is a conventional choice: recipients see "Undisclosed recipients" in the `To:` field, which makes the nature of the mailing explicit.

```bash
--bcc-blast-to "Undisclosed recipients <noreply@yourdomain.com>"
```

#### BCC blast workflow

Follow the same staged approach as a standard send:

**Step 1 — Dry run (no flags beyond `--bcc-blast` and `--bcc-blast-to`)**

```bash
uv run mergemail365 \
  --spreadsheet recipients.xlsx \
  --body announcement.txt \
  --subject "Upcoming event on Friday" \
  --email-column email \
  --bcc-blast \
  --bcc-blast-to noreply@example.com
```

This validates the spreadsheet, calculates how many batches will be sent, and logs a summary without making any API calls. Check the log output to confirm the recipient count and batch count.

**Step 2 — Test send with `--test-email`**

`--test-email` works in BCC blast mode. Instead of sending to the full recipient list, it sends a single BCC blast batch to only the test address, using the real subject and body. No `--send` flag is needed:

```bash
uv run mergemail365 \
  --spreadsheet recipients.xlsx \
  --body announcement.txt \
  --subject "Upcoming event on Friday" \
  --email-column email \
  --bcc-blast \
  --bcc-blast-to noreply@example.com \
  --client-id YOUR_CLIENT_ID \
  --tenant-id YOUR_TENANT_ID \
  --test-email your.own@example.com
```

To verify BCC privacy, pass two addresses by running twice with different `--test-email` addresses, or instead run a brief two-address send (see below). Check the inbox and verify:
- The subject and body look correct
- The `From:` address is your Microsoft 365 account (not the `--bcc-blast-to` address)
- The `To:` field shows the `--bcc-blast-to` address, not your personal address
- Any CC, attachments, or reply-to addresses are present if you used those flags

To verify BCC privacy (neither test recipient sees the other), send to a small two-address spreadsheet instead:

```
email
you@example.com
colleague@example.com
```

```bash
uv run mergemail365 \
  --spreadsheet test-recipients.xlsx \
  --body announcement.txt \
  --subject "Upcoming event on Friday" \
  --email-column email \
  --bcc-blast \
  --bcc-blast-to noreply@example.com \
  --client-id YOUR_CLIENT_ID \
  --tenant-id YOUR_TENANT_ID \
  --send \
  --yes
```

**Step 3 — Full send with confirmation**

```bash
uv run mergemail365 \
  --spreadsheet recipients.xlsx \
  --body announcement.txt \
  --subject "Upcoming event on Friday" \
  --email-column email \
  --bcc-blast \
  --bcc-blast-to noreply@example.com \
  --client-id YOUR_CLIENT_ID \
  --tenant-id YOUR_TENANT_ID \
  --send
```

The confirmation prompt shows the `To:` address, the total recipient count, and how many batches will be sent. Type `y` to proceed.

#### Error recovery in BCC blast mode

If a batch fails (network error, 5xx, or rate limit exhaustion), the tool logs the failure and moves on to the next batch. Every recipient in that batch is marked as failed. After the run, inspect the console output or exit code:

- **Exit code 0** — all batches succeeded
- **Exit code 1** — one or more batches failed

Results in BCC blast mode are tracked per recipient email address (the same as individual sends). When a batch succeeds, every recipient in that batch is recorded as successful; when a batch fails, every recipient in that batch is recorded as failed with the same error.

If you pass `--output`, the CSV contains one row per recipient. On re-run, resume automatically skips already-successful recipients and only re-sends the failed ones — just like individual sends:

```bash
# First run — might fail partway through
uv run mergemail365 \
  --spreadsheet recipients.xlsx \
  --body announcement.txt \
  --subject "Upcoming event on Friday" \
  --email-column email \
  --bcc-blast \
  --bcc-blast-to noreply@example.com \
  --output report.csv \
  --send

# Just re-run — successes are skipped, failures are retried
uv run mergemail365 \
  --spreadsheet recipients.xlsx \
  --body announcement.txt \
  --subject "Upcoming event on Friday" \
  --email-column email \
  --bcc-blast \
  --bcc-blast-to noreply@example.com \
  --output report.csv \
  --send
```

When all recipients have succeeded, the tool logs "All emails already sent" and exits 0.

### Specific sheet

If your workbook has multiple sheets, select one by name:

```bash
--sheet "March contacts"
```

By default, the first sheet is used.

## Recommended workflow

### Standard (personalised) send

1. **Dry run** — validate placeholders and data (the default — no flags needed)
2. **Test email** — send one real email to yourself (`--test-email you@example.com`)
3. **Check your inbox** — verify subject, body, and formatting
4. **Full send** — add `--send` (confirmation prompt appears automatically)
5. **Review report** — check console summary or `--output report.csv`
6. **Resume if needed** — re-run the same command (resume is automatic with `--output`)

### BCC blast (privacy-preserving bulk send)

1. **Dry run** — validate the spreadsheet and confirm batch count (no extra flags needed)
2. **Test email** — `--test-email you@example.com` sends the blast to only your address
3. **Check your inbox** — verify subject, body, `To:` address, and any CC/attachments
4. **Full send** — add `--send` (confirmation prompt shows recipient and batch count)
5. **Review report** — check console summary or `--output report.csv`
6. **Resume if needed** — re-run the same command (resume is automatic with `--output`)

## 10. Logging and troubleshooting

MergeMail365 has three independent log destinations. Each has its own level and is active only when appropriate:

| Destination | Level | When active |
|---|---|---|
| **Console** (stderr) | `--log-level` (default INFO) | Always |
| **File** | Always DEBUG | `--log-file` or PyInstaller bundle |
| **Browser panel** (SSE) | INFO | Web UI only, during send jobs |

Enabling file logging never changes what appears on the console or in the browser.

### Console logging

Control console log verbosity with `--log-level` (available on both `mergemail365` and `mergemail365-web`):

```bash
uv run mergemail365 --log-level DEBUG ...
uv run mergemail365-web --log-level DEBUG
```

### File logging

Both `mergemail365` and `mergemail365-web` support `--log-file` for opt-in file logging. This is especially useful for troubleshooting send failures and for the standalone desktop app (PyInstaller bundle), where there is no terminal to see console output.

**When file logging is enabled:**

| Scenario | File logging |
|---|---|
| **Desktop app (PyInstaller bundle)** | Always on automatically |
| `mergemail365 --log-file` | On (explicit opt-in) |
| `mergemail365-web --log-file` | On (explicit opt-in) |
| Default (no flags) | Off |

**File logging always captures at DEBUG level**, regardless of the console log level. This means that even with default INFO console output, the file will contain full details including exception tracebacks from API errors.

**Log file locations:**

| Platform | Path |
|---|---|
| **macOS** | `~/Library/Logs/mergemail365/mergemail365.log` |
| **Windows** | `%LOCALAPPDATA%\mergemail365\logs\mergemail365.log` |
| **Linux** | `~/.local/state/mergemail365/log/mergemail365.log` |

On macOS, the log directory is indexed by Console.app — open Console and search for "mergemail365". On Windows, open File Explorer and paste `%LOCALAPPDATA%\mergemail365\logs` into the address bar.

The log file rotates automatically at 5 MB with 3 backups (20 MB maximum disk usage).

**Finding the log file path programmatically:**

The web UI exposes `GET /api/log-path` which returns the log file path and whether it exists:

```json
{"path": "/Users/you/Library/Logs/mergemail365/mergemail365.log", "exists": true}
```

### What gets logged

When the web UI encounters an error (e.g. a corrupt spreadsheet, invalid column name, or send failure), the error message is shown in the browser. The full Python stack trace is logged at DEBUG level in the log file for troubleshooting. This applies to all API error paths: spreadsheet upload, recipient validation, job startup, and background send failures.

Each line in the log file names the thread that wrote it (for example `[MainThread]` or `[job-1a2b3c4d]` for a send job), and when file logging is on the web UI records the Python, operating system and key package versions at startup.

**Freeze diagnostics (web UI):** when file logging is on, `mergemail365-web` also runs a watchdog thread that checks in every second. If it is held up for 10 seconds or more, a warning such as `The app was unresponsive for 165 seconds` is logged. If a freeze lasts 30 seconds or more, the stack of every thread is written to `mergemail365-stalls.log` in the same directory as the log file. That file is only written during a freeze and is not rotated. When reporting a hang, send both files.

## 11. Python API

If you want to call MergeMail365 from Python code instead of the command line, use the `send_merge()` function. It mirrors the CLI flags and returns a list of `SendResult` objects.

```python
from mail_merge.api import send_merge

# Dry run — validate without sending (this is the default)
results = send_merge(
    spreadsheet="recipients.xlsx",
    body="body.txt",
    subject="Hello {{name}}",
    email_column="email",
)

# Send for real — must explicitly set send=True
results = send_merge(
    spreadsheet="recipients.xlsx",
    body="body.html",
    subject="Hello {{name}}",
    email_column="email",
    send=True,
    html=True,
    attachment=["report.pdf"],
    cc=["manager@example.com"],
)

# Filter recipients and send in batches
# (resume and confirm are on by default)
results = send_merge(
    spreadsheet="recipients.xlsx",
    body="body.txt",
    subject="Hello {{name}}",
    email_column="email",
    send=True,
    filters=["company=Acme Corp"],
    output="report.csv",
    batch_size=50,
)

# BCC blast — same message to everyone, recipients cannot see each other
results = send_merge(
    spreadsheet="recipients.xlsx",
    body="announcement.txt",
    subject="Upcoming event on Friday",
    email_column="email",
    send=True,
    bcc_blast=True,
    bcc_blast_to="noreply@example.com",
    confirm=False,
)

# Inspect results
for r in results:
    if not r.success:
        print(f"Failed: {r.email} — {r.error}")
```

Key differences from the CLI:

- **Exceptions instead of exit codes** — raises `FileNotFoundError`, `ValueError`, or `RuntimeError` on errors.
- **`cc`/`bcc`/`reply_to`** accept a Python list or a comma-separated string.
- **`save_to_sent_items`** is `True` by default (the CLI uses the `--no-save-to-sent` flag to set it to `False`).
- **`attachment`** takes a list of file paths (strings or `Path` objects).
- **`filters`** takes a list of filter expressions (e.g., `["company=Acme"]`).
- **Safe defaults** — `send` is `False`, `confirm` and `resume` are `True` by default. Pass `send=True` to actually send.
- **`test_email`** always sends (authenticates and delivers) regardless of `send`. Resume and batch size are ignored.
- **`confirm`** is automatically disabled when `send=False` or `test_email` is set.
- **`bcc_blast`** / **`bcc_blast_to`** enable privacy-preserving bulk sends; `bcc_blast_to` is required when `bcc_blast=True`. Raises `ValueError` if combined with `batch_size` or templates containing `{{placeholders}}`. When `test_email` is set, the blast is sent to only that address instead of the full list. `delay` is accepted but silently ignored. `bcc` works as extra static BCC addresses added to every batch. Results are tracked per recipient (not per batch), so `output` + `resume` work the same as individual sends.

See `examples/send_merge.py` for a complete example.

## Releasing a new version

### Version bump

The version is defined in `pyproject.toml` (`version = "X.Y.Z"`). Update it, and add a section for the new version to `CHANGELOG.md`, before creating a release:

```bash
# Edit pyproject.toml and change the version field
# e.g. version = "0.2.0"
```

### Create a release

1. **Ensure all tests pass:**

   ```bash
   uv run pytest
   uv run mypy
   biome lint src/mail_merge/web/static/app.js
   ```

2. **Commit the version bump:**

   ```bash
   git add pyproject.toml uv.lock CHANGELOG.md
   git commit -m "Bump version to 0.5.0"
   git push
   ```

3. **Create a git tag matching the version (prefixed with `v`):**

   ```bash
   git tag v0.5.0
   git push origin v0.5.0
   ```

4. **Create a GitHub release** from the tag. This triggers the `release.yml` workflow which builds macOS and Windows bundles via PyInstaller and uploads them as release assets:

   ```bash
   awk '/^## \[0.5.0\]/{f=1;next} /^## \[/{f=0} f' CHANGELOG.md > release-notes.md
   gh release create v0.5.0 --title "v0.5.0" --notes-file release-notes.md
   rm release-notes.md
   ```

   Alternatively, create the release from the GitHub web UI at **Releases** > **Draft a new release**, selecting the tag you just pushed.

5. **Verify the build** — check the Actions tab for the "Build release bundles" workflow. It builds on both macOS and Windows, then uploads `MergeMail365-macOS.zip` and `MergeMail365-Windows.zip` to the release.

### Manual workflow trigger

If you need to rebuild release bundles without creating a new release, trigger the workflow manually:

```bash
gh workflow run release.yml -f tag=v0.2.0
```

### Version conventions

- Use [semantic versioning](https://semver.org/): `MAJOR.MINOR.PATCH`
- Git tags must be prefixed with `v` (e.g. `v0.2.0`) — the CI workflow strips the `v` prefix when patching the version into the build

## Future features

The following features are not yet implemented but are under consideration:

### Input and templating

- **CSV/TSV input** — accept `.csv` and `.tsv` recipient files in addition to `.xlsx`, since many users already have recipient lists in these formats
- **Subject file** (`--subject-file`) — read the subject from a file instead of the command line, avoiding shell quoting issues with special characters and supporting long subjects
- **Markdown support** — write the body in Markdown and have it auto-converted to HTML
- **Signatures** — append a separate signature file to the body template
- **Dynamic body** — per-recipient body template selection via `--body-column`, for when different people need entirely different content
- **Per-recipient attachments** (`--attachment-column`) — a spreadsheet column containing file paths, so different recipients get different attachments (e.g. personalised invoices, certificates)

### Sending and delivery

- **Send-as / shared mailbox** — send from a different address or shared mailbox using `/users/{id}/sendMail` instead of `/me/sendMail` (requires `Mail.Send.Shared` permission and Exchange Online mailbox permissions)
- **Scheduling** — queue emails to send at a specific time (e.g. 9am Monday) to avoid the "why are you emailing at 2am" problem
- **Unsubscribe headers** (`--unsubscribe-url`) — add `List-Unsubscribe` and `List-Unsubscribe-Post` headers per RFC 8058, required by Gmail and Yahoo for bulk senders (>5000/day)
- **Connection pooling** — use a `requests.Session` to reuse TCP connections across sends, improving throughput for large recipient lists
- **Progress bar** — replace `[i/n]` log lines with a `rich` progress bar showing ETA and throughput (the `rich` dependency is already present)

### Workflow and review

- **Preview mode** (`--preview N`) — render and display the first N emails in the terminal for visual review before confirming the full send
- **Dry-run output** (`--dry-run-output DIR`) — write each rendered email to a file in a directory during dry run, allowing offline review of exact content before committing to send
- **Blocklist** (`--exclude emails.txt`) — skip addresses in a blocklist (people who've already replied, opted out, etc.)

### BCC blast enhancements

- **Inter-batch delay** — add a configurable delay between batches to avoid rate limits on large blasts; currently batches fire back-to-back with no pause, and the `--delay` parameter is accepted but has no effect in blast mode; could also reuse the adaptive throttling logic from individual sends
- **Partial placeholder support** — allow `{{placeholders}}` that resolve to the same value for all recipients after filtering (e.g. `{{company}}` when all recipients share the same company); the tool would check that every row produces the same rendered output and proceed if so
- **Confirmation recipient sample** — show the first and last few email addresses in the confirmation prompt (e.g. "alice@..., bob@..., ... and 497 more") to help catch wrong-spreadsheet mistakes before sending
- **Configurable BCC batch size** (`--bcc-batch-size N`) — override the default batch size of 499 for organisations with lower per-message limits, separate from the existing `--batch-size` flag which controls per-invocation recipient count
- **Shuffle recipients across batches** (`--shuffle`) — randomise recipient order before batching to distribute domains across batches; without this, a spreadsheet sorted by domain puts all `@example.com` addresses in the same batch, which could trigger per-domain rate limits on the receiving side
- **To-address validation** — preflight check via Graph API (e.g. `/me/mailboxSettings`) to warn if the `--bcc-blast-to` address doesn't belong to the authenticated sender, catching typos before emails are sent to an unmonitored address

### Advanced

- **Group-by** — send one email per unique value in a column, with a `{{members}}` placeholder listing all rows in that group (e.g. one email per research group)
- **Follow-up emails** — re-send (with modified subject/body) to recipients who haven't replied after N days
- **Calendar-aware sending** — check recipients' free/busy status and send during their working hours
- **Read receipts** — request read receipts and track them via the Graph API
- **Teams fallback** — if an email bounces, optionally send a message via Teams chat instead
