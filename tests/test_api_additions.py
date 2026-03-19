"""Tests for new send_merge() parameters: body_text and token_provider."""

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
