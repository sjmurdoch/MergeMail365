"""Shared rich console and logging configuration."""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler


def _ensure_utf8_stderr() -> None:
    """Reconfigure stderr to UTF-8 on Windows where cp1252 can't encode emoji in log messages."""
    encoding = getattr(sys.stderr, "encoding", "") or ""
    if encoding.lower().replace("-", "") == "utf8":
        return
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


_ensure_utf8_stderr()
console = Console(stderr=True, force_terminal=True)

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
        return log_file
    except OSError:
        return None
