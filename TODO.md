- Don't allow progress if not signed in
- Validate user flow state machine

## Open issues from the Quint model work

Left over when the plan in `archive/quint-model-plan.md` was closed (2026-10-03). The model (`spec/wizard.qnt`) covers one page, one session and one server process at a time; the first three items would extend it.

- **A second tab.** Two pages sharing one session and job store: what should the second tab see while the first one's send runs? The server already refuses a second send (409), but the page side is not modelled or designed.
- **Session expiry and a lost session cookie.** The 24-hour sliding window and a cookie cleared mid-merge are not modelled; decide what the page should do when its session is gone (especially mid-send).
- **Out-of-order `/auth/status` answers (R16).** Handled in the code by request ids (a newer check supersedes an older one), but the model treats a sign-in check as atomic. Splitting it into request and response actions would let the conformance tests deliver answers out of order.
- **Sheet change and view state.** A sheet change invalidating column selections, and the HTML/source toggle's view state, are not modelled.
- **What the send log keeps (R15).** A running send's results, including recipient addresses, are kept on disk until the send ends, or until the user dismisses the report of a send the app didn't finish. Packaged builds already log addresses to disk; if that isn't acceptable, keep counts only.
- **Windows 0.4.1 report.** "Sending a test email sometimes did nothing for several minutes until the user clicked Back" may have been the device-code stall fixed as bug 9 (unverified). If it recurs, the stall logs (`mergemail365-stalls.log`) should show the cause.
- **Quint's `adm-zip` dependency.** `npm audit` reports a high-severity issue. Quint uses it only to unpack the Apalache download, which CI and the conformance tests never do; revisit when bumping Quint (cooldown rules apply).
- **CI.** The `spec` job (scenario tests, simulation, conformance) has not run yet, since the branch has no pull request. Apalache (`spec/check.sh --all fixed`, about 2 hours) is not in CI: run it locally whenever `spec/wizard.qnt` changes.
- **Shorter routes to the later steps, so Apalache can check longer bugs.** Each extra Apalache step takes about 2½ times as long as the one before, so 19 steps (about 7 hours) is the practical limit (`docs/quint-model.md`, §9). Most of a long counterexample is setup (upload, sign in, Next ×3, a test email, a dry run), and bugs such as `next5Honest` (the stale dry run) need about 20 steps, beyond what simulation can find. A model variant that starts at step 4, or one action that stands for the setup, would let a 19-step bound reach what now needs about 25. The conformance mapping (`spec/coverage.toml`, `tests/test_conformance.py`) would need to cover the shortcut, or the variant would be used for Apalache only.
- **Browser conformance doesn't hold responses.** `tests/test_conformance_e2e.py` replays `eStep` traces, where a pending preview or start-job response is always answered next; those await windows are covered by the client tier and `tests/test_web_e2e_workflow.py` instead.
