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
| Python (local, CI, release) | 3.13 / 3.10 | 3.14 | ✅ Done — see below |
| uv | 0.11.2 | 0.12.21 | Tooling |
| Biome (schema in biome.json) | 2.4.9 | 2.5.14 | Tooling |

All of the above were upgraded on 2026-09-30 — see *Upgrade order*.

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
7. ✅ `.github/workflows/test.yml`: Python 3.10 and 3.14 on Ubuntu, macOS and Windows, running pytest (incl. Playwright), mypy and Biome. Suite also verified locally on 3.10. Not yet run on GitHub — first push will be its first run.
8. ⏳ PyInstaller smoke test — open question: needs a way to run the bundled app headlessly, e.g. a `--self-check` flag that imports everything, verifies bundled templates/static exist, then exits. Until then, manually launch the built app after upgrading pyinstaller or pywebview.

After steps 1–7: 470 passed, 14 skipped (was 444 / 14).

## Upgrade order

Done 2026-09-30, one commit per group, full suite and mypy on 3.14 and 3.10 before each:

1. ✅ Python lock, non-major bumps (msal 1.39.0, requests 2.34.2, pywebview 6.2.1, playwright 1.63.0, pytest-playwright 0.9.0, pyinstaller 6.22.3, pytest 9.1.1, pytest-cov 7.1.0, responses 0.26.3, plus transitive)
2. ✅ rich 15.0.0
3. ✅ mypy 2.3.1 — no new errors
4. ✅ Trix 2.1.19; Pico re-vendored from the official 2.1.1 build (the old copy differed from it)
5. ✅ Actions: checkout v7.0.1, setup-python v7.0.0, setup-uv v10.2.0, setup-biome v2.7.1 — pinned to SHAs; uv 0.12.18 and Biome 2.5.14 pinned in CI
6. ✅ Biome schema → 2.5.14
7. ⏳ Manually launch a PyInstaller build of the desktop app (see step 8), and check the first CI and release runs

## Supply-chain policy

Nothing is used until it has been public for at least 7 days:

- **Python:** `exclude-newer = "7 days"` in `pyproject.toml` (recorded in `uv.lock` as `exclude-newer-span = "P7D"`). CI and release use `uv sync --locked`, and the release build uses `uv run --frozen`, so neither re-resolves.
- **Vendored JS/CSS:** `scripts/update-vendor.sh` downloads pinned versions only and refuses any version npm shows as younger than 7 days.
- **GitHub Actions:** pinned to commit SHAs (tags can be moved). uv and Biome versions are pinned explicitly, since `setup-uv` and `setup-biome` would otherwise install the latest release.
- **Playwright browsers** are tied to the locked `playwright` version.

When updating any of these, check the release date first.

## Python 3.14

Local (`.python-version`), CI test matrix (3.10 + 3.14) and release builds moved to 3.14. `requires-python` stays `>=3.10` and mypy still targets 3.10. This required one lock change: pythonnet 3.0.5 (pywebview's Windows backend) declares `<3.14`, so it was upgraded to 3.1.0 (supports 3.10–3.14), which also brought clr-loader 0.2.10 → 0.3.1. pythonnet 3.2.0 is newer but drops 3.10 and is inside the 7-day `exclude-newer` window. The Windows side can only be verified on CI or a Windows machine.

## Minimum Python 3.14 (plan)

Raise the supported floor from 3.10 to 3.14, the newest stable release (3.15 is still a release candidate). Users on 3.10–3.13 will no longer be able to install the package. Steps, each tested and committed separately:

1. ✅ `requires-python = ">=3.14"`, drop the `tomli` dependency and its `sys.version_info` fallback in `config.py`, mypy `python_version = "3.14"`, re-lock.
2. ✅ Drop `from __future__ import annotations` (annotations are lazily evaluated by default since 3.14, PEP 649/749).
3. ✅ CI test matrix → 3.14 only; update `CLAUDE.md` and `docs/tutorial.md`.

## Other findings

- msal warns that `initiate_auth_code_flow` should use `response_mode='form_post'` (RFC 9700 §4.3.1). Not changed here; the `/auth/callback` route currently expects a GET.
