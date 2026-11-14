"""Shared rich console and logging configuration."""

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
        except Exception:  # noqa: S110 - logging isn't set up yet; fall back below
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


# Credentials that must not reach a log file or the browser's log panel.
# The code avoids logging them in the first place; this catches what slips
# through, including in a dependency's messages and in tracebacks.
_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [redacted]"),
    # JSON Web Tokens: Entra access and ID tokens.
    (re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*"), "[redacted token]"),
    # Query parameters: the startup token (/?token=) and the OAuth
    # redirect's (/auth/callback?code=...), as werkzeug's access log has them.
    (re.compile(r"(?i)([?&](?:token|code|client_info|session_state|state)=)[^&\s\"']+"), r"\1[redacted]"),
)


def redact(text: str) -> str:
    """Replace credentials in a log line with a placeholder."""
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFormatter(logging.Formatter):
    """A Formatter whose output has credentials removed (see redact()).

    A formatter rather than a filter: a filter would have to rewrite the
    record, which other handlers share (the console must still print the
    access URL with its token), and would miss tracebacks.
    """

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


class _NotConsoleOnly(logging.Filter):
    """Keeps records marked console-only (message content) out of a handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not getattr(record, "console_only", False)


class _NoMsalDebug(logging.Filter):
    """Drops msal's DEBUG records: its token-request dumps include the
    OAuth authorisation code and the PKCE verifier (it masks the tokens in
    the response, but not those). msal's INFO and above are kept."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.INFO or not record.name.startswith("msal")


def setup_logging(level: int) -> None:
    """Configure root logging with a RichHandler on stderr."""
    handler = RichHandler(console=console, show_path=False, markup=False)
    handler.setLevel(level)

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
        handler.setFormatter(RedactingFormatter(
            "%(asctime)s %(levelname)-8s [%(threadName)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        handler.addFilter(_StripAnsiFilter())
        handler.addFilter(_NotConsoleOnly())
        handler.addFilter(_NoMsalDebug())

        root = logging.getLogger()
        root.addHandler(handler)
        # Lower the root logger level so DEBUG messages reach the file
        # handler even when the console handler is set to INFO or above.
        if root.level > level:
            root.setLevel(level)

        return log_file
    except OSError:
        return None


def maybe_enable_file_logging(log_file_flag: bool) -> bool:
    """Enable file logging if explicitly requested or running as a PyInstaller bundle.

    Returns ``True`` if running as a PyInstaller bundle (caller may need this
    for desktop-mode decisions).
    """
    is_bundled = getattr(sys, "frozen", False)
    if is_bundled or log_file_flag:
        log_file = setup_file_logging()
        if log_file:
            logging.getLogger(__name__).info("Log file: %s", log_file)
    return is_bundled
