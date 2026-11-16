"""Platform-aware paths for config and cache files, and the helpers that
create the app's private files.

Everything that holds tokens, recipient addresses or logs is created
through private_dir(), write_private() or open_private_append(), so it is
readable by the user alone from the moment it exists, and the app never
changes a directory it doesn't own (tests/test_fs_footprint.py).
"""

import os
import sys
import tempfile
from pathlib import Path
from typing import TextIO

_WINDOWS = sys.platform == "win32"


def private_dir(path: Path) -> Path:
    """Create a directory of the app's own, for the user only (0700).

    Refuses the home directory and its ancestors: those belong to the user,
    and changing their mode breaks whatever else relies on it (file sharing,
    a web server's user directories). On Windows the per-user profile's
    ACLs already restrict access, so only the directory is created.
    """
    home = Path.home()
    resolved = path.expanduser().absolute()
    if resolved == home or resolved in home.parents:
        raise ValueError(f"{path} is not a directory of the app's own")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not _WINDOWS:
        path.chmod(0o700)
    return path


def write_private(path: Path, text: str) -> None:
    """Replace `path` with `text`, readable by the user only (0600).

    Written to a temporary file in the same directory and renamed into
    place, so the file is never world-readable, and a crash or a failed
    write leaves the previous contents intact rather than a truncated file.
    The directory is not created or changed: use private_dir() for one the
    app owns.
    """
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")  # 0600
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def open_private_append(path: Path, *, encoding: str = "utf-8", errors: str | None = None) -> TextIO:
    """Open `path` for appending, creating it for the user only (0600).

    A file left by an earlier version with wider permissions is restricted.
    """
    # An opener rather than os.fdopen(), so the stream keeps its file name.
    stream = open(  # noqa: SIM115 - the caller closes it
        path, "a", encoding=encoding, errors=errors,
        opener=lambda name, flags: os.open(name, flags, 0o600),
    )
    if not _WINDOWS:
        os.fchmod(stream.fileno(), 0o600)
    return stream


def log_dir() -> Path:
    """Return the platform-appropriate log directory for MergeMail365.

    macOS:   ~/Library/Logs/mergemail365/
    Windows: %LOCALAPPDATA%/mergemail365/logs/
    Linux:   ~/.local/state/mergemail365/log/
    """
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "mergemail365"
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
        return base / "mergemail365" / "logs"
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / "mergemail365" / "log"


def data_dir() -> Path:
    """Return the platform-appropriate data directory for MergeMail365.

    Windows: %LOCALAPPDATA%/mergemail365  (falls back to ~/mergemail365)
    macOS/Linux: ~ (preserves existing dotfile behaviour)
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
        return base / "mergemail365"
    return Path.home()


def state_dir() -> Path:
    """Return the platform-appropriate state directory for MergeMail365:
    files the app keeps between runs that are not config or logs.

    macOS:   ~/Library/Application Support/mergemail365/
    Windows: %LOCALAPPDATA%/mergemail365/
    Linux:   ~/.local/state/mergemail365/
    """
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "mergemail365"
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
        return base / "mergemail365"
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / "mergemail365"
