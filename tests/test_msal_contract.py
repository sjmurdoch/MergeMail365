"""Contract tests that run the real msal library against mocked Microsoft endpoints.

The other auth tests mock ``msal.PublicClientApplication`` entirely, so they
cannot notice changes in how msal talks to Entra ID, stores its token cache,
or shapes its result dicts.  These tests exercise real msal code end to end,
with only the HTTP layer replaced by ``responses``.
"""

import base64
import inspect
import json
import sys
import time
from urllib.parse import parse_qs, urlparse

import msal
import pytest
import responses

import mail_merge.auth as auth_module
from mail_merge.auth import (
    acquire_token,
    acquire_token_by_auth_code,
    acquire_token_interactive_flow,
    diagnose_auth,
    initiate_auth_code_flow,
    sign_out,
    token_expires_at,
)

CLIENT_ID = "11111111-2222-3333-4444-555555555555"
TENANT_ID = "contoso.onmicrosoft.com"
TENANT_GUID = "99999999-8888-7777-6666-555555555555"
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
ISSUER = f"https://login.microsoftonline.com/{TENANT_GUID}/v2.0"
TOKEN_ENDPOINT = f"{AUTHORITY}/oauth2/v2.0/token"
DEVICE_ENDPOINT = f"{AUTHORITY}/oauth2/v2.0/devicecode"
REDIRECT_URI = "http://localhost:5050/auth/callback"
USERNAME = "alice@contoso.onmicrosoft.com"


def _b64url(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def _jwt(claims: dict) -> str:
    """An unsigned JWT; msal does not verify id_token signatures."""
    return f"{_b64url({'alg': 'none', 'typ': 'JWT'})}.{_b64url(claims)}.sig"


def _token_response(nonce: str | None = None, expires_in: int = 3600) -> dict:
    now = int(time.time())
    id_claims = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "iat": now,
        "nbf": now,
        "exp": now + expires_in,
        "oid": "user-oid",
        "sub": "user-sub",
        "tid": TENANT_GUID,
        "preferred_username": USERNAME,
    }
    if nonce is not None:
        id_claims["nonce"] = nonce
    return {
        "token_type": "Bearer",
        "scope": "https://graph.microsoft.com/Mail.Send openid profile offline_access",
        "expires_in": expires_in,
        "ext_expires_in": expires_in,
        "access_token": _jwt({"aud": "https://graph.microsoft.com", "exp": now + expires_in}),
        "refresh_token": "fake-refresh-token",
        "id_token": _jwt(id_claims),
        "client_info": _b64url({"uid": "user-oid", "utid": TENANT_GUID}),
    }


@pytest.fixture
def entra(tmp_path, monkeypatch):
    """Mock the Entra ID endpoints msal needs, and isolate the token cache."""
    monkeypatch.setattr(auth_module, "CACHE_PATH", tmp_path / "token-cache.json")
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.get(
            f"{AUTHORITY}/v2.0/.well-known/openid-configuration",
            json={
                "authorization_endpoint": f"{AUTHORITY}/oauth2/v2.0/authorize",
                "token_endpoint": TOKEN_ENDPOINT,
                "device_authorization_endpoint": DEVICE_ENDPOINT,
                "issuer": ISSUER,
            },
        )
        # Used by msal when reading/writing cache entries to resolve host aliases
        rsps.get(
            "https://login.microsoftonline.com/common/discovery/instance",
            json={
                "tenant_discovery_endpoint": f"{AUTHORITY}/v2.0/.well-known/openid-configuration",
                "api-version": "1.1",
                "metadata": [{
                    "preferred_network": "login.microsoftonline.com",
                    "preferred_cache": "login.windows.net",
                    "aliases": [
                        "login.microsoftonline.com", "login.windows.net",
                        "login.microsoft.com", "sts.windows.net",
                    ],
                }],
            },
            match=[responses.matchers.query_param_matcher({}, strict_match=False)],
        )
        yield rsps


def _sign_in_via_auth_code(entra) -> str:
    """Run the web UI's auth code flow against the mocked endpoints."""
    flow = initiate_auth_code_flow(CLIENT_ID, TENANT_ID, redirect_uri=REDIRECT_URI)
    nonce = parse_qs(urlparse(flow["auth_uri"]).query).get("nonce", [None])[0]
    entra.post(TOKEN_ENDPOINT, json=_token_response(nonce=nonce))
    return acquire_token_by_auth_code(
        CLIENT_ID, TENANT_ID,
        auth_code_flow=flow,
        auth_response={"code": "fake-auth-code", "state": flow["state"]},
    )


class TestInteractiveSignature:
    def test_acquire_token_interactive_accepts_our_kwargs(self):
        """acquire_token_interactive takes **kwargs, so autospec cannot catch a
        renamed 'port' or 'timeout'; check the named parameters explicitly."""
        params = inspect.signature(msal.PublicClientApplication.acquire_token_interactive).parameters
        assert {"scopes", "port", "timeout"} <= params.keys()


class TestAuthCodeFlow:
    def test_initiate_builds_pkce_authorize_url(self, entra):
        flow = initiate_auth_code_flow(CLIENT_ID, TENANT_ID, redirect_uri=REDIRECT_URI)

        url = urlparse(flow["auth_uri"])
        query = parse_qs(url.query)
        assert f"{url.scheme}://{url.netloc}{url.path}" == f"{AUTHORITY}/oauth2/v2.0/authorize"
        assert query["client_id"] == [CLIENT_ID]
        assert query["redirect_uri"] == [REDIRECT_URI]
        assert query["response_type"] == ["code"]
        assert query["code_challenge_method"] == ["S256"]
        assert "code_challenge" in query
        assert "Mail.Send" in query["scope"][0]
        assert query["state"] == [flow["state"]]
        # The flow dict is stored in the Flask session, so it must be JSON-serialisable
        json.dumps(flow)

    def test_exchange_returns_token_and_writes_cache(self, entra):
        token = _sign_in_via_auth_code(entra)

        assert token_expires_at(token) is not None
        token_request = next(c.request for c in entra.calls if c.request.url == TOKEN_ENDPOINT)
        body = parse_qs(token_request.body)
        assert body["grant_type"] == ["authorization_code"]
        assert body["code"] == ["fake-auth-code"]
        assert "code_verifier" in body

        cache_file = auth_module.CACHE_PATH
        assert cache_file.exists()
        assert USERNAME in cache_file.read_text(encoding="utf-8")
        if sys.platform != "win32":
            assert cache_file.stat().st_mode & 0o777 == 0o600

    def test_state_mismatch_is_rejected(self, entra):
        flow = initiate_auth_code_flow(CLIENT_ID, TENANT_ID, redirect_uri=REDIRECT_URI)
        with pytest.raises((RuntimeError, ValueError)):
            acquire_token_by_auth_code(
                CLIENT_ID, TENANT_ID,
                auth_code_flow=flow,
                auth_response={"code": "fake-auth-code", "state": "wrong-state"},
            )

    def test_error_response_raises(self, entra):
        flow = initiate_auth_code_flow(CLIENT_ID, TENANT_ID, redirect_uri=REDIRECT_URI)
        entra.post(
            TOKEN_ENDPOINT,
            status=400,
            json={"error": "invalid_grant", "error_description": "AADSTS70000: code expired"},
        )
        with pytest.raises(RuntimeError, match="AADSTS70000"):
            acquire_token_by_auth_code(
                CLIENT_ID, TENANT_ID,
                auth_code_flow=flow,
                auth_response={"code": "fake-auth-code", "state": flow["state"]},
            )


class TestCachedToken:
    """After sign-in, a fresh msal app must find the account in the cache file."""

    def test_interactive_flow_uses_cached_token_silently(self, entra, monkeypatch):
        token = _sign_in_via_auth_code(entra)

        def no_browser(*args, **kwargs):
            raise AssertionError("interactive prompt should not be needed")

        monkeypatch.setattr(msal.PublicClientApplication, "acquire_token_interactive", no_browser)
        assert acquire_token_interactive_flow(CLIENT_ID, TENANT_ID) == token

    def test_device_code_uses_cached_token_silently(self, entra, monkeypatch):
        token = _sign_in_via_auth_code(entra)

        def no_device_flow(*args, **kwargs):
            raise AssertionError("device flow should not be needed")

        monkeypatch.setattr(msal.PublicClientApplication, "initiate_device_flow", no_device_flow)
        assert acquire_token(CLIENT_ID, TENANT_ID) == token

    def test_diagnose_reports_account_and_valid_token(self, entra):
        _sign_in_via_auth_code(entra)

        info = diagnose_auth(CLIENT_ID, TENANT_ID)

        assert info["error"] is None
        assert info["authority_reachable"] is True
        assert info["cache_exists"] is True
        assert [a["username"] for a in info["accounts"]] == [USERNAME]
        assert info["token_valid"] is True
        assert info["token_expires_at"] is not None

    def test_sign_out_removes_account(self, entra):
        _sign_in_via_auth_code(entra)

        assert sign_out(CLIENT_ID, TENANT_ID) is True
        assert diagnose_auth(CLIENT_ID, TENANT_ID)["accounts"] == []
        assert sign_out(CLIENT_ID, TENANT_ID) is False


class TestDeviceCodeFlow:
    def test_device_code_flow_returns_token(self, entra):
        entra.post(
            DEVICE_ENDPOINT,
            json={
                "device_code": "fake-device-code",
                "user_code": "ABCD-EFGH",
                "verification_uri": "https://microsoft.com/devicelogin",
                "expires_in": 900,
                "interval": 0,
                "message": "To sign in, enter ABCD-EFGH",
            },
        )
        entra.post(TOKEN_ENDPOINT, json=_token_response())

        token = acquire_token(CLIENT_ID, TENANT_ID)

        assert token_expires_at(token) is not None
        token_request = next(c.request for c in entra.calls if c.request.url == TOKEN_ENDPOINT)
        body = parse_qs(token_request.body)
        assert body["device_code"] == ["fake-device-code"]
        assert USERNAME in auth_module.CACHE_PATH.read_text(encoding="utf-8")
