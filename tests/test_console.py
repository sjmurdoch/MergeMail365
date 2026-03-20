"""Tests for mail_merge.console — ANSI stripping filter."""

import logging

from mail_merge.console import _StripAnsiFilter


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
