"""Tests for the stall watchdog and environment logging."""

import faulthandler
import logging
import time

import pytest

from mail_merge.diagnostics import (
    STALL_DUMP_FILENAME,
    StallWatchdog,
    log_environment,
    start_diagnostics,
)


@pytest.fixture(autouse=True)
def _cancel_faulthandler_timer():
    yield
    faulthandler.cancel_dump_traceback_later()


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _wait_taking(clock: FakeClock, seconds: float):
    def wait(_timeout: float) -> None:
        clock.now += seconds
    return wait


class TestTick:
    def test_on_time_wake_is_not_reported(self, caplog):
        clock = FakeClock()
        wd = StallWatchdog(None, interval=1.0, threshold=10.0, clock=clock)
        with caplog.at_level(logging.WARNING, logger="mail_merge.diagnostics"):
            late = wd.tick(_wait_taking(clock, 1.0))
        assert late == pytest.approx(0.0)
        assert caplog.records == []

    def test_late_wake_is_reported_with_duration(self, caplog):
        clock = FakeClock()
        wd = StallWatchdog(None, interval=1.0, threshold=10.0, clock=clock)
        with caplog.at_level(logging.WARNING, logger="mail_merge.diagnostics"):
            late = wd.tick(_wait_taking(clock, 166.0))
        assert late == pytest.approx(165.0)
        [record] = caplog.records
        assert record.levelno == logging.WARNING
        assert "unresponsive for 165 seconds" in record.getMessage()
        assert "thread stacks" not in record.getMessage()

    def test_just_under_threshold_is_not_reported(self, caplog):
        clock = FakeClock()
        wd = StallWatchdog(None, interval=1.0, threshold=10.0, clock=clock)
        with caplog.at_level(logging.WARNING, logger="mail_merge.diagnostics"):
            wd.tick(_wait_taking(clock, 10.9))
        assert caplog.records == []

    def test_long_stall_notes_dump_file_and_end_time(self, tmp_path, caplog):
        clock = FakeClock()
        with open(tmp_path / "dump.log", "a", encoding="utf-8") as f:
            wd = StallWatchdog(f, interval=1.0, threshold=10.0, dump_after=30.0, clock=clock)
            with caplog.at_level(logging.WARNING, logger="mail_merge.diagnostics"):
                wd.tick(_wait_taking(clock, 61.0))
        assert "thread stacks written to" in caplog.records[0].getMessage()
        assert "dump.log" in caplog.records[0].getMessage()
        assert "--- stall of 60s ended at " in (tmp_path / "dump.log").read_text(encoding="utf-8")

    def test_short_stall_does_not_claim_a_dump(self, tmp_path, caplog):
        clock = FakeClock()
        with open(tmp_path / "dump.log", "a", encoding="utf-8") as f:
            wd = StallWatchdog(f, interval=1.0, threshold=10.0, dump_after=30.0, clock=clock)
            with caplog.at_level(logging.WARNING, logger="mail_merge.diagnostics"):
                wd.tick(_wait_taking(clock, 15.0))
        assert "thread stacks" not in caplog.records[0].getMessage()
        assert (tmp_path / "dump.log").read_text(encoding="utf-8") == ""


class TestFaulthandlerDump:
    def test_starved_tick_dumps_all_thread_stacks(self, tmp_path):
        """If the wait overruns dump_after, faulthandler writes every thread's stack."""
        dump_path = tmp_path / "dump.log"
        with open(dump_path, "a", encoding="utf-8") as f:
            wd = StallWatchdog(f, interval=0.01, threshold=10.0, dump_after=0.2)
            # time.sleep stands in for a stall: the timer fires from C meanwhile
            wd.tick(lambda _t: time.sleep(0.6))
        content = dump_path.read_text(encoding="utf-8")
        assert "Timeout (0:00:00.200000)!" in content
        assert "test_starved_tick_dumps_all_thread_stacks" in content

    def test_on_time_ticks_do_not_dump(self, tmp_path):
        dump_path = tmp_path / "dump.log"
        with open(dump_path, "a", encoding="utf-8") as f:
            wd = StallWatchdog(f, interval=0.05, threshold=10.0, dump_after=0.5)
            for _ in range(15):  # 0.75s in total, longer than dump_after
                wd.tick(time.sleep)
            faulthandler.cancel_dump_traceback_later()
        assert dump_path.read_text(encoding="utf-8") == ""


class TestThread:
    def test_start_and_stop(self, tmp_path):
        with open(tmp_path / "dump.log", "a", encoding="utf-8") as f:
            wd = StallWatchdog(f, interval=0.01)
            wd.start()
            assert wd._thread is not None and wd._thread.name == "stall-watchdog"
            assert wd._thread.daemon
            wd.stop()
            assert not wd._thread.is_alive()


class TestStartDiagnostics:
    def test_opens_dump_file_in_given_dir(self, tmp_path):
        wd = start_diagnostics(tmp_path)
        try:
            assert wd.dump_file is not None
            assert wd.dump_file.name == str(tmp_path / STALL_DUMP_FILENAME)
        finally:
            wd.stop()
            wd.dump_file.close()

    def test_runs_without_dump_file_if_it_cannot_be_opened(self, tmp_path):
        wd = start_diagnostics(tmp_path / "missing-dir")
        try:
            assert wd.dump_file is None
        finally:
            wd.stop()


def test_log_environment_records_versions(caplog):
    with caplog.at_level(logging.INFO, logger="mail_merge.diagnostics"):
        log_environment()
    message = caplog.records[0].getMessage()
    assert message.startswith("Python 3.")
    assert "mergemail365 " in message
    assert "msal " in message
    assert "frozen=False" in message
