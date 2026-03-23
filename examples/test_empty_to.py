"""Probe whether the Graph API accepts an empty toRecipients array.

Uses the token already cached by MergeMail365 so no browser login is needed
(as long as you have run mergemail365 --send or --test-email at least once).

Usage:
    uv run python examples/test_empty_to.py --to you@example.com
    uv run python examples/test_empty_to.py --to you@example.com --client-id ... --tenant-id ...

The script sends two real emails to --to and reports which payloads the
Graph API accepted:

  Test A — toRecipients: []  (empty array, recipient only in BCC)
  Test B — toRecipients omitted entirely

A 202 response means the API accepted that form; anything else is printed
with its status code and error body.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import requests

from mail_merge.auth import acquire_token
from mail_merge.config import load_config
from mail_merge.sender import GRAPH_SEND_URL


def _token(client_id: str | None, tenant_id: str | None) -> str:
    config = load_config()
    cid = client_id or os.environ.get("MERGEMAIL365_CLIENT_ID") or config.get("client_id")
    tid = tenant_id or os.environ.get("MERGEMAIL365_TENANT_ID") or config.get("tenant_id") or "common"
    if not cid:
        sys.exit(
            "client-id is required (pass --client-id, set MERGEMAIL365_CLIENT_ID, or add to ~/.mergemail365.toml)"
        )
    return acquire_token(cid, tid)


def _send(token: str, payload: dict) -> tuple[int, str]:
    resp = requests.post(
        GRAPH_SEND_URL,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    return resp.status_code, resp.text


def _base_message(to_addr: str) -> dict:
    return {
        "subject": "[MergeMail365 probe] empty-To test — ignore",
        "body": {"contentType": "Text", "content": "This is an automated probe email. You can delete it."},
        "bccRecipients": [{"emailAddress": {"address": to_addr}}],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--to", required=True, help="Address to receive the probe emails (placed in BCC)")
    parser.add_argument("--client-id", default=None)
    parser.add_argument("--tenant-id", default=None)
    args = parser.parse_args()

    print("Acquiring token (using cached credentials if available)…")
    token = _token(args.client_id, args.tenant_id)
    print("Token acquired.\n")

    tests = [
        (
            "Test A — toRecipients: []  (empty array)",
            {"message": {**_base_message(args.to), "toRecipients": []}},
        ),
        (
            "Test B — toRecipients omitted entirely",
            {"message": _base_message(args.to)},
        ),
        (
            "Test C — toRecipients set to normal address",
            {"message": {**_base_message(args.to), "toRecipients": [{
                "emailAddress": {
                    "address": "steven@test.murdoch.is"
                }
            }]}},
        ),
                (
            "Test D — toRecipients set to undisclosed-recipients (with semicolon)",
            {"message": {**_base_message(args.to), "toRecipients": [{
                "emailAddress": {
                    "address": "undisclosed-recipients:;"
                }
            }]}},
        ),
    ]

    for label, payload in tests:
        print(f"{label}")
        print(f"  Payload: {json.dumps(payload['message'], separators=(',', ':'))}")
        status, body = _send(token, payload)
        if status == 202:
            print(f"  ✅ Accepted (HTTP 202)\n")
        else:
            print(f"  ❌ Rejected (HTTP {status})")
            if body:
                try:
                    print(f"  Error: {json.loads(body)['error']['message']}")
                except Exception:
                    print(f"  Body:  {body[:300]}")
            print()


if __name__ == "__main__":
    main()
