"""Example: using the MergeMail365 Python API."""

from mail_merge.api import send_merge

# --- 1. Dry run: validate templates without sending (the default) ---

results = send_merge(
    spreadsheet="recipients.xlsx",
    body="body.txt",
    subject="Event invitation for {{name}}",
    email_column="email",
    # send=False is the default — safe by default
)
print(f"Dry run: {sum(r.success for r in results)}/{len(results)} OK")

# --- 2. Send HTML email with attachments ---
# Must set send=True to actually send.
# confirm=True is the default — prompts before sending.

results = send_merge(
    spreadsheet="recipients.xlsx",
    body="body.html",
    subject="Monthly report for {{name}}",
    email_column="email",
    client_id="YOUR_CLIENT_ID",       # or set MERGEMAIL365_CLIENT_ID env var
    tenant_id="YOUR_TENANT_ID",       # or set MERGEMAIL365_TENANT_ID env var
    send=True,
    html=True,
    attachment=["report.pdf", "logo.png"],
    cc=["manager@example.com"],       # accepts a list or comma-separated string
    reply_to="support@example.com",
    importance="high",
)

# --- 3. Filter recipients ---

results = send_merge(
    spreadsheet="recipients.xlsx",
    body="body.txt",
    subject="Hello {{name}}",
    email_column="email",
    filters=["company=Acme Corp"],              # only Acme Corp recipients
)
print(f"Filtered: {len(results)} recipients")

# --- 4. Resume and batch: send in controlled chunks ---
# resume=True is the default — with --output set, previous successes
# are automatically skipped on re-run.

results = send_merge(
    spreadsheet="recipients.xlsx",
    body="body.txt",
    subject="Hello {{name}}",
    email_column="email",
    send=True,
    output="report.csv",             # resume reads this on next run
    batch_size=50,
)

# Just re-run the same call — successes are skipped automatically
results = send_merge(
    spreadsheet="recipients.xlsx",
    body="body.txt",
    subject="Hello {{name}}",
    email_column="email",
    send=True,
    output="report.csv",
    batch_size=50,
)

# --- 5. BCC blast: send same message to all recipients via BCC ---
# All recipients are BCC'd in batches (up to 499 per batch).
# Subject and body must be static (no {{placeholders}}).

# 5a. Dry run — validate without sending
results = send_merge(
    spreadsheet="recipients.xlsx",
    body="announcement.txt",
    subject="Important announcement",
    email_column="email",
    bcc_blast=True,
    bcc_blast_to="noreply@example.com",        # the To: address (recipients are BCC)
    # send=False is the default
)
print(f"BCC blast dry run: {len(results)} batch(es)")

# 5b. Test email — send the blast to yourself first
results = send_merge(
    spreadsheet="recipients.xlsx",
    body="announcement.txt",
    subject="Important announcement",
    email_column="email",
    client_id="YOUR_CLIENT_ID",
    bcc_blast=True,
    bcc_blast_to="noreply@example.com",
    test_email="your-email@example.com",       # sends only to you, not the list
)

# 5c. Send for real
results = send_merge(
    spreadsheet="recipients.xlsx",
    body="announcement.txt",
    subject="Important announcement",
    email_column="email",
    client_id="YOUR_CLIENT_ID",
    bcc_blast=True,
    bcc_blast_to="Undisclosed recipients <noreply@example.com>",  # display name supported
    send=True,
    confirm=True,                              # prompts before sending (the default)
)

# 5d. Recover from errors — use output + resume (same as individual sends)
results = send_merge(
    spreadsheet="recipients.xlsx",
    body="announcement.txt",
    subject="Important announcement",
    email_column="email",
    client_id="YOUR_CLIENT_ID",
    bcc_blast=True,
    bcc_blast_to="noreply@example.com",
    send=True,
    output="blast_report.csv",              # tracks per-recipient results
)
# If a batch fails, all recipients in that batch are marked as failed.
# Just re-run the same call — resume skips already-successful recipients.
for r in results:
    if not r.success:
        print(f"Failed: {r.email} — {r.status_code}: {r.error}")

# --- 6. Inspect results ---

for r in results:
    status = "OK" if r.success else f"FAILED ({r.status_code}: {r.error})"
    print(f"  {r.email}: {status}")
