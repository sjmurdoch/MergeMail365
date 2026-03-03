import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import msal

logger = logging.getLogger(__name__)

SCOPES = ["Mail.Send"]
AUTHORITY_BASE = "https://login.microsoftonline.com"
CACHE_PATH = Path.home() / ".mail-merge-token-cache.json"


def _load_cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if CACHE_PATH.exists():
        cache.deserialize(CACHE_PATH.read_text())
    return cache


def _save_cache(cache: msal.SerializableTokenCache) -> None:
    if cache.has_state_changed:
        CACHE_PATH.write_text(cache.serialize())
        CACHE_PATH.chmod(0o600)


def acquire_token(client_id: str, tenant_id: str = "common") -> str:
    """Acquire an access token via MSAL device code flow.

    Tries silent acquisition first (cached refresh token), then falls back
    to device code flow.

    Returns the access token string.
    """
    authority = f"{AUTHORITY_BASE}/{tenant_id}"
    cache = _load_cache()
    app = msal.PublicClientApplication(
        client_id,
        authority=authority,
        token_cache=cache,
    )

    accounts: list[dict[str, Any]] = app.get_accounts()
    result: dict[str, Any] | None = None

    if accounts:
        logger.info("🔑 Found cached account, attempting silent token acquisition")
        result = app.acquire_token_silent(SCOPES, account=accounts[0])

    if not result:
        logger.info("🔑 Starting device code authentication flow")
        flow: dict[str, Any] = app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            raise RuntimeError(f"Device code flow failed: {json.dumps(flow, indent=2)}")

        print(flow["message"], file=sys.stderr)
        result = app.acquire_token_by_device_flow(flow)

    _save_cache(cache)

    if "access_token" not in result:
        error = result.get("error_description", result.get("error", "Unknown error"))
        raise RuntimeError(f"Authentication failed: {error}")

    token: str = result["access_token"]
    return token
