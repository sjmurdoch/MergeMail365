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
4. **Full send** — run without `--dry-run` or `--test-email`
5. **Review report** — check console summary or `--output report.csv`

## Future features

The following features are not yet implemented but are under consideration:

- **Send-as / shared mailbox** — send from a different address or shared mailbox (requires `Mail.Send.Shared` permission and Exchange Online mailbox permissions)
