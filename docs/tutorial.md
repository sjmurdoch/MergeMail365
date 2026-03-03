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

## 6. Dry run

Before sending anything, validate your setup with `--dry-run`. This checks the spreadsheet, resolves all placeholders, and logs what would be sent — without authenticating or making any API calls.

```bash
uv run mail-merge \
  --spreadsheet recipients.xlsx \
  --body body.txt \
  --subject "Event invitation for {{name}}" \
  --email-column email \
  --dry-run
```

If a placeholder in your subject or body doesn't match any spreadsheet column, the tool will abort with an error listing the unresolvable placeholders and the available columns.

Use `--log-level DEBUG` to see the fully rendered body for each recipient.

## 7. Send a test email

Once the dry run looks good, send a single real email to yourself to verify delivery and formatting. `--test-email` renders the email using the first recipient's data but sends it to the address you specify:

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

```bash
uv run mail-merge \
  --spreadsheet recipients.xlsx \
  --body body.txt \
  --subject "Event invitation for {{name}}" \
  --email-column email \
  --client-id YOUR_CLIENT_ID \
  --tenant-id YOUR_TENANT_ID
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

By default, mail-merge shows a summary (subject, recipient count, CC/BCC, attachments) and asks for confirmation before sending. Type `y` to proceed or anything else to abort (exit code 130).

Confirmation is automatically skipped for `--dry-run`, `--test-email`, and when `--yes`/`-y` is passed:

```bash
# Skip the confirmation prompt
--yes
```

### Resume and batch size

When sending to large lists, runs can fail partway through (network issues, rate limits, auth expiry). Use `--resume` with `--output` to restart where you left off — already-successful recipients are skipped and failures are retried:

```bash
# First run — might fail partway through
uv run mail-merge \
  --spreadsheet recipients.xlsx \
  --body body.txt \
  --subject "Hello {{name}}" \
  --email-column email \
  --output report.csv

# Resume — skips successes, retries failures
uv run mail-merge \
  --spreadsheet recipients.xlsx \
  --body body.txt \
  --subject "Hello {{name}}" \
  --email-column email \
  --output report.csv \
  --resume
```

Use `--batch-size N` to limit how many emails are sent per invocation. This is useful for controlled rollout and combines naturally with `--resume`:

```bash
# Send in batches of 50
uv run mail-merge \
  --spreadsheet recipients.xlsx \
  --body body.txt \
  --subject "Hello {{name}}" \
  --email-column email \
  --output report.csv \
  --batch-size 50

# Send the next 50
uv run mail-merge \
  --spreadsheet recipients.xlsx \
  --body body.txt \
  --subject "Hello {{name}}" \
  --email-column email \
  --output report.csv \
  --batch-size 50 \
  --resume
```

Run repeatedly with `--resume --batch-size N` until all emails are sent. When all recipients have succeeded, the tool logs "All emails already sent" and exits 0.

### Specific sheet

If your workbook has multiple sheets, select one by name:

```bash
--sheet "March contacts"
```

By default, the first sheet is used.

## Recommended workflow

1. **Dry run** — validate placeholders and data (`--dry-run`)
2. **Test email** — send one real email to yourself (`--test-email you@example.com`)
3. **Check your inbox** — verify subject, body, and formatting
4. **Full send** — run without `--dry-run` or `--test-email` (confirm prompt appears)
5. **Review report** — check console summary or `--output report.csv`
6. **Resume if needed** — re-run with `--resume` to retry any failures

## 10. Python API

If you want to call mail-merge from Python code instead of the command line, use the `send_merge()` function. It mirrors the CLI flags and returns a list of `SendResult` objects.

```python
from mail_merge.api import send_merge

# Dry run — validate without sending
results = send_merge(
    spreadsheet="recipients.xlsx",
    body="body.txt",
    subject="Hello {{name}}",
    email_column="email",
    dry_run=True,
)

# Send for real (client_id resolved from env var or ~/.mail-merge.toml)
results = send_merge(
    spreadsheet="recipients.xlsx",
    body="body.html",
    subject="Hello {{name}}",
    email_column="email",
    html=True,
    attachment=["report.pdf"],
    cc=["manager@example.com"],
)

# Filter recipients and send in batches with resume
results = send_merge(
    spreadsheet="recipients.xlsx",
    body="body.txt",
    subject="Hello {{name}}",
    email_column="email",
    filter=["company=Acme Corp"],
    output="report.csv",
    batch_size=50,
    resume=True,        # skip already-successful recipients
    confirm=True,       # show summary and prompt before sending
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
- **`confirm`** is `False` by default (the CLI enables it unless `--yes`, `--dry-run`, or `--test-email` is used).
- **`filter`** takes a list of filter expressions (e.g., `["company=Acme"]`).
- **`resume`** and **`batch_size`** work the same as the CLI flags.

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
