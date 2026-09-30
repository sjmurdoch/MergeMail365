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

1. ✅ Make the three network-dependent tests hermetic, and add an autouse guard (`tests/conftest.py`) that fails any test making a non-localhost HTTP request.
2. ✅ Autospec MSAL mocks so call signatures are checked against the installed `msal`.
3. ✅ MSAL contract tests (`tests/test_msal_contract.py`) run the real `PublicClientApplication` against `responses`-mocked endpoints: auth code + PKCE, device code, token-cache round-trip and silent reuse, `diagnose_auth`, `sign_out`, and the `port`/`timeout` kwargs of `acquire_token_interactive` (which autospec cannot check because of `**kwargs`).
4. ✅ Rich tests: rendered log output, literal `[brackets]`, UTF-8 on a cp1252 stderr, and the confirmation summary. Writing these exposed an existing bug — user text in the send confirmation was parsed as rich markup (`Q3 [draft]` lost `[draft]`, `[/]` crashed, the `[y/N]` hint was never shown) — fixed in its own commit.
5. ✅ `--desktop` path tested against an autospec of the real `webview` module, plus bundled-fallback and missing-pywebview paths.
6. ✅ Trix E2E: real clipboard paste checks Trix still passes `paste.html` as a string and honours edits to it; toolbar bold/bullet; links and placeholders through `loadHTML`.
7. ✅ `.github/workflows/test.yml`: Python 3.10 and 3.13 on Ubuntu, macOS and Windows, running pytest (incl. Playwright), mypy and Biome. Suite also verified locally on 3.10. Not yet run on GitHub — first push will be its first run.
8. ⏳ PyInstaller smoke test — open question: needs a way to run the bundled app headlessly, e.g. a `--self-check` flag that imports everything, verifies bundled templates/static exist, then exits. Until then, manually launch the built app after upgrading pyinstaller or pywebview.

After steps 1–7: 470 passed, 14 skipped (was 444 / 14).

## Upgrade order

One commit per group, full suite (3.13 and 3.10) before each:

1. Trix 2.1.19 (`scripts/update-vendor.sh`)
2. Python lock, non-major bumps (msal, requests, pywebview, playwright + `playwright install chromium`, pytest-playwright, pyinstaller, pytest, pytest-cov, responses)
3. rich 15
4. mypy 2 (fix any new strict errors separately from the bump)
5. Release workflow: Actions majors, and CI/release Python off 3.10
6. Biome schema (`biome migrate`)
7. Manually launch a PyInstaller build of the desktop app (see step 8)

## Other findings

- msal warns that `initiate_auth_code_flow` should use `response_mode='form_post'` (RFC 9700 §4.3.1). Not changed here; the `/auth/callback` route currently expects a GET.
