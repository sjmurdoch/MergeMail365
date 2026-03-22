"""Shared rich console and logging configuration."""

import logging
import re

from rich.console import Console
from rich.logging import RichHandler

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
