"""Web interface for mail-merge."""

from __future__ import annotations

import os

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
        prog="mail-merge-web",
        description="Web interface for mail-merge",
    )
    parser.add_argument("--host", default="localhost", help="Host to bind to (default: localhost)")
    parser.add_argument("--port", type=int, default=5050, help="Port to bind to (default: 5050)")
    parser.add_argument("--desktop", action="store_true", help="Open in a native desktop window (requires pywebview)")
    parser.add_argument("--client-id", default="", help="Azure AD client ID (pre-fills and locks the field in the UI)")
    parser.add_argument("--tenant-id", default="", help="Azure AD tenant ID (pre-fills and locks the field in the UI)")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    args = parser.parse_args(argv)

    setup_logging(getattr(logging, args.log_level.upper(), logging.INFO))
    logger = logging.getLogger(__name__)

    port = _find_open_port(args.port)
    if port != args.port:
        logger.info("Port %d in use, using %d instead", args.port, port)

    # Auto-enable desktop mode when running as a PyInstaller bundle
    is_bundled = getattr(sys, "frozen", False)
    desktop = args.desktop or is_bundled

    from mail_merge.web.app import create_app

    startup_token = secrets.token_urlsafe(32)
    app = create_app(
        startup_token=startup_token,
        port=port,
        client_id=args.client_id,
        tenant_id=args.tenant_id,
    )

    url = f"http://{args.host}:{port}/?token={startup_token}"
    logger.info("Starting mail-merge web UI on http://%s:%d", args.host, port)
    logger.info("Access URL: %s", url)

    if desktop:
        try:
            import webview
        except ImportError:
            if is_bundled:
                logger.error("pywebview not found in bundle — falling back to browser mode")
                desktop = False
            else:
                logger.error("pywebview is required for --desktop mode. Install with: uv pip install 'mail-merge[desktop]'")
                sys.exit(1)

    if desktop:
        # Run Flask on a real HTTP port so OAuth redirect callbacks work.
        # (Passing the WSGI app directly to pywebview uses a random internal
        # port, which breaks the OAuth redirect_uri.)
        flask_thread = threading.Thread(
            target=app.run,
            kwargs={"host": args.host, "port": port, "debug": False, "use_reloader": False},
            daemon=True,
        )
        flask_thread.start()
        # Wait for Flask to be ready before opening the window
        for _ in range(50):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.connect(("127.0.0.1", port))
                    break
            except OSError:
                import time
                time.sleep(0.1)
        webview.create_window("Mail Merge", url, width=1100, height=800)
        webview.start()
    else:
        # Open browser after a short delay
        threading.Timer(1.0, webbrowser.open, args=[url]).start()
        app.run(host=args.host, port=port, debug=False)


if __name__ == "__main__":
    main()
