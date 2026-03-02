"""Load persistent configuration from ~/.mail-merge.toml."""

import logging
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path.home() / ".mail-merge.toml"


def load_config(path: Path | None = None) -> dict:
    """Read TOML config and return {"client_id": ..., "tenant_id": ...}.

    Keys that are absent in the file are omitted from the result.
    Returns an empty dict if the file does not exist or is malformed.
    """
    if path is None:
        path = DEFAULT_PATH

    if not path.is_file():
        return {}

    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except Exception as exc:
        logger.warning("Could not parse config file %s: %s", path, exc)
        return {}

    result = {}
    if "client-id" in raw:
        result["client_id"] = str(raw["client-id"])
    if "tenant-id" in raw:
        result["tenant_id"] = str(raw["tenant-id"])
    return result
