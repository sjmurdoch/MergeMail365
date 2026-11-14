"""Addresses typed by the user: CC, BCC, reply-to, the To address of BCC
mode and the test address.

One parser for all of them, so each is checked the same way as the
recipients' column, before anything is sent. Without that, a mistyped CC
address was only discovered when Microsoft Graph rejected the message, once
per recipient (docs/review-fixes-plan.md, F7, G5).

Accepted: ``alice@example.com`` or ``Alice Example <alice@example.com>``,
several separated by commas or semicolons (what Outlook's address line
uses). A display name containing a comma must be quoted, as in
``"Example, Alice" <alice@example.com>``.
"""

import re

from mail_merge.sender import EmailAddress

_NAME_AND_ADDRESS_RE = re.compile(r"^(.*)<([^<>]*)>$", re.DOTALL)


def split_addresses(text: str) -> list[str]:
    """Split on commas and semicolons that are not inside a quoted display
    name or an <address>. Empty entries (a trailing comma) are dropped."""
    parts: list[str] = []
    current: list[str] = []
    in_quotes = False
    in_angle = False
    escaped = False
    for ch in text:
        if escaped:
            escaped = False
        elif ch == "\\" and in_quotes:
            escaped = True
        elif ch == '"':
            in_quotes = not in_quotes
        elif ch == "<" and not in_quotes:
            in_angle = True
        elif ch == ">" and not in_quotes:
            in_angle = False
        elif ch in ",;\n" and not in_quotes and not in_angle:
            parts.append("".join(current))
            current = []
            continue
        current.append(ch)
    parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


def _parse_one(entry: str, label: str) -> EmailAddress:
    from email_validator import EmailNotValidError, validate_email

    # "Display Name <address>", or just the address. Deliberately not an
    # RFC 5322 parser: people write names such as [Team] Lead or Dr. A. Jones
    # unquoted, which a strict parser refuses. The name is whatever precedes
    # the <address>; the address itself is what gets validated.
    match = _NAME_AND_ADDRESS_RE.match(entry)
    name, address = (match[1].strip(), match[2].strip()) if match else ("", entry)
    if len(name) >= 2 and name[0] == name[-1] == '"':
        name = name[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    try:
        # The same check as the recipients' column (api.validate_emails).
        validate_email(address, check_deliverability=False, allow_smtputf8=False)
    except EmailNotValidError as exc:
        raise ValueError(f"Invalid {label} address {entry!r}: {exc}") from exc
    return EmailAddress(address=address, name=name or None)


def parse_addresses(value: str | list[str] | None, label: str) -> list[EmailAddress]:
    """Parse and validate a list of addresses; ``label`` ("CC", "reply-to")
    names the field in the error.

    Accepts one string holding several addresses, or a list of such strings.
    Raises ``ValueError`` naming the first entry that isn't a valid address.
    """
    if value is None:
        return []
    texts = [value] if isinstance(value, str) else list(value)
    return [_parse_one(entry, label) for text in texts for entry in split_addresses(text)]


def parse_address(value: str, label: str) -> EmailAddress:
    """Parse and validate exactly one address."""
    found = parse_addresses(value, label)
    if len(found) != 1:
        raise ValueError(f"Expected one {label} address, got {len(found)}: {value!r}")
    return found[0]
