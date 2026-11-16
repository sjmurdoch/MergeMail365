## Open issues from the Quint model work

Left over when the plan in `archive/quint-model-plan.md` was closed (2026-10-03). The model (`spec/wizard.qnt`) covers one page, one session and one server process at a time; the first three items would extend it.

- **A second tab.** Two pages sharing one session and job store: what should the second tab see while the first one's send runs? The server already refuses a second send (409), but the page side is not modelled or designed.
- **Session expiry and a lost session cookie.** The 24-hour sliding window and a cookie cleared mid-merge are not modelled; decide what the page should do when its session is gone (especially mid-send).
- **Out-of-order `/auth/status` answers (R16).** Handled in the code by request ids (a newer check supersedes an older one), but the model treats a sign-in check as atomic. Splitting it into request and response actions would let the conformance tests deliver answers out of order.
- **Sheet change and view state.** A sheet change invalidating column selections, and the HTML/source toggle's view state, are not modelled.
- **What the send log keeps (R15).** A running send's results, including recipient addresses, are kept on disk until the send ends, or until the user dismisses the report of a send the app didn't finish. Packaged builds already log addresses to disk; if that isn't acceptable, keep counts only.
- **Windows 0.4.1 report.** "Sending a test email sometimes did nothing for several minutes until the user clicked Back" may have been the device-code stall fixed as bug 9 (unverified). If it recurs, the stall logs (`mergemail365-stalls.log`) should show the cause.
- **Apalache is not in CI.** The `spec` job runs the scenario tests, a simulation and conformance. Apalache (`spec/check.sh --all fixed`, about 2 hours) runs locally: whenever `spec/wizard.qnt` changes, and after a Quint update, which brings a new Apalache.
- **Shorter routes to the later steps, so Apalache can check longer bugs.** Each extra Apalache step takes about 2½ times as long as the one before, so 19 steps (about 7 hours) is the practical limit (`docs/quint-model.md`, §9). Most of a long counterexample is setup (upload, sign in, Next ×3, a test email, a dry run), and bugs such as `next5Honest` (the stale dry run) need about 20 steps, beyond what simulation can find. A model variant that starts at step 4, or one action that stands for the setup, would let a 19-step bound reach what now needs about 25. The conformance mapping (`spec/coverage.toml`, `tests/test_conformance.py`) would need to cover the shortcut, or the variant would be used for Apalache only.
- **Browser conformance doesn't hold responses.** `tests/test_conformance_e2e.py` replays `eStep` traces, where a pending preview or start-job response is always answered next; those await windows are covered by the client tier and `tests/test_web_e2e_workflow.py` instead.

## Open after the November 2026 review fixes

From `docs/review-fixes-plan.md` ("Loose ends and things not verified", and the open items of phase H). Open when 0.7.0 was released (2026-11-16); the first item under "Release and packaging" was not checked before the release.

- **The 4 MB request limit.** `api._check_message_size()` and the per-attachment check assume Microsoft Graph accepts about 4 MB per `sendMail` request (3 MB of files once base64-encoded). That figure is not in the copies of Microsoft's documentation in `docs/`; check it against the current documentation.
- **Filters and address warnings.** Recipients' addresses are validated before filters are applied, so rows a filter excludes can still produce "invalid address" warnings.
- **Duplicate column names.** A spreadsheet with two columns of the same name uses the last one's values, without a warning.
- **Two web processes.** Two `mergemail365-web` processes running at once each treat the other's running send log as an interrupted send.
- **Token cache in a file.** The token cache is a 0600 file rather than the system keychain (macOS Keychain, Windows Credential Manager); `msal-extensions` would provide that.
- **Browser conformance has no mutant for `jobSucceeded`**; `TestRejectedTestEmail` covers the page instead.
- **Timestamps and logger names in the console format at DEBUG.** The logging guidelines ask for them; the console format is still the message alone at every level.
- **The web UI's downloaded CSV** writes `true`/`false` where the command line's report writes `True`/`False`, and doesn't double a `"` inside an address. Nothing reads these files back, but they are not interchangeable with `--output` reports.
- **Sign-in uses the query response mode.** msal warns (`UserWarning`, seen in the test run) that `response_mode='form_post'` is recommended for the authorisation code flow, so that the code is not in the callback URL. The callback would have to accept a POST from Microsoft's origin, which the session cookie's `SameSite` setting and the CSRF check don't allow as they are; the log already redacts `code=`.
- **File modes on Windows.** `write_private()` and `private_dir()` set modes only on POSIX, and the permission tests are skipped on Windows, where the files rely on the profile directory's ACL. Not checked beyond that.
- **Python 3.15.** Held at 3.14 only. Every dependency supports 3.15; adding it to the CI matrix doubles the test jobs' minutes.
- **This plan** has not been moved to `archive/`: comments in the tests, the source and `spec/` cite it at `docs/review-fixes-plan.md` and would need changing with it.

### Release and packaging

- **The real-window test has not been run on Windows.** `tests/test_window.py` (a merge in the desktop window, closed and reopened) passes on macOS only. Run `scripts/pre-release-checks.sh window` on the Windows PC before the next release; instructions are in `docs/windows-window-test.md`.
- **A blank HTML preview cannot be seen by a test.** Phase H's blank preview on Windows (after New merge) held the right document and drew nothing; look at step 3 by eye on Windows before a release.
- **Windows SmartScreen.** On `v0.7.0rc4`, a bundle downloaded in a browser (so carrying the Mark of the Web) was blocked by SmartScreen, and "Run anyway" did nothing: the build is self-signed. Tested once only, and not compared with 0.6.0, so it is not known whether this is new. Check that a user can start a downloaded 0.7.0 build; the lasting fix is a trusted code-signing certificate (`docs/codesigning.md`).
- **A rejected test email was not tried on a real system.** Checklist item 10 of phase H (Graph refuses the test email, the step must show a failure) needs an account Graph refuses, such as one without a mailbox; none was available on either platform. `tests/test_outcomes.py` and `TestRejectedTestEmail` cover it against mocked answers.
- **The command-line tool** was not part of phase H: the release workflow builds only the desktop app. Its sending path is covered by the mocked tests and shares `send_merge()` with the app.
- **Log lines from earlier versions.** Versions 0.4.1 to 0.6.0 wrote access tokens (expired within about an hour) and message bodies to the log file; upgrading leaves those lines in place, with a changelog note saying where the file is. Deleting or rotating the old file on first start would remove them.

### Desktop app, found in phase H and left as they are

- **Quitting during a send.** Cmd+Q (or closing the window) mid-send quits without asking. The next start reports which emails went out, but a confirmation would be kinder.
- **No single-instance lock.** A second copy of the app opens on the next port with an empty wizard, and each copy reports the other's running send as interrupted (the "Two web processes" item above).
- **No way to continue after Stop.** Step 6 offers only New merge after a stopped send; sending to the rest means starting again and filtering out those already sent. Deliberate (the safe path), but the web UI has no resume like the command line's `--output`.
