# Changelog

All notable changes to MergeMail365 are recorded here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [semantic versioning](https://semver.org/).

## [Unreleased]

### Security

- Desktop app (macOS/Windows, and `mergemail365-web --desktop`): the app now requires the per-launch access token and CSRF token, as browser mode does. Since 0.1.0 the desktop app had skipped both, on the mistaken belief that it opened no network port; in fact it was served on a random `127.0.0.1` port that any program on the machine could use to act as the signed-in user, including sending email.
- Web UI (both modes): requests whose `Host` header isn't `localhost`, `127.0.0.1`, `::1` or the `--host` value are refused, which blocks DNS-rebinding attacks from web pages. The check is skipped when binding to all interfaces (`--host 0.0.0.0`).
- Web UI: a spreadsheet whose column headers contained HTML could run script in the app when the Compose step reported an unknown placeholder, letting whoever made the spreadsheet send email from the user's account. Column names are now always shown as plain text.
- Web UI: pasting into the HTML editor could run script hidden in the copied content (for example, text copied from a malicious web page) before the editor cleaned it up. Pasted HTML is now processed without running anything in it.
- Web UI: an attachment's filename could contain `../` or an absolute path, causing the file to be written outside the app's temporary folder, for example over a startup script. Only the final part of the filename is now used, and names that are left empty, such as `..`, are rejected.

### Added

- Web UI: if the app quits or crashes during a send, the next time it starts it shows which emails were sent before it stopped, with a CSV download, until dismissed. While a send runs, its results are kept in a file readable only by the user (in the app's state folder), which is deleted when the send ends or the report is dismissed.

### Fixed

- Web UI: attaching two files with the same name no longer sends the second file twice. Both are now attached with their own contents.
- Web UI: column names containing `<`, such as `Price <GBP>`, are now shown in full in the "No column named …" message on the Compose step. Previously part of the name was missing.
- Web UI: a test email that was still sending when the user went back could later mark the step as passed, even if the message had been edited in the meantime. The edited message could then be sent to everyone without ever being test-sent. Results from a test email or dry run that the user has since gone back from are now ignored.
- Web UI: likewise, an earlier dry run that finished while a newer one was running could enable Next on the Verify step before the dry run of the current message had finished.
- Web UI: after sending a test email again, Next on the Test step stayed enabled while the new test was running, and did nothing if clicked. It is now disabled until the test passes.
- Web UI: after a completed send and "New merge", the Back button on the Send step stayed disabled, so the user couldn't go back from it before sending.
- Web UI: reloading the page after sending a test email or running a dry run jumped to the Send step and showed "Sending…" as if a real send were under way. Reloading now only returns to the Send step when a real send was started.
- Web UI: reloading the page after a job had finished, including a real send, could leave it stuck on "Sending…" with no way to continue. A finished send now shows its results after a reload.
- Command line: if a send was interrupted part-way (Ctrl-C, an error or a crash), no `--output` report was written, so running again with resume sent the same emails a second time. The report is now written as each email goes, so a resumed run only sends to the people who haven't had one.
- Web UI: "Stop sending" did nothing; the send carried on to the end. It now stops before the next email, and the results list the emails that were sent.
- Web UI: "Stop sending" pressed just after "Send emails", before the send had properly started, went to the earlier dry run instead and was lost. It now stops the send.
- Web UI: while signed out, the Test and Send steps could be reached with their send buttons enabled and no way to sign in from there. The buttons are now disabled until the user signs in, and both steps offer a sign-in button.
- Web UI: a test email or send started while signed out could wait for several minutes, silently, for a sign-in code that was never shown. It now fails at once with "Not signed in".
- Web UI: going back, editing the message or uploading another spreadsheet while the recipient list was loading could jump to the Preview step with a list for the old content. The late list is now ignored.
- Web UI: reloading the page just after clicking "Send emails" could leave the send running with nothing on screen to show it. A running send is now always shown after a reload, and a second send can't be started while one is running.
- Web UI: a send that failed part-way only showed the error, not which emails had already gone out. Those emails are now listed under the error.
- Web UI: a second send started with the first send's progress text until its first email went out.
- Web UI: "New merge" kept the BCC "To" address from the previous merge.
- Web UI: placeholders for column names with non-English letters, such as `{{Prénom}}`, were filled in the sent email but shown unfilled in the preview, and weren't checked against the spreadsheet's columns. The preview now treats them like the email does.
- Web UI: occasionally, if the page was slow to load, the HTML editor didn't work properly: switching to HTML didn't show the message already typed, and clicking a column-name chip didn't insert the placeholder into the editor. The editor now works however quickly the page loads.

### Changed

- Desktop app: the app is now served by the same web server as browser mode, on the same port range (5050–5099), rather than by pywebview's built-in server.

## [0.4.1] — 2026-09-30

### Added

- Web UI: diagnostics for reports of the app freezing. When file logging is on (always, in the macOS and Windows apps), a warning is logged if the app becomes unresponsive for 10 seconds or more. If a freeze lasts 30 seconds or more, the state of every thread is written to `mergemail365-stalls.log` next to the main log file. This is to investigate a report that, in the Windows app, sending a test email sometimes did nothing for several minutes until the user clicked Back.
- The log file now records which thread wrote each line and, for the web UI, the Python, operating system and package versions in use.

## [0.4.0] — 2026-09-30

### Breaking changes

- **Python 3.14 or later is now required** (previously 3.10). Users installing with `pip` or `uv` on Python 3.10–3.13 must upgrade Python first. The macOS and Windows release bundles include their own Python, so their users are unaffected.

### Added

- Web UI: clickable column-name chips below the recipient filter box, so filters can be written without typing column names by hand.

### Fixed

- CLI: subjects, addresses and attachment names containing square brackets are now shown correctly in the send confirmation summary. Previously `Q3 [draft]` was displayed as `Q3`, text containing `[/]` crashed the confirmation with a `MarkupError`, and the `[y/N]` hint was never shown.
- Web UI: placeholder and filter chips are restored correctly after reloading the page.
- Web UI: the rich-text editor no longer shows a file-attachment button, which did nothing useful (use the Attachments field under *Additional options* instead).
- Web UI: tidier spacing and grouping on the Compose step.

### Changed

- Release bundles are built with Python 3.14 (previously 3.10).
- Updated dependencies, including msal 1.39.0, requests 2.34.2, rich 15.0.0, pywebview 6.2.1 and pythonnet 3.1.0 (Windows desktop backend, needed for Python 3.14).
- Updated the bundled Trix editor to 2.1.19, and replaced the bundled Pico CSS with the official 2.1.1 build (the previous copy differed slightly from the published file).
- The `tomli` dependency is no longer needed.

### Security and supply chain

- Dependencies, bundled JavaScript/CSS, GitHub Actions and CI tools are only adopted once they have been public for at least 7 days. GitHub Actions are pinned to commit SHAs.

### Development

- New CI workflow runs the full test suite (including browser tests), mypy and Biome on Linux, macOS and Windows.
- Tests now fail if they make a real network request, check calls against the real `msal` and `pywebview` APIs, and include contract tests that run real `msal` against mocked Microsoft Entra endpoints.
- Added browser tests for pasting into the editor, toolbar formatting and links, plus checks for invalid HTML in the web UI.

[Unreleased]: https://github.com/sjmurdoch/MergeMail365/compare/v0.4.1...HEAD
[0.4.1]: https://github.com/sjmurdoch/MergeMail365/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/sjmurdoch/MergeMail365/compare/v0.3.1...v0.4.0
