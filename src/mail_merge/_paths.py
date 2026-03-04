"""Platform-aware paths for config and cache files."""

import os
import sys
from pathlib import Path


def data_dir() -> Path:
    """Return the platform-appropriate data directory for mail-merge.

    Windows: %LOCALAPPDATA%/mail-merge  (falls back to ~/mail-merge)
    macOS/Linux: ~ (preserves existing dotfile behaviour)
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
        return base / "mail-merge"
    return Path.home()
