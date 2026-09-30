"""Tests for mail_merge.auth — cache loading/saving and JWT parsing."""
import sys
from unittest.mock import MagicMock, create_autospec, patch

import msal
import pytest

import mail_merge.auth as auth_module
from mail_merge.auth import _load_cache, _save_cache


# Captured at import, before any test patches msal.PublicClientApplication.
_RealPublicClientApplication = msal.PublicClientApplication


def _mock_msal_app():
    """An MSAL app mock whose methods enforce the real msal signatures."""
    return create_autospec(_RealPublicClientApplication, instance=True)


class TestLoadCache:
    def test_missing_file_returns_empty_cache(self, tmp_path, monkeypatch):
        """When the cache file doesn't exist, an empty cache is returned."""
        monkeypatch.setattr(auth_module, "CACHE_PATH", tmp_path / "nonexistent.json")
        cache = _load_cache()
        assert isinstance(cache, msal.SerializableTokenCache)
        # An empty cache has no state change pending
        assert not cache.has_state_changed

    def test_existing_file_is_deserialized(self, tmp_path, monkeypatch):
        """When the cache file exists, its contents are loaded into the cache."""
        # Write a minimal valid serialized cache (empty but structurally valid)
        cache_path = tmp_path / "token-cache.json"
        empty_cache = msal.SerializableTokenCache()
        cache_path.write_text(empty_cache.serialize(), encoding="utf-8")

        monkeypatch.setattr(auth_module, "CACHE_PATH", cache_path)
        cache = _load_cache()
        assert isinstance(cache, msal.SerializableTokenCache)

    def test_cache_path_is_read_when_present(self, tmp_path, monkeypatch):
        """The cache file is read when it exists (vs. skipped when absent)."""
        cache_path = tmp_path / "cache.json"
        cache_path.write_text('{"AccessToken": {}}', encoding="utf-8")

        monkeypatch.setattr(auth_module, "CACHE_PATH", cache_path)

        # Patch deserialize so we can confirm it was called
        deserialized_values: list[str] = []
        original_deserialize = msal.SerializableTokenCache.deserialize

        def capturing_deserialize(self, state):
            deserialized_values.append(state)
            # Don't call original — the JSON above isn't a full valid cache,
            # we just want to verify the call was made
            return None

        with patch.object(msal.SerializableTokenCache, "deserialize", capturing_deserialize):
            _load_cache()

        assert len(deserialized_values) == 1
        assert '"AccessToken"' in deserialized_values[0]


class TestSaveCache:
    def test_writes_file_when_state_has_changed(self, tmp_path, monkeypatch):
        """_save_cache writes the serialized cache to CACHE_PATH when state has changed."""
        cache_path = tmp_path / "cache.json"
        monkeypatch.setattr(auth_module, "CACHE_PATH", cache_path)

        mock_cache = MagicMock(spec=msal.SerializableTokenCache)
        mock_cache.has_state_changed = True
        mock_cache.serialize.return_value = '{"AccessToken": {}}'

        _save_cache(mock_cache)

        assert cache_path.exists()
        assert cache_path.read_text(encoding="utf-8") == '{"AccessToken": {}}'

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix permissions test")
    def test_sets_unix_permissions_to_600(self, tmp_path, monkeypatch):
        """On non-Windows, the cache file is chmod'd to 0o600."""
        cache_path = tmp_path / "cache.json"
        monkeypatch.setattr(auth_module, "CACHE_PATH", cache_path)

        mock_cache = MagicMock(spec=msal.SerializableTokenCache)
        mock_cache.has_state_changed = True
        mock_cache.serialize.return_value = "{}"

        _save_cache(mock_cache)

        mode = cache_path.stat().st_mode & 0o777
        assert mode == 0o600

    def test_no_op_when_state_unchanged(self, tmp_path, monkeypatch):
        """_save_cache does nothing when the cache state hasn't changed."""
        cache_path = tmp_path / "cache.json"
        monkeypatch.setattr(auth_module, "CACHE_PATH", cache_path)

        mock_cache = MagicMock(spec=msal.SerializableTokenCache)
        mock_cache.has_state_changed = False

        _save_cache(mock_cache)

        assert not cache_path.exists()
        mock_cache.serialize.assert_not_called()

    def test_creates_parent_directories(self, tmp_path, monkeypatch):
        """_save_cache creates intermediate directories if they don't exist."""
        cache_path = tmp_path / "nested" / "dir" / "cache.json"
        monkeypatch.setattr(auth_module, "CACHE_PATH", cache_path)

        mock_cache = MagicMock(spec=msal.SerializableTokenCache)
        mock_cache.has_state_changed = True
        mock_cache.serialize.return_value = "{}"

        _save_cache(mock_cache)

        assert cache_path.exists()


class TestTenantIdValidation:
    def test_path_traversal_rejected(self):
        """tenant_id containing path traversal characters raises ValueError."""
        from mail_merge.auth import acquire_token
        with pytest.raises(ValueError, match="Invalid tenant_id"):
            acquire_token("fake-client", tenant_id="common/../../evil.com")

    def test_newline_injection_rejected(self):
        """tenant_id containing a newline raises ValueError."""
        from mail_merge.auth import acquire_token
        with pytest.raises(ValueError, match="Invalid tenant_id"):
            acquire_token("fake-client", tenant_id="common\nevil")

    def test_common_accepted(self):
        """'common' is a valid tenant_id and passes validation."""
        from unittest.mock import patch
        mock_app = _mock_msal_app()
        mock_app.get_accounts.return_value = []
        mock_app.initiate_device_flow.return_value = {"user_code": "ABC", "message": "go here"}
        mock_app.acquire_token_by_device_flow.return_value = {"access_token": "tok"}
        with patch("msal.PublicClientApplication", autospec=True, return_value=mock_app), \
             patch.object(auth_module, "_load_cache", return_value=MagicMock(has_state_changed=False)):
            from mail_merge.auth import acquire_token
            token = acquire_token("fake-client", tenant_id="common")
        assert token == "tok"

    def test_uuid_accepted(self):
        """A valid UUID tenant_id passes validation."""
        from unittest.mock import patch
        mock_app = _mock_msal_app()
        mock_app.get_accounts.return_value = []
        mock_app.initiate_device_flow.return_value = {"user_code": "ABC", "message": "go here"}
        mock_app.acquire_token_by_device_flow.return_value = {"access_token": "tok"}
        with patch("msal.PublicClientApplication", autospec=True, return_value=mock_app), \
             patch.object(auth_module, "_load_cache", return_value=MagicMock(has_state_changed=False)):
            from mail_merge.auth import acquire_token
            token = acquire_token("fake-client", tenant_id="12345678-1234-1234-1234-123456789abc")
        assert token == "tok"

    def test_domain_accepted(self):
        """A domain name tenant_id passes validation."""
        from unittest.mock import patch
        mock_app = _mock_msal_app()
        mock_app.get_accounts.return_value = []
        mock_app.initiate_device_flow.return_value = {"user_code": "ABC", "message": "go here"}
        mock_app.acquire_token_by_device_flow.return_value = {"access_token": "tok"}
        with patch("msal.PublicClientApplication", autospec=True, return_value=mock_app), \
             patch.object(auth_module, "_load_cache", return_value=MagicMock(has_state_changed=False)):
            from mail_merge.auth import acquire_token
            token = acquire_token("fake-client", tenant_id="contoso.onmicrosoft.com")
        assert token == "tok"


class TestAcquireTokenEdgeCases:
    """Test uncovered paths in acquire_token."""

    def test_silent_acquisition_from_cache(self):
        """When a cached account exists, silent acquisition is tried first."""
        mock_app = _mock_msal_app()
        mock_app.get_accounts.return_value = [{"username": "user@example.com"}]
        mock_app.acquire_token_silent.return_value = {"access_token": "cached-tok"}

        with patch("msal.PublicClientApplication", autospec=True, return_value=mock_app), \
             patch.object(auth_module, "_load_cache", return_value=MagicMock(has_state_changed=False)):
            from mail_merge.auth import acquire_token
            token = acquire_token("fake-client")

        assert token == "cached-tok"
        mock_app.acquire_token_silent.assert_called_once()
        mock_app.initiate_device_flow.assert_not_called()

    def test_device_code_flow_failure(self):
        """When device code flow returns no user_code, RuntimeError is raised."""
        mock_app = _mock_msal_app()
        mock_app.get_accounts.return_value = []
        mock_app.initiate_device_flow.return_value = {"error": "something went wrong"}

        with patch("msal.PublicClientApplication", autospec=True, return_value=mock_app), \
             patch.object(auth_module, "_load_cache", return_value=MagicMock(has_state_changed=False)):
            from mail_merge.auth import acquire_token
            with pytest.raises(RuntimeError, match="Device code flow failed"):
                acquire_token("fake-client")

    def test_missing_access_token(self):
        """When token result has no access_token, RuntimeError is raised."""
        mock_app = _mock_msal_app()
        mock_app.get_accounts.return_value = []
        mock_app.initiate_device_flow.return_value = {"user_code": "ABC", "message": "go here"}
        mock_app.acquire_token_by_device_flow.return_value = {
            "error": "auth_failed",
            "error_description": "User cancelled",
        }

        with patch("msal.PublicClientApplication", autospec=True, return_value=mock_app), \
             patch.object(auth_module, "_load_cache", return_value=MagicMock(has_state_changed=False)):
            from mail_merge.auth import acquire_token
            with pytest.raises(RuntimeError, match="Authentication failed"):
                acquire_token("fake-client")


class TestDiagnoseAuthEdgeCases:
    """Test uncovered paths in diagnose_auth."""

    def test_authority_unreachable(self):
        """When authority check raises an exception, authority_reachable is False."""
        from mail_merge.auth import diagnose_auth

        with patch("requests.get", side_effect=ConnectionError("network down")), \
             patch.object(auth_module, "_build_msal_app", side_effect=ConnectionError("network down")):
            info = diagnose_auth("fake-client", "common")

        assert info["authority_reachable"] is False

    def test_msal_app_build_failure(self):
        """When MSAL app operations raise, client_id_valid is False."""
        from mail_merge.auth import diagnose_auth

        with patch("requests.get") as mock_get, \
             patch("msal.PublicClientApplication", autospec=True, side_effect=Exception("bad client")), \
             patch.object(auth_module, "_load_cache", return_value=MagicMock()):
            mock_get.return_value = MagicMock(status_code=200)
            info = diagnose_auth("bad-client", "common")

        assert info["client_id_valid"] is False
        assert "bad client" in info["error"]


class TestAcquireTokenInteractiveFlow:
    """Tests for acquire_token_interactive_flow."""

    def test_silent_acquisition_from_cache(self):
        """When a cached account exists, silent acquisition is tried first."""
        mock_app = _mock_msal_app()
        mock_app.get_accounts.return_value = [{"username": "user@example.com"}]
        mock_app.acquire_token_silent.return_value = {"access_token": "cached-tok"}

        with patch("msal.PublicClientApplication", autospec=True, return_value=mock_app), \
             patch.object(auth_module, "_load_cache", return_value=MagicMock(has_state_changed=False)):
            from mail_merge.auth import acquire_token_interactive_flow
            token = acquire_token_interactive_flow("fake-client")

        assert token == "cached-tok"
        mock_app.acquire_token_silent.assert_called_once()
        mock_app.acquire_token_interactive.assert_not_called()

    def test_interactive_flow_success(self):
        """When no cached account, interactive flow is used."""
        mock_app = _mock_msal_app()
        mock_app.get_accounts.return_value = []
        mock_app.acquire_token_interactive.return_value = {"access_token": "interactive-tok"}

        with patch("msal.PublicClientApplication", autospec=True, return_value=mock_app), \
             patch.object(auth_module, "_load_cache", return_value=MagicMock(has_state_changed=False)):
            from mail_merge.auth import acquire_token_interactive_flow
            token = acquire_token_interactive_flow("fake-client")

        assert token == "interactive-tok"
        mock_app.acquire_token_interactive.assert_called_once()

    def test_interactive_flow_failure_raises(self):
        """When interactive flow returns an error, RuntimeError is raised."""
        mock_app = _mock_msal_app()
        mock_app.get_accounts.return_value = []
        mock_app.acquire_token_interactive.return_value = {
            "error": "auth_failed",
            "error_description": "User cancelled",
        }

        with patch("msal.PublicClientApplication", autospec=True, return_value=mock_app), \
             patch.object(auth_module, "_load_cache", return_value=MagicMock(has_state_changed=False)):
            from mail_merge.auth import acquire_token_interactive_flow
            with pytest.raises(RuntimeError, match="Authentication failed"):
                acquire_token_interactive_flow("fake-client")

    def test_timeout_passed_through(self):
        """The timeout parameter is forwarded to acquire_token_interactive."""
        mock_app = _mock_msal_app()
        mock_app.get_accounts.return_value = []
        mock_app.acquire_token_interactive.return_value = {"access_token": "tok"}

        with patch("msal.PublicClientApplication", autospec=True, return_value=mock_app), \
             patch.object(auth_module, "_load_cache", return_value=MagicMock(has_state_changed=False)):
            from mail_merge.auth import acquire_token_interactive_flow
            acquire_token_interactive_flow("fake-client", timeout=60)

        call_kwargs = mock_app.acquire_token_interactive.call_args
        assert call_kwargs.kwargs.get("timeout") == 60

    def test_timeout_none_omits_kwarg(self):
        """When timeout=None, the timeout kwarg is not passed to MSAL."""
        mock_app = _mock_msal_app()
        mock_app.get_accounts.return_value = []
        mock_app.acquire_token_interactive.return_value = {"access_token": "tok"}

        with patch("msal.PublicClientApplication", autospec=True, return_value=mock_app), \
             patch.object(auth_module, "_load_cache", return_value=MagicMock(has_state_changed=False)):
            from mail_merge.auth import acquire_token_interactive_flow
            acquire_token_interactive_flow("fake-client", timeout=None)

        call_kwargs = mock_app.acquire_token_interactive.call_args
        assert "timeout" not in call_kwargs.kwargs

    def test_cache_saved_after_success(self, tmp_path, monkeypatch):
        """Cache is saved after successful interactive flow."""
        cache_path = tmp_path / "cache.json"
        monkeypatch.setattr(auth_module, "CACHE_PATH", cache_path)

        mock_app = _mock_msal_app()
        mock_app.get_accounts.return_value = []
        mock_app.acquire_token_interactive.return_value = {"access_token": "tok"}

        mock_cache = MagicMock()
        mock_cache.has_state_changed = True
        mock_cache.serialize.return_value = '{"tokens": "here"}'

        with patch("msal.PublicClientApplication", autospec=True, return_value=mock_app), \
             patch.object(auth_module, "_load_cache", return_value=mock_cache):
            from mail_merge.auth import acquire_token_interactive_flow
            acquire_token_interactive_flow("fake-client")

        assert cache_path.exists()
