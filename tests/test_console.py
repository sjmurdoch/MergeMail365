"""Tests for mail_merge.console — ANSI stripping filter, file logging, and console setup."""

import io
import logging
from unittest.mock import patch

from rich.logging import RichHandler

from mail_merge.console import _StripAnsiFilter, _make_console, setup_file_logging, setup_logging


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


class TestConsoleLevelIndependence:
    def test_file_logging_does_not_change_console_level(self, tmp_path):
        """Console handler stays at INFO after setup_file_logging lowers root to DEBUG."""
        root = logging.getLogger()
        original_handlers = list(root.handlers)
        original_level = root.level

        # Clear existing handlers so basicConfig will add our RichHandler
        root.handlers.clear()
        try:
            setup_logging(logging.INFO)

            with patch("mail_merge._paths.log_dir", return_value=tmp_path):
                setup_file_logging(logging.DEBUG)

            # Root logger should be lowered to DEBUG for the file handler
            assert root.level == logging.DEBUG

            # The RichHandler should still be at INFO
            rich_handlers = [h for h in root.handlers if isinstance(h, RichHandler)]
            assert rich_handlers, "Expected a RichHandler on the root logger"
            assert rich_handlers[0].level == logging.INFO
        finally:
            # Clean up: remove handlers we added, restore originals
            from logging.handlers import RotatingFileHandler
            for h in list(root.handlers):
                if isinstance(h, RotatingFileHandler) and str(tmp_path) in str(h.baseFilename):
                    h.close()
            root.handlers[:] = original_handlers
            root.level = original_level


class TestMakeConsole:
    def test_stderr_none_returns_stringio_console(self):
        """PyInstaller console=False: stderr is None, console uses StringIO."""
        with patch("mail_merge.console.sys") as mock_sys:
            mock_sys.stderr = None
            c = _make_console()
        assert isinstance(c.file, io.StringIO)

    def test_stderr_no_buffer_uses_stderr(self):
        """stderr with write but no buffer attr falls through to Console(stderr=True)."""
        mock_stderr = io.StringIO()  # has write() but no buffer attr
        with patch("mail_merge.console.sys") as mock_sys:
            mock_sys.stderr = mock_stderr
            c = _make_console()
        # Should have fallen through to Console(stderr=True) or similar
        assert c is not None

    def test_stderr_with_buffer_gets_utf8_wrapper(self):
        """Normal stderr with buffer gets a UTF-8 TextIOWrapper."""
        with patch("mail_merge.console.sys") as mock_sys:
            raw = io.BytesIO()
            mock_sys.stderr = io.TextIOWrapper(raw, encoding="ascii")
            c = _make_console()
        assert isinstance(c.file, io.TextIOWrapper)
        assert c.file.encoding == "utf-8"
