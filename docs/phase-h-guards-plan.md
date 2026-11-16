# Plan: tests for the classes of bug that phase H found

Written 2026-11-16, after 0.7.0. Phase H of `docs/review-fixes-plan.md` ran the release candidates on a real Mac and a real Windows PC and found about twenty problems over five candidates, none of which the 1,250 automated tests had noticed. Each was fixed with a test for that one bug. This plan asks why the suite missed them and adds a guard for each *class*, so that the next bug of the same kind fails a test before a candidate is built.

## What phase H found, by class

| # | Finding | Candidate | Class |
|---|---|---|---|
| 1 | After New merge, Verify showed no dry-run log | rc2, both | A |
| 2 | After New merge, the HTML preview was an empty box (Windows) | rc2 | A, D |
| 3 | After New merge, step 4 said "(enter test address above)" beside the pre-filled address | rc3 | A |
| 4 | New merge leaves the diagnostics and options panels open (still open) | rc1 | A |
| 5 | Test connection's result stays on screen after Sign out (still open) | rc4 | A |
| 6 | Compose fields not restored when the desktop app is reopened (pywebview's private mode) | rc1 | B, D |
| 7 | Name column not restored after a restart | rc2 | B |
| 8 | Name column wiped by an auto-save that ran before the upload | rc4 | B |
| 9 | A restart straight after quitting mid-send moved to port 5051, another origin, so nothing saved was found | rc3 | B, C |
| 10 | A second copy of the app shared the first one's port (Windows) | rc2 | C |
| 11 | macOS turns typed straight quotes into curly ones, so `"Surname, First" <a@b>` was refused | rc1 | D, E |
| 12 | Diagnostics box wider than the page column (fixed twice) | rc1, rc2 | F |
| 13 | Preview table's header row very tall with long headings (still open) | rc1 | F |
| 14 | A 14-byte attachment shown as "(0 KB)" | rc1 | G |
| 15 | A dry run's summary said "Sent: 7" | rc1 | G |
| 16 | Web jobs didn't log "Sending as", which the command line does | rc1 | G |
| 17 | Cmd+Q during a send quits without asking (still open) | rc1 | D |
| 18 | SmartScreen "Run anyway" did nothing (still open) | rc4 | H |

Not bugs in the app: the checklist expected "Send emails" after Stop (the app's behaviour is the intended one), and log lines written by earlier versions stay in the log file (a decision).

## Why the tests missed each class

**A. The second time through (5 findings).** Every browser test starts from a freshly loaded page. `clearForm()` in `app.js` is a hand-written list of fields to reset, and nothing compares what the page shows after New merge with what a new page shows. The Quint model's `newMergeClears` covers the workflow flags, not what is on screen.

**B. Closing the app and opening it again (4 findings).** The reload tests reload a page of a server that keeps running. No test stops the server and starts another, lets the 5-second auto-save run at an awkward moment, or checks every remembered field rather than the one a bug was reported for.

**C. Ports and a second copy (2 findings).** The port probe was tested against sockets the test opened itself, in one process, on the developer's platform. What matters is what the operating system does with the real server's socket (TIME_WAIT after a kill, `SO_REUSEADDR` on Windows, `localhost` resolving to `::1`), and that differs between the three platforms.

**D. The real window (4 findings).** No automated test runs WKWebView or WebView2: the browser tests use Playwright's Chromium, and the desktop entry point is tested against a mock of pywebview. Private mode, typing substitutions, a frame that stays blank and the window's close button exist only there.

**E. What the system does to typed text (1 finding).** Address parsing was tested with the characters a developer types in an editor, not the ones macOS substitutes while a user types.

**F. Layout (2 findings).** No test looks at geometry. Content from outside (a long account identifier, sixty long column headings) is what breaks it, and the tests' spreadsheets have two short columns.

**G. What the app says (3 findings).** The outcome matrix (`tests/test_outcomes.py`) checks that success is reported only when Graph accepted the email, for real sends. It has no dry-run row, nothing compares what the command line and a web job say about the same send, and number formatting had no boundary cases.

**H. Getting the download to start (1 finding).** Outside what a test of the code can see; it stays on the release checklist (`TODO.md`).

## The guards

Each is a test that fails for the class, not for one bug, and each must be shown to fail with one of the original bugs put back.

| Guard | Class | What it does | Where it runs |
|---|---|---|---|
| G-A | A | Walk the whole wizard with every field used, recording what every element with an `id` shows (visible, text, value, open, disabled) at each step. Press New merge, walk again with the same inputs: every recording must equal the first pass's, and the page after New merge must equal a freshly loaded page. The same comparison after Sign out against a page loaded signed out. Differences that are intended go in a table with the reason, and an entry that stops being a difference fails too. | Chromium, in the suite |
| G-B | B | Start a server, fill in the wizard, stop the server, start a new one on the same port, open it in the same browser profile: every field the app says it remembers (the `mm_*` keys, read from `app.js`, so a new key needs a row) is restored. Repeated with the auto-save firing before the upload, after it, and with "none" chosen on purpose. | Chromium, in the suite |
| G-C | C | Run the real `mergemail365-web` as a subprocess: kill it with a client connected and start it again (same port); start a second copy while the first runs (a different port, and the first still answers). | All three platforms in CI; a few seconds |
| G-D1 | D | The browser tests that don't depend on Chromium also pass in Playwright's WebKit, the engine nearest WKWebView. | Local, before a release (CI cost) |
| G-D2 | D | A smoke test of the real window: start `mergemail365-web --desktop` with Graph and sign-in faked, drive the wizard through pywebview's `evaluate_js`, quit and reopen, check what is remembered. | Local on macOS; Windows needs a decision (CI minutes, or the user's PC) |
| G-E | E | A table of the substitutions macOS and Windows make while typing (curly quotes, dashes, ellipsis, non-breaking and narrow spaces, full-width `@` and `<>`), run against every field that parses what the user types (addresses, filters, placeholders, the SEND box): each row says whether the field accepts it as the plain character or refuses it with a message naming the character. | In the suite |
| G-F | F | At every step, with a wide spreadsheet of long headings, long cell values, a long account name and long error text, at three window widths: nothing with an `id` extends past the page column, the page doesn't scroll sideways, and no table row is taller than a set limit. | Chromium, in the suite |
| G-G | G | A dry-run row in the outcome matrix (no interface may say "sent"); the command line and a web job run the same send and must log the same lines, apart from a listed few; boundary cases for every number the page formats. | In the suite |

## Phases

At the end of each phase: full suite, commit, update Status below, and ask before starting the next.

| Phase | Guards | Notes |
|---|---|---|
| 1 | G-A | The largest class. Findings 4 and 5 are still open, so the guard will fail on them until they are fixed or listed. |
| 2 | G-B, G-C | G-C adds a subprocess test to CI on three platforms. |
| 3 | G-E, G-F, G-G | Finding 13 is still open. |
| 4 | G-D1, G-D2 | Needs decisions: WebKit download, and whether the real-window smoke test runs anywhere but locally. |

## Status

Updated 2026-11-16. Work is on the `phase-h-guards` branch.

### Phase 1 (G-A): done

`TestSecondPass` in `tests/test_web_e2e_workflow.py`. `test_second_merge_shows_what_the_first_did` walks a merge that uses every field (HTML body, name column, CC, BCC, Reply-To, importance, a filter, an attachment, Test connection, both collapsible panels), recording 15 points; after New merge the same walk must record the same. `test_signing_out_shows_what_a_signed_out_page_does` compares the page after Sign out with a reloaded, signed-out page. Only what is on screen is compared: an element hidden both times is skipped, and is compared when it is next shown.

| Bug put back | Caught? |
|---|---|
| Finding 1 (no dry-run log after New merge) | Yes: `#verify-log` hidden at "5 dry run done" |
| Finding 3 (stale summary on the Test step) | Yes: `#test-preview-info` at "4 entered" |
| Finding 4 (panels left open) | Yes: it failed on the code as it was; fixed (`clearForm()` restores the panels to how the page loads and removes the Test connection result) |
| Finding 5 (Test connection's result after Sign out) | Yes: it failed on the code as it was; fixed (`hideAuthDiagnostics()` in `doSignOut()`) |
| A field left out of `clearForm()` (Reply-To) | Yes: `#reply-to-input` at "2 entered" |
| Finding 2 (blank HTML preview, Windows) | No: Chromium draws the frame either way, and the recordings (the frame's `srcdoc`) are equal. This one belongs to class D |

The two tests take about 12 seconds together. Before the on-screen rule, the comparison listed some 30 leftovers in hidden steps after New merge (the previous merge's CC on the Preview step, its recipient count on the Send step, and so on). None is visible when its step is next shown, because each is redrawn on entry, which is what the guard checks.

### Phase 2 (G-B, G-C): done

**G-B, `tests/test_web_e2e_restart.py`** (16 tests, about 28 seconds). The server is stopped and a new one started on the same port, with a new startup token and no sessions, as reopening the app does. Each of the six remembered fields is changed last in turn (a field whose change doesn't lead to a save would be the bug), and the spreadsheet is uploaded again either at once or after the auto-save has run with no spreadsheet loaded. A deliberate "none" for the name column must stay "none", and New merge must not be undone by a restart. The table of remembered fields is compared with the `mm_*` keys in `app.js`. The 5-second auto-save is driven by `page.clock`, so nothing waits for it.

| Bug put back | Caught? |
|---|---|
| Finding 7 (saved columns not used after an upload) | Yes: 14 of 16 fail |
| Finding 8 (auto-save before the upload wipes the columns) | Yes: all 7 "upload later" cases fail |
| **New: the chosen sheet was not restored after a restart** | It failed on the code as it was. `mm_sheet` was applied only on a reload (from `/api/config`), not after an upload, so reopening the app and uploading the workbook silently used the first sheet. Fixed: `restoreSavedSheet()` is used in both places |
| Finding 6 (pywebview's private mode) | No: this is the window's own storage, class D. `tests/test_web_cli.py` checks the argument passed to pywebview |

The first version of the test chose `E-mail` as the address column and passed for the wrong reason: the page picks a column of that name by itself. The workbook now has a second address column, which the test chooses.

**G-C, `tests/test_web_process.py`** (2 tests, about 2 seconds). Starts `mail_merge.web.main()` in a subprocess with a temporary home directory; only `webbrowser.open` is replaced.

| Bug put back | Caught? |
|---|---|
| Finding 9 (probe without `SO_REUSEADDR`: reopening moves to the next port) | Yes on macOS: `assert 5071 == 5070` |
| No probing at all (two copies on one port) | Yes: `assert 5070 != 5070` |
| Finding 10 (Windows lets a second socket bind a listening port) | Not checked: needs Windows. The test runs there in CI; the mutant has not been run there |

What reproducing finding 9 showed: the port stays busy only if a connection is still unanswered when the app dies (30 seconds on macOS, twice `net.inet.tcp.msl`); a connection whose request has been answered doesn't hold it. The test therefore holds an open connection, as the page's event stream is during a send. The first version sent a request first, and passed with the fix removed.

Not yet run on Linux or Windows: the branch has not been pushed.
