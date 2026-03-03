"""Example: using the mail-merge Python API."""

from mail_merge.api import send_merge

# --- 1. Dry run: validate templates without sending ---

results = send_merge(
    spreadsheet="recipients.xlsx",
    body="body.txt",
    subject="Event invitation for {{name}}",
    email_column="email",
    dry_run=True,
)
print(f"Dry run: {sum(r.success for r in results)}/{len(results)} OK")

# --- 2. Send HTML email with attachments ---

results = send_merge(
    spreadsheet="recipients.xlsx",
    body="body.html",
    subject="Monthly report for {{name}}",
    email_column="email",
    client_id="YOUR_CLIENT_ID",       # or set MAIL_MERGE_CLIENT_ID env var
    tenant_id="YOUR_TENANT_ID",       # or set MAIL_MERGE_TENANT_ID env var
    html=True,
    attachment=["report.pdf", "logo.png"],
    cc=["manager@example.com"],       # accepts a list or comma-separated string
    reply_to="support@example.com",
    importance="high",
    confirm=True,                     # prompt for confirmation before sending
)

# --- 3. Filter recipients ---

results = send_merge(
    spreadsheet="recipients.xlsx",
    body="body.txt",
    subject="Hello {{name}}",
    email_column="email",
    dry_run=True,
    filter=["company=Acme Corp"],              # only Acme Corp recipients
)
print(f"Filtered: {len(results)} recipients")

# --- 4. Resume and batch: send in controlled chunks ---

# First batch — sends up to 50 emails, writes results to report.csv
results = send_merge(
    spreadsheet="recipients.xlsx",
    body="body.txt",
    subject="Hello {{name}}",
    email_column="email",
    output="report.csv",
    batch_size=50,
)

# Subsequent batches — resume skips successes, retries failures
results = send_merge(
    spreadsheet="recipients.xlsx",
    body="body.txt",
    subject="Hello {{name}}",
    email_column="email",
    output="report.csv",
    batch_size=50,
    resume=True,                      # read report.csv and skip successes
)

# --- 5. Inspect results ---

for r in results:
    status = "OK" if r.success else f"FAILED ({r.status_code}: {r.error})"
    print(f"  {r.email}: {status}")
