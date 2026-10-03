"""Keep spec/wizard.qnt in step with the web UI it models.

These checks are textual and fast (no browser, no Quint):

- every entry point in the UI and server is listed in spec/coverage.toml,
  and every listed entry point still exists;
- every action named in coverage.toml is defined in the model, and every
  action in the model's ``step`` relation is reachable from an entry point
  or listed as an environment action;
- every action in ``step`` cites the code it transcribes;
- spec/check.sh checks exactly the invariants in ``allInvariants``;
- every invariant has a requirement in spec/requirements.md, and every
  check named there exists.
"""

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "spec" / "wizard.qnt"
COVERAGE = ROOT / "spec" / "coverage.toml"
CHECK_SH = ROOT / "spec" / "check.sh"
REQUIREMENTS = ROOT / "spec" / "requirements.md"
WEB = ROOT / "src" / "mail_merge" / "web"
INDEX_HTML = WEB / "templates" / "index.html"
APP_JS = WEB / "static" / "app.js"
APP_PY = WEB / "app.py"

# A comment above each action in `step` must name the code it models.
CITATION_RE = re.compile(r"\b(app\.js|app\.py|sender\.py|api\.py|auth\.py|environment):")

# Top-level constructs that give a timer its context.
_CONTEXT_RES = [
    (re.compile(r"^(?:async\s+)?function\s+(\w+)"), lambda m: f"fn:{m[1]}"),
    (re.compile(r"""^\$\(["']([\w-]+)["']\)\.addEventListener\(\s*["']([\w-]+)["']"""),
     lambda m: f"#{m[1]}:{m[2]}"),
    (re.compile(r"""^(document|window)\.addEventListener\(\s*["']([\w-]+)["']"""),
     lambda m: f"{m[1]}:{m[2]}"),
]


def html_entry_points(text: str) -> set[str]:
    return {f"html:{m[2]}" for m in re.finditer(r'\bon(click|change|input|submit)="([^"]*)"', text)}


def js_entry_points(text: str) -> set[str]:
    found: set[str] = set()
    for m in re.finditer(
        r"""(\$\(["']([\w-]+)["']\)|\b[A-Za-z_]\w*)\.addEventListener\(\s*["']([\w-]+)["']""", text,
    ):
        receiver = f"#{m[2]}" if m[2] else m[1]
        found.add(f"js:{receiver}:{m[3]}")
    for m in re.finditer(r"\b\w+\.on(\w+)\s*=", text):
        found.add(f"js:EventSource:{m[1]}")
    lines = text.splitlines()
    for i, line in enumerate(lines):
        for timer in re.findall(r"\b(setInterval|setTimeout)\(", line):
            context = "top"
            for prev in reversed(lines[: i + 1]):
                for pattern, name in _CONTEXT_RES:
                    cm = pattern.match(prev)
                    if cm:
                        context = name(cm)
                        break
                if context != "top":
                    break
            found.add(f"js:{timer}@{context}")
    return found


def route_entry_points(text: str) -> set[str]:
    found: set[str] = set()
    for m in re.finditer(r'@app\.route\("([^"]+)"(?:,\s*methods=\[([^\]]*)\])?\)', text):
        methods = re.findall(r'"(\w+)"', m[2] or "") or ["GET"]
        for method in methods:
            found.add(f"route:{method} {m[1]}")
    return found


def all_entry_points() -> set[str]:
    return (
        html_entry_points(INDEX_HTML.read_text(encoding="utf-8"))
        | js_entry_points(APP_JS.read_text(encoding="utf-8"))
        | route_entry_points(APP_PY.read_text(encoding="utf-8"))
    )


def spec_text() -> str:
    return SPEC.read_text(encoding="utf-8")


def defined_actions(text: str) -> set[str]:
    return set(re.findall(r"^\s*action\s+(\w+)", text, re.MULTILINE))


def step_actions(text: str) -> list[str]:
    body = re.search(r"action step = any \{(.*?)\n  \}", text, re.DOTALL)
    assert body, "could not find `action step = any { ... }` in wizard.qnt"
    # Drop the `nondet x = S.oneOf()` binders, keep the action names.
    cleaned = re.sub(r"nondet\s+\w+\s*=\s*[\w.]+\(\)", "", body[1])
    return re.findall(r"\b([a-z]\w*)\s*(?:\(|,|\n|$)", cleaned)


def coverage() -> dict:
    with COVERAGE.open("rb") as f:
        return tomllib.load(f)


class TestExtraction:
    """The extractors find the kinds of entry point the inventory relies on."""

    def test_html(self):
        assert html_entry_points('<button onclick="goToStep(2)">') == {"html:goToStep(2)"}

    def test_js_listeners(self):
        src = '$("btn-x").addEventListener("click", f);\ndocument.addEventListener("trix-change", g);\nchip.addEventListener("mousedown", h);\nevtSource.onmessage = (e) => {};'
        assert js_entry_points(src) == {
            "js:#btn-x:click", "js:document:trix-change", "js:chip:mousedown", "js:EventSource:message",
        }

    def test_js_timer_context(self):
        src = 'function onTemplateChange() {\n    t = setTimeout(() => {}, 5);\n}\n$("b").addEventListener("click", () => {\n    setInterval(f, 1);\n});'
        assert js_entry_points(src) >= {"js:setTimeout@fn:onTemplateChange", "js:setInterval@#b:click"}

    def test_routes(self):
        src = '@app.route("/a")\n@app.route("/b", methods=["POST"])'
        assert route_entry_points(src) == {"route:GET /a", "route:POST /b"}

    def test_step_actions(self):
        assert step_actions(spec_text())[:2] == ["upload", "next1"]


class TestCoverageInventory:
    def test_extractor_sees_every_listener(self):
        """A listener in a form the regex can't read (e.g. ``$(id).addEventListener``) fails here."""
        text = APP_JS.read_text(encoding="utf-8")
        total = len(re.findall(r"\.addEventListener\(", text))
        seen = len(re.findall(
            r"""(\$\(["'][\w-]+["']\)|\b[A-Za-z_]\w*)\.addEventListener\(\s*["'][\w-]+["']""", text,
        ))
        assert seen == total, "app.js has addEventListener calls the coverage extractor cannot key"

    def test_every_entry_point_is_listed(self):
        missing = sorted(all_entry_points() - set(coverage()["entries"]))
        assert not missing, (
            "Entry points not in spec/coverage.toml; map each to model actions "
            f"or exclude it with out_of_scope = \"<reason>\": {missing}"
        )

    def test_every_listed_entry_point_exists(self):
        stale = sorted(set(coverage()["entries"]) - all_entry_points())
        assert not stale, f"spec/coverage.toml lists entry points that no longer exist: {stale}"

    def test_each_entry_maps_or_is_excluded(self):
        for key, entry in coverage()["entries"].items():
            has_actions = bool(entry.get("actions"))
            has_reason = bool(entry.get("out_of_scope", "").strip())
            assert has_actions != has_reason, f"{key}: give either actions or out_of_scope, not both or neither"

    def test_listed_actions_exist_in_model(self):
        defined = defined_actions(spec_text())
        cov = coverage()
        named = {a for e in cov["entries"].values() for a in e.get("actions", [])}
        named |= set(cov["environment"]["actions"])
        unknown = sorted(named - defined)
        assert not unknown, f"spec/coverage.toml names actions not defined in wizard.qnt: {unknown}"

    def test_every_model_action_has_a_source(self):
        cov = coverage()
        reachable = {a for e in cov["entries"].values() for a in e.get("actions", [])}
        reachable |= set(cov["environment"]["actions"])
        orphans = sorted(set(step_actions(spec_text())) - reachable)
        assert not orphans, (
            "Actions in `step` that no entry point in spec/coverage.toml triggers "
            f"(add the entry point, or list the action under [environment]): {orphans}"
        )


class TestCitations:
    @pytest.mark.parametrize("action", step_actions(spec_text()))
    def test_action_cites_code(self, action):
        lines = spec_text().splitlines()
        idx = next(i for i, l in enumerate(lines) if re.match(rf"\s*action\s+{action}\b", l))
        comments = []
        for line in reversed(lines[:idx]):
            if not line.strip().startswith("//"):
                break
            comments.append(line)
        assert CITATION_RE.search("\n".join(comments)), (
            f"action {action} in wizard.qnt needs a comment naming the code it models, "
            "e.g. `// app.js: stopSend(); web/app.py: api_job_stop` or `// environment: ...`"
        )


def all_invariants() -> set[str]:
    body = re.search(r"val allInvariants = and \{(.*?)\}", spec_text(), re.DOTALL)
    assert body
    return set(re.findall(r"\w+", body[1]))


class TestCheckScript:
    def test_check_sh_runs_every_invariant(self):
        listed = re.search(r'^invariants="([^"]*)"', CHECK_SH.read_text(encoding="utf-8"), re.MULTILINE)
        assert listed
        assert set(listed[1].split()) == all_invariants()


class TestRequirements:
    def _checked_by(self) -> dict[str, set[str]]:
        """Requirement ID -> names in its "Checked by" cell."""
        rows: dict[str, set[str]] = {}
        for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) == 4 and re.fullmatch(r"R\d+", cells[0]):
                rows[cells[0]] = set(re.findall(r"`(\w+)`", cells[2]))
        assert rows, "no requirement rows found in spec/requirements.md"
        return rows

    def test_named_checks_exist_in_model(self):
        defined = set(re.findall(r"^\s*val\s+(\w+)", spec_text(), re.MULTILINE))
        for req, names in self._checked_by().items():
            unknown = names - defined
            assert not unknown, f"{req} names checks not defined in wizard.qnt: {sorted(unknown)}"

    def test_every_invariant_has_a_requirement(self):
        named = set().union(*self._checked_by().values())
        missing = sorted(all_invariants() - named)
        assert not missing, f"invariants with no requirement in spec/requirements.md: {missing}"

    def test_named_invariants_are_checked(self):
        """A name in the table is either an invariant run by check.sh or a witness."""
        witnesses_section = REQUIREMENTS.read_text(encoding="utf-8").split("## Witnesses", 1)[1]
        witnesses = set(re.findall(r"`(\w+)`", witnesses_section))
        for req, names in self._checked_by().items():
            stray = names - all_invariants() - witnesses
            assert not stray, f"{req}: {sorted(stray)} are neither in allInvariants nor listed as witnesses"
