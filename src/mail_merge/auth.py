import base64
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import msal

from mail_merge._paths import data_dir

logger = logging.getLogger(__name__)

SCOPES = ["Mail.Send"]
AUTHORITY_BASE = "https://login.microsoftonline.com"

# Allowlist for tenant_id: UUIDs, "common", "organizations", "consumers",
# and domain names (e.g. "contoso.com"). Rejects path-traversal sequences.
_TENANT_ID_RE = re.compile(r'^[a-zA-Z0-9._-]+$')

if sys.platform == "win32":
    CACHE_PATH = data_dir() / "token-cache.json"
else:
    CACHE_PATH = Path.home() / ".mail-merge-token-cache.json"


def _load_cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if CACHE_PATH.exists():
        cache.deserialize(CACHE_PATH.read_text(encoding="utf-8"))
    return cache


def _save_cache(cache: msal.SerializableTokenCache) -> None:
    if cache.has_state_changed:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        if sys.platform != "win32":
            CACHE_PATH.parent.chmod(0o700)
        CACHE_PATH.write_text(cache.serialize(), encoding="utf-8")
        if sys.platform != "win32":
            CACHE_PATH.chmod(0o600)


def _extract_msal_error(result: dict[str, Any]) -> str:
    """Extract a human-readable error message from an MSAL result dict."""
    return str(result.get("error_description", result.get("error", "Unknown error")))


def _build_msal_app(
    client_id: str, tenant_id: str,
) -> tuple[msal.PublicClientApplication, msal.SerializableTokenCache]:
    """Validate tenant_id, load cache, and build an MSAL app."""
    if not _TENANT_ID_RE.match(tenant_id):
        raise ValueError(
            f"Invalid tenant_id {tenant_id!r}: must be a UUID, 'common', "
            f"'organizations', 'consumers', or a domain name"
        )
    cache = _load_cache()
    app = msal.PublicClientApplication(
        client_id,
        authority=f"{AUTHORITY_BASE}/{tenant_id}",
        token_cache=cache,
    )
    return app, cache


def acquire_token_interactive_flow(
    client_id: str,
    tenant_id: str = "common",
    timeout: int | None = 120,
) -> str:
    """Acquire an access token via MSAL interactive browser flow.

    Opens the system browser for Microsoft login; a temporary local HTTP server
    catches the callback.  Tries silent acquisition first (cached refresh token),
    then falls back to the interactive prompt.

    Returns the access token string.
    """
    app, cache = _build_msal_app(client_id, tenant_id)

    accounts: list[dict[str, Any]] = app.get_accounts()
    result: dict[str, Any] | None = None

    if accounts:
        logger.info("🔑 Found cached account, attempting silent token acquisition")
        result = app.acquire_token_silent(SCOPES, account=accounts[0])

    if not result:
        logger.info("🔑 Opening system browser for authentication")
        kwargs: dict[str, Any] = {"scopes": SCOPES, "port": None}
        if timeout is not None:
            kwargs["timeout"] = timeout
        result = app.acquire_token_interactive(**kwargs)

    _save_cache(cache)

    if "access_token" not in result:
        raise RuntimeError(f"Authentication failed: {_extract_msal_error(result)}")

    token: str = result["access_token"]
    return token


def acquire_token(client_id: str, tenant_id: str = "common") -> str:
    """Acquire an access token via MSAL device code flow.

    Tries silent acquisition first (cached refresh token), then falls back
    to device code flow.

    Returns the access token string.
    """
    app, cache = _build_msal_app(client_id, tenant_id)

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
        raise RuntimeError(f"Authentication failed: {_extract_msal_error(result)}")

    token: str = result["access_token"]
    return token


def initiate_auth_code_flow(
    client_id: str,
    tenant_id: str = "common",
    redirect_uri: str = "http://localhost:5050/auth/callback",
) -> dict[str, Any]:
    """Start an authorization code flow. Returns the flow dict to store in the session."""
    app, _cache = _build_msal_app(client_id, tenant_id)
    flow: dict[str, Any] = app.initiate_auth_code_flow(
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )
    if "auth_uri" not in flow:
        raise RuntimeError(
            f"Failed to initiate auth code flow: {json.dumps(flow, indent=2)}"
        )
    return flow


def acquire_token_by_auth_code(
    client_id: str,
    tenant_id: str = "common",
    auth_code_flow: dict[str, Any] | None = None,
    auth_response: dict[str, str] | None = None,
) -> str:
    """Complete the authorization code flow. Returns the access token."""
    app, cache = _build_msal_app(client_id, tenant_id)
    result: dict[str, Any] = app.acquire_token_by_auth_code_flow(
        auth_code_flow or {}, auth_response or {},
    )
    _save_cache(cache)

    if "access_token" not in result:
        raise RuntimeError(f"Auth code exchange failed: {_extract_msal_error(result)}")

    token: str = result["access_token"]
    return token


def diagnose_auth(client_id: str, tenant_id: str = "common") -> dict[str, Any]:
    """Test Entra auth config and return diagnostic info."""
    info: dict[str, Any] = {
        "cache_exists": CACHE_PATH.exists(),
        "cache_path": str(CACHE_PATH),
        "accounts": [],
        "token_valid": False,
        "token_expires_at": None,
        "authority_reachable": False,
        "client_id_valid": True,
        "error": None,
    }

    if not _TENANT_ID_RE.match(tenant_id):
        info["error"] = f"Invalid tenant_id: {tenant_id!r}"
        return info

    authority = f"{AUTHORITY_BASE}/{tenant_id}"

    # Check authority reachability
    try:
        import requests as _requests
        resp = _requests.get(
            f"{authority}/v2.0/.well-known/openid-configuration",
            timeout=3,
        )
        info["authority_reachable"] = resp.status_code == 200
    except Exception:
        info["authority_reachable"] = False

    # Check cached accounts and token
    try:
        app, _cache = _build_msal_app(client_id, tenant_id)
        accounts: list[dict[str, Any]] = app.get_accounts()
        info["accounts"] = [
            {"username": a.get("username", ""), "home_account_id": a.get("home_account_id", "")}
            for a in accounts
        ]
        if accounts:
            result = app.acquire_token_silent(SCOPES, account=accounts[0])
            if result and "access_token" in result:
                info["token_valid"] = True
                expires = token_expires_at(result["access_token"])
                if expires:
                    info["token_expires_at"] = expires.isoformat()
    except Exception as exc:
        info["client_id_valid"] = False
        info["error"] = str(exc)

    return info


def token_expires_at(token: str) -> datetime | None:
    """Decode JWT exp claim without signature verification.

    Returns a timezone-aware UTC datetime, or None if the token
    cannot be parsed.
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        # base64url decode the payload (segment 1)
        payload_b64 = parts[1]
        # Add padding if needed
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        claims = json.loads(payload_bytes)
        exp = claims.get("exp")
        if exp is None:
            return None
        return datetime.fromtimestamp(int(exp), tz=timezone.utc)
    except Exception:
        return None
