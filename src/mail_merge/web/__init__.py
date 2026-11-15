"""Web interface for MergeMail365."""

import argparse
import ipaddress
import logging
import secrets
import socket
import sys
import threading
import webbrowser

from mail_merge.console import add_log_level_arguments, configure_console_logging


def _find_open_port(start: int = 5050, end: int = 5099, host: str = "127.0.0.1") -> int:
    """Find a port in the range that is free on `host`, the address the
    server will listen on (a port free on 127.0.0.1 may be taken on another
    interface, and the reverse).

    The probe binds the address Werkzeug will bind (for "localhost" that is
    127.0.0.1, not getaddrinfo's first answer, which may be ::1). On Windows
    it binds exclusively: Werkzeug sets SO_REUSEADDR, with which Windows lets
    a second socket bind a port that is already listening, so a plain probe
    would succeed there and two copies of the app would share one port.
    """
    from werkzeug.serving import get_sockaddr, select_address_family

    for port in range(start, end + 1):
        family = select_address_family(host, port)
        address = get_sockaddr(host, port, family)
        with socket.socket(family, socket.SOCK_STREAM) as s:
            if sys.platform == "win32":
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                s.bind(address)
                return port
            except socket.gaierror as exc:
                raise RuntimeError(f"Cannot listen on host {host!r}: {exc}") from exc
            except OSError:
                continue
    raise RuntimeError(f"No available port in range {start}-{end}")


def _is_loopback(host: str) -> bool:
    """Whether `host` can only be reached from this computer."""
    name = host.strip("[]").lower()
    if name == "localhost":
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False  # another name, or a wildcard such as "" or 0.0.0.0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="mergemail365-web",
        description="MergeMail365 web interface",
    )
    parser.add_argument("--host", default="localhost", help="Host to bind to (default: localhost). Anything but this computer's own loopback address also needs --allow-remote")
    parser.add_argument("--allow-remote", action="store_true", help="Allow --host to be an address other computers can reach. The connection is not encrypted, and anyone who learns the access URL can send email as the signed-in account")
    parser.add_argument("--port", type=int, default=5050, help="Port to bind to (default: 5050)")
    parser.add_argument("--desktop", action="store_true", help="Open in a native desktop window (requires pywebview)")
    parser.add_argument("--client-id", default="", help="Azure AD client ID (pre-fills and locks the field in the UI)")
    parser.add_argument("--tenant-id", default="", help="Azure AD tenant ID (pre-fills and locks the field in the UI)")
    add_log_level_arguments(parser)
    parser.add_argument("--log-file", action="store_true", help="Enable debug logging to a file")
    args = parser.parse_args(argv)

    configure_console_logging(parser, args)
    logger = logging.getLogger(__name__)

    from mail_merge.console import maybe_enable_file_logging
    is_bundled = maybe_enable_file_logging(args.log_file)
    if is_bundled or args.log_file:
        from mail_merge._paths import log_dir
        from mail_merge.diagnostics import start_diagnostics
        start_diagnostics(log_dir())

    desktop = args.desktop or is_bundled

    if not _is_loopback(args.host):
        if not args.allow_remote:
            logger.error(
                "--host %s would let other computers reach this app, which sends email as "
                "whoever is signed in. Add --allow-remote if that is what you want.", args.host,
            )
            sys.exit(2)
        logger.warning(
            "⚠️  Listening on %s: other computers can reach this app. The connection is not "
            "encrypted (plain HTTP), so the access URL and everything sent can be read on the "
            "network, and anyone who has the URL can send email as the signed-in account. "
            "Signing in with Microsoft only works in a browser on this computer.", args.host,
        )

    if desktop:
        try:
            import webview
        except ImportError:
            if is_bundled:
                logger.error("pywebview not found in bundle — falling back to browser mode")
                desktop = False
            else:
                logger.error("pywebview is required for --desktop mode. Install with: uv pip install 'mergemail365[desktop]'")
                sys.exit(1)

    from mail_merge._paths import private_dir, state_dir
    from mail_merge.web.app import create_app

    # Both modes serve the app on a localhost port and open it at the same
    # token URL; only what opens that URL differs.
    port = _find_open_port(args.port, host=args.host)
    if port != args.port:
        logger.info("Port %d in use, using %d instead", args.port, port)

    startup_token = secrets.token_urlsafe(32)
    app = create_app(
        startup_token=startup_token,
        port=port,
        client_id=args.client_id,
        tenant_id=args.tenant_id,
        desktop_mode=desktop,
        host=args.host,
        send_log_dir=state_dir() / "sends",
    )

    url = f"http://{args.host}:{port}/?token={startup_token}"
    logger.info("Starting MergeMail365 web UI on http://%s:%d", args.host, port)

    if desktop:
        # Serve the app ourselves rather than handing it to pywebview, whose
        # own server would open the window without the startup token.
        # Auth happens via the system browser (acquire_token_interactive_flow),
        # not via OAuth redirect callbacks.
        from werkzeug.serving import make_server

        server = make_server(args.host, port, app, threaded=True)
        threading.Thread(target=server.serve_forever, name="http-server", daemon=True).start()
        # Saving a report is a download. pywebview blocks those by default:
        # macOS then shows the CSV in place of the app and Windows does
        # nothing. Allowed, both ask where to save the file.
        webview.settings["ALLOW_DOWNLOADS"] = True
        webview.create_window("MergeMail365", url, width=1100, height=800)
        # Not private mode: the page keeps the subject and body in
        # localStorage so that they survive quitting the app (the origin,
        # localhost:5050, is the same each run). WebView2 keeps its data in
        # storage_path; WKWebView ignores it and uses the app's default
        # store under ~/Library/WebKit.
        webview.start(
            private_mode=False,
            storage_path=str(private_dir(state_dir() / "webview")),
        )
    else:
        logger.info("Access URL: %s", url)

        # Open browser after a short delay
        threading.Timer(1.0, webbrowser.open, args=[url]).start()
        app.run(host=args.host, port=port, debug=False)

if __name__ == "__main__":
    main()
