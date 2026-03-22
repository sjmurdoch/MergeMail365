"""Tests for new auth functions: initiate_auth_code_flow, acquire_token_by_auth_code, diagnose_auth, sign_out."""

from unittest.mock import MagicMock, patch

import pytest

from mail_merge.auth import (
    acquire_token_by_auth_code,
    diagnose_auth,
    initiate_auth_code_flow,
    sign_out,
)


class TestInitiateAuthCodeFlow:
    @patch("mail_merge.auth.msal.PublicClientApplication")
    @patch("mail_merge.auth._load_cache")
    def test_returns_flow_with_auth_uri(self, mock_cache, mock_app_cls):
        mock_cache.return_value = MagicMock()
        mock_app = MagicMock()
        mock_app.initiate_auth_code_flow.return_value = {
            "auth_uri": "https://login.microsoftonline.com/...",
            "state": "abc123",
        }
        mock_app_cls.return_value = mock_app

        flow = initiate_auth_code_flow("test-client-id", "common")
        assert "auth_uri" in flow
        mock_app.initiate_auth_code_flow.assert_called_once()

    @patch("mail_merge.auth.msal.PublicClientApplication")
    @patch("mail_merge.auth._load_cache")
    def test_raises_on_failure(self, mock_cache, mock_app_cls):
        mock_cache.return_value = MagicMock()
        mock_app = MagicMock()
        mock_app.initiate_auth_code_flow.return_value = {"error": "bad"}
        mock_app_cls.return_value = mock_app

        with pytest.raises(RuntimeError, match="Failed to initiate"):
            initiate_auth_code_flow("test-client-id")

    def test_invalid_tenant_id(self):
        with pytest.raises(ValueError, match="Invalid tenant_id"):
            initiate_auth_code_flow("test-client-id", "../evil")


class TestAcquireTokenByAuthCode:
    @patch("mail_merge.auth._save_cache")
    @patch("mail_merge.auth.msal.PublicClientApplication")
    @patch("mail_merge.auth._load_cache")
    def test_returns_token(self, mock_cache, mock_app_cls, mock_save):
        mock_cache.return_value = MagicMock()
        mock_app = MagicMock()
        mock_app.acquire_token_by_auth_code_flow.return_value = {
            "access_token": "test-token-123",
        }
        mock_app_cls.return_value = mock_app

        token = acquire_token_by_auth_code(
            "test-client-id",
            auth_code_flow={"state": "abc"},
            auth_response={"code": "xyz"},
        )
        assert token == "test-token-123"
        mock_save.assert_called_once()

    @patch("mail_merge.auth._save_cache")
    @patch("mail_merge.auth.msal.PublicClientApplication")
    @patch("mail_merge.auth._load_cache")
    def test_raises_on_error(self, mock_cache, mock_app_cls, mock_save):
        mock_cache.return_value = MagicMock()
        mock_app = MagicMock()
        mock_app.acquire_token_by_auth_code_flow.return_value = {
            "error": "invalid_grant",
            "error_description": "Code expired",
        }
        mock_app_cls.return_value = mock_app

        with pytest.raises(RuntimeError, match="Code expired"):
            acquire_token_by_auth_code(
                "test-client-id",
                auth_code_flow={"state": "abc"},
                auth_response={"code": "xyz"},
            )


class TestDiagnoseAuth:
    @patch("mail_merge.auth._load_cache")
    def test_no_cache(self, mock_cache, tmp_path):
        mock_cache.return_value = MagicMock()

        with patch("mail_merge.auth.CACHE_PATH", tmp_path / "nonexistent.json"):
            info = diagnose_auth("test-client-id")

        assert info["cache_exists"] is False
        assert "cache_path" in info

    def test_invalid_tenant_id(self):
        info = diagnose_auth("test-client-id", "../evil")
        assert info["error"] is not None
        assert "Invalid tenant_id" in info["error"]

    @patch("mail_merge.auth.msal.PublicClientApplication")
    @patch("mail_merge.auth._load_cache")
    def test_with_valid_token(self, mock_cache, mock_app_cls):
        mock_cache.return_value = MagicMock()
        mock_app = MagicMock()
        mock_app.get_accounts.return_value = [{"username": "user@example.com", "home_account_id": "123"}]
        mock_app.acquire_token_silent.return_value = {"access_token": "eyJ.eyJleHAiOjE3MDAwMDAwMDB9.sig"}
        mock_app_cls.return_value = mock_app

        with patch("mail_merge.auth.CACHE_PATH") as mock_path:
            mock_path.exists.return_value = True
            mock_path.__str__ = lambda self: "/fake/path"
            with patch("requests.get") as mock_get:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_get.return_value = mock_resp

                info = diagnose_auth("test-client-id")

        assert info["token_valid"] is True
        assert len(info["accounts"]) == 1
        assert info["authority_reachable"] is True

    @patch("mail_merge.auth.msal.PublicClientApplication")
    @patch("mail_merge.auth._load_cache")
    def test_expired_token(self, mock_cache, mock_app_cls):
        """Silent acquisition fails for expired tokens — token_valid should be False."""
        mock_cache.return_value = MagicMock()
        mock_app = MagicMock()
        mock_app.get_accounts.return_value = [{"username": "user@example.com", "home_account_id": "123"}]
        # Silent acquisition returns error (expired refresh token)
        mock_app.acquire_token_silent.return_value = {
            "error": "interaction_required",
            "error_description": "Token expired",
        }
        mock_app_cls.return_value = mock_app

        with patch("mail_merge.auth.CACHE_PATH") as mock_path:
            mock_path.exists.return_value = True
            mock_path.__str__ = lambda self: "/fake/path"
            with patch("requests.get") as mock_get:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_get.return_value = mock_resp

                info = diagnose_auth("test-client-id")

        assert info["token_valid"] is False
        assert len(info["accounts"]) == 1
        assert info["authority_reachable"] is True


class TestSignOut:
    @patch("mail_merge.auth._save_cache")
    @patch("mail_merge.auth.msal.PublicClientApplication")
    @patch("mail_merge.auth._load_cache")
    def test_removes_accounts(self, mock_cache, mock_app_cls, mock_save):
        mock_cache.return_value = MagicMock()
        mock_app = MagicMock()
        account1 = {"username": "user@example.com"}
        mock_app.get_accounts.return_value = [account1]
        mock_app_cls.return_value = mock_app

        result = sign_out("test-client-id", "common")

        assert result is True
        mock_app.remove_account.assert_called_once_with(account1)
        mock_save.assert_called_once()

    @patch("mail_merge.auth._save_cache")
    @patch("mail_merge.auth.msal.PublicClientApplication")
    @patch("mail_merge.auth._load_cache")
    def test_returns_false_when_no_accounts(self, mock_cache, mock_app_cls, mock_save):
        mock_cache.return_value = MagicMock()
        mock_app = MagicMock()
        mock_app.get_accounts.return_value = []
        mock_app_cls.return_value = mock_app

        result = sign_out("test-client-id", "common")

        assert result is False
        mock_app.remove_account.assert_not_called()
