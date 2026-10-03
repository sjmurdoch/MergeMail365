"""Tests for new send_merge() parameters: body_text, token_provider, device_code."""

from pathlib import Path
from unittest.mock import patch

import responses

from mail_merge.api import send_merge
from mail_merge.sender import GRAPH_SEND_URL


class TestBodyText:
    """Tests for the body_text parameter."""

    @responses.activate
    def test_body_text_used(self, sample_xlsx):
        """body_text is used directly as the template without reading a file."""
        results = send_merge(
            spreadsheet=sample_xlsx,
            subject="Hello {{name}}",
            email_column="email",
            body_text="Dear {{name}}, welcome.",
            send=False,
            confirm=False,
        )
        assert len(results) == 2
        assert all(r.success for r in results)

    @responses.activate
    def test_body_text_precedence(self, sample_xlsx, body_template_file):
        """body_text takes precedence over body file path."""
        results = send_merge(
            spreadsheet=sample_xlsx,
            body=body_template_file,
            subject="Hello {{name}}",
            email_column="email",
            body_text="Custom body for {{name}}.",
            send=False,
            confirm=False,
        )
        # If body_text takes precedence, we should get results without error
        assert len(results) == 2

    def test_no_body_or_body_text_raises(self, sample_xlsx):
        """Omitting both body and body_text raises ValueError."""
        try:
            send_merge(
                spreadsheet=sample_xlsx,
                subject="Hello",
                email_column="email",
                send=False,
                confirm=False,
            )
            assert False, "Should have raised ValueError"
        except ValueError as exc:
            assert "body" in str(exc).lower()


class TestTokenProvider:
    """Tests for the token_provider parameter."""

    @responses.activate
    def test_token_provider_used_for_send(self, sample_xlsx):
        """When token_provider is set, it's used instead of the auth module."""
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)

        token_calls = []

        def fake_token() -> str:
            token_calls.append(1)
            return "fake-token-from-provider"

        results = send_merge(
            spreadsheet=sample_xlsx,
            subject="Hello {{name}}",
            email_column="email",
            body_text="Body for {{name}}.",
            send=True,
            confirm=False,
            token_provider=fake_token,
        )
        assert len(results) == 2
        assert all(r.success for r in results)
        # Token provider should have been called
        assert len(token_calls) > 0

    @responses.activate
    def test_token_provider_skips_auth_block(self, sample_xlsx):
        """Auth module is not imported when token_provider is provided."""
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)

        def fake_token() -> str:
            return "fake-token"

        # This should succeed without needing client_id
        results = send_merge(
            spreadsheet=sample_xlsx,
            subject="Test",
            email_column="email",
            body_text="Body.",
            send=True,
            confirm=False,
            token_provider=fake_token,
        )
        assert all(r.success for r in results)

    @responses.activate
    def test_token_provider_test_email(self, sample_xlsx):
        """token_provider works with test_email mode."""
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)

        def fake_token() -> str:
            return "fake-token"

        results = send_merge(
            spreadsheet=sample_xlsx,
            subject="Hello {{name}}",
            email_column="email",
            body_text="Body for {{name}}.",
            test_email="test@example.com",
            confirm=False,
            token_provider=fake_token,
        )
        assert len(results) == 1
        assert results[0].email == "test@example.com"


class TestDeviceCodeParam:
    """Tests for the device_code parameter on send_merge()."""

    @responses.activate
    def test_interactive_is_default(self, sample_xlsx, monkeypatch):
        """When device_code=False (default), interactive flow is tried first."""
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)

        interactive_calls = []

        def fake_interactive(*a, **kw):
            interactive_calls.append(1)
            return "interactive-token"

        monkeypatch.setattr(
            "mail_merge.auth.acquire_token_interactive_flow", fake_interactive,
        )
        monkeypatch.setattr(
            "mail_merge.auth.acquire_token", lambda *a, **kw: "device-token",
        )

        results = send_merge(
            spreadsheet=sample_xlsx,
            subject="Hello {{name}}",
            email_column="email",
            body_text="Body.",
            client_id="fake-client",
            test_email="test@example.com",
            confirm=False,
        )
        assert len(results) == 1
        assert len(interactive_calls) == 1

    @responses.activate
    def test_device_code_true_skips_interactive(self, sample_xlsx, monkeypatch):
        """When device_code=True, device code flow is used directly."""
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)

        device_calls = []

        def fake_device(*a, **kw):
            device_calls.append(1)
            return "device-token"

        monkeypatch.setattr(
            "mail_merge.auth.acquire_token_interactive_flow",
            lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not be called")),
        )
        monkeypatch.setattr("mail_merge.auth.acquire_token", fake_device)

        results = send_merge(
            spreadsheet=sample_xlsx,
            subject="Hello {{name}}",
            email_column="email",
            body_text="Body.",
            client_id="fake-client",
            test_email="test@example.com",
            confirm=False,
            device_code=True,
        )
        assert len(results) == 1
        # Called once for initial auth, plus once via get_token during send
        assert len(device_calls) >= 1

    @responses.activate
    def test_interactive_failure_falls_back_to_device_code(self, sample_xlsx, monkeypatch):
        """When interactive flow fails, falls back to device code."""
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)

        device_calls = []

        def fake_interactive(*a, **kw):
            raise OSError("No browser available")

        def fake_device(*a, **kw):
            device_calls.append(1)
            return "device-token"

        monkeypatch.setattr(
            "mail_merge.auth.acquire_token_interactive_flow", fake_interactive,
        )
        monkeypatch.setattr("mail_merge.auth.acquire_token", fake_device)

        results = send_merge(
            spreadsheet=sample_xlsx,
            subject="Hello {{name}}",
            email_column="email",
            body_text="Body.",
            client_id="fake-client",
            test_email="test@example.com",
            confirm=False,
        )
        assert len(results) == 1
        # Called once for fallback auth, plus once via get_token during send
        assert len(device_calls) >= 1


class TestShouldStop:
    """Tests for the should_stop parameter."""

    @responses.activate
    def test_should_stop_stops_individual_send(self, sample_xlsx):
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        with patch("mail_merge.sender.time.sleep"):
            results = send_merge(
                spreadsheet=sample_xlsx,
                subject="Hello {{name}}",
                email_column="email",
                body_text="Body.",
                send=True,
                confirm=False,
                token_provider=lambda: "tok",
                should_stop=lambda: len(responses.calls) >= 1,
            )
        assert [r.email for r in results] == ["alice@example.com"]
        assert len(responses.calls) == 1

    @responses.activate
    def test_should_stop_stops_bcc_blast(self, sample_xlsx):
        results = send_merge(
            spreadsheet=sample_xlsx,
            subject="Hello",
            email_column="email",
            body_text="Body.",
            send=True,
            confirm=False,
            bcc_blast=True,
            bcc_blast_to="noreply@example.com",
            token_provider=lambda: "tok",
            should_stop=lambda: True,
        )
        assert results == []
        assert len(responses.calls) == 0
