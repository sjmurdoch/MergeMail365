# Changelog

All notable changes to MergeMail365 are recorded here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [semantic versioning](https://semver.org/).

## [Unreleased]

### Security

- Updated bundled libraries with security fixes: certifi, the list of certificate authorities used to check the connection to Microsoft, no longer trusts a root whose intermediate certificates' keys were compromised; Werkzeug, the web UI's server library, no longer lets Windows device names through when serving the app's files (GHSA-6q48-6c7w-9gw2, GHSA-g6x2-hccm-hh4m). The macOS and Windows apps also get newer versions of the libraries behind their window (pyobjc 13, pythonnet 3.2).
- Log files no longer contain access tokens or the content of your emails. Since file logging was added, each email sent was logged with its full request, including the `Authorization` header (a token that can send mail as you for about an hour after it was issued) and the message, recipients and attachments. The macOS and Windows apps always write a log file, and `--log-file` turns it on elsewhere. **If you have run an earlier version with file logging, delete the old log files**, and don't send them to anyone: `~/Library/Logs/mergemail365/` on macOS, `%LOCALAPPDATA%\mergemail365\logs\` on Windows, `~/.local/state/mergemail365/log/` on Linux. Tokens in them have long expired, but the emails and addresses are still there.
- The log file also no longer records the web UI's access token, the sign-in redirect's authorisation code, or the rendered body of each email in a dry run (a dry run at `--log-level DEBUG` still shows the bodies in the terminal).
- Web UI: the sign-in route (`/auth/login`) now requires the app's access token like every other page. Before, any web page open in your browser could send it to `http://localhost:5050/auth/login` with an app registration of its choosing and start a Microsoft sign-in for it, and the choice replaced a client ID fixed with `--client-id`. A fixed client or tenant ID can no longer be overridden by a request.
- Web UI: the page now has a Content Security Policy that only allows the app's own scripts to run, as a second line of defence if text from a spreadsheet or a server response were ever shown without escaping. All text placed on the page now goes through one escaping function. This also fixes the "Test connection" panel, which showed its diagnostic details (including the tenant ID and error text) without escaping them, and column names containing a double quote, which could not be selected as the email or name column.
- `mergemail365-web --host` with an address other computers can reach (`0.0.0.0`, a LAN address or name) is refused unless `--allow-remote` is also given, and then starts with a warning: the connection is plain HTTP, and anyone who learns the access URL can send email as the signed-in account.
- Log files and the folder they are in are now readable by you only, as is the token cache from the moment it is written (it used to be created readable by others and restricted a moment later). Existing log files are restricted when the app next starts.

### Changed

- **Placeholders accept any column name, and spaces inside the braces.** `{{First-Name}}`, `{{E-mail}}` and `{{Price <GBP>}}` now work; before, a placeholder for a column whose name had punctuation was never filled in, and went out to recipients exactly as typed, with no warning. `{{ name }}` (with spaces inside the braces) is now the column `name`; before, it too was sent as typed. If you relied on either being left alone, note the change.
- **In an HTML email, values from the spreadsheet are now escaped.** A cell containing `<`, `>` or `&` is shown to the recipient as typed, and line breaks within a cell are kept. Before, the cell's text was inserted as HTML, so `R&D <team>` could lose text or break the layout, and a spreadsheet built from other people's answers (a form, say) let them put their own links or images into your email. If you deliberately keep HTML in cells, it will now be shown as text; put the markup in the body instead.
- **Dates, times, percentages and numbers from the spreadsheet are written as you'd expect.** A date cell is now `2026-12-01` (it was `2026-12-01 00:00:00`), with the time added only when there is one (`2026-12-01 14:30`); a cell formatted as a percentage is `25%` (it was `0.25`); numbers never appear as `3.0` or `1.23e+19`. Other Excel number formats, such as currency symbols, thousands separators and a fixed number of decimals, are still not applied (`£1,250.50` is sent as `1250.5`): the web UI lists the affected columns when you upload the spreadsheet, and the command line warns when a message uses one. To control exactly what is sent, format the column as Text in Excel.
- A placeholder that names no column stops the send, as before, and the web UI now says so when you press Next on the Compose step instead of at the test email. A `{{` or `}}` that isn't part of a placeholder (such as `{{name}`) gives a warning, since it is probably a typo and will be sent as written.

### Fixed

- A display name in curly quotes is accepted in CC, BCC, Reply-To and the other address fields: `“Murdoch, Steven” <steven@example.com>`. macOS replaces straight quotes with curly ones as you type, so in the desktop app a name containing a comma could not be typed; it was refused with "An email address must have an @-sign".
- Desktop app: the subject, body and chosen columns are restored when you open the app again, as they are in a browser. The desktop window used to forget them when it closed. (In a browser too, the name column wasn't restored once the spreadsheet was uploaded again.)
- Opening the app a second time while it is running no longer makes the two share one port on Windows, where the second window then talked to the first copy's server. On macOS and Linux the second copy failed to start; now it uses the next free port, as intended.
- Web UI: after New merge, the Verify step shows the dry run's log again; it showed only the summary line.
- Web UI: the log of a test email or send names the account it is sent from ("Sending as …"), as the command line does.
- A dry run's summary says "Would send", not "Sent", and that nothing was sent.
- Web UI: an attachment smaller than 1 KB is shown with its size in bytes on the Send step, not as "0 KB". The sign-in diagnostics no longer run past the edge of the window.
- Web UI: the advice shown for a failed test email is chosen from Microsoft's status code. It used to be chosen by searching the error text for numbers, so an address or request ID containing, say, `403` or `500` could produce the wrong advice. A network failure now says "Could not reach Microsoft".
- `--log-level` with a misspelt level (`--log-level DEGUB`) is refused; it used to be quietly treated as `INFO`. At `DEBUG`, an unexpected error on the command line is now followed by its traceback.
- Web UI: a spreadsheet whose name ends in upper-case `.XLSX` was refused as "Only .xlsx files are supported".
- **A network timeout could send an email twice.** When Microsoft received a request but no answer came back in time (a read timeout), the email was sent again, up to `--max-retries` times, although the first attempt may well have been delivered. It is now not retried, and is reported as "outcome unknown: may have been delivered" rather than as failed: in the summary, in a new `unknown` column of the `--output` report, and in the web UI's results. Resuming from the report doesn't send it again, and says so; delete its line from the report to send it anyway. Connection errors, where nothing reached Microsoft, are still retried.
- **Resuming a send skipped rows that share an address.** If the spreadsheet had several rows for one address (one person, several personalised emails) and a run stopped after the first of them, re-running with `--output` never sent the others, because any recorded success for the address skipped every row with it. Rows are now counted: each recorded success skips one row. The report also keeps one line per row instead of one per address.
- Resuming a send re-sent to an address starting with `+`, `-`, `=` or `@` (such as `+tag@example.com`) every time, because the character that the report adds to stop spreadsheets reading such a value as a formula was not taken off again when the report was read back.
- CC, BCC and reply-to addresses are checked before anything is sent, like the recipients' addresses. A mistyped address used to be discovered only when Microsoft rejected the email, once for every recipient. The web UI reports it when you leave the Compose step. The test address and BCC mode's To address are checked too.
- A display name containing a comma now works when quoted: `"Doe, Jane" <jane@example.com>` used to be split into the "addresses" `Doe` and `Jane`. Addresses may also be separated by semicolons, as in Outlook.
- `--batch-size`, `--delay` and `--max-retries` refuse values that make no sense. `--batch-size -1` used to send to everyone except the last recipient. `--batch-size 0`, which did nothing, is now an error too.
- Several attachments that each fit but together exceed what one message can carry (about 3 MB) are refused before sending, instead of failing for every recipient.
- `--sheet` with a name that isn't in the workbook gives a message listing the sheets, instead of "Unexpected error".
- **A test email that Microsoft rejected was reported as sent.** In the web UI, step 4 showed "Test email sent successfully!" and let you continue even when Microsoft Graph refused the email (for example, a permission error or an invalid address). It now shows the failure and offers Retry. On the command line, a rejected `--test-email` exited with status 1 but printed nothing; it now says why. In the Python API, `send_merge(test_email=...)` raises `SendAborted` if the test email is not accepted, instead of returning a failed result.
- Web UI: signing in after opening the app at `127.0.0.1` (rather than `localhost`) ended on a "Forbidden" page, although the sign-in itself had worked. It now returns to the app.
- Web UI: a sign-in that can't start (no network, a mistyped tenant ID) shows the reason on the page instead of an "Internal Server Error" page.
- Web UI: a spreadsheet with many columns or long column headings (a survey export, for example) could make the app forget the upload, answering "No spreadsheet uploaded" or "Forbidden" at the next step. The session's data was kept in a browser cookie, which browsers discard once it passes about 4 KB; it is now kept in the app, and the cookie is only an identifier.
- Web UI: attachments are deleted from the temporary folder when the job that used them ends. A copy used to be kept for every test email, dry run and send until the next upload or until the app closed.
- Web UI: an upload over 64 MB is refused with a message instead of being written to disk first.
- `mergemail365-web`: the search for a free port now checks the address the server will listen on, not always `127.0.0.1`.
- Signing in no longer changes the permissions of your home directory. On macOS and Linux, saving the token cache set the home directory to mode 0700 each time, which could stop other accounts and services (file sharing, a web server's user directories) from reaching files you had shared.
- A token cache file that is damaged (for example by a crash while it was being written) no longer blocks sign-in: it is ignored with a warning and replaced the next time you sign in. The cache is now written atomically, so a crash can't truncate it.

### Added

- The command line says which account it sends from: `Sending as you@example.com` once signed in, and a `From:` line in the confirmation prompt before a send (or "you will be asked to sign in"). If more than one account is signed in, a warning lists them and names the one used.
- `mergemail365 --sign-out` signs out of every cached account. Before, only the web UI could sign out.
- `-v` / `--verbose` (short for `--log-level DEBUG`) on `mergemail365` and `mergemail365-web`, and the log level can be set with the `MERGEMAIL365_LOG_LEVEL` environment variable or `log-level` in `~/.mergemail365.toml`.
- Web UI: a footer showing the running version, e.g. "MergeMail365 v0.6.0".

## [0.6.0] — 2026-10-04

### Added

- An app icon: a spreadsheet with an envelope in front. The macOS and Windows apps use it, and the web UI shows it as the browser tab's icon.

### Changed

- Web UI: the box where you type SEND to confirm a send is now empty, instead of showing a greyed-out "SEND" that could look as if it were already filled in.

### Fixed

- Desktop app: "Download mail merge report" (and "Download CSV" for an interrupted send) now asks where to save the file. On macOS it used to show the report in place of the app, with no way back; on Windows it did nothing.

## [0.5.0] — 2026-10-04

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

[Unreleased]: https://github.com/sjmurdoch/MergeMail365/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/sjmurdoch/MergeMail365/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/sjmurdoch/MergeMail365/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/sjmurdoch/MergeMail365/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/sjmurdoch/MergeMail365/compare/v0.3.1...v0.4.0
