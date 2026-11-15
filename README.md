# Office 365 Mail Merge

A Python CLI tool to send personalized emails via the Microsoft Graph API using an Excel/XLSX spreadsheet as the data source.

This tool allows you to send mail merge campaigns using your Office 365 account. It uses modern delegated authentication (OAuth 2.0 device code flow) and respects API rate limits.

## Features

- **Personalized Emails**: Use `{{column_name}}` placeholders in the subject and body to insert data from your spreadsheet. Any column name works (`{{First Name}}`, `{{E-mail}}`), case and spaces inside the braces don't matter, and a placeholder that names no column stops the send. Dates are written `2026-12-01` and percentages `25%`; other number formats, such as currency, are not applied (see the [tutorial](docs/tutorial.md#5-write-your-email-template)).
- **Flexible Data Source**: Reads recipients from an `.xlsx` file.
- **Safe by Default**: Performs a dry run by default. You must explicitly pass `--send` to deliver emails.
- **Authentication**: Signs in through your web browser (or with a device code, `--device-code`, on a machine without one). Tokens are cached for future use; each run says which account it sends as, and `--sign-out` signs out.
- **HTML & Attachments**: Send HTML emails (`--html`), with spreadsheet values inserted as text rather than markup, and include multiple attachments (`--attachment`).
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

    Every row is sent to, including rows hidden or filtered out in Excel: delete the rows you want left out, or use `--filter`.

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
usage: mergemail365 --spreadsheet SPREADSHEET --body BODY --subject SUBJECT --email-column EMAIL_COLUMN [options]
       mergemail365 --sign-out [--client-id CLIENT_ID] [--tenant-id TENANT_ID]

Send personalised emails via Microsoft Graph API

options:
  -h, --help            show this help message and exit
  --spreadsheet SPREADSHEET
                        Path to .xlsx file with recipients (required)
  --body BODY           Path to body template file (plain text by default; use --html for HTML) (required)
  --subject SUBJECT     Email subject (supports {{placeholders}}) (required)
  --email-column EMAIL_COLUMN
                        Column name containing email addresses (required)
  --client-id CLIENT_ID
                        Azure AD application (client) ID (or set MERGEMAIL365_CLIENT_ID env var, or config file)
  --tenant-id TENANT_ID
                        Azure AD tenant ID (or set MERGEMAIL365_TENANT_ID env var, or config file; default: 'common')
  --sheet SHEET         Sheet name (default: first sheet)
  --name-column NAME_COLUMN
                        Column name containing recipient display names (included in the To: header)
  --test-email TEST_EMAIL
                        Send a single test email to this address using the first recipient's data, then exit
  --send                Actually send emails (default is dry-run)
  --device-code         Use device code flow for headless/SSH environments (default: opens system browser)
  --output OUTPUT       Path to write CSV report
  --delay DELAY         Base seconds between sends (default 2s; Exchange Online allows ~30 msgs/min; adaptive throttling increases this on rate limits)
  --max-retries MAX_RETRIES
                        Max retries per recipient for server (5xx) and connection errors (default 3; a timeout after sending is never retried)
  --importance {low,normal,high}
                        Email importance level
  --cc CC               CC addresses, separated by commas or semicolons; each 'Name <address>' or a bare address
  --bcc BCC             BCC addresses, as for --cc
  --html                Treat body as HTML (default: plain text)
  --no-save-to-sent     Do not save sent messages to Sent Items folder
  --attachment ATTACHMENT
                        Path to file attachment (repeatable)
  --reply-to REPLY_TO   Reply-to addresses, as for --cc
  --filter FILTERS      Filter recipients: 'column=value' or 'column!=value' (repeatable, AND logic)
  --no-resume           Send to all recipients even if --output CSV shows previous successes
  --batch-size BATCH_SIZE
                        Max emails to send per invocation (use with --output for resumable batching)
  -y, --yes             Skip confirmation prompt
  --sign-out            Sign out of every cached Microsoft account, then exit (needs only the client ID)
  --log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}
                        Logging level (or set MERGEMAIL365_LOG_LEVEL, or log-level in the config file; default: INFO)
  -v, --verbose         Same as --log-level DEBUG
  --log-file            Enable debug logging to a file
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

> **Only on this computer**: the web interface listens on `localhost`, so only you can reach it. `--host` with an address other computers can reach is refused unless you add `--allow-remote`; the connection is not encrypted, and anyone who learns the access URL could send email as the signed-in account, so don't do this on a network you don't control.

> **Note on Authentication**: The web interface uses `localhost` for authentication redirects. If you open the app at `127.0.0.1` instead, signing in moves you to `localhost`: the app keeps your uploaded spreadsheet, and the page starts again at step 1.

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
