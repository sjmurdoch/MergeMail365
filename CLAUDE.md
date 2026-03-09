# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A Python CLI tool (`mail-merge`) that sends personalised emails via Microsoft Graph API. Recipients come from an Excel spreadsheet, and the email body/subject use `{{column_name}}` placeholders.

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
```

## Architecture

Source lives under `src/mail_merge/` (src layout). There are two entry points:

1. **CLI** (`cli.py:main()`) — parses args, sets up logging, delegates to `send_merge()`, converts exceptions to exit codes.
2. **Python API** (`api.py:send_merge()`) — single function mirroring all CLI flags. Raises exceptions (`FileNotFoundError`, `ValueError`, `RuntimeError`) instead of returning exit codes. Returns `list[SendResult]`.

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
