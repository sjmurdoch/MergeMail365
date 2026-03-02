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

# CLI usage (after install)
uv run mail-merge --spreadsheet recipients.xlsx --body body.txt --subject "Hello {{name}}" --email-column email --client-id <azure-app-id>
```

## Architecture

Source lives under `src/mail_merge/` (src layout). The CLI orchestration flow in `cli.py` is strictly ordered: parse args → read spreadsheet → read body template → validate all placeholders (abort if any unresolvable) → authenticate (MSAL device code) → send → report. All validation happens before any sending.

Key design decisions:
- **`config.py`** reads `~/.mail-merge.toml` for persistent `client-id` / `tenant-id`. Precedence: CLI flag → env var → config file → default (`"common"` for tenant-id).
- **`auth.py`** uses lazy import in `cli.py` — only imported when authentication is actually needed (skipped for `--dry-run`)
- **`sender.py`** has two retry strategies: 429 (rate limit) honours `Retry-After` with a cap of 20 attempts; 5xx retries use exponential backoff capped at `--max-retries`. 4xx errors (non-429) fail immediately. `--delay` defaults to 1s with adaptive throttling: delay doubles (up to 30s) on 429s and halves back to the base when clear.
- **`template.py`** uses case-insensitive matching — `{{Name}}` matches a column called `name`
- **`cli.py:main()`** accepts `argv` parameter for testability — all CLI tests call `main([...])` directly
- **`--test-email`** sends one email to a specified address using first recipient's data, then exits (for pre-send verification)
- **`--importance`** sets email importance (`low`, `normal`, `high`); omitted from API by default
- **`--cc`** / **`--bcc`** accept comma-separated addresses for CC/BCC recipients

## Testing

Tests use `responses` library to mock HTTP calls to Graph API. Auth (`mail_merge.auth.acquire_token`) is monkeypatched in CLI tests that need authentication. The `sample_xlsx` and `body_template_file` fixtures in `conftest.py` create temporary test files.
