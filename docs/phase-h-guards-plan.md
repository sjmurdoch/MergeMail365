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
| G-D2 | D | A smoke test of the real window: start `mergemail365-web --desktop` with Graph and sign-in faked, drive the wizard through pywebview's `evaluate_js`, quit and reopen, check what is remembered. | Local, before a release, on macOS and on the Windows PC |
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
| 4 | G-D1, G-D2 | Decided 2026-11-16: both run locally before a release, not in CI. |

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

### Phase 3 (G-E, G-F, G-G): done

**G-G, `tests/test_wording.py`** (22 tests, 3 seconds) and `TestOneOfEverything`.

| Test | Bug put back | Caught? |
|---|---|---|
| A dry run never says "sent" (command line and web, individual and BCC) | Finding 15 | Yes: all 4 |
| The command line and a web job log the same lines | Finding 16 (no "Sending as" in web jobs) | Yes: the 4 sending modes |
| One of something is not plural, in the logs and on the page | (finding 14's kind) | It failed on the code as it was: "Loaded 1 recipients", "1 columns, 1 rows", "1 emails ready to send", "all 1 emails". Fixed with `sender.count()` and `WizardCore.count()` |

The lines are compared as a set, not in order: a web job fetches its token when the first email needs it, so "Sending as" comes after the first "Sending" line there. `formatSize()` gained boundary cases, which found "1024 KB" for a file just under 1 MB.

**G-F, `TestLayoutWithAwkwardContent`** (10 seconds). Sixty columns with long headings, values with nowhere to break, a 116-character account name, long file names, at 1100, 800 and 480 pixels wide, measured at seven points of the wizard.

| Bug | Caught? |
|---|---|
| Finding 12 (diagnostics wider than the column), with its fix removed | Yes |
| Finding 13 (tall header row), still open | It failed on the code as it was: cells up to 392px tall. Fixed: table rows are one line, cut short with the full text as a title |
| **New: a long account name made the page scroll sideways** (by 271px at the desktop window's width) | Fixed: it wraps inside the header |
| **New: the row of steps ran past a 480px window** | Fixed: it wraps |

**G-E, `tests/test_typed_text.py`** (37 tests, under a second). Four fields (address lists, filters with `=` and with `!=`, placeholder names) against nine substitutions. Every pair must read the same as the plain text or be refused; the seven exceptions are listed with reasons.

| Bug | Caught? |
|---|---|
| Finding 11 (curly quotes don't quote a display name), put back | Yes |
| **New: a filter value typed with a curly apostrophe or a no-break space matched nothing**, so `Company!=O’Neil` excluded nobody and those rows would have been sent to. In the macOS app a straight apostrophe cannot be typed | It failed on the code as it was. Fixed: `typed_text.plain()` on both sides of the comparison, and for the column name |
| **New: `{{Manager’s name}}` named no column** when the heading has a straight apostrophe (refused with a message, so not silent, but untypeable in the macOS app) | Fixed in `template.py` and `template-core.js`, with six shared vectors |
| **New: an address with invisible characters** (direction marks from Outlook, a zero-width space from a web page) was refused with a message about a character that cannot be seen | Fixed: stripped before parsing |

Left as they are: an address in the spreadsheet's own column with an invisible character is still skipped as invalid, with a warning naming it; a filter value in quotes (`Company="Acme"`) is compared with the quotes.

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

Since run in CI on Linux, macOS and Windows (pull request #5): both pass on all three.

### Phase 4 (G-D1, G-D2): done

Both run on a developer's machine before a release, not in CI: `scripts/pre-release-checks.sh` (or with `webkit` or `window` for one of them).

**G-D1, the browser tests in WebKit.** `pytest --browser webkit` over the six browser test files. Everything passes except the five tests that paste from the real clipboard, which need a permission only Chromium has; they are skipped in WebKit (`_allow_clipboard()` in `tests/test_web_e2e.py`). No fault was found: the page behaves the same in both engines.

**G-D2, `tests/test_window.py`** (one test, about 15 seconds, skipped unless `MERGEMAIL365_WINDOW_TESTS=1`). `tests/window_driver.py` runs `mergemail365-web --desktop` in a separate process with a temporary home directory (`CFFIXED_USER_HOME` moves the window's own storage there too, so the developer's is not touched). Sign-in is a token cache holding one account and Graph answers 202; everything else is the app, in its real window. The driver uploads a two-sheet workbook, chooses the second sheet and columns the page would not choose by itself, writes an HTML body, and goes through preview, test email, dry run and send. It closes the window, starts the app again, uploads the workbook and reads the six remembered fields.

| Bug put back | Caught? |
|---|---|
| Finding 6 (pywebview's private mode) | Yes: the reopened window has not kept the sheet |
| Finding 2 (blank HTML preview on Windows) | No. The test checks the preview frame is shown, has a size and holds the email, but a frame that holds the right document and draws nothing looks the same from inside the page. It needs a person, or a screenshot comparison |
| Finding 17 (Cmd+Q during a send) | Not tested: still open (`TODO.md`) |

What writing it showed: pywebview's `evaluate_js()` does not work in this app, because it wraps the script in `eval()` and the Content Security Policy refuses that in the real window, as it should. The driver uses `run_js()` (the script as it is) and the page posts each answer back to the app's own port, where a WSGI layer added by the driver takes it. So the policy is known to be in force in the desktop window, which no test had shown.

**The Windows run (2026-11-16).** Windows 10 Enterprise 22H2 (build 19045.7807), Microsoft Edge WebView2 Runtime 157.0.4341.46, pywebview 6.2.1, Python 3.14.2, following `docs/windows-window-test.md`. `tests/test_window.py` passed on the first run (26 s), with no change to the driver or the app: `run_js()` with answers posted back to the app's port, and the upload through `DataTransfer`, both work on WebView2. The window's storage was where the test expects it (`storage_path` under the temporary home's `AppData\mergemail365\webview`), so the developer's own was not touched. With `private_mode=True` put back in `webview.start()` the test failed in the `reopen` half, as on macOS ("timed out waiting for the remembered sheet"), so it guards finding 6 on Windows too; the line was then restored. No finding about the app.

**Finding 2 looked at by eye on Windows (2026-11-16).** Same machine, the `phase-h-guards` branch (the page says v0.7.0). For two extra runs the driver was changed temporarily, and the change was not committed. One run paused 4 seconds on step 3, scrolled to the preview. The other ran a second pass after the send: New merge, the same upload and HTML body again, then step 3 with the same pause. Screenshots of the window, taken several times a second, show the preview drawing the email ("Dear **Bob**, see you soon.") both times, unchanged throughout the pause. The page reported the same frame before and after New merge (shown, 803×200, the same document). So the blank preview did not come back. This was one look at one build, and a test still cannot see it, so `TODO.md` keeps it as a check by eye before each release.
