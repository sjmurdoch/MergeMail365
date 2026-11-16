"""What the system does to typed text (docs/phase-h-guards-plan.md, class E).

Phase H, macOS: the desktop app's window turned the typed
``"Murdoch, Steven" <s@example.com>`` into curly quotes, and the CC field
refused it. The parser had only been tested with the characters a developer
types in an editor.

Here every field that parses or compares what the user types is run against
every character a system puts in while typing or pasting. For each pair the
table says what must happen: SAME (as if the plain character had been
typed) or REFUSED (an error naming the entry). What must never happen is
the third thing: accepted, with a different meaning. That is how
``Company!=O’Neil`` came to exclude nobody.
"""

from collections.abc import Callable

import pytest

from mail_merge.addresses import parse_addresses
from mail_merge.api import apply_filters
from mail_merge.template import render, validate_template

SAME, REFUSED = "same", "refused"

# name -> (the plain text, what the system makes of it)
SUBSTITUTIONS: dict[str, tuple[str, str]] = {
    "curly double quotes (macOS, Word)": ('"', "“”"),
    "curly apostrophe (macOS, Word)": ("'", "’"),
    "no-break space (Option-space, web pages)": (" ", " "),
    "narrow no-break space (French punctuation)": (" ", " "),
    "zero-width space (copied from a web page)": ("", "​"),
    "byte-order mark (start of a pasted file)": ("", "﻿"),
    "direction marks (copied from Outlook)": ("", "‪‬"),
    "full-width at sign (East Asian input)": ("@", "＠"),
    "full-width comma (East Asian input)": (",", "，"),
}


def _substitute(text: str, name: str) -> str | None:
    """`text` as the system would deliver it, or None if the substitution
    doesn't apply to it. Paired characters open and close in turn; an
    invisible character is put at the start, the middle and the end."""
    plain, typed = SUBSTITUTIONS[name]
    if plain == "":
        middle = len(text) // 2
        mark, end = (typed[0], typed[-1])
        return mark + text[:middle] + mark + text[middle:] + end
    if plain not in text:
        return None
    out, i = [], 0
    for ch in text:
        if ch == plain:
            out.append(typed[i % len(typed)])
            i += 1
        else:
            out.append(ch)
    return "".join(out)


ROWS = [
    {"Company": "Acme Corp", "Manager's name": "Bob", "Email": "a@example.com"},
    {"Company": "O'Neil & Co", "Manager's name": 'Al "Big" Jones', "Email": "b@example.com"},
    {"Company": "Other, Inc", "Manager's name": "Di", "Email": "c@example.com"},
]


def _addresses(text: str) -> object:
    return [(a.name, a.address) for a in parse_addresses(text, "CC")]


def _kept(text: str) -> object:
    return [r["Email"] for r in apply_filters(ROWS, [text])]


def _rendered(name: str) -> object:
    """What a placeholder for the column typed as `name` is filled with.
    (Text outside the braces is the message, and is sent as typed.)"""
    template = "Dear {{" + name + "}},"
    unresolved = validate_template(template, list(ROWS[0]))
    if unresolved:
        raise ValueError(f"No column named {unresolved}")
    return render(template, ROWS[1])


# field -> (how it reads what was typed, the plain texts it is tried with)
FIELDS: dict[str, tuple[Callable[[str], object], list[str]]] = {
    "address list": (_addresses, [
        '"Doe, Jane" <jane@example.com>, bob@example.com',
        "Jane O'Brien <jane@example.com>",
        "jane@example.com",
    ]),
    "filter, equal": (_kept, ["Company=O'Neil & Co", "Company=Acme Corp", "Manager's name=Al \"Big\" Jones",
                              "Company=Other, Inc"]),
    "filter, not equal": (_kept, ["Company!=O'Neil & Co", "Company!=Acme Corp", "Manager's name!=Al \"Big\" Jones",
                                  "Company!=Other, Inc"]),
    "placeholder": (_rendered, ["Manager's name", "Company"]),
}

# What must happen where it isn't SAME, with the reason.
EXCEPTIONS: dict[tuple[str, str], tuple[str, str]] = {
    ("address list", "curly apostrophe (macOS, Word)"):
        ("kept", "a display name is sent as typed; O’Brien is a correct spelling"),
    ("address list", "no-break space (Option-space, web pages)"):
        ("kept", "inside a display name it is sent as typed; around an address it is trimmed"),
    ("address list", "narrow no-break space (French punctuation)"):
        ("kept", "as for the no-break space"),
    ("address list", "full-width at sign (East Asian input)"):
        (REFUSED, "the validator names the character; guessing an address is worse than asking"),
    ("address list", "full-width comma (East Asian input)"):
        (REFUSED, "not a separator; the entry is refused as one invalid address"),
    ("filter, equal", "full-width comma (East Asian input)"):
        ("differs", "a different character in a value: no cell matches, and a filter matching nobody is an error"),
    ("filter, not equal", "full-width comma (East Asian input)"):
        ("differs", "a different character in a value, not one a keyboard substitutes for a comma"),
}


def _cases() -> list[tuple[str, str]]:
    return [(field, name) for field in FIELDS for name in SUBSTITUTIONS]


@pytest.mark.parametrize(("field", "name"), _cases())
def test_substituted_text_means_the_same_or_is_refused(field: str, name: str) -> None:
    read, texts = FIELDS[field]
    expected, _why = EXCEPTIONS.get((field, name), (SAME, ""))
    applied = 0
    for text in texts:
        typed = _substitute(text, name)
        if typed is None:
            continue
        applied += 1
        meant = read(text)
        try:
            got = read(typed)
        except ValueError as exc:
            assert expected == REFUSED or (expected == "differs" and field == "filter, equal"), (
                f"{field}: {typed!r} was refused ({exc}); expected {expected}")
            assert str(exc), "a refusal must say why"
            continue
        if expected == SAME:
            assert got == meant, f"{field}: {typed!r} was read as {got!r}, but {text!r} as {meant!r}"
        elif expected == "kept":
            # Accepted with the typed character kept in a name: the
            # addresses themselves must be the same.
            assert [a for _, a in got] == [a for _, a in meant], (typed, got)  # type: ignore[union-attr]
        elif expected == REFUSED:
            pytest.fail(f"{field}: {typed!r} should be refused, but was read as {got!r}")
    if applied == 0:
        assert (field, name) not in EXCEPTIONS, "an exception is listed for a pair that never applies"


def test_exceptions_name_real_pairs() -> None:
    assert set(EXCEPTIONS) <= set(_cases())
