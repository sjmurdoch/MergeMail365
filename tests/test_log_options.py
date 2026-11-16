"""The logging level options shared by mergemail365 and mergemail365-web
(docs/review-fixes-plan.md, E4): --log-level with fixed choices, -v for
DEBUG, and the same setting from MERGEMAIL365_LOG_LEVEL and the config
file's log-level key. Precedence as for the client ID: command line,
environment, config file, default."""

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from mail_merge.cli import main as cli_main
from mail_merge.console import resolve_log_level


@pytest.fixture(autouse=True)
def _no_user_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.delenv("MERGEMAIL365_LOG_LEVEL", raising=False)
    config = tmp_path / "config.toml"
    monkeypatch.setattr("mail_merge.config.DEFAULT_PATH", config)
    return config


@pytest.fixture
def config_file(_no_user_settings: Path) -> Path:
    return _no_user_settings


class TestResolve:
    def test_default_is_info(self):
        assert resolve_log_level(None, verbose=False) == (logging.INFO, "default")

    def test_command_line(self):
        assert resolve_log_level("warning", verbose=False) == (logging.WARNING, "--log-level")

    def test_verbose_is_debug(self):
        assert resolve_log_level(None, verbose=True) == (logging.DEBUG, "-v/--verbose")

    def test_environment(self, monkeypatch):
        monkeypatch.setenv("MERGEMAIL365_LOG_LEVEL", "error")
        assert resolve_log_level(None, verbose=False) == (logging.ERROR, "MERGEMAIL365_LOG_LEVEL")

    def test_config_file(self, config_file):
        config_file.write_text('log-level = "WARNING"\n', encoding="utf-8")
        assert resolve_log_level(None, verbose=False) == (logging.WARNING, f"{config_file}")

    def test_precedence(self, monkeypatch, config_file):
        config_file.write_text('log-level = "ERROR"\n', encoding="utf-8")
        monkeypatch.setenv("MERGEMAIL365_LOG_LEVEL", "WARNING")
        assert resolve_log_level(None, verbose=False)[0] == logging.WARNING
        assert resolve_log_level("CRITICAL", verbose=False)[0] == logging.CRITICAL
        assert resolve_log_level(None, verbose=True)[0] == logging.DEBUG

    @pytest.mark.parametrize("where", ["env", "config"])
    def test_unknown_level_outside_the_command_line_is_an_error(self, where, monkeypatch, config_file):
        if where == "env":
            monkeypatch.setenv("MERGEMAIL365_LOG_LEVEL", "LOUD")
        else:
            config_file.write_text('log-level = "LOUD"\n', encoding="utf-8")
        with pytest.raises(ValueError, match="LOUD"):
            resolve_log_level(None, verbose=False)


ENTRY_POINTS = ["mergemail365", "mergemail365-web"]


def _run(entry: str, argv: list[str]) -> int | None:
    if entry == "mergemail365":
        return cli_main(argv)
    from mail_merge.web import main as web_main
    return web_main(argv)


@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_unknown_log_level_is_refused(entry, capsys):
    """It used to be silently treated as INFO."""
    if entry == "mergemail365-web":
        pytest.importorskip("flask")
    with pytest.raises(SystemExit) as info:
        _run(entry, ["--log-level", "LOUD", "--spreadsheet", "x", "--body", "x", "--subject", "x",
                     "--email-column", "x"] if entry == "mergemail365" else ["--log-level", "LOUD"])
    assert info.value.code == 2
    assert "LOUD" in capsys.readouterr().err


@pytest.mark.parametrize("entry", ENTRY_POINTS)
@pytest.mark.parametrize("flag", [["-v"], ["--verbose"], ["--log-level", "debug"]])
def test_debug_flags_reach_setup_logging(entry, flag, sample_xlsx, body_template_file):
    if entry == "mergemail365-web":
        pytest.importorskip("flask")
        argv = flag
        target = "mail_merge.console.setup_logging"
    else:
        argv = ["--spreadsheet", str(sample_xlsx), "--body", str(body_template_file),
                "--subject", "Hello {{name}}", "--email-column", "email", *flag]
        target = "mail_merge.console.setup_logging"
    with patch(target, side_effect=SystemExit(0)) as setup:
        with pytest.raises(SystemExit):
            _run(entry, argv)
    setup.assert_called_once_with(logging.DEBUG)


@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_bad_environment_value_is_refused(entry, monkeypatch, capsys):
    if entry == "mergemail365-web":
        pytest.importorskip("flask")
    monkeypatch.setenv("MERGEMAIL365_LOG_LEVEL", "LOUD")
    argv = ["--spreadsheet", "x", "--body", "x", "--subject", "x", "--email-column", "x"] \
        if entry == "mergemail365" else []
    with pytest.raises(SystemExit) as info:
        _run(entry, argv)
    assert info.value.code == 2
    assert "MERGEMAIL365_LOG_LEVEL" in capsys.readouterr().err


def test_unexpected_error_traceback_at_debug(sample_xlsx, body_template_file, caplog):
    """One line at ERROR; the traceback at DEBUG, for the log file."""
    argv = ["--spreadsheet", str(sample_xlsx), "--body", str(body_template_file),
            "--subject", "Hello {{name}}", "--email-column", "email"]
    with patch("mail_merge.cli.send_merge", side_effect=KeyError("boom")), \
            caplog.at_level(logging.DEBUG, logger="mail_merge"):
        assert cli_main(argv) == 1
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert [r.getMessage() for r in errors] == ["Unexpected error: 'boom'"]
    assert errors[0].exc_info is None
    [debug] = [r for r in caplog.records if r.levelno == logging.DEBUG and r.exc_info]
    assert debug.exc_info[0] is KeyError
