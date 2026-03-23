"""Tests for mail_merge.console — ANSI stripping filter and file logging."""

import logging
from unittest.mock import patch

from mail_merge.console import _StripAnsiFilter, setup_file_logging


class TestStripAnsiFilter:
    def _make_record(self, msg, args=()):
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg=msg, args=args, exc_info=None,
        )
        return record

    def test_strips_ansi_from_message(self):
        f = _StripAnsiFilter()
        record = self._make_record("\x1b[31mError\x1b[0m occurred")
        f.filter(record)
        assert record.msg == "Error occurred"

    def test_strips_ansi_from_string_args(self):
        f = _StripAnsiFilter()
        record = self._make_record("Value: %s", ("\x1b[1mbold\x1b[0m",))
        f.filter(record)
        assert record.args == ("bold",)

    def test_preserves_non_string_args(self):
        f = _StripAnsiFilter()
        record = self._make_record("Count: %d, name: %s", (42, "\x1b[32mgreen\x1b[0m"))
        f.filter(record)
        assert record.args == (42, "green")

    def test_no_ansi_passthrough(self):
        f = _StripAnsiFilter()
        record = self._make_record("plain message")
        f.filter(record)
        assert record.msg == "plain message"

    def test_non_string_msg_unchanged(self):
        f = _StripAnsiFilter()
        record = self._make_record(12345)
        f.filter(record)
        assert record.msg == 12345

    def test_always_returns_true(self):
        f = _StripAnsiFilter()
        record = self._make_record("test")
        assert f.filter(record) is True

    def test_none_args_unchanged(self):
        f = _StripAnsiFilter()
        record = self._make_record("no args")
        record.args = None
        f.filter(record)
        assert record.args is None


class TestSetupFileLogging:
    def test_creates_log_file_and_captures_debug(self, tmp_path):
        """setup_file_logging creates a log file that captures DEBUG messages."""
        with patch("mail_merge._paths.log_dir", return_value=tmp_path):
            log_file = setup_file_logging()

        assert log_file is not None
        assert log_file == tmp_path / "mergemail365.log"

        # Write a debug message through a child logger
        test_logger = logging.getLogger("mail_merge.test_file_logging")
        test_logger.setLevel(logging.DEBUG)
        try:
            raise ValueError("test error")
        except ValueError:
            test_logger.debug("something failed", exc_info=True)

        # Flush handlers
        root = logging.getLogger()
        for h in root.handlers:
            h.flush()

        content = log_file.read_text(encoding="utf-8")
        assert "something failed" in content
        assert "ValueError: test error" in content
        assert "Traceback" in content

        # Clean up: remove the handler we added
        from logging.handlers import RotatingFileHandler
        for h in list(root.handlers):
            if isinstance(h, RotatingFileHandler) and str(tmp_path) in str(h.baseFilename):
                root.removeHandler(h)
                h.close()

    def test_returns_none_on_unwritable_dir(self):
        """setup_file_logging returns None if directory creation fails."""
        with patch("mail_merge._paths.log_dir", side_effect=OSError("permission denied")):
            result = setup_file_logging()
        assert result is None
