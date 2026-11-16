from mail_merge.template import extract_placeholders, render, validate_template


class TestExtractPlaceholders:
    def test_simple(self):
        assert extract_placeholders("Hello {{name}}") == {"name"}

    def test_multiple(self):
        assert extract_placeholders("{{a}} and {{b}}") == {"a", "b"}

    def test_no_placeholders(self):
        assert extract_placeholders("No placeholders here") == set()

    def test_duplicate(self):
        assert extract_placeholders("{{x}} {{x}}") == {"x"}

    def test_space_in_name(self):
        assert extract_placeholders("{{first name}}") == {"first name"}

    def test_multiple_spaces(self):
        assert extract_placeholders("{{full legal name}}") == {"full legal name"}


class TestValidateTemplate:
    def test_all_resolved(self):
        assert validate_template("Hi {{name}}", ["name", "email"]) == []

    def test_unresolvable(self):
        assert validate_template("Hi {{name}} {{missing}}", ["name"]) == ["missing"]

    def test_case_insensitive(self):
        assert validate_template("Hi {{Name}}", ["name"]) == []

    def test_space_in_name(self):
        assert validate_template("Hi {{first name}}", ["first name"]) == []

    def test_space_in_name_unresolvable(self):
        assert validate_template("{{first name}}", ["email"]) == ["first name"]


class TestRender:
    def test_basic(self):
        result = render("Hello {{name}}, from {{company}}", {"name": "Alice", "company": "Acme"})
        assert result == "Hello Alice, from Acme"

    def test_case_insensitive(self):
        result = render("Hello {{Name}}", {"name": "Alice"})
        assert result == "Hello Alice"

    def test_missing_placeholder_preserved(self):
        result = render("Hello {{missing}}", {})
        assert result == "Hello {{missing}}"

    def test_no_placeholders(self):
        result = render("Plain text", {"name": "Alice"})
        assert result == "Plain text"

    def test_space_in_name(self):
        result = render("Hello {{first name}}", {"first name": "Alice"})
        assert result == "Hello Alice"

    def test_space_case_insensitive(self):
        result = render("Hello {{First Name}}", {"first name": "Alice"})
        assert result == "Hello Alice"


# ---------------------------------------------------------------------------
# The grammar shared with the browser's preview (docs/review-fixes-plan.md,
# F4, F8, G4). tests/js/template.test.js runs the same file against
# web/static/template-core.js.
# ---------------------------------------------------------------------------

import json  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from mail_merge.template import (  # noqa: E402
    escape_value,
    has_stray_braces,
    unescape_entities,
    unusable_columns,
)

SHARED = json.loads((Path(__file__).parent / "data" / "template_vectors.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("v", SHARED["vectors"], ids=[v["name"] for v in SHARED["vectors"]])
def test_shared_vector(v):
    columns = list(v["row"])
    assert validate_template(v["template"], columns, html=v["html"]) == v["unresolved"]
    assert render(v["template"], v["row"], html=v["html"]) == v["rendered"]
    assert has_stray_braces(v["template"]) == v["stray"]


@pytest.mark.parametrize("column", SHARED["chip_columns"])
def test_chip_text_renders_to_the_cell_value(column):
    """The property that failed for {{First-Name}}: what a chip inserts for
    a column renders to that column's value, whatever the column is called."""
    value = f"value of <{column}> & more"
    row = {"email": "a@example.com", column: value}
    chip = "{{" + column + "}}"
    assert validate_template(chip, list(row)) == []
    assert render(f"[{chip}]", row) == f"[{value}]"
    # In an HTML body: typed raw, or as the rich-text editor writes it.
    for written in (chip, "{{" + escape_value(column) + "}}"):
        assert validate_template(written, list(row), html=True) == [], written
        assert render(f"<p>{written}</p>", row, html=True) == f"<p>{escape_value(value)}</p>", written
    assert not has_stray_braces(chip)


def test_unusable_columns():
    assert unusable_columns(SHARED["chip_columns"] + SHARED["unusable_columns"]) == SHARED["unusable_columns"]


def test_unescape_entities_knows_a_fixed_list_and_numeric_references():
    assert unescape_entities("&amp;&lt;&gt;&quot;&apos;&nbsp;&#65;&#x42;&#X43;") == "&<>\"' ABC"
    untouched = "&eacute; &unknown; &#0; &#xD800; &#99999999; & ;"
    assert unescape_entities(untouched) == untouched


class TestHtmlValuesCannotInjectMarkup:
    """F8: a cell is data. In an HTML email it is shown as typed."""

    PAYLOAD = '<img src=x onerror="alert(1)"><a href="https://evil.example">click</a>'

    def test_markup_in_a_cell_is_escaped(self):
        out = render("<p>Dear {{name}},</p>", {"name": self.PAYLOAD}, html=True)
        assert "<img" not in out and "<a " not in out
        assert out == ("<p>Dear &lt;img src=x onerror=&quot;alert(1)&quot;&gt;"
                       "&lt;a href=&quot;https://evil.example&quot;&gt;click&lt;/a&gt;,</p>")

    def test_a_cell_cannot_break_out_of_an_attribute(self):
        out = render('<a href="https://example.com/?q={{q}}">x</a>', {"q": '" onclick="alert(1)'}, html=True)
        assert out == '<a href="https://example.com/?q=&quot; onclick=&quot;alert(1)">x</a>'

    def test_subject_and_plain_bodies_are_not_escaped(self):
        assert render("R&D: {{name}}", {"name": "A & B <c>"}) == "R&D: A & B <c>"
