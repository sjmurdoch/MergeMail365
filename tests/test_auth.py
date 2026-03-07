"""Tests for mail_merge.auth — cache loading/saving and JWT parsing."""
import sys
from unittest.mock import MagicMock, patch

import pytest

import msal
import pytest

import mail_merge.auth as auth_module
from mail_merge.auth import _load_cache, _save_cache


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
        mock_app = MagicMock()
        mock_app.get_accounts.return_value = []
        mock_app.initiate_device_flow.return_value = {"user_code": "ABC", "message": "go here"}
        mock_app.acquire_token_by_device_flow.return_value = {"access_token": "tok"}
        with patch("msal.PublicClientApplication", return_value=mock_app), \
             patch.object(auth_module, "_load_cache", return_value=MagicMock(has_state_changed=False)):
            from mail_merge.auth import acquire_token
            token = acquire_token("fake-client", tenant_id="common")
        assert token == "tok"

    def test_uuid_accepted(self):
        """A valid UUID tenant_id passes validation."""
        from unittest.mock import patch
        mock_app = MagicMock()
        mock_app.get_accounts.return_value = []
        mock_app.initiate_device_flow.return_value = {"user_code": "ABC", "message": "go here"}
        mock_app.acquire_token_by_device_flow.return_value = {"access_token": "tok"}
        with patch("msal.PublicClientApplication", return_value=mock_app), \
             patch.object(auth_module, "_load_cache", return_value=MagicMock(has_state_changed=False)):
            from mail_merge.auth import acquire_token
            token = acquire_token("fake-client", tenant_id="12345678-1234-1234-1234-123456789abc")
        assert token == "tok"

    def test_domain_accepted(self):
        """A domain name tenant_id passes validation."""
        from unittest.mock import patch
        mock_app = MagicMock()
        mock_app.get_accounts.return_value = []
        mock_app.initiate_device_flow.return_value = {"user_code": "ABC", "message": "go here"}
        mock_app.acquire_token_by_device_flow.return_value = {"access_token": "tok"}
        with patch("msal.PublicClientApplication", return_value=mock_app), \
             patch.object(auth_module, "_load_cache", return_value=MagicMock(has_state_changed=False)):
            from mail_merge.auth import acquire_token
            token = acquire_token("fake-client", tenant_id="contoso.onmicrosoft.com")
        assert token == "tok"
