"""Platform-aware paths for config and cache files."""

import os
import sys
from pathlib import Path


def data_dir() -> Path:
    """Return the platform-appropriate data directory for MergeMail365.

    Windows: %LOCALAPPDATA%/mergemail365  (falls back to ~/mergemail365)
    macOS/Linux: ~ (preserves existing dotfile behaviour)
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
        return base / "mergemail365"
    return Path.home()
