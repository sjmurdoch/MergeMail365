"""Web interface for MergeMail365."""

from __future__ import annotations

import argparse
import logging
import secrets
import socket
import sys
import threading
import webbrowser

from mail_merge.console import setup_logging


def _find_open_port(start: int = 5050, end: int = 5099) -> int:
    """Find an available port in the given range."""
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No available port in range {start}-{end}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="mergemail365-web",
        description="MergeMail365 web interface",
    )
    parser.add_argument("--host", default="localhost", help="Host to bind to (default: localhost)")
    parser.add_argument("--port", type=int, default=5050, help="Port to bind to (default: 5050)")
    parser.add_argument("--desktop", action="store_true", help="Open in a native desktop window (requires pywebview)")
    parser.add_argument("--client-id", default="", help="Azure AD client ID (pre-fills and locks the field in the UI)")
    parser.add_argument("--tenant-id", default="", help="Azure AD tenant ID (pre-fills and locks the field in the UI)")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    parser.add_argument("--log-file", action="store_true", help="Enable debug logging to a file")
    args = parser.parse_args(argv)

    setup_logging(getattr(logging, args.log_level.upper(), logging.INFO))
    logger = logging.getLogger(__name__)

    # Auto-enable desktop mode when running as a PyInstaller bundle
    is_bundled = getattr(sys, "frozen", False)

    # Always enable file logging in bundled mode (no stderr visible),
    # or when explicitly requested.
    if is_bundled or args.log_file or args.log_level.upper() == "DEBUG":
        from mail_merge.console import setup_file_logging
        log_file = setup_file_logging()
        if log_file:
            logger.info("Log file: %s", log_file)

    desktop = args.desktop or is_bundled

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

    from mail_merge.web.app import create_app

    if desktop:
        # Pass the Flask app directly to pywebview — no localhost listener,
        # so no CSRF risk.  Auth happens via the system browser
        # (acquire_token_interactive_flow), not via OAuth redirect callbacks.
        app = create_app(
            client_id=args.client_id,
            tenant_id=args.tenant_id,
            desktop_mode=True,
        )
        webview.create_window("MergeMail365", app, width=1100, height=800)
        webview.start()
    else:
        port = _find_open_port(args.port)
        if port != args.port:
            logger.info("Port %d in use, using %d instead", args.port, port)

        startup_token = secrets.token_urlsafe(32)
        app = create_app(
            startup_token=startup_token,
            port=port,
            client_id=args.client_id,
            tenant_id=args.tenant_id,
        )

        url = f"http://{args.host}:{port}/?token={startup_token}"
        logger.info("Starting MergeMail365 web UI on http://%s:%d", args.host, port)
        logger.info("Access URL: %s", url)

        # Open browser after a short delay
        threading.Timer(1.0, webbrowser.open, args=[url]).start()
        app.run(host=args.host, port=port, debug=False)


if __name__ == "__main__":
    main()
