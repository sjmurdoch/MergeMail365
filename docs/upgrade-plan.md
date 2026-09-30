# Dependency upgrade plan (2026-09-30)

Goal: before bumping any vendored code or pins, make sure the test suite would catch regressions each upgrade could plausibly introduce.

## Pending upgrades

| Item | Current | Latest | Risk |
|---|---|---|---|
| Trix (vendored) | 2.1.18 | 2.1.19 | Low |
| Pico CSS (vendored) | 2.1.1 | 2.1.1 | None |
| msal | 1.35.1 | 1.39.0 | Medium — auth |
| requests | 2.32.5 | 2.34.2 | Low |
| rich | 14.3.3 | 15.0.0 | Medium — major |
| pywebview | 6.1 | 6.2.1 | Medium — untested path |
| mypy | 1.19.1 | 2.3.1 | Tooling — major |
| playwright / pytest-playwright | 1.58.0 / 0.7.2 | 1.63.0 / 0.9.0 | Tooling |
| pyinstaller | 6.19.0 | 6.22.3 | Medium — release only |
| pytest / pytest-cov / responses | 9.0.2 / 7.0.0 / 0.26.0 | 9.1.1 / 7.1.0 / 0.26.3 | Tooling |
| actions/checkout, setup-python, setup-uv | v4 / v5 / v4 | v7 / v7 / v10 | Medium — release only |
| CI Python | 3.10 | 3.10 EOL Oct 2026 | Medium |
| uv | 0.11.2 | 0.12.21 | Tooling |
| Biome (schema in biome.json) | 2.4.9 | 2.5.14 | Tooling |

## Baseline

- `uv run pytest`: 444 passed, 14 skipped (all skips are Windows-only tests in `test_windows.py`). Line coverage 92%.
- `uv run mypy`: clean.
- Playwright tests need to run outside the Claude Code sandbox (Chromium cannot register mach ports inside it).

## Gaps found

1. **MSAL is mocked without a spec.** Every test patches `msal.PublicClientApplication` with a bare `MagicMock`, so renamed kwargs (`port`, `timeout`, `redirect_uri`), removed methods, or changed result dicts would still pass. Nothing exercises real MSAL code.
2. **Three tests hit the real network.** `test_api.py::TestAuthFailure::test_auth_exception_wrapped_in_runtime_error`, `test_auth.py::TestDiagnoseAuthEdgeCases::test_authority_unreachable`, and `test_auth_additions.py::TestDiagnoseAuth::test_no_cache` fetch `login.microsoftonline.com/.../openid-configuration`. Their result depends on network availability, not the code under test.
3. **Rich output is not checked.** Tests confirm a `RichHandler` is installed but never that a log line is actually rendered, or that `markup=False` keeps literal `[brackets]` (common in email subjects) intact.
4. **pywebview has no coverage.** The `--desktop` path in `web/__init__.py` is never executed by tests; an API change in `webview.create_window` / `webview.start` would only show up at runtime.
5. **Trix paste tests use synthetic events.** They dispatch a hand-built `trix-before-paste` event, so they would not notice if Trix changed the event's `paste` payload. No test drives a real paste or the toolbar formatting buttons.
6. **No CI test workflow.** Only `release.yml` exists, so GitHub Actions / Python-version changes are only exercised at release time, and the Windows-only tests never run anywhere.
7. **Only Python 3.13 is tested locally**, but `requires-python = ">=3.10"` and release builds use 3.10. Upgraded deps may resolve differently (or drop support) on 3.10.
8. **PyInstaller bundle is never smoke-tested** — missing hidden imports or data files would only be found by running the released app.

## Steps

Each step is a separate commit, with the full suite run before committing.

1. Make the three network-dependent tests hermetic (mock the openid-configuration GET with `responses`). Add a guard fixture that fails any test making a non-localhost HTTP request.
2. Autospec MSAL mocks so call signatures are checked against the installed `msal`.
3. Add MSAL contract tests that run the real `PublicClientApplication` against `responses`-mocked endpoints: token-cache round-trip + `acquire_token_silent` returning a cached token; `initiate_auth_code_flow` producing an `auth_uri`; `acquire_token_by_auth_code_flow` exchanging a code.
4. Add rich rendering tests: `setup_logging()` output contains the message; literal `[bold]` text is not interpreted as markup.
5. Add pywebview contract test: when installed, `create_window` accepts `(title, app, width=, height=)` and `start` exists; test the `--desktop` code path with `webview` stubbed.
6. Add Trix E2E tests: real clipboard paste of HTML, and toolbar bold/list buttons producing the expected HTML.
7. Add `.github/workflows/test.yml`: matrix of Python 3.10 and 3.13 on macOS, Windows and Ubuntu, running pytest (incl. Playwright) and mypy.
8. (Open question) PyInstaller smoke test — needs a way to run the bundled app headlessly, e.g. a `--self-check` flag that imports everything and verifies bundled templates/static exist, then exits.

Then upgrade, one commit per group: Trix → Python lock (non-major) → rich 15 → mypy 2 → Actions + CI Python → Biome schema.
