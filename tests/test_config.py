from pathlib import Path

from mail_merge.config import load_config


class TestLoadConfig:
    def test_valid_toml(self, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text('client-id = "abc-123"\ntenant-id = "xyz-789"\n', encoding="utf-8")
        result = load_config(cfg)
        assert result == {"client_id": "abc-123", "tenant_id": "xyz-789"}

    def test_partial_toml(self, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text('client-id = "only-client"\n', encoding="utf-8")
        result = load_config(cfg)
        assert result == {"client_id": "only-client"}
        assert "tenant_id" not in result

    def test_missing_file(self, tmp_path):
        result = load_config(tmp_path / "nonexistent.toml")
        assert result == {}

    def test_malformed_file(self, tmp_path):
        cfg = tmp_path / "bad.toml"
        cfg.write_text("not valid toml [[[", encoding="utf-8")
        result = load_config(cfg)
        assert result == {}

    def test_empty_file(self, tmp_path):
        cfg = tmp_path / "empty.toml"
        cfg.write_text("", encoding="utf-8")
        result = load_config(cfg)
        assert result == {}
