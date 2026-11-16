# MergeMail365

Mail merge for Microsoft 365: send each person on a spreadsheet their own email, from your own account, through the Microsoft Graph API. Recipients come from an Excel (`.xlsx`) file, and `{{column name}}` placeholders in the subject and body are filled in from each row.

There are three ways to use it:

- **Desktop app** for macOS and Windows: a step-by-step wizard in its own window, with nothing to install.
- **Web interface** (`mergemail365-web`): the same wizard in your browser, run from a terminal.
- **Command line** (`mergemail365`) and a **Python function** (`send_merge()`), for larger sends, scripting, resuming and batching.

Nothing is sent by accident: the wizard makes you send yourself a test email and do a dry run first, and the command line does a dry run unless you add `--send`.

## What it does

- **Placeholders.** `{{First Name}}`, `{{E-mail}}` or any other column name, in the subject and the body. Case and spaces inside the braces don't matter. A placeholder that names no column stops the send before anything goes out.
- **Readable values.** Dates are written `2026-12-01` (with `14:30` when there is a time) and percentages `25%`. Other Excel number formats, such as currency, are not applied; the value is sent as the plain number, and you are told which columns that affects.
- **Plain text or HTML.** The wizard has a rich text editor; the command line takes an HTML file with `--html`. In HTML, spreadsheet values are inserted as text, never as markup.
- **Attachments, CC, BCC, Reply-To, importance**, and a display name for each recipient from a spreadsheet column. Addresses can be written `Name <address>` and separated by commas or semicolons.
- **Filters**: send to the rows where a column equals, or doesn't equal, a value.
- **BCC mode**: one message to everyone, with every recipient in BCC so that they cannot see each other.
- **Everything is checked first.** Addresses, placeholders, options and attachment sizes are validated before the first email, and before you are asked to sign in.
- **Honest results.** Each email is reported as sent, failed, or unknown (Microsoft received the request but didn't answer in time, so it may have been delivered; such an email is not retried, to avoid sending it twice).
- **Rate limits.** Sends are spaced 2 seconds apart by default and slow down when Microsoft asks.
- **Resume and batches** (command line): with `--output report.csv`, re-running the same command skips everyone already sent to, and `--batch-size` sends a limited number per run.
- **Interrupted sends** (wizard): if the app quits part-way through a send, the next start tells you which emails went out.

## What you need

- A Microsoft 365 account that can send email.
- An **app registration** in Microsoft Entra ID (Azure AD) with the delegated `Mail.Send` permission; see [Register an app](#register-an-app). You need its client ID and, usually, your tenant ID. The desktop app on the releases page already has these built in for UCL accounts.
- To run from source: Python 3.14 or later and [uv](https://docs.astral.sh/uv/).

## Desktop app

1. Download `MergeMail365-macOS.zip` or `MergeMail365-Windows.zip` from the [latest release](https://github.com/sjmurdoch/MergeMail365/releases/latest) and unzip it.
2. Open the app. It is not signed with a certificate that macOS or Windows trusts, so the first time you have to allow it:
   - **macOS 15 or later:** try to open it, then go to System Settings > Privacy & Security and click **Open Anyway**. On earlier versions, Control-click the app and choose **Open**.
   - **Windows:** if SmartScreen blocks it, choose **More info**, then **Run anyway**.
3. Click **Sign in**. Your usual browser opens for the Microsoft sign-in, and the app shows your account when it is done.
4. Follow the six steps described under [The wizard](#the-wizard).

The released builds use UCL's app registration, so they work with UCL accounts. For another organisation, run the web interface from source with your own client ID, or build your own bundle (`MERGEMAIL365_CLIENT_ID=... MERGEMAIL365_TENANT_ID=... uv run pyinstaller mergemail365.spec`).

The desktop app always writes a log file, which is what to send when reporting a problem; see [Logs](#logs).

## Install from source

```bash
git clone https://github.com/sjmurdoch/MergeMail365.git
cd MergeMail365
uv sync --extra web        # command line and web interface
uv sync --extra desktop    # the same, plus the native window (--desktop)
```

`uv sync` alone installs only the command line. Commands are then run as `uv run mergemail365 ...` and `uv run mergemail365-web ...`.

### Register an app

The full steps are in the [tutorial](docs/tutorial.md#2-register-an-azure-ad-application). In short, in the Azure portal under App registrations:

1. Create a registration for accounts in your organisation.
2. Under Authentication, add the platform **Mobile and desktop applications** with these redirect URIs: `http://localhost` (sign-in from the command line and the desktop window) and `http://localhost:5050/auth/callback` (sign-in from the web interface in a browser).
3. Set **Allow public client flows** to Yes, which `--device-code` needs.
4. Under API permissions, add the Microsoft Graph delegated permission `Mail.Send`, and grant admin consent if your organisation requires it.

### Save your IDs

Rather than passing `--client-id` and `--tenant-id` every time, put them in `~/.mergemail365.toml` (on Windows, `%LOCALAPPDATA%\mergemail365\config.toml`):

```toml
client-id = "YOUR_CLIENT_ID"
tenant-id = "YOUR_TENANT_ID"
log-level = "INFO"    # optional
```

Each setting can also come from an environment variable (`MERGEMAIL365_CLIENT_ID`, `MERGEMAIL365_TENANT_ID`, `MERGEMAIL365_LOG_LEVEL`). A command-line option wins over the environment, which wins over the file.

## Web interface

```bash
uv run mergemail365-web             # opens the wizard in your browser
uv run mergemail365-web --desktop   # opens it in its own window instead
uv run mergemail365-web --port 8080 --log-file
```

The terminal prints an access URL (`http://localhost:5050/?token=...`) and opens it for you. The token is new each time the app starts, and the page cannot be used without it.

### The wizard

1. **Data.** Sign in, and upload the spreadsheet (choose the sheet if there are several). The page lists any columns whose number format won't be applied.
2. **Compose.** Choose the email column and, optionally, a name column. Write the subject and body, in plain text or with the rich text editor; click a column's chip to insert its placeholder. Under the additional options are CC, BCC, Reply-To, importance, attachments, filters and BCC mode. Mistakes (a placeholder naming no column, a malformed address) are reported here.
3. **Preview.** Page through every email as it will be sent, and see which rows were skipped for an invalid address.
4. **Test.** Send one real email to yourself, using the first recipient's data. You can't go on until Microsoft has accepted it.
5. **Verify.** A dry run of the whole send.
6. **Send.** Type `SEND` to confirm, then watch each email go. **Stop sending** stops before the next email. Afterwards you can download a report as CSV.

Going back and changing anything means the test email and dry run have to be done again. **New merge** clears everything.

The wizard sends to at most 99 recipients at a time, 2 seconds apart; use the command line for more. The subject, body and chosen columns are remembered if you reload the page or reopen the app.

### Security of the web interface

The web interface listens on `localhost`, so only this computer can reach it, and every request needs the access token. `--host` with an address other computers can reach is refused unless you add `--allow-remote`: the connection is not encrypted, and anyone who learns the access URL could send email as the signed-in account, so only do that on a network you control.

Sign-in returns to `localhost`. If you opened the app at `127.0.0.1`, signing in moves you to `localhost`; your uploaded spreadsheet is kept and the page starts again at step 1.

## Command line

A spreadsheet (`recipients.xlsx`):

| name  | email             |
|-------|-------------------|
| Alice | alice@example.com |
| Bob   | bob@example.com   |

A body file (`body.txt`):

```
Hi {{name}},

This is a test email.
```

**1. Dry run** (the default): checks everything and shows what would be sent, without signing in.

```bash
uv run mergemail365 \
  --spreadsheet recipients.xlsx \
  --body body.txt \
  --subject "Hello {{name}}" \
  --email-column email
```

**2. Test email**: add `--test-email you@example.com` to send one real email to yourself, using the first row's data. Your browser opens for you to sign in; on a machine without one, add `--device-code`.

**3. Send**: add `--send`. You are shown the account it will send from and the number of recipients, and asked to confirm (`--yes` skips the question). Add `--output report.csv` to get a report and to be able to resume.

```bash
uv run mergemail365 \
  --spreadsheet recipients.xlsx \
  --body body.txt \
  --subject "Hello {{name}}" \
  --email-column email \
  --output report.csv \
  --send
```

Things to know:

- **Every row is sent to**, including rows hidden or filtered out in Excel. Delete the rows you want left out, or use `--filter`.
- **Resuming.** If a send with `--output` is interrupted or some emails fail, run the same command again: rows already sent are skipped and the rest are tried. An email whose outcome is unknown is skipped with a warning; delete its line from the report to send it again. `--no-resume` sends to everyone regardless.
- **Sign-in is remembered** between runs, and shared with the web interface. Each run says which account it sends as; `mergemail365 --sign-out` forgets it.
- **Limits.** Attachments can total about 3 MB per message. In BCC mode (`--bcc-blast --bcc-blast-to you@example.com`) recipients are sent in batches of up to 500 addresses per message.

The [tutorial](docs/tutorial.md) covers each option with examples, including HTML emails, filters, batches and BCC mode.

### Options

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

## Python API

`send_merge()` takes the same options as the command line and returns one `SendResult` for each email. It raises `FileNotFoundError`, `ValueError` or `RuntimeError` instead of exiting, and like the command line it does a dry run unless `send=True`.

```python
from mail_merge.api import send_merge

results = send_merge(
    spreadsheet="recipients.xlsx",
    body="body.txt",
    subject="Hello {{name}}",
    email_column="email",
    output="report.csv",
    send=True,
    confirm=False,  # don't ask on the terminal
)

for result in results:
    if result.unknown:
        print(f"{result.email}: no answer from Microsoft; it may have been delivered")
    elif not result.success:
        print(f"{result.email}: failed: {result.error}")
```

See the [tutorial](docs/tutorial.md#11-python-api) for more.

## Logs

`--log-level` (or `-v` for `DEBUG`) sets how much the terminal shows. `--log-file` also writes a detailed log to a file; the desktop app always does.

| Platform | Log file |
|---|---|
| macOS | `~/Library/Logs/mergemail365/mergemail365.log` |
| Windows | `%LOCALAPPDATA%\mergemail365\logs\mergemail365.log` |
| Linux | `~/.local/state/mergemail365/log/mergemail365.log` |

The log file records recipients' addresses and the result of each send. It does not contain your access token or the content of your emails, so it is safe to send when asking for help. Versions up to 0.6.0 did log both; if you used one with file logging, delete the old log files.

## Development

```bash
uv sync --all-extras              # everything, including the test tools
uv run playwright install chromium   # once, for the browser tests
uv run pytest                     # all tests
uv run pytest tests/test_cli.py   # one file
uv run mypy                       # types
uv run ruff check .               # lint (Python)
biome lint                        # lint (JavaScript; brew install biome)
```

Note that `uv run` without `--all-extras` removes the web extras again; after `uv sync --all-extras`, use `uv run --all-extras ...` or `.venv/bin/python -m pytest`.

Further reading: [CLAUDE.md](CLAUDE.md) describes the architecture, [CHANGELOG.md](CHANGELOG.md) what changed in each version, [docs/quint-model.md](docs/quint-model.md) the formal model of the wizard, and [docs/codesigning.md](docs/codesigning.md) how the bundles are signed.
