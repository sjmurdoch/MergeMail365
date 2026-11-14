"""Addresses typed by the user (docs/review-fixes-plan.md, F7, G5)."""

import pytest

from mail_merge.addresses import parse_address, parse_addresses, split_addresses
from mail_merge.sender import EmailAddress as A


@pytest.mark.parametrize(("text", "expected"), [
    ("a@example.com", [A("a@example.com")]),
    ("  a@example.com  ", [A("a@example.com")]),
    ("Alice Example <a@example.com>", [A("a@example.com", "Alice Example")]),
    ("a@example.com, b@example.com", [A("a@example.com"), A("b@example.com")]),
    # Outlook's address line uses semicolons; a pasted list may have newlines.
    ("a@example.com; Bob <b@example.com>\nc@example.com", [A("a@example.com"), A("b@example.com", "Bob"), A("c@example.com")]),
    # The case that used to become the "addresses" Doe and Jane.
    ('"Doe, Jane" <jane@example.com>, bob@example.com', [A("jane@example.com", "Doe, Jane"), A("bob@example.com")]),
    ('"Doe; Jane" <jane@example.com>', [A("jane@example.com", "Doe; Jane")]),
    ('"The \\"Boss\\"" <boss@example.com>', [A("boss@example.com", 'The "Boss"')]),
    # Names people write unquoted, which a strict RFC parser refuses.
    ("[Team] Lead <lead@example.com>", [A("lead@example.com", "[Team] Lead")]),
    ("Dr. A. Jones (Maths) <aj@example.com>", [A("aj@example.com", "Dr. A. Jones (Maths)")]),
    ("Séan O'Brien <sean@example.com>", [A("sean@example.com", "Séan O'Brien")]),
    ("<a@example.com>", [A("a@example.com")]),
    ("a+tag@example.co.uk,", [A("a+tag@example.co.uk")]),
    ("", []),
    (" , ;  ", []),
])
def test_parse_addresses(text, expected):
    assert parse_addresses(text, "CC") == expected


def test_list_input_and_none():
    assert parse_addresses(None, "CC") == []
    assert parse_addresses(["a@example.com", "", "Bob <b@example.com>; c@example.com"], "CC") == [
        A("a@example.com"), A("b@example.com", "Bob"), A("c@example.com"),
    ]


@pytest.mark.parametrize("text", [
    "not-an-address",
    "a@example.com, not-an-address",
    "Doe, Jane <jane@example.com>",       # unquoted comma: "Doe" is not an address
    "a@",
    "@example.com",
    "a b@example.com",
    "a@example",                            # no top-level domain
    "Alice <>",
    "Alice <alice@example.com> extra",
    "a@exam ple.com",
    "ünïcode@example.com",                  # non-ASCII local part, as for recipients
    "a@example.com b@example.com",          # two addresses with no separator
    "<script>alert(1)</script>",
])
def test_invalid_entries_are_refused_with_the_field_and_the_entry_named(text):
    with pytest.raises(ValueError) as error:
        parse_addresses(text, "reply-to")
    message = str(error.value)
    assert message.startswith("Invalid reply-to address ")


def test_error_names_the_bad_entry_not_the_whole_list():
    with pytest.raises(ValueError, match=r"Invalid CC address 'bad@'"):
        parse_addresses("good@example.com, bad@, also-good@example.com", "CC")


def test_parse_address_wants_exactly_one():
    assert parse_address("Alice <a@example.com>", "test email") == A("a@example.com", "Alice")
    for text in ("", "a@example.com, b@example.com"):
        with pytest.raises(ValueError, match="Expected one test email address"):
            parse_address(text, "test email")


def test_split_addresses_keeps_quoted_and_bracketed_separators():
    assert split_addresses('"a,b" <x@example.com>;c@example.com , <d,e@example.com>') == [
        '"a,b" <x@example.com>', "c@example.com", "<d,e@example.com>",
    ]
