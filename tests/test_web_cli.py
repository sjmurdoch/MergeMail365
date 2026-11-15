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
                main(["--host", "0.0.0.0", "--allow-remote"])
                
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
    def fake_webview(self, monkeypatch, tmp_path):
        webview = pytest.importorskip("webview")
        # main() creates the web view's storage directory under state_dir().
        monkeypatch.setattr("mail_merge._paths.state_dir", lambda: tmp_path / "state")
        # Autospec only the functions we call: autospeccing the whole module
        # touches webview.screens, a lazy proxy that initialises the GUI
        # backend and fails on Linux runners without GTK/Qt.
        fake = types.ModuleType("webview")
        fake.create_window = create_autospec(webview.create_window)
        fake.start = create_autospec(webview.start)
        fake.settings = dict(webview.settings)
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
        fake_webview.start.assert_called_once()
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

    def test_desktop_allows_downloads(self, fake_webview, fake_server):
        """Saving a report is a download; pywebview blocks those by default.

        With downloads off, macOS shows the CSV in place of the app (with no
        way back) and Windows does nothing; with them on, both ask where to
        save the file.
        """
        assert fake_webview.settings["ALLOW_DOWNLOADS"] is False
        fake_webview.start.side_effect = lambda **kw: started.append(
            fake_webview.settings["ALLOW_DOWNLOADS"])
        started: list[bool] = []
        with patch("threading.Timer"):
            main(["--desktop"])
        assert started == [True]

    def test_desktop_keeps_web_storage_between_runs(self, fake_webview, fake_server):
        """The page saves the subject and body in localStorage so that they
        survive a restart; pywebview's default private mode discarded it
        when the app quit (phase H, macOS)."""
        from mail_merge import _paths

        with patch("threading.Timer"):
            main(["--desktop"])
        kwargs = fake_webview.start.call_args.kwargs
        assert kwargs["private_mode"] is False
        # Windows (WebView2) keeps it here; WKWebView uses its own store.
        storage = _paths.state_dir() / "webview"
        assert kwargs["storage_path"] == str(storage)
        assert storage.is_dir()
        if sys.platform != "win32":
            assert storage.stat().st_mode & 0o777 == 0o700

    def test_pywebview_has_allow_downloads_setting(self):
        webview = pytest.importorskip("webview")
        assert "ALLOW_DOWNLOADS" in webview.settings

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
        main(["--host", "myhost.lan", "--allow-remote"])
    assert mock_create.call_args.kwargs["host"] == "myhost.lan"


class TestRemoteHosts:
    """docs/review-fixes-plan.md, F12: a host other computers can reach has
    to be asked for twice."""

    @pytest.mark.parametrize("host", ["0.0.0.0", "::", "", "192.168.1.20", "my-laptop.local"])
    def test_non_loopback_host_is_refused_without_allow_remote(self, host, caplog):
        with patch("mail_merge.web.app.create_app") as mock_create, \
             patch("mail_merge.web._find_open_port", return_value=5050), \
             patch("threading.Timer"), \
             pytest.raises(SystemExit) as exit_info:
            main(["--host", host])
        assert exit_info.value.code == 2
        mock_create.assert_not_called()
        assert any("--allow-remote" in r.getMessage() and r.levelname == "ERROR" for r in caplog.records)

    def test_allow_remote_starts_with_a_warning(self, caplog):
        with patch("mail_merge.web.app.create_app") as mock_create, \
             patch("mail_merge.web._find_open_port", return_value=5050), \
             patch("threading.Timer"):
            main(["--host", "0.0.0.0", "--allow-remote"])
        mock_create.return_value.run.assert_called_once()
        warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 1
        assert "not encrypted" in warnings[0] and "0.0.0.0" in warnings[0]

    @pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1", "[::1]", "LOCALHOST", "127.0.0.2"])
    def test_loopback_hosts_need_no_flag_and_give_no_warning(self, host, caplog):
        with patch("mail_merge.web.app.create_app") as mock_create, \
             patch("mail_merge.web._find_open_port", return_value=5050), \
             patch("threading.Timer"):
            main(["--host", host])
        mock_create.return_value.run.assert_called_once()
        assert not [r for r in caplog.records if r.levelno >= 30]

    def test_port_is_probed_on_the_host_that_will_be_served(self):
        with patch("mail_merge.web.app.create_app"), \
             patch("mail_merge.web._find_open_port", return_value=5050) as find, \
             patch("threading.Timer"):
            main(["--host", "127.0.0.1", "--port", "5051"])
        find.assert_called_once_with(5051, host="127.0.0.1")


def test_find_open_port_skips_a_port_taken_on_that_host():
    import socket

    from mail_merge.web import _find_open_port

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen(1)
        port = taken.getsockname()[1]
        found = _find_open_port(port, port + 20, host="127.0.0.1")
        assert port < found <= port + 20


def test_find_open_port_checks_the_address_the_server_binds():
    """Phase H, Windows: a second copy of the app shared the first one's
    port. For "localhost" the probe tried ::1 (getaddrinfo's first answer)
    while Werkzeug listens on 127.0.0.1, and Werkzeug sets SO_REUSEADDR,
    which on Windows lets a second socket bind a port already listening."""
    import socket

    from mail_merge.web import _find_open_port

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as taken:
        taken.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # as Werkzeug does
        taken.bind(("127.0.0.1", 0))
        taken.listen(1)
        port = taken.getsockname()[1]
        found = _find_open_port(port, port + 20, host="localhost")
        assert port < found <= port + 20


def test_find_open_port_reuses_a_port_left_by_a_closed_server():
    """Phase H, macOS rc3: reopened just after quitting mid-send, the app
    moved to port 5051, a different origin, so the saved compose fields
    weren't restored. The quit server's connections were still closing
    (TIME_WAIT); Werkzeug binds such a port with SO_REUSEADDR, so the probe
    must accept it too."""
    import socket

    from mail_merge.web import _find_open_port

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    client = socket.create_connection(("127.0.0.1", port))
    accepted, _ = server.accept()
    accepted.close()  # the server side closes first: its end is in TIME_WAIT
    client.recv(1)
    client.close()
    server.close()
    # The server's end reaches TIME_WAIT once the client's FIN arrives; until
    # then (FIN_WAIT_2) the port is busy for Werkzeug too, so allow a moment.
    import time

    deadline = time.monotonic() + 5
    while (found := _find_open_port(port, port + 20, host="localhost")) != port:
        assert time.monotonic() < deadline, f"port {port} still busy; probe chose {found}"
        time.sleep(0.05)


def test_find_open_port_reports_an_unusable_host():
    from mail_merge.web import _find_open_port

    with pytest.raises(RuntimeError, match="Cannot listen on host"):
        _find_open_port(5050, 5051, host="no-such-host.invalid")
