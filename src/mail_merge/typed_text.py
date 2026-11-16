"""Characters that systems put into text as it is typed or pasted.

macOS replaces a typed ``"`` or ``'`` with a curly one (in the desktop app's
window too, where the user cannot turn it off), a space typed with Option
held is a no-break space, and text copied from a web page or from Outlook
can carry characters that take no space on screen. The user sees what they
meant to type, so the fields that compare or parse typed text treat these
as the plain character (tests/test_typed_text.py lists each field and
character).
"""

# Take no space and are not part of any address or name: zero-width space,
# word joiner, byte-order mark, soft hyphen, and the direction marks that
# Outlook and Teams put around a copied address. Zero-width joiners are
# left alone: emoji and some scripts need them.
_INVISIBLE = dict.fromkeys(map(ord, "​⁠﻿­‎‏‪‫‬‭‮⁦⁧⁨⁩"))
_PLAIN = {
    **_INVISIBLE,
    ord("‘"): "'", ord("’"): "'",
    ord("“"): '"', ord("”"): '"',
    ord(" "): " ", ord(" "): " ", ord(" "): " ",
}


def strip_invisible(text: str) -> str:
    """``text`` without characters that take no space on screen."""
    return text.translate(_INVISIBLE)


def plain(text: str) -> str:
    """``text`` for comparing with other text: curly quotes as straight
    ones, no-break spaces as spaces, invisible characters removed."""
    return text.translate(_PLAIN)
