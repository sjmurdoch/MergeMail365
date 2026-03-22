"""Windows-specific tests — verifying correct behaviour on Windows.

These tests are skipped on non-Windows platforms. They check:
- Platform-aware paths (LOCALAPPDATA, data_dir, config, token cache)
- Token cache saving without Unix chmod
- CSV round-trip with Windows line endings
- Body template with UTF-8 BOM
- Attachment names extracted from backslash paths
"""

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only tests")


class TestDataDir:
    """_paths.data_dir() on Windows uses %LOCALAPPDATA%."""

    def test_uses_localappdata(self, monkeypatch):
        from mail_merge._paths import data_dir

        monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\test\AppData\Local")
        result = data_dir()
        assert str(result) == r"C:\Users\test\AppData\Local\mergemail365"

    def test_falls_back_to_home(self, monkeypatch):
        from pathlib import Path

        from mail_merge._paths import data_dir

        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        result = data_dir()
        assert result == Path.home() / "mergemail365"


class TestWindowsDefaultPaths:
    """Config and token cache paths live under data_dir() on Windows."""

    def test_config_default_path_under_data_dir(self):
        from mail_merge._paths import data_dir
        from mail_merge.config import DEFAULT_PATH

        assert DEFAULT_PATH == data_dir() / "config.toml"

    def test_cache_path_under_data_dir(self):
        from mail_merge._paths import data_dir
        from mail_merge.auth import CACHE_PATH

        assert CACHE_PATH == data_dir() / "token-cache.json"


class TestSaveCacheOnWindows:
    """_save_cache works on Windows without chmod calls."""

    def test_writes_cache_without_chmod(self, tmp_path, monkeypatch):
        from unittest.mock import MagicMock

        import mail_merge.auth as auth_module
        from mail_merge.auth import _save_cache

        cache_path = tmp_path / "token-cache.json"
        monkeypatch.setattr(auth_module, "CACHE_PATH", cache_path)

        mock_cache = MagicMock()
        mock_cache.has_state_changed = True
        mock_cache.serialize.return_value = '{"AccessToken": {}}'

        _save_cache(mock_cache)

        assert cache_path.exists()
        assert cache_path.read_text(encoding="utf-8") == '{"AccessToken": {}}'

    def test_creates_nested_dirs_on_windows(self, tmp_path, monkeypatch):
        from unittest.mock import MagicMock

        import mail_merge.auth as auth_module
        from mail_merge.auth import _save_cache

        cache_path = tmp_path / "nested" / "deep" / "cache.json"
        monkeypatch.setattr(auth_module, "CACHE_PATH", cache_path)

        mock_cache = MagicMock()
        mock_cache.has_state_changed = True
        mock_cache.serialize.return_value = "{}"

        _save_cache(mock_cache)

        assert cache_path.exists()


class TestCsvWindowsLineEndings:
    """CSV round-trip works correctly on Windows (newline='' prevents double \\r)."""

    def test_csv_round_trip_no_extra_blank_lines(self, tmp_path):
        from mail_merge.report import read_csv, write_csv
        from mail_merge.sender import SendResult

        results = [
            SendResult(email="alice@example.com", success=True, status_code=202, error=""),
            SendResult(email="bob@example.com", success=False, status_code=500, error="Server error"),
        ]
        path = tmp_path / "report.csv"
        write_csv(results, path)

        # Read raw bytes to check line endings — should be \r\n on Windows
        raw = path.read_bytes()
        # Must not contain \r\r\n (double carriage return from missing newline='')
        assert b"\r\r\n" not in raw

        # Round-trip via read_csv should recover the data
        loaded = read_csv(path)
        assert len(loaded) == 2
        assert loaded[0].email == "alice@example.com"
        assert loaded[0].success is True
        assert loaded[1].email == "bob@example.com"
        assert loaded[1].success is False
        assert loaded[1].error == "Server error"


class TestBodyTemplateWithBom:
    """Body template files with a UTF-8 BOM are read correctly."""

    def test_bom_in_body_template(self, sample_xlsx, tmp_path):
        from mail_merge.api import send_merge

        body = tmp_path / "body_bom.txt"
        # Write with UTF-8 BOM
        body.write_bytes(b"\xef\xbb\xbfHello {{name}},\n\nWelcome from {{company}}.\n")

        results = send_merge(
            spreadsheet=sample_xlsx,
            body=body,
            subject="Hello {{name}}",
            email_column="email",
        )
        # Should succeed despite BOM (body is just text content, BOM is harmless)
        assert len(results) == 2
        assert all(r.success for r in results)


class TestBackslashPaths:
    """Attachment names are extracted correctly from Windows backslash paths."""

    def test_attachment_name_from_backslash_path(self, tmp_path):
        from pathlib import Path

        from mail_merge.api import _process_attachments

        att = tmp_path / "subdir" / "report.pdf"
        att.parent.mkdir(parents=True, exist_ok=True)
        att.write_bytes(b"%PDF-fake-content")

        result = _process_attachments([att])
        assert result is not None
        assert len(result) == 1
        # Path.name should give just the filename regardless of separator
        assert result[0]["name"] == "report.pdf"

    def test_attachment_name_from_string_path(self, tmp_path):
        from mail_merge.api import _process_attachments

        att = tmp_path / "doc.txt"
        att.write_text("content", encoding="utf-8")

        # Pass as string with backslashes (as Windows paths typically are)
        result = _process_attachments([str(att)])
        assert result is not None
        assert result[0]["name"] == "doc.txt"


class TestConfigLoadOnWindows:
    """Config file loading works with Windows paths."""

    def test_load_config_from_windows_path(self, tmp_path):
        from mail_merge.config import load_config

        cfg = tmp_path / "subdir" / "config.toml"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(
            'client-id = "win-client"\ntenant-id = "win-tenant"\n',
            encoding="utf-8",
        )

        result = load_config(cfg)
        assert result == {"client_id": "win-client", "tenant_id": "win-tenant"}


class TestEndToEndOnWindows:
    """Full dry-run pipeline works on Windows with tmp_path (backslash paths)."""

    def test_dry_run_with_windows_paths(self, sample_xlsx, body_template_file):
        from mail_merge.api import send_merge

        # Paths from pytest fixtures will use backslashes on Windows
        results = send_merge(
            spreadsheet=sample_xlsx,
            body=body_template_file,
            subject="Hello {{name}}",
            email_column="email",
        )
        assert len(results) == 2
        assert all(r.success for r in results)

    def test_cli_with_windows_paths(self, sample_xlsx, body_template_file, tmp_path):
        from mail_merge.cli import main

        report = tmp_path / "output.csv"
        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
        ])
        assert exit_code == 0

    def test_output_csv_with_windows_paths(self, sample_xlsx, body_template_file, tmp_path, monkeypatch):
        import responses

        from mail_merge.cli import main
        from mail_merge.sender import GRAPH_SEND_URL

        responses.start()
        try:
            responses.add(responses.POST, GRAPH_SEND_URL, status=202)
            monkeypatch.setattr(
                "mail_merge.auth.acquire_token",
                lambda client_id, tenant_id="common": "fake-token",
            )

            report = tmp_path / "sub" / "dir" / "report.csv"
            report.parent.mkdir(parents=True, exist_ok=True)

            exit_code = main([
                "--spreadsheet", str(sample_xlsx),
                "--body", str(body_template_file),
                "--subject", "Hello {{name}}",
                "--email-column", "email",
                "--client-id", "fake",
                "--output", str(report),
                "--send", "-y",
            ])
            assert exit_code == 0
            assert report.exists()

            from mail_merge.report import read_csv

            loaded = read_csv(report)
            assert len(loaded) == 2
        finally:
            responses.stop()
            responses.reset()
