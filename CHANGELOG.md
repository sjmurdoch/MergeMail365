# Changelog

All notable changes to MergeMail365 are recorded here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [semantic versioning](https://semver.org/).

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

[0.4.0]: https://github.com/sjmurdoch/MergeMail365/compare/v0.3.1...v0.4.0
