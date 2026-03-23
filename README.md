# Office 365 Mail Merge

A Python CLI tool to send personalized emails via the Microsoft Graph API using an Excel/XLSX spreadsheet as the data source.

This tool allows you to send mail merge campaigns using your Office 365 account. It uses modern delegated authentication (OAuth 2.0 device code flow) and respects API rate limits.

## Features

- **Personalized Emails**: Use `{{column_name}}` placeholders in the subject and body to insert data from your spreadsheet.
- **Flexible Data Source**: Reads recipients from an `.xlsx` file.
- **Safe by Default**: Performs a dry run by default. You must explicitly pass `--send` to deliver emails.
- **Authentication**: Uses a secure, interactive device authorization flow to get permissions. Tokens are cached for future use.
- **HTML & Attachments**: Send HTML emails (`--html`) and include multiple attachments (`--attachment`).
- **CC & BCC**: Add static CC and BCC recipients to every email.
- **Test Before Sending**: Send a test email to yourself (`--test-email`) to verify formatting.
- **Rate Limit Aware**: Automatically handles Microsoft Graph API rate limiting with adaptive backoff.
- **Resume Failed Sends**: Optionally create a CSV report (`--output`) and automatically resume from where you left off, skipping already successful recipients.
- **Filter Recipients**: Send to a subset of your list by filtering on column values.
- **BCC Blast**: Send a single message to a large audience with each recipient in the BCC field for privacy.
- **Python API**: A `send_merge()` function is available for programmatic use.

## Installation

1.  Clone the repository:
    ```bash
    git clone https://github.com/your-username/MergeMail365.git
    cd MergeMail365
    ```

2.  Install dependencies using `uv` (recommended) or `pip`:
    ```bash
    # Using uv
    uv sync

    # Or using pip and a virtual environment
    python -m venv .venv
    source .venv/bin/activate
    pip install -e .
    ```

## Quick Start

1.  **Register an Azure AD Application**: Follow the [tutorial](docs/tutorial.md#2-register-an-azure-ad-application) to set up an app registration with `Mail.Send` permissions. You will need the **Application (client) ID**.

2.  **Create a spreadsheet** (`recipients.xlsx`):
    | name  | email             |
    |-------|-------------------|
    | Alice | alice@example.com |
    | Bob   | bob@example.com   |

3.  **Create a body file** (`body.txt`):
    ```
    Hi {{name}},

    This is a test email.
    ```

4.  **Run a dry run**:
    ```bash
    mergemail365
      --spreadsheet recipients.xlsx 
      --body body.txt 
      --subject "Hello {{name}}" 
      --email-column email 
      --client-id YOUR_CLIENT_ID
    ```

5.  **Send a test email** to yourself:
    ```bash
    mergemail365
      --spreadsheet recipients.xlsx 
      --body body.txt 
      --subject "Hello {{name}}" 
      --email-column email 
      --client-id YOUR_CLIENT_ID 
      --test-email your.address@example.com
    ```
    You will be prompted to sign in to your Microsoft 365 account in a browser.

6.  **Send for real**:
    ```bash
    mergemail365
      --spreadsheet recipients.xlsx 
      --body body.txt 
      --subject "Hello {{name}}" 
      --email-column email 
      --client-id YOUR_CLIENT_ID 
      --send
    ```

For detailed instructions and advanced features, see the [**Tutorial**](docs/tutorial.md).

## Usage

```
usage: mergemail365 [-h] --spreadsheet SPREADSHEET --body BODY --subject SUBJECT --email-column EMAIL_COLUMN [--client-id CLIENT_ID] [--tenant-id TENANT_ID] [--sheet SHEET]
                    [--test-email TEST_EMAIL] [--send] [--output OUTPUT] [--delay DELAY] [--max-retries MAX_RETRIES] [--importance {low,normal,high}] [--cc CC] [--bcc BCC]
                    [--html] [--no-save-to-sent] [--attachment ATTACHMENT] [--reply-to REPLY_TO] [--filter FILTERS] [--no-resume] [--batch-size BATCH_SIZE] [-y]
                    [--log-level LOG_LEVEL] [--bcc-blast] [--bcc-blast-to BCC_BLAST_TO]

Send personalised emails via Microsoft Graph API

options:
  -h, --help            show this help message and exit
  --spreadsheet SPREADSHEET
                        Path to .xlsx file with recipients
  --body BODY           Path to body template file (plain text by default; use --html for HTML)
  --subject SUBJECT     Email subject (supports {{placeholders}})
  --email-column EMAIL_COLUMN
                        Column name containing email addresses
  --client-id CLIENT_ID
                        Azure AD application (client) ID (or set MERGEMAIL365_CLIENT_ID env var, or config file)
  --tenant-id TENANT_ID
                        Azure AD tenant ID (or set MERGEMAIL365_TENANT_ID env var, or config file; default: 'common')
  --sheet SHEET         Sheet name (default: first sheet)
  --test-email TEST_EMAIL
                        Send a single test email to this address using the first recipient's data, then exit
  --send                Actually send emails (default is dry-run)
  --output OUTPUT       Path to write CSV report
  --delay DELAY         Base seconds between sends (default 2s; Exchange Online allows ~30 msgs/min; adaptive throttling increases this on rate limits)
  --max-retries MAX_RETRIES
                        Max retries per recipient for 5xx errors
  --importance {low,normal,high}
                        Email importance level
  --cc CC               Comma-separated CC addresses
  --bcc BCC             Comma-separated BCC addresses
  --html                Treat body as HTML (default: plain text)
  --no-save-to-sent     Do not save sent messages to Sent Items folder
  --attachment ATTACHMENT
                        Path to file attachment (repeatable)
  --reply-to REPLY_TO   Comma-separated reply-to addresses
  --filter FILTERS      Filter recipients: 'column=value' or 'column!=value' (repeatable, AND logic)
  --no-resume           Send to all recipients even if --output CSV shows previous successes
  --batch-size BATCH_SIZE
                        Max emails to send per invocation (use with --output for resumable batching)
  -y, --yes             Skip confirmation prompt
  --log-level LOG_LEVEL
                        Logging level
  --bcc-blast           Send all recipients via BCC in batches (recipients cannot see each other)
  --bcc-blast-to BCC_BLAST_TO
                        The To: address used in BCC blast mode (required with --bcc-blast)
```

## Web Interface

Mail Merge includes a browser-based wizard to guide you through the process.

1.  **Install web dependencies**:
    ```bash
    uv sync --extra web
    ```

2.  **Start the web server**:
    ```bash
    mergemail365-web
    ```

3.  **Open your browser**: Navigate to the URL printed in the terminal (usually `http://localhost:5050/?token=...`).

The web interface provides a step-by-step wizard:
- **Setup**: Configure your Azure App ID, upload your spreadsheet, and compose your message with live placeholder validation.
- **Preview**: Scroll through rendered versions of every email before sending.
- **Test**: Send a single real email to your own address to verify formatting.
- **Verify**: Run a full dry-run to ensure all data is valid.
- **Send**: Monitor real-time progress as emails are delivered.

> **Note on Authentication**: The web interface uses `localhost` for authentication redirects. If you manually access the app via `127.0.0.1`, you will be automatically redirected to `localhost` when signing in to ensure your session is preserved.

## Development & Testing

### Setup for Development

To install all development tools and dependencies:

```bash
uv sync --all-extras --group dev
```

### Running Tests

We use `pytest` for testing. The suite includes CLI tests, API tests, and Web Interface tests.

```bash
# Run all tests
uv run pytest

# Run specific test files
uv run pytest tests/test_web.py
uv run pytest tests/test_cli.py

# Run with coverage report
uv run pytest --cov=mail_merge
```

### Type Checking

The project uses `mypy` for static type analysis:

```bash
uv run mypy
```

## Python API

The core logic can also be used as a Python library.

```python
from mail_merge.api import send_merge

results = send_merge(
    spreadsheet="recipients.xlsx",
    body="body.txt",
    subject="Hello {{name}}",
    email_column="email",
    send=True,
    client_id="YOUR_CLIENT_ID",
)

for result in results:
    if not result.success:
        print(f"Failed to send to {result.email}: {result.error}")
```
See the [API documentation in the tutorial](docs/tutorial.md#10-python-api) for more details.
