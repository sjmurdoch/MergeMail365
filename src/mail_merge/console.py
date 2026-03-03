"""Shared rich console and logging configuration."""

import logging

from rich.console import Console
from rich.logging import RichHandler

console = Console(stderr=True)


def setup_logging(level: int) -> None:
    """Configure root logging with a RichHandler on stderr."""
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, show_path=False, markup=True)],
    )
