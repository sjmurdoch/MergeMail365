import inspect
import sys
import types
from unittest.mock import create_autospec, patch

import pytest

from mail_merge.web import main

def test_web_host_default_is_localhost():
    """Verify that the web interface defaults to 'localhost' for session consistency."""
    # We mock create_app and app.run to avoid actually starting a server
    with patch("mail_merge.web.app.create_app") as mock_create:
        mock_app = mock_create.return_value
        with patch("mail_merge.web._find_open_port", return_value=5050):
            with patch("threading.Timer"): # Avoid opening browser
                # We call main with empty args, so it uses defaults
                main([])
                
                # Check what host was passed to app.run
                mock_app.run.assert_called_once()
                args, kwargs = mock_app.run.call_args
                assert kwargs["host"] == "localhost"

def test_web_host_override():
    """Verify that the --host flag can still override the default."""
    with patch("mail_merge.web.app.create_app") as mock_create:
        mock_app = mock_create.return_value
        with patch("mail_merge.web._find_open_port", return_value=5050):
            with patch("threading.Timer"):
                main(["--host", "0.0.0.0"])
                
                mock_app.run.assert_called_once()
                args, kwargs = mock_app.run.call_args
                assert kwargs["host"] == "0.0.0.0"

def test_log_file_flag_enables_file_logging(tmp_path):
    """--log-file flag triggers setup_file_logging."""
    with patch("mail_merge.web.app.create_app") as mock_create:
        mock_app = mock_create.return_value
        with patch("mail_merge.web._find_open_port", return_value=5050):
            with patch("threading.Timer"):
                with patch("mail_merge.console.setup_file_logging", return_value=tmp_path / "test.log") as mock_file_log:
                    main(["--log-file"])
                    mock_file_log.assert_called_once()

def test_debug_level_does_not_enable_file_logging(tmp_path):
    """--log-level DEBUG alone does NOT trigger setup_file_logging."""
    with patch("mail_merge.web.app.create_app") as mock_create:
        mock_app = mock_create.return_value
        with patch("mail_merge.web._find_open_port", return_value=5050):
            with patch("threading.Timer"):
                with patch("mail_merge.console.setup_file_logging", return_value=tmp_path / "test.log") as mock_file_log:
                    main(["--log-level", "DEBUG"])
                    mock_file_log.assert_not_called()


class TestDesktopMode:
    """--desktop path, run against autospecs of the real pywebview functions.

    Autospec makes create_window/start calls fail if pywebview renames or
    removes the parameters we use, without opening a native window.
    """

    @pytest.fixture
    def fake_webview(self, monkeypatch):
        webview = pytest.importorskip("webview")
        # Autospec only the functions we call: autospeccing the whole module
        # touches webview.screens, a lazy proxy that initialises the GUI
        # backend and fails on Linux runners without GTK/Qt.
        fake = types.ModuleType("webview")
        fake.create_window = create_autospec(webview.create_window)
        fake.start = create_autospec(webview.start)
        monkeypatch.setitem(sys.modules, "webview", fake)
        return fake

    def test_desktop_opens_native_window_with_flask_app(self, fake_webview):
        from flask import Flask

        with patch("threading.Timer") as timer:
            main(["--desktop", "--client-id", "cid", "--tenant-id", "tid"])

        fake_webview.create_window.assert_called_once()
        args, kwargs = fake_webview.create_window.call_args
        assert args[0] == "MergeMail365"
        assert isinstance(args[1], Flask)
        assert args[1].config["DESKTOP_MODE"] is True
        assert kwargs == {"width": 1100, "height": 800}
        fake_webview.start.assert_called_once_with()
        timer.assert_not_called()  # no system browser launch in desktop mode

    def test_create_window_accepts_wsgi_app_as_url(self):
        """We pass the Flask app as ``url``; pywebview must still document that."""
        webview = pytest.importorskip("webview")
        params = inspect.signature(webview.create_window).parameters
        assert list(params)[:2] == ["title", "url"]
        assert "callable" in str(params["url"].annotation)
        assert {"width", "height"} <= params.keys()

    def test_bundled_app_without_webview_falls_back_to_browser(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "webview", None)  # makes import fail
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        with patch("mail_merge.web.app.create_app") as mock_create, \
             patch("mail_merge.web._find_open_port", return_value=5050), \
             patch("mail_merge.console.setup_file_logging", return_value=None), \
             patch("threading.Timer"):
            main([])
        assert mock_create.call_args.kwargs.get("desktop_mode") in (None, False)
        mock_create.return_value.run.assert_called_once()

    def test_desktop_without_webview_exits(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "webview", None)
        with pytest.raises(SystemExit) as exc:
            main(["--desktop"])
        assert exc.value.code == 1
