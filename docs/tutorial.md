# Getting Started with mail-merge

This tutorial walks you through setting up mail-merge and sending your first batch of personalised emails via Office 365.

## Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- An Azure AD app registration with **Mail.Send** delegated permission
- A Microsoft 365 account that can send email

## 1. Install

```bash
git clone <repo-url> && cd mail-merge
uv sync
```

Verify it works:

```bash
uv run mail-merge --help
```

## 2. Register an Azure AD application

1. Go to the [Azure portal](https://portal.azure.com/) > **App registrations** > **New registration**.
2. Set **Name** to something like `mail-merge-cli`.
3. Under **Supported account types**, choose the option that matches your organisation (typically "Accounts in this organizational directory only").
4. Under **Redirect URI**, select **Public client/native (mobile & desktop)** and set the URI to `https://login.microsoftonline.com/common/oauth2/nativeclient`.
5. Click **Register**.
6. Copy the **Application (client) ID** — you'll need this as `--client-id`.
7. Go to **API permissions** > **Add a permission** > **Microsoft Graph** > **Delegated permissions** > search for `Mail.Send` > **Add**.
8. If your tenant requires it, click **Grant admin consent**.
9. Go to **Authentication** > **Advanced settings** > set **Allow public client flows** to **Yes** > **Save**. (Required for the device code flow used by this tool.)

## 3. Save your credentials (optional)

Instead of passing `--client-id` and `--tenant-id` on every run (or exporting environment variables), you can save them in `~/.mail-merge.toml`:

```toml
client-id = "YOUR_CLIENT_ID"
tenant-id = "YOUR_TENANT_ID"
```

Values are resolved in this order (highest wins):

1. CLI flags (`--client-id`, `--tenant-id`)
2. Environment variables (`MAIL_MERGE_CLIENT_ID`, `MAIL_MERGE_TENANT_ID`)
3. Config file (`~/.mail-merge.toml`)
4. Hardcoded default (`"common"` for tenant-id only)

## 4. Prepare your spreadsheet

Create an `.xlsx` file with a header row. One column must contain recipient email addresses. Other columns can be used as placeholders in your subject and body.

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

Running mail-merge performs a dry run by default — it checks the spreadsheet, resolves all placeholders, and logs what would be sent, without authenticating or making any API calls.

```bash
uv run mail-merge \
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
uv run mail-merge \
  --spreadsheet recipients.xlsx \
  --body body.txt \
  --subject "Event invitation for {{name}}" \
  --email-column email \
  --client-id YOUR_CLIENT_ID \
  --tenant-id YOUR_TENANT_ID \
  --test-email your.own@example.com
```

If your Azure AD app is registered as single-tenant (the most common setup), you must provide `--tenant-id` with your directory (tenant) ID. You can find this in the Azure portal under **App registrations** > your app > **Overview**. You can also set it via the `MAIL_MERGE_TENANT_ID` environment variable. Multi-tenant apps can omit this flag (it defaults to `common`).

On first run, you'll see a device code prompt like:

```
To sign in, use a web browser to open https://microsoft.com/devicelogin
and enter the code XXXXXXXXX to authenticate.
```

Open the URL, enter the code, and sign in with your Microsoft 365 account. The token is cached at `~/.mail-merge-token-cache.json` so subsequent runs won't require this step.

Check your inbox. If the email looks right, proceed to the full send.

## 8. Send to all recipients

Add `--send` to actually deliver emails. You'll see a confirmation prompt before anything is sent:

```bash
uv run mail-merge \
  --spreadsheet recipients.xlsx \
  --body body.txt \
  --subject "Event invitation for {{name}}" \
  --email-column email \
  --client-id YOUR_CLIENT_ID \
  --tenant-id YOUR_TENANT_ID \
  --send
```

If you saved your credentials in `~/.mail-merge.toml` (step 3), you can omit `--client-id` and `--tenant-id`. You can also use environment variables:

```bash
export MAIL_MERGE_CLIENT_ID=YOUR_CLIENT_ID
export MAIL_MERGE_TENANT_ID=YOUR_TENANT_ID
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
uv run mail-merge \
  --spreadsheet recipients.xlsx \
  --body body.txt \
  --subject "Hello {{name}}" \
  --email-column email \
  --output report.csv
```

The CSV contains columns: `email`, `success`, `status_code`, `error`.

### Rate limiting

By default, mail-merge waits 2 seconds between sends (Exchange Online allows ~30 messages/minute) and uses adaptive throttling: if Microsoft Graph returns a 429 (rate limit) response, the delay doubles (up to 30s); once sends succeed without throttling, the delay halves back toward the base.

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

Add CC and/or BCC recipients to every email in the merge. Provide comma-separated addresses:

```bash
--cc "manager@example.com,team@example.com"
--bcc "archive@example.com"
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

Set custom reply-to addresses (comma-separated) so replies go somewhere other than the sender:

```bash
--reply-to "support@example.com,team@example.com"
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

When sending (`--send`), mail-merge shows a summary (subject, recipient count, CC/BCC, attachments) and asks for confirmation before proceeding. Type `y` to proceed or anything else to abort (exit code 130).

Confirmation is automatically skipped for dry runs (the default), `--test-email`, and when `--yes`/`-y` is passed:

```bash
# Skip the confirmation prompt
--yes
```

### Resume and batch size

When sending to large lists, runs can fail partway through (network issues, rate limits, auth expiry). Resume is automatic: when `--output` is set, mail-merge reads the existing CSV on each run, skips already-successful recipients, and retries failures. Just re-run the same command:

```bash
# First run — might fail partway through
uv run mail-merge \
  --spreadsheet recipients.xlsx \
  --body body.txt \
  --subject "Hello {{name}}" \
  --email-column email \
  --output report.csv \
  --send

# Just re-run the same command — successes are skipped automatically
uv run mail-merge \
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
uv run mail-merge \
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

When every recipient should receive the same email and must not be able to see other recipients' addresses, use BCC blast mode. Instead of sending one email per row, mail-merge groups all recipients into BCC batches (up to 499 addresses per email, respecting the Microsoft Graph API limit of 500 total recipients per message) and sends a small number of emails in total.

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
- `--no-resume` — resume is already bypassed in BCC blast mode regardless

**Flags that work with modified semantics:**
- `--bcc` — the specified addresses are added as static extra BCC recipients on every batch, in addition to the blast recipients. They are not shown in the confirmation prompt (only the blast recipient count is shown).
- `--output` — a results CSV is written, but rows use batch labels (`"batch 1/5 (499 recipients)"`) not individual email addresses, so the CSV serves as a run log only. On re-run, the CSV is **not** read for resume (resume is bypassed).

**Basic usage:**

```bash
uv run mail-merge \
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
uv run mail-merge \
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
uv run mail-merge \
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
uv run mail-merge \
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
uv run mail-merge \
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

If a batch fails (network error, 5xx, or rate limit exhaustion), the tool logs the failure and moves on to the next batch. After the run, inspect the console output or exit code:

- **Exit code 0** — all batches succeeded
- **Exit code 1** — one or more batches failed

Results in BCC blast mode are labelled by batch (e.g. `"batch 2/5 (499 recipients)"`) rather than by individual email address. If you pass `--output`, the CSV is written with those batch labels — useful as a run log — but re-running the same command will **not** skip already-sent batches (resume is bypassed in blast mode). If a run fails partway through, re-run with a trimmed spreadsheet that excludes the addresses already covered by successful batches.

A practical approach for large lists:

```bash
# Split recipients.xlsx into chunks of ~490 rows using your spreadsheet tool,
# then send each chunk individually:
uv run mail-merge \
  --spreadsheet recipients-chunk-1.xlsx \
  --body announcement.txt \
  --subject "Upcoming event on Friday" \
  --email-column email \
  --bcc-blast \
  --bcc-blast-to noreply@example.com \
  --send \
  --yes
```

This keeps each invocation self-contained and makes it easy to identify exactly which addresses were covered if you need to retry.

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
5. **Review exit code** — exit 0 means all batches succeeded, 1 means at least one failed
6. **Retry failures** — re-run with a trimmed spreadsheet covering only the failed range

## 10. Python API

If you want to call mail-merge from Python code instead of the command line, use the `send_merge()` function. It mirrors the CLI flags and returns a list of `SendResult` objects.

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
    filter=["company=Acme Corp"],
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
- **`filter`** takes a list of filter expressions (e.g., `["company=Acme"]`).
- **Safe defaults** — `send` is `False`, `confirm` and `resume` are `True` by default. Pass `send=True` to actually send.
- **`test_email`** always sends (authenticates and delivers) regardless of `send`. Resume and batch size are ignored.
- **`confirm`** is automatically disabled when `send=False` or `test_email` is set.
- **`bcc_blast`** / **`bcc_blast_to`** enable privacy-preserving bulk sends; `bcc_blast_to` is required when `bcc_blast=True`. Raises `ValueError` if combined with `batch_size` or templates containing `{{placeholders}}`. When `test_email` is set, the blast is sent to only that address instead of the full list. `delay` is accepted but silently ignored. `bcc` works as extra static BCC addresses added to every batch. `output` writes a results CSV with batch labels but does not enable resume.

See `examples/send_merge.py` for a complete example.

## Future features

The following features are not yet implemented but are under consideration:

- **Send-as / shared mailbox** — send from a different address or shared mailbox (requires `Mail.Send.Shared` permission and Exchange Online mailbox permissions)
- **Scheduling** — queue emails to send at a specific time (e.g. 9am Monday) to avoid the "why are you emailing at 2am" problem
- **Blocklist** (`--exclude emails.txt`) — skip addresses in a blocklist (people who've already replied, opted out, etc.)
- **Group-by** — send one email per unique value in a column, with a `{{members}}` placeholder listing all rows in that group (e.g. one email per research group)
- **Dynamic body** — per-recipient body template selection via `--body-column`, for when different people need entirely different content
- **Signatures** — append a separate signature file to the body template
- **Markdown support** — write the body in Markdown and have it auto-converted to HTML
- **Follow-up emails** — re-send (with modified subject/body) to recipients who haven't replied after N days
- **Preview mode** — render and display the first N emails in the terminal for visual review before confirming the full send
- **Calendar-aware sending** — check recipients' free/busy status and send during their working hours
- **Read receipts** — request read receipts and track them via the Graph API
- **Teams fallback** — if an email bounces, optionally send a message via Teams chat instead
