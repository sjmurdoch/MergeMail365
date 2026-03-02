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


class TestValidateTemplate:
    def test_all_resolved(self):
        assert validate_template("Hi {{name}}", ["name", "email"]) == []

    def test_unresolvable(self):
        assert validate_template("Hi {{name}} {{missing}}", ["name"]) == ["missing"]

    def test_case_insensitive(self):
        assert validate_template("Hi {{Name}}", ["name"]) == []


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
