"""Diagnostics for reports of the app freezing.

A user reported (v0.3.1, Windows desktop bundle) that network requests in
background threads stalled for minutes until they clicked in the window.
One suspected cause is the GUI thread holding the GIL, which would starve
every other Python thread.  The watchdog here records evidence either way:

* A heartbeat thread wakes every ``interval`` seconds.  If it wakes late by
  ``threshold`` seconds or more, no Python thread could run it for that
  long, and a WARNING with the length of the stall goes to the log.
* Each heartbeat also re-arms ``faulthandler.dump_traceback_later``.  That
  timer runs in C without needing the GIL, so if the heartbeat is starved
  for ``dump_after`` seconds the stack of every thread is written to a
  separate file, showing which thread was holding things up.
"""

import faulthandler
import importlib.metadata
import logging
import platform
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TextIO

logger = logging.getLogger(__name__)

STALL_DUMP_FILENAME = "mergemail365-stalls.log"


class StallWatchdog:
    """Detect and record periods when no Python thread could run."""

    def __init__(
        self,
        dump_file: TextIO | None,
        *,
        interval: float = 1.0,
        threshold: float = 10.0,
        dump_after: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.dump_file = dump_file
        self.interval = interval
        self.threshold = threshold
        self.dump_after = dump_after
        self._clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="stall-watchdog", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        if self.dump_file is not None:
            faulthandler.cancel_dump_traceback_later()

    def _run(self) -> None:
        while not self._stop.is_set():
            self.tick(self._stop.wait)

    def tick(self, wait: Callable[[float], object]) -> float:
        """Wait one interval and return how late the wake-up was, in seconds."""
        if self.dump_file is not None:
            faulthandler.dump_traceback_later(
                self.dump_after, repeat=False, file=self.dump_file,
            )
        before = self._clock()
        wait(self.interval)
        late = self._clock() - before - self.interval
        if late >= self.threshold:
            self._report(late)
        return late

    def _report(self, late: float) -> None:
        dumped = self.dump_file is not None and late >= self.dump_after
        logger.warning(
            "⚠️  The app was unresponsive for %.0f seconds "
            "(no Python thread could run, or the computer was asleep)%s",
            late,
            f"; thread stacks written to {self.dump_file.name}" if dumped and self.dump_file else "",
        )
        if dumped and self.dump_file is not None:
            # faulthandler's dump has no timestamp, so note when it ended
            self.dump_file.write(
                f"--- stall of {late:.0f}s ended at "
                f"{datetime.now().isoformat(sep=' ', timespec='seconds')} ---\n\n",
            )
            self.dump_file.flush()


def log_environment() -> None:
    """Log the versions that matter when diagnosing a user's report."""
    versions = []
    for dist in ("mergemail365", "pywebview", "pythonnet", "msal", "requests"):
        try:
            versions.append(f"{dist} {importlib.metadata.version(dist)}")
        except importlib.metadata.PackageNotFoundError:
            pass
    logger.info(
        "Python %s on %s; %s; frozen=%s",
        platform.python_version(),
        platform.platform(),
        ", ".join(versions),
        getattr(sys, "frozen", False),
    )


def start_diagnostics(dump_dir: Path) -> StallWatchdog:
    """Log the environment and start a stall watchdog dumping into ``dump_dir``."""
    log_environment()
    dump_file: TextIO | None
    try:
        dump_file = open(dump_dir / STALL_DUMP_FILENAME, "a", encoding="utf-8")  # noqa: SIM115
    except OSError:
        logger.debug("Could not open stall dump file", exc_info=True)
        dump_file = None
    watchdog = StallWatchdog(dump_file)
    watchdog.start()
    return watchdog
