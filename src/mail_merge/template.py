"""Placeholders: ``{{column name}}`` in a subject or body.

The grammar, shared with the browser's preview (web/static/template-core.js;
both run every case in tests/data/template_vectors.json, so the preview and
the email cannot differ):

* A placeholder is ``{{``, any text without braces, ``}}``. The text names
  a column: surrounding spaces are ignored, runs of spaces count as one, and
  case doesn't matter. So ``{{ First   name }}`` is the column
  ``First Name``. Curly quotes count as straight ones, no-break spaces as
  spaces, and invisible characters are ignored (``typed_text.plain``):
  macOS types ``{{Manager’s name}}`` for the column ``Manager's name``.
* Any column name without braces can be used, whatever punctuation it has
  (``{{E-mail}}``, ``{{Price <GBP>}}``).
* A placeholder that names no column is *unresolved*: an error, never text
  to send. A ``{{`` or ``}}`` that isn't part of a placeholder (``{{name}``)
  is *stray*: probably a typo, reported as a warning.
* In an HTML body, the name may be written as HTML (the rich-text editor
  writes ``{{R&amp;D budget}}``), may be written raw, and may have tags
  inside it (bold applied to half a placeholder); and the value is escaped,
  so a cell containing ``<`` or ``&`` is shown as typed and can't inject
  markup, with line breaks kept as ``<br>``. The subject is always plain.
"""

import re

from mail_merge.typed_text import plain

PLACEHOLDER_RE = re.compile(r"\{\{([^{}]*)\}\}")
_TAG_RE = re.compile(r"<[^<>]*>")
# Spelt out, not \s: Python's and JavaScript's \s differ.
_SPACES_RE = re.compile(r"[ \t\n\r\f\v ]+")
_HTML_ESCAPES = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}
_HTML_ESCAPE_RE = re.compile(r"[&<>\"']")
# The character references an editor or a person writes in a column name.
# A fixed list, not html.unescape()'s two thousand names, so that the
# JavaScript implementation can be the same.
_ENTITIES = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'", "nbsp": "\u00a0"}
_ENTITY_RE = re.compile(r"&(?:#([0-9]{1,7})|#[xX]([0-9a-fA-F]{1,6})|([a-zA-Z]+));")


def unescape_entities(text: str) -> str:
    """Replace the HTML character references in _ENTITIES, and numeric ones."""

    def replacer(match: re.Match[str]) -> str:
        decimal, hexadecimal, name = match.groups()
        if name is not None:
            return _ENTITIES.get(name, match[0])
        code = int(decimal) if decimal is not None else int(hexadecimal, 16)
        return chr(code) if 0 < code <= 0x10FFFF and not 0xD800 <= code <= 0xDFFF else match[0]

    return _ENTITY_RE.sub(replacer, text)


def normalize_name(name: str) -> str:
    """A column or placeholder name as compared: trimmed, single-spaced,
    lower case, with the characters a system substitutes while typing
    as the plain ones."""
    return _SPACES_RE.sub(" ", plain(name)).strip().lower()


def display_name(raw: str) -> str:
    """A placeholder's text as shown in messages: trimmed, single-spaced."""
    return _SPACES_RE.sub(" ", raw).strip()


def candidate_names(raw: str, html: bool = False) -> list[str]:
    """The column names the text between the braces may mean, most likely
    first. Plain text means what it says. In HTML it may be HTML-escaped,
    raw, or have tags inside it."""
    if not html:
        return [normalize_name(raw)]
    names = [
        normalize_name(unescape_entities(raw)),
        normalize_name(raw),
        normalize_name(unescape_entities(_TAG_RE.sub("", raw))),
    ]
    return list(dict.fromkeys(names))


def escape_value(value: str) -> str:
    """A cell's text as HTML: markup characters escaped, line breaks kept."""
    escaped = _HTML_ESCAPE_RE.sub(lambda m: _HTML_ESCAPES[m[0]], value)
    return escaped.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def extract_placeholders(template: str) -> set[str]:
    """The names of the placeholders in a template, as written (trimmed)."""
    return {display_name(raw) for raw in PLACEHOLDER_RE.findall(template)}


def _lookup(columns: dict[str, str], raw: str, html: bool) -> str | None:
    for name in candidate_names(raw, html):
        if name in columns:
            return columns[name]
    return None


def validate_template(template: str, columns: list[str], html: bool = False) -> list[str]:
    """Return the placeholders that name no column, sorted."""
    known = {normalize_name(c): c for c in columns}
    return sorted({
        display_name(raw) for raw in PLACEHOLDER_RE.findall(template)
        if _lookup(known, raw, html) is None
    })


def used_columns(template: str, columns: list[str], html: bool = False) -> set[str]:
    """The columns (as named in the spreadsheet) that the template's
    placeholders refer to."""
    known = {normalize_name(c): c for c in columns}
    found = {_lookup(known, raw, html) for raw in PLACEHOLDER_RE.findall(template)}
    return {c for c in found if c is not None}


def has_stray_braces(template: str) -> bool:
    """Whether a ``{{`` or ``}}`` is left once the placeholders are taken
    out: an unfinished placeholder such as ``{{name}``."""
    rest = PLACEHOLDER_RE.sub("", template)
    return "{{" in rest or "}}" in rest


def unusable_columns(columns: list[str]) -> list[str]:
    """Columns that no placeholder can name, because the name has a brace."""
    return [c for c in columns if "{" in c or "}" in c]


def render(template: str, data: dict[str, str], html: bool = False) -> str:
    """Substitute ``{{column}}`` placeholders with values from ``data``.

    With ``html``, names are read as HTML and values are escaped. A
    placeholder that names no column is left as written (callers validate
    first, so this only happens when they chose not to).
    """
    values = {normalize_name(k): str(v) for k, v in data.items()}

    def replacer(match: re.Match[str]) -> str:
        value = _lookup(values, match.group(1), html)
        if value is None:
            return match.group(0)
        return escape_value(value) if html else value

    return PLACEHOLDER_RE.sub(replacer, template)
