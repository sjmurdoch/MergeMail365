"""Shared rich console and logging configuration."""

from __future__ import annotations

import io
import logging
import re
import sys
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler


def _make_console() -> Console:
    """Create a Console that writes UTF-8 to stderr regardless of the Windows codepage."""
    # Wrap stderr's raw buffer in a UTF-8 TextIOWrapper so rich never hits cp1252.
    # Works with any rich version (no 'encoding' kwarg needed).
    buf = getattr(sys.stderr, "buffer", None)
    if buf is not None:
        try:
            utf8_stderr = io.TextIOWrapper(buf, encoding="utf-8", errors="replace")
            return Console(file=utf8_stderr, force_terminal=True)
        except Exception:
            pass
    # PyInstaller console=False sets stderr to None; use devnull to avoid cp1252 errors.
    if sys.stderr is None or not hasattr(sys.stderr, "write"):
        return Console(file=io.StringIO(), force_terminal=True)
    return Console(stderr=True, force_terminal=True)


console = _make_console()

# Regex to match ANSI escape sequences
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mK]")


class _StripAnsiFilter(logging.Filter):
    """Filter that strips ANSI escape sequences from log messages and arguments."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _ANSI_RE.sub("", record.msg)
        if record.args:
            new_args: list[object] = []
            for arg in record.args:
                if isinstance(arg, str):
                    new_args.append(_ANSI_RE.sub("", arg))
                else:
                    new_args.append(arg)
            record.args = tuple(new_args)
        return True


def setup_logging(level: int) -> None:
    """Configure root logging with a RichHandler on stderr."""
    handler = RichHandler(console=console, show_path=False, markup=False)

    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[handler],
    )


def setup_file_logging(level: int = logging.DEBUG) -> Path | None:
    """Add a rotating file handler to the root logger.

    Returns the log file path, or ``None`` if setup fails.
    """
    from logging.handlers import RotatingFileHandler

    from mail_merge._paths import log_dir

    try:
        log_path = log_dir()
        log_path.mkdir(parents=True, exist_ok=True)
        log_file = log_path / "mergemail365.log"

        handler = RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=3,
            encoding="utf-8",
        )
        handler.setLevel(level)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        handler.addFilter(_StripAnsiFilter())

        root = logging.getLogger()
        root.addHandler(handler)
        # Lower the root logger level so DEBUG messages reach the file
        # handler even when the console handler is set to INFO or above.
        if root.level > level:
            root.setLevel(level)

        try:
            _rich_ver = _pkg_version("rich")
        except Exception:
            _rich_ver = "unknown"
        logging.getLogger(__name__).debug("rich version: %s", _rich_ver)

        return log_file
    except OSError:
        return None
