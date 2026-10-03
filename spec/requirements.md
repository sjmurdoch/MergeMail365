# Wizard requirements

Each user-facing requirement of the web wizard, with the invariant or witness
in `spec/wizard.qnt` that checks it, or the reason it is unchecked.
`tests/test_spec_coverage.py` checks that every name in the "Checked by"
column is defined in the model, and that every invariant named here is run by
`spec/check.sh`.

Adding a step, button or job mode means adding its entry and success
requirements here in the same change: what must be true to enter the step,
and what must be true for its main action to succeed. The entry conditions
must include the success conditions that are under the app's control.

| ID | Requirement | Checked by | Status |
|---|---|---|---|
| R1 | Entering step 2 requires a spreadsheet. | `stepNeedsData` | Holds |
| R2 | Step 4 can be entered while signed out, because it offers sign-in itself (see R3). | `canProgress` | Holds. Changed from the plan, see below |
| R3 | On step 4, while the page shows signed out, "Send test email" is disabled and a sign-in button is shown on the step. | `testNeedsSignIn` | Fixed (bug 8) |
| R4 | "Send emails" on step 6 is only enabled while the page shows signed in, and step 6 offers sign-in before sending while it shows signed out. | `sendNeedsSignIn` | Fixed (bug 8) |
| R5 | No web job waits for interactive input: a job without a usable token fails at once with a "Not signed in" error. | `noInteractiveAuthInJob` | Fixed (bug 9) |
| R6 | Nothing false is claimed or sent: a real send only goes out for content that was test-sent and dry-run in its current form; Next buttons only claim checks that happened; the Sending screen is only shown for a real send and always has a way out; Back works on step 6 before sending. | `noUntestedSend`, `next4Honest`, `next5Honest`, `buttonsMatchFlags`, `sendScreenHonest`, `sendScreenNotStuck`, `back6Usable` | Fixed (bugs 1 to 6) |
| R7 | "Stop sending" stops the send before the next email, and a send stopped while emails remained ends as Stopped, showing the emails that were sent. | `stopHonoured`, `stoppedReported` | Fixed (bug 7) |
| R8 | On steps 4 and 6 the user can always finish the step from the step itself, without going back. | `canProgress` | Holds |
| R9 | A send that fails part-way reports which emails went out. | `partialFailedSend` (witness) | **Not met.** If `send_merge()` raises mid-send (for example the token is lost after the first email), the job keeps no results and the page shows only the error. Found while modelling R5; not fixed |
| R10 | The progress bar never runs ahead of the send. | None | Unchecked: display only, and a reload legitimately resets it. The plan's `progressMonotone` was not added |

## R2: why step 4 is not gated

The plan proposed `step4NeedsSignIn`: refuse to enter step 4 while signed out.
That would leave the user on step 3 with the sign-in button two steps back,
and the dead end the requirement was meant to remove would only move. Step 4
(and step 6) now show a sign-in callout while signed out and disable the send
button until sign-in completes, which `testNeedsSignIn`, `sendNeedsSignIn` and
`canProgress` check.

In browser mode, signing in redirects to Microsoft and back, which reloads the
page and returns to step 1, so filters, CC, BCC, reply-to, importance,
attachments and BCC mode must be set again (they are not persisted; see
"What is and is not recoverable after page reload" in `CLAUDE.md`). The
callout says so. Desktop mode signs in without leaving the page.

## Witnesses

States that are allowed but worth a look. Counts are from random simulation:

```sh
quint run spec/wizard.qnt --main=fixed --backend=typescript --max-samples=5000 \
  --max-steps=25 --invariant=allInvariants --seed=1 \
  --witnesses staleSignIn orphanJob partialFailedSend
```

| Witness | Traces (of 5,000) | Why it is acceptable |
|---|---|---|
| `staleSignIn`: the page shows signed in on step 4 or 6, but the token is gone | 180 | The token can only go between two `/auth/status` checks. On step 4 the test email then fails at once and the step offers sign-in. On step 6 the send fails at once with nothing sent, and the user has to start a new merge; rare, because silent refresh keeps the token alive for as long as the refresh token lasts. |
| `orphanJob`: a job runs on the server with no page listening | 88 | Reloading during a test email or dry run. The job finishes and nothing reads its result, because `/api/config` only resumes send jobs. |
| `partialFailedSend`: a send failed after some emails went out | 0 | Not acceptable, see R9. Random traces rarely reach a send; the scenario `sendWithoutTokenTest` reaches this state. |
