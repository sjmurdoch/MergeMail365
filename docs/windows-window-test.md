# Instructions: run the real-window test on Windows

For an agent working on the Windows PC. This is the last open item of `docs/phase-h-guards-plan.md` (phase 4, guard G-D2). Read that plan's "Phase 4" section first; `CLAUDE.md` describes the project and its rules, which apply here.

## The task

`tests/test_window.py` starts `mergemail365-web --desktop` in its real window, does a whole merge in it, closes it, opens it again and checks that the subject, body, columns and sheet were remembered. It passes on macOS (WKWebView). It has never been run on Windows (WebView2), so on Windows both the app and the test's driver (`tests/window_driver.py`) are unproven.

Done means:

1. The test passes on Windows, or you have found why it cannot and written that down.
2. You have shown it fails when the bug it guards against is put back (step 4).
3. The plan's Status and `TODO.md` say what happened, and the work is committed and pushed.

Nothing here signs in to Microsoft or sends email: sign-in is a faked token cache and Microsoft Graph is a mock inside the test process. Never ask for or handle a password. If anything tries to open a Microsoft sign-in page, stop: something is wrong.

## 1. Set up

Work on the `phase-h-guards` branch (pull request #5), in Git Bash.

```bash
git fetch origin
git checkout phase-h-guards
git pull
uv sync --all-extras
.venv/Scripts/python.exe -m playwright install chromium
```

Do not use plain `uv run` for the tests: it drops the extras. Use `.venv/Scripts/python.exe -m pytest`. Do not upgrade any dependency (`CLAUDE.md`, "Supply-chain policy").

The window needs the Microsoft Edge WebView2 Runtime, which Windows 11 has. If pywebview reports that it is missing, say so and stop; do not install software without asking the user.

## 2. Run the test

A window titled MergeMail365 appears for about fifteen seconds, twice. Leave it alone while it runs.

```bash
scripts/pre-release-checks.sh window
```

or, the same thing directly, with the failure in full:

```bash
MERGEMAIL365_WINDOW_TESTS=1 .venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_window.py
```

If it passes, go to step 4.

## 3. If it fails

First decide which side is at fault. The app is at fault if a person doing the same thing by hand in the desktop window would see the problem. Otherwise the driver is, and the driver is the likelier one, since it has only met WKWebView.

To see what happened, run one half by hand with a home directory of its own:

```bash
home="$(mktemp -d)"
HOME="$home" USERPROFILE="$home" LOCALAPPDATA="$home/AppData" \
  .venv/Scripts/python.exe tests/window_driver.py merge "$home/merge.json" path/to/people.xlsx --port 5085 --client-id window-test
cat "$home/merge.json"
```

(The workbook is built by the `xlsx` fixture in `tests/test_window.py`; make one the same way. Run the phase `reopen` afterwards with the same environment for the second half.) The JSON holds everything the driver saw, and `error` holds the traceback and any `alert()` the page raised.

Things that may differ on Windows, most likely first:

- **`run_js()`.** The driver runs scripts with pywebview's `window.run_js()` and each script posts its answer to `/window-test-answer/<n>` on the app's own port. It does not use `evaluate_js()`, because that wraps the script in `eval()`, which the app's Content Security Policy refuses. If no answers arrive ("no answer from the page"), find out whether the script runs at all on WebView2 and whether the `fetch` is made. Do not weaken the Content Security Policy to make the driver work.
- **The upload.** `Page.upload()` builds a `File` in the page and assigns it through `DataTransfer` to the file input, then dispatches `change`.
- **Where the window keeps its storage.** On Windows it is `storage_path`, under `state_dir()/webview`, which the test's `LOCALAPPDATA` moves into the temporary home. The assertion `stored_at_start == []` fails if the window is using storage from somewhere else; find out where before changing anything, and make sure the user's real app data is not touched.
- **Storage reaching the disk.** The driver waits two seconds after the auto-save before closing the window. If the reopened window remembers nothing although `stored_at_end` in `merge.json` is complete, try a longer wait before concluding the app loses data, and report which it was.
- **The port.** The test uses 5085. If another copy of the app or a leftover test process holds it, the app moves to 5086 and the test says so ("the app moved to another port"). Look for leftover `python.exe` processes from an earlier failed run.
- **Closing.** `window.destroy()` must end the process. If the test times out after 180 seconds with the window gone, the process did not exit.

Rules for fixing:

- Fix the driver so that it works on both platforms; keep macOS working (it cannot be rerun there by you, so keep changes small and say what you changed).
- Do not relax an assertion in `tests/test_window.py` to get a pass. If an assertion is wrong for Windows, say why in the plan.
- If the app itself is at fault, that is a finding. Write it up in the plan with what a user would see. Fix it only if the fix is small and clearly right, in a separate commit with a `CHANGELOG.md` entry under "Unreleased"; otherwise add it to `TODO.md` and leave it.

## 4. Show that the test catches the bug

In `src/mail_merge/web/__init__.py`, change `private_mode=False` to `private_mode=True` in the `webview.start()` call and run the test again. It must fail in the `reopen` half (on macOS: "timed out waiting for the remembered sheet"). Then restore the line and check `git diff src/` is empty.

If it still passes with private mode on, the test does not guard against phase H's finding 6 on Windows. Find out why (most likely the storage is not where the test thinks) before reporting.

## 5. Two things to look at while the window is open (optional, only if you can see the screen)

A test cannot see these; a screenshot or the user can.

- **The HTML preview at step 3.** Phase H found it blank on Windows after New merge (finding 2). The test checks that the frame is shown and holds the right document, which was also true when it drew nothing.
- **SmartScreen** is not part of this task (`TODO.md`, "Release and packaging").

If you cannot look, say that these were not checked. Do not report them as fine.

## 6. Run the rest, record, commit

1. Run the whole suite, which must pass before any commit: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`, then `.venv/Scripts/python.exe -m ruff check .` and `.venv/Scripts/python.exe -m mypy`.
2. In `docs/phase-h-guards-plan.md`, under "Phase 4": replace the "Not done: the Windows run" paragraph with what happened (the Windows and WebView2 versions, pass or fail, the result of step 4, anything changed in the driver and why, any finding). Change the heading to say phase 4 is done, if it is. Update the date at the top of Status.
3. In `TODO.md`, under "Release and packaging", remove "The real-window test has not been run on Windows" if it now has been; leave the blank-preview item unless you looked at it.
4. If you changed how the driver works, update its description in `CLAUDE.md` (the `test_window.py` entry under "Testing").
5. Commit, with separate commits for driver changes, app fixes and the plan, and push to `phase-h-guards`. Do not merge the pull request; the user decides that.

Markdown paragraphs are single long lines (no hard wrapping).

## What to report to the user

State the result first: passed, passed after changes to the driver, or failed and why. Then the step 4 result, any finding about the app, what you could not check, and what you pushed. If you ran something and it failed, show the output; do not describe an unrun check as passing.
