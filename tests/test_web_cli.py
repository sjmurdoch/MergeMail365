import inspect
import sys
import types
from unittest.mock import create_autospec, patch

import pytest

from mail_merge.web import main


@pytest.fixture(autouse=True)
def fake_diagnostics():
    """Don't start a real stall watchdog (it writes to the user's log dir)."""
    with patch("mail_merge.diagnostics.start_diagnostics") as start:
        yield start


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

def test_log_file_flag_starts_diagnostics(fake_diagnostics):
    """--log-file also starts the stall watchdog, dumping into the log dir."""
    with patch("mail_merge.web.app.create_app"), \
         patch("mail_merge.web._find_open_port", return_value=5050), \
         patch("threading.Timer"), \
         patch("mail_merge.console.setup_file_logging", return_value=None), \
         patch("mail_merge._paths.log_dir", return_value="LOGDIR"):
        main(["--log-file"])
    fake_diagnostics.assert_called_once_with("LOGDIR")


def test_no_diagnostics_without_file_logging(fake_diagnostics):
    with patch("mail_merge.web.app.create_app"), \
         patch("mail_merge.web._find_open_port", return_value=5050), \
         patch("threading.Timer"):
        main([])
    fake_diagnostics.assert_not_called()


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

    @pytest.fixture
    def fake_server(self):
        """Stand-in for the werkzeug server desktop mode runs in a thread."""
        with patch("werkzeug.serving.make_server") as make_server, \
             patch("mail_merge.web._find_open_port", return_value=5057):
            yield make_server

    def test_desktop_opens_native_window_at_token_url(self, fake_webview, fake_server):
        from flask import Flask

        with patch("threading.Timer") as timer:
            main(["--desktop", "--client-id", "cid", "--tenant-id", "tid"])

        fake_server.assert_called_once()
        host, port, app = fake_server.call_args.args[:3]
        assert (host, port) == ("localhost", 5057)
        assert isinstance(app, Flask)
        assert app.config["DESKTOP_MODE"] is True
        assert app.config["FIXED_CLIENT_ID"] == "cid"
        fake_server.return_value.serve_forever.assert_called_once()

        fake_webview.create_window.assert_called_once()
        args, kwargs = fake_webview.create_window.call_args
        assert args[0] == "MergeMail365"
        token = app.config["STARTUP_TOKEN"]
        assert len(token) >= 32
        assert args[1] == f"http://localhost:5057/?token={token}"
        assert kwargs == {"width": 1100, "height": 800}
        fake_webview.start.assert_called_once_with()
        timer.assert_not_called()  # no system browser launch in desktop mode

    def test_desktop_app_enforces_token_and_csrf(self, fake_webview, fake_server):
        """The app handed to the server must not auto-authenticate."""
        with patch("threading.Timer"):
            main(["--desktop"])
        app = fake_server.call_args.args[2]
        c = app.test_client()
        assert c.get("/").status_code == 403
        assert c.get("/", base_url="http://evil.example:5057").status_code == 403
        c.get("/?token=" + app.config["STARTUP_TOKEN"])
        assert c.get("/").status_code == 200
        assert c.post("/api/state", json={}).status_code == 403

    def test_desktop_and_browser_build_the_app_the_same_way(self, fake_webview, fake_server):
        calls = {}
        for mode, argv in (("browser", []), ("desktop", ["--desktop"])):
            with patch("mail_merge.web.app.create_app") as mock_create, \
                 patch("threading.Timer"):
                main(argv + ["--host", "127.0.0.1"])
            kwargs = dict(mock_create.call_args.kwargs)
            assert kwargs.pop("desktop_mode", False) is (mode == "desktop")
            assert kwargs["startup_token"]
            kwargs.pop("startup_token")
            calls[mode] = kwargs
        assert calls["browser"] == calls["desktop"]
        assert calls["desktop"]["host"] == "127.0.0.1"
        assert calls["desktop"]["port"] == 5057

    def test_create_window_accepts_url_string(self):
        """We pass a URL string as ``url``; pywebview must still accept that."""
        webview = pytest.importorskip("webview")
        params = inspect.signature(webview.create_window).parameters
        assert list(params)[:2] == ["title", "url"]
        assert "str" in str(params["url"].annotation)
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

    def test_bundled_app_starts_diagnostics(self, monkeypatch, fake_diagnostics):
        monkeypatch.setitem(sys.modules, "webview", None)
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        with patch("mail_merge.web.app.create_app"), \
             patch("mail_merge.web._find_open_port", return_value=5050), \
             patch("mail_merge.console.setup_file_logging", return_value=None), \
             patch("threading.Timer"):
            main([])
        fake_diagnostics.assert_called_once()

    def test_desktop_without_webview_exits(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "webview", None)
        with pytest.raises(SystemExit) as exc:
            main(["--desktop"])
        assert exc.value.code == 1


def test_browser_mode_passes_bind_host_to_app():
    """The Host-header allowlist needs to know which host we bound to."""
    with patch("mail_merge.web.app.create_app") as mock_create, \
         patch("mail_merge.web._find_open_port", return_value=5050), \
         patch("threading.Timer"):
        main(["--host", "myhost.lan"])
    assert mock_create.call_args.kwargs["host"] == "myhost.lan"
