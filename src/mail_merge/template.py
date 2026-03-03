import re

PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


def extract_placeholders(template: str) -> set[str]:
    return set(PLACEHOLDER_RE.findall(template))


def validate_template(template: str, columns: list[str]) -> list[str]:
    """Return list of placeholder names that cannot be resolved from columns."""
    placeholders = extract_placeholders(template)
    column_set = {c.lower() for c in columns}
    return sorted(p for p in placeholders if p.lower() not in column_set)


def render(template: str, data: dict[str, str]) -> str:
    """Substitute {{column_name}} placeholders with values from data dict."""
    lower_data = {k.lower(): v for k, v in data.items()}

    def replacer(match: re.Match[str]) -> str:
        key = match.group(1).lower()
        return str(lower_data.get(key, match.group(0)))

    return PLACEHOLDER_RE.sub(replacer, template)
