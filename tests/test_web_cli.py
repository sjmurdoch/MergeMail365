from mail_merge.web import main
import argparse
from unittest.mock import patch

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
