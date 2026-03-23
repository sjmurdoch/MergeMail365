"""Platform-aware paths for config and cache files."""

import os
import sys
from pathlib import Path


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
