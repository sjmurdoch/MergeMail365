import base64
import json
import logging
import time
from pathlib import Path

import openpyxl
import pytest
import responses

from mail_merge.api import send_merge
from mail_merge.report import write_csv
from mail_merge.sender import GRAPH_SEND_URL, SendResult


class TestDryRun:
    def test_dry_run_returns_results(self, sample_xlsx, body_template_file):
        results = send_merge(
            spreadsheet=sample_xlsx,
            body=body_template_file,
            subject="Hello {{name}}",
            email_column="email",
        )
        assert len(results) == 2
        assert all(r.success for r in results)

    @responses.activate
    def test_test_email_always_sends(self, sample_xlsx, body_template_file, monkeypatch):
        """test_email sends even without send=True."""
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        monkeypatch.setattr("mail_merge.auth.acquire_token", lambda client_id, tenant_id="common": "fake-token")
        monkeypatch.setattr("mail_merge.auth.acquire_token_interactive_flow", lambda *a, **kw: "fake-token")
        results = send_merge(
            spreadsheet=sample_xlsx,
            body=body_template_file,
            subject="Hello {{name}}",
            email_column="email",
            client_id="fake-client-id",
            test_email="me@example.com",
        )
        assert len(results) == 1
        assert results[0].success
        assert results[0].email == "me@example.com"

    def test_confirm_disabled_on_dry_run(self, sample_xlsx, body_template_file, monkeypatch):
        """No prompt should happen during dry run even if confirm=True."""
        def fail_on_input(prompt: str) -> str:
            pytest.fail("console.input was called during dry run!")

        monkeypatch.setattr("mail_merge.console.console.input", fail_on_input)
        send_merge(
            spreadsheet=sample_xlsx,
            body=body_template_file,
            subject="Hello {{name}}",
            email_column="email",
            confirm=True,
        )

    @responses.activate
    def test_confirm_disabled_on_test_email(self, sample_xlsx, body_template_file, monkeypatch):
        """No prompt should happen for test_email even if confirm=True."""
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        monkeypatch.setattr("mail_merge.auth.acquire_token", lambda client_id, tenant_id="common": "fake-token")
        monkeypatch.setattr("mail_merge.auth.acquire_token_interactive_flow", lambda *a, **kw: "fake-token")
        def fail_on_input(prompt: str) -> str:
            pytest.fail("console.input was called during test_email!")

        monkeypatch.setattr("mail_merge.console.console.input", fail_on_input)
        send_merge(
            spreadsheet=sample_xlsx,
            body=body_template_file,
            subject="Hello {{name}}",
            email_column="email",
            client_id="fake-client-id",
            test_email="me@example.com",
            confirm=True,
        )


class TestFileErrors:
    def test_missing_spreadsheet(self, tmp_path, body_template_file):
        with pytest.raises(FileNotFoundError, match="Spreadsheet not found"):
            send_merge(
                spreadsheet=tmp_path / "nonexistent.xlsx",
                body=body_template_file,
                subject="Hi",
                email_column="email",
                )

    def test_missing_body(self, sample_xlsx, tmp_path):
        with pytest.raises(FileNotFoundError, match="Body template not found"):
            send_merge(
                spreadsheet=sample_xlsx,
                body=tmp_path / "nonexistent.txt",
                subject="Hi",
                email_column="email",
                )

    def test_missing_attachment(self, sample_xlsx, body_template_file, tmp_path):
        with pytest.raises(FileNotFoundError, match="Attachment not found"):
            send_merge(
                spreadsheet=sample_xlsx,
                body=body_template_file,
                subject="Hello {{name}}",
                email_column="email",
                    attachment=[tmp_path / "gone.pdf"],
            )


class TestValidationErrors:
    def test_bad_placeholder(self, sample_xlsx, body_template_file):
        with pytest.raises(ValueError, match="Unresolvable placeholders.*missing"):
            send_merge(
                spreadsheet=sample_xlsx,
                body=body_template_file,
                subject="Hello {{missing}}",
                email_column="email",
                )

    def test_attachment_too_large(self, sample_xlsx, body_template_file, tmp_path):
        big = tmp_path / "huge.bin"
        big.write_bytes(b"\x00" * (4 * 1024 * 1024))
        with pytest.raises(ValueError, match="Attachment too large"):
            send_merge(
                spreadsheet=sample_xlsx,
                body=body_template_file,
                subject="Hello {{name}}",
                email_column="email",
                    attachment=[big],
            )

    def test_too_many_recipients(self, sample_xlsx, body_template_file):
        cc_list = [f"user{i}@example.com" for i in range(500)]
        with pytest.raises(ValueError, match="Too many recipients"):
            send_merge(
                spreadsheet=sample_xlsx,
                body=body_template_file,
                subject="Hello {{name}}",
                email_column="email",
                    cc=cc_list,
            )

    def test_invalid_importance_raises(self, sample_xlsx, body_template_file):
        with pytest.raises(ValueError, match="Invalid importance"):
            send_merge(
                spreadsheet=sample_xlsx,
                body=body_template_file,
                subject="Hello {{name}}",
                email_column="email",
                importance="urgent",
            )

    def test_valid_importance_accepted(self, sample_xlsx, body_template_file):
        for level in ("low", "normal", "high"):
            results = send_merge(
                spreadsheet=sample_xlsx,
                body=body_template_file,
                subject="Hello {{name}}",
                email_column="email",
                importance=level,
            )
            assert all(r.success for r in results)


class TestEmailValidation:
    def test_non_ascii_email_skipped_with_warning(self, tmp_path, body_template_file, caplog):
        """Recipients with non-ASCII email addresses are skipped with a warning."""
        path = tmp_path / "non_ascii.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["name", "email", "company"])
        ws.append(["Alice", "alice@example.com", "Acme"])
        ws.append(["Böb", "böb@example.com", "Widgets"])
        ws.append(["José", "josé@example.com", "Corp"])
        wb.save(path)

        with caplog.at_level(logging.WARNING):
            results = send_merge(
                spreadsheet=path,
                body=body_template_file,
                subject="Hello {{name}}",
                email_column="email",
            )
        assert len(results) == 1
        assert results[0].email == "alice@example.com"
        assert "Skipping invalid email address" in caplog.text
        assert "böb@example.com" in caplog.text
        assert "josé@example.com" in caplog.text

    def test_all_invalid_raises(self, tmp_path, body_template_file):
        """If all recipients have invalid emails, raise ValueError."""
        path = tmp_path / "all_invalid.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["name", "email", "company"])
        ws.append(["Böb", "böb@example.com", "Widgets"])
        wb.save(path)

        with pytest.raises(ValueError, match="No recipients remaining"):
            send_merge(
                spreadsheet=path,
                body=body_template_file,
                subject="Hello {{name}}",
                email_column="email",
            )

    def test_malformed_emails_skipped(self, tmp_path, body_template_file, caplog):
        """Malformed emails (missing @, no domain, etc.) are skipped."""
        path = tmp_path / "malformed.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["name", "email", "company"])
        ws.append(["Alice", "alice@example.com", "Acme"])
        ws.append(["NoAt", "noatsign", "Corp"])
        ws.append(["NoDomain", "user@", "Corp"])
        ws.append(["Empty", "", "Corp"])
        wb.save(path)

        with caplog.at_level(logging.WARNING):
            results = send_merge(
                spreadsheet=path,
                body=body_template_file,
                subject="Hello {{name}}",
                email_column="email",
            )
        assert len(results) == 1
        assert results[0].email == "alice@example.com"
        assert "noatsign" in caplog.text
        assert "user@" in caplog.text

    def test_valid_edge_cases_pass(self, tmp_path, body_template_file):
        """Plus-addressing and subdomains are valid and should pass."""
        path = tmp_path / "valid_edge.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["name", "email", "company"])
        ws.append(["Plus", "user+tag@example.com", "Acme"])
        ws.append(["Sub", "user@mail.sub.example.com", "Acme"])
        wb.save(path)

        results = send_merge(
            spreadsheet=path,
            body=body_template_file,
            subject="Hello {{name}}",
            email_column="email",
        )
        assert len(results) == 2
        emails = {r.email for r in results}
        assert "user+tag@example.com" in emails
        assert "user@mail.sub.example.com" in emails


class TestEmptyRecipients:
    def test_empty_spreadsheet_raises(self, tmp_path, body_template_file):
        """Spreadsheet with headers but no data rows raises ValueError."""
        path = tmp_path / "headers_only.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["name", "email", "company"])
        wb.save(path)

        with pytest.raises(ValueError, match="No recipients found"):
            send_merge(
                spreadsheet=path,
                body=body_template_file,
                subject="Hello {{name}}",
                email_column="email",
            )

    def test_apply_filters_empty_recipients(self):
        """apply_filters with empty list returns empty list."""
        from mail_merge.api import apply_filters
        result = apply_filters([], ["company=Acme"])
        assert result == []


class TestParseAddressEntries:
    def test_empty_string_returns_none(self):
        from mail_merge.api import _parse_address_entries
        assert _parse_address_entries("") is None

    def test_whitespace_only_returns_none(self):
        from mail_merge.api import _parse_address_entries
        assert _parse_address_entries("  ,  , ") is None

    def test_empty_list_returns_none(self):
        from mail_merge.api import _parse_address_entries
        assert _parse_address_entries(["", " "]) is None


class TestBatchSizeEmptyBatch:
    def test_batch_size_zero_returns_previous(self, sample_xlsx, body_template_file, tmp_path):
        """batch_size=0 means no recipients in this batch."""
        output = tmp_path / "report.csv"
        write_csv([
            SendResult(email="alice@example.com", success=True, status_code=202),
        ], output)

        results = send_merge(
            spreadsheet=sample_xlsx,
            body=body_template_file,
            subject="Hello {{name}}",
            email_column="email",
            output=output,
            resume=True,
            batch_size=0,
        )
        # Only the previous result (Alice), no new sends
        assert len(results) == 1
        assert results[0].email == "alice@example.com"


class TestAuthFailure:
    def test_auth_exception_wrapped_in_runtime_error(
        self, sample_xlsx, body_template_file, monkeypatch
    ):
        """When acquire_token raises, it's wrapped in a RuntimeError."""
        monkeypatch.setattr(
            "mail_merge.auth.acquire_token",
            lambda *a, **kw: (_ for _ in ()).throw(ConnectionError("network down")),
        )
        with pytest.raises(RuntimeError, match="Authentication failed.*network down"):
            send_merge(
                spreadsheet=sample_xlsx,
                body=body_template_file,
                subject="Hello {{name}}",
                email_column="email",
                client_id="fake-client-id",
                send=True,
                confirm=False,
            )


class TestAuthError:
    def test_missing_client_id(self, sample_xlsx, body_template_file, monkeypatch):
        monkeypatch.delenv("MAIL_MERGE_CLIENT_ID", raising=False)
        monkeypatch.setattr("mail_merge.config.DEFAULT_PATH", sample_xlsx.parent / "nope.toml")
        with pytest.raises(RuntimeError, match="client-id is required"):
            send_merge(
                spreadsheet=sample_xlsx,
                body=body_template_file,
                subject="Hello {{name}}",
                email_column="email",
                send=True,
                confirm=False,
            )


class TestPassThrough:
    @responses.activate
    def test_html_attachment_reply_to(self, sample_xlsx, body_template_file, tmp_path, monkeypatch):
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        monkeypatch.setattr("mail_merge.auth.acquire_token", lambda client_id, tenant_id="common": "fake-token")
        monkeypatch.setattr("mail_merge.auth.acquire_token_interactive_flow", lambda *a, **kw: "fake-token")

        att = tmp_path / "file.txt"
        att.write_text("data", encoding="utf-8")

        results = send_merge(
            spreadsheet=sample_xlsx,
            body=body_template_file,
            subject="Hello {{name}}",
            email_column="email",
            client_id="fake-client-id",
            test_email="tester@example.com",
            send=True,
            html=True,
            attachment=[att],
            reply_to=["reply@example.com", "other@example.com"],
        )
        assert len(results) == 1
        assert results[0].success

        assert isinstance(responses.calls[0].request.body, (str, bytes))
        payload = json.loads(responses.calls[0].request.body)
        assert payload["message"]["body"]["contentType"] == "HTML"
        assert len(payload["message"]["attachments"]) == 1
        assert payload["message"]["attachments"][0]["name"] == "file.txt"
        reply_addrs = [r["emailAddress"]["address"] for r in payload["message"]["replyTo"]]
        assert reply_addrs == ["reply@example.com", "other@example.com"]

    @responses.activate
    def test_cc_bcc_as_lists(self, sample_xlsx, body_template_file, monkeypatch):
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        monkeypatch.setattr("mail_merge.auth.acquire_token", lambda client_id, tenant_id="common": "fake-token")
        monkeypatch.setattr("mail_merge.auth.acquire_token_interactive_flow", lambda *a, **kw: "fake-token")

        results = send_merge(
            spreadsheet=sample_xlsx,
            body=body_template_file,
            subject="Hello {{name}}",
            email_column="email",
            client_id="fake-client-id",
            test_email="tester@example.com",
            send=True,
            cc=["a@x.com", "b@x.com"],
            bcc="c@x.com",
        )
        assert results[0].success

        assert isinstance(responses.calls[0].request.body, (str, bytes))
        payload = json.loads(responses.calls[0].request.body)
        cc_addrs = [r["emailAddress"]["address"] for r in payload["message"]["ccRecipients"]]
        assert cc_addrs == ["a@x.com", "b@x.com"]
        bcc_addrs = [r["emailAddress"]["address"] for r in payload["message"]["bccRecipients"]]
        assert bcc_addrs == ["c@x.com"]


class TestFilter:
    def test_equality_filter(self, sample_xlsx, body_template_file):
        results = send_merge(
            spreadsheet=sample_xlsx,
            body=body_template_file,
            subject="Hello {{name}}",
            email_column="email",
            filters=["company=Acme"],
        )
        assert len(results) == 1
        assert results[0].email == "alice@example.com"

    def test_not_equal_filter(self, sample_xlsx, body_template_file):
        results = send_merge(
            spreadsheet=sample_xlsx,
            body=body_template_file,
            subject="Hello {{name}}",
            email_column="email",
            filters=["company!=Acme"],
        )
        assert len(results) == 1
        assert results[0].email == "bob@example.com"

    def test_multiple_filters_and_logic(self, tmp_path):
        """Multiple filters use AND logic — all must match."""
        import openpyxl

        path = tmp_path / "multi.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["name", "email", "role", "group"])
        ws.append(["Alice", "alice@example.com", "PhD", "Security"])
        ws.append(["Bob", "bob@example.com", "PhD", "Networks"])
        ws.append(["Carol", "carol@example.com", "MSc", "Security"])
        wb.save(path)

        body = tmp_path / "body.txt"
        body.write_text("Hi {{name}}", encoding="utf-8")

        results = send_merge(
            spreadsheet=path,
            body=body,
            subject="Hello {{name}}",
            email_column="email",
            filters=["role=PhD", "group=Security"],
        )
        assert len(results) == 1
        assert results[0].email == "alice@example.com"

    def test_case_insensitive(self, sample_xlsx, body_template_file):
        results = send_merge(
            spreadsheet=sample_xlsx,
            body=body_template_file,
            subject="Hello {{name}}",
            email_column="email",
            filters=["Company=acme"],
        )
        assert len(results) == 1
        assert results[0].email == "alice@example.com"

    def test_no_match_raises(self, sample_xlsx, body_template_file):
        with pytest.raises(ValueError, match="No recipients match"):
            send_merge(
                spreadsheet=sample_xlsx,
                body=body_template_file,
                subject="Hello {{name}}",
                email_column="email",
                    filters=["company=NonExistent"],
            )

    def test_bad_syntax_raises(self, sample_xlsx, body_template_file):
        with pytest.raises(ValueError, match="Invalid filter syntax"):
            send_merge(
                spreadsheet=sample_xlsx,
                body=body_template_file,
                subject="Hello {{name}}",
                email_column="email",
                    filters=["no-operator-here"],
            )

    def test_unknown_column_raises(self, sample_xlsx, body_template_file):
        with pytest.raises(ValueError, match="Filter column.*not found"):
            send_merge(
                spreadsheet=sample_xlsx,
                body=body_template_file,
                subject="Hello {{name}}",
                email_column="email",
                    filters=["nonexistent=value"],
            )


class TestResume:
    def test_resume_skips_successful(self, sample_xlsx, body_template_file, tmp_path):
        """Resume skips recipients that previously succeeded."""

        output = tmp_path / "report.csv"
        # Alice succeeded previously
        write_csv([
            SendResult(email="alice@example.com", success=True, status_code=202),
        ], output)

        results = send_merge(
            spreadsheet=sample_xlsx,
            body=body_template_file,
            subject="Hello {{name}}",
            email_column="email",
            output=output,
            resume=True,
        )
        # Should have sent to Bob only, plus Alice from previous
        emails = {r.email for r in results}
        assert "alice@example.com" in emails
        assert "bob@example.com" in emails
        # Bob was the only one actually sent in this run
        bob = next(r for r in results if r.email == "bob@example.com")
        assert bob.success

    def test_resume_retries_failed(self, sample_xlsx, body_template_file, tmp_path):
        """Resume retries recipients that previously failed."""

        output = tmp_path / "report.csv"
        write_csv([
            SendResult(email="alice@example.com", success=True, status_code=202),
            SendResult(email="bob@example.com", success=False, status_code=500, error="Server error"),
        ], output)

        results = send_merge(
            spreadsheet=sample_xlsx,
            body=body_template_file,
            subject="Hello {{name}}",
            email_column="email",
            output=output,
            resume=True,
        )
        bob = next(r for r in results if r.email == "bob@example.com")
        assert bob.success  # dry run always succeeds

    def test_resume_all_sent_returns_previous(self, sample_xlsx, body_template_file, tmp_path):
        """When all recipients already succeeded, return previous results."""

        output = tmp_path / "report.csv"
        write_csv([
            SendResult(email="alice@example.com", success=True, status_code=202),
            SendResult(email="bob@example.com", success=True, status_code=202),
        ], output)

        results = send_merge(
            spreadsheet=sample_xlsx,
            body=body_template_file,
            subject="Hello {{name}}",
            email_column="email",
            output=output,
            resume=True,
        )
        assert len(results) == 2
        assert all(r.success for r in results)

    def test_resume_without_output_skips_silently(self, sample_xlsx, body_template_file):
        """Resume without output just runs normally (no error)."""
        results = send_merge(
            spreadsheet=sample_xlsx,
            body=body_template_file,
            subject="Hello {{name}}",
            email_column="email",
            resume=True,
        )
        assert len(results) == 2
        assert all(r.success for r in results)


class TestBatchSize:
    def test_batch_size_limits_sends(self, sample_xlsx, body_template_file):
        results = send_merge(
            spreadsheet=sample_xlsx,
            body=body_template_file,
            subject="Hello {{name}}",
            email_column="email",
            batch_size=1,
        )
        assert len(results) == 1

    def test_resume_with_batch_size(self, sample_xlsx, body_template_file, tmp_path):
        """Resume + batch_size sends next batch of remaining."""

        output = tmp_path / "report.csv"
        write_csv([
            SendResult(email="alice@example.com", success=True, status_code=202),
        ], output)

        results = send_merge(
            spreadsheet=sample_xlsx,
            body=body_template_file,
            subject="Hello {{name}}",
            email_column="email",
            output=output,
            resume=True,
            batch_size=1,
        )
        # Should have Alice (previous) + Bob (this batch)
        assert len(results) == 2
        bob = next(r for r in results if r.email == "bob@example.com")
        assert bob.success


class TestConfigResolution:
    def test_client_id_from_config(self, sample_xlsx, body_template_file, tmp_path, monkeypatch):
        cfg = tmp_path / "config.toml"
        cfg.write_text('client-id = "cfg-client"\ntenant-id = "cfg-tenant"\n', encoding="utf-8")
        monkeypatch.setattr("mail_merge.config.DEFAULT_PATH", cfg)
        monkeypatch.delenv("MAIL_MERGE_CLIENT_ID", raising=False)
        monkeypatch.delenv("MAIL_MERGE_TENANT_ID", raising=False)

        # dry run so no auth needed, but client_id should resolve
        results = send_merge(
            spreadsheet=sample_xlsx,
            body=body_template_file,
            subject="Hello {{name}}",
            email_column="email",
        )
        assert len(results) == 2


class TestTokenExpiryWarning:
    @responses.activate
    def test_warns_when_token_expires_before_send_completes(
        self, sample_xlsx, body_template_file, monkeypatch, caplog
    ):
        """Warning is logged when estimated send time exceeds token lifetime."""
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)

        # Build a JWT with exp = now + 60 seconds (1 minute)
        exp = int(time.time()) + 60
        payload = base64.urlsafe_b64encode(
            json.dumps({"exp": exp}).encode()
        ).rstrip(b"=").decode()
        fake_jwt = f"header.{payload}.signature"

        monkeypatch.setattr(
            "mail_merge.auth.acquire_token",
            lambda client_id, tenant_id="common": fake_jwt,
        )

        with caplog.at_level(logging.WARNING):
            send_merge(
                spreadsheet=sample_xlsx,
                body=body_template_file,
                subject="Hello {{name}}",
                email_column="email",
                client_id="fake-client-id",
                test_email="me@example.com",
                delay=120.0,  # 2 recipients * 120s = 240s > 60s token lifetime
            )

        assert any("Token expires" in msg for msg in caplog.messages)


class TestTokenExpiresAt:
    def test_valid_jwt(self):
        from datetime import datetime, timezone

        from mail_merge.auth import token_expires_at

        exp = 1700000000
        payload = base64.urlsafe_b64encode(
            json.dumps({"exp": exp}).encode()
        ).rstrip(b"=").decode()
        token = f"header.{payload}.signature"

        result = token_expires_at(token)
        assert result == datetime.fromtimestamp(exp, tz=timezone.utc)

    def test_invalid_token_returns_none(self):
        from mail_merge.auth import token_expires_at

        assert token_expires_at("not-a-jwt") is None
        assert token_expires_at("a.b") is None
        assert token_expires_at("") is None
        assert token_expires_at("a.!!!.c") is None

    def test_missing_exp_returns_none(self):
        from mail_merge.auth import token_expires_at

        payload = base64.urlsafe_b64encode(
            json.dumps({"sub": "user"}).encode()
        ).rstrip(b"=").decode()
        token = f"header.{payload}.signature"

        assert token_expires_at(token) is None


class TestParseFilter:
    """Unit tests for _parse_filter edge cases not reachable via send_merge."""

    def setup_method(self):
        from mail_merge.api import _parse_filter
        self._parse_filter = _parse_filter

    def test_empty_lhs_equals_raises(self):
        """'=value' has empty left-hand side → ValueError."""
        with pytest.raises(ValueError, match="Invalid filter syntax"):
            self._parse_filter("=value")

    def test_empty_rhs_equals_raises(self):
        """'column=' has empty right-hand side → ValueError."""
        with pytest.raises(ValueError, match="Invalid filter syntax"):
            self._parse_filter("column=")

    def test_empty_lhs_not_equals_raises(self):
        """'!=value' has empty left-hand side → ValueError."""
        with pytest.raises(ValueError, match="Invalid filter syntax"):
            self._parse_filter("!=value")

    def test_empty_rhs_not_equals_raises(self):
        """'column!=' has empty right-hand side → ValueError."""
        with pytest.raises(ValueError, match="Invalid filter syntax"):
            self._parse_filter("column!=")

    def test_valid_equals(self):
        assert self._parse_filter("col=val") == ("col", "=", "val")

    def test_valid_not_equals(self):
        assert self._parse_filter("col!=val") == ("col", "!=", "val")


class TestConfirmDisplay:
    @responses.activate
    def test_confirm_shows_cc_bcc_and_attachments(
        self, sample_xlsx, body_template_file, tmp_path, monkeypatch
    ):
        """Confirmation prompt prints CC, BCC, and attachment lines when present."""
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        monkeypatch.setattr("mail_merge.auth.acquire_token", lambda client_id, tenant_id="common": "fake-token")
        monkeypatch.setattr("mail_merge.auth.acquire_token_interactive_flow", lambda *a, **kw: "fake-token")

        att = tmp_path / "report.pdf"
        att.write_bytes(b"PDF content")

        printed_lines: list[str] = []
        original_print = __import__("mail_merge.console", fromlist=["console"]).console.print

        def capture_print(text="", *args, **kwargs):
            printed_lines.append(str(text))
            return original_print(text, *args, **kwargs)

        monkeypatch.setattr("mail_merge.console.console.print", capture_print)
        monkeypatch.setattr("mail_merge.console.console.input", lambda prompt: "y")

        send_merge(
            spreadsheet=sample_xlsx,
            body=body_template_file,
            subject="Hello {{name}}",
            email_column="email",
            client_id="fake-client-id",
            send=True,
            cc="cc@example.com",
            bcc="bcc@example.com",
            attachment=[att],
            confirm=True,
        )

        combined = "\n".join(printed_lines)
        assert "cc@example.com" in combined
        assert "bcc@example.com" in combined
        assert "report.pdf" in combined


class TestTokenRefreshFailure:
    @responses.activate
    def test_token_refresh_failure_logs_warning_and_continues(
        self, sample_xlsx, body_template_file, monkeypatch, caplog
    ):
        """When preflight token refresh raises, a warning is logged and sending proceeds."""
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)

        # Build a JWT that expires soon (< 5 min → triggers preflight refresh)
        exp = int(time.time()) + 60
        payload_b64 = base64.urlsafe_b64encode(
            json.dumps({"exp": exp}).encode()
        ).rstrip(b"=").decode()
        expiring_jwt = f"header.{payload_b64}.signature"

        call_count = 0

        def fake_acquire(client_id, tenant_id="common"):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return expiring_jwt       # initial auth
            if call_count == 2:
                raise RuntimeError("refresh failed")   # preflight refresh fails
            return "fresh-token"          # subsequent get_token calls in send_one

        monkeypatch.setattr("mail_merge.auth.acquire_token", fake_acquire)
        monkeypatch.setattr("mail_merge.auth.acquire_token_interactive_flow", fake_acquire)

        with caplog.at_level(logging.WARNING):
            results = send_merge(
                spreadsheet=sample_xlsx,
                body=body_template_file,
                subject="Hello {{name}}",
                email_column="email",
                client_id="fake-client-id",
                test_email="me@example.com",
            )

        assert any("Token refresh failed" in msg for msg in caplog.messages)
        assert results[0].success


class TestBccBlast:
    @responses.activate
    def test_test_email_sends_to_single_address(self, sample_xlsx, tmp_path, monkeypatch):
        """--bcc-blast + --test-email sends the blast to just the test address."""
        import mail_merge.auth as auth_module

        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        monkeypatch.setattr(auth_module, "acquire_token", lambda *a, **kw: "fake-tok")
        monkeypatch.setattr(auth_module, "acquire_token_interactive_flow", lambda *a, **kw: "fake-tok")
        monkeypatch.setattr("mail_merge.auth.token_expires_at", lambda tok: None)

        body = tmp_path / "body.txt"
        body.write_text("Hello everyone.", encoding="utf-8")
        results = send_merge(
            spreadsheet=sample_xlsx,
            body=body,
            subject="Announcement",
            email_column="email",
            client_id="fake-client",
            bcc_blast=True,
            bcc_blast_to="noreply@x.com",
            test_email="tester@x.com",
        )
        # One per-recipient result for the test address, one HTTP call
        assert len(results) == 1
        assert results[0].success
        assert results[0].email == "tester@x.com"
        assert len(responses.calls) == 1
        payload = json.loads(responses.calls[0].request.body)
        bcc_addrs = [b["emailAddress"]["address"] for b in payload["message"]["bccRecipients"]]
        # Only the test address should be in BCC — not the spreadsheet recipients
        assert bcc_addrs == ["tester@x.com"]
        assert "alice@example.com" not in bcc_addrs

    def test_conflict_with_batch_size(self, sample_xlsx, body_template_file):
        """--bcc-blast and --batch-size are mutually exclusive."""
        with pytest.raises(ValueError, match="--batch-size is not supported"):
            send_merge(
                spreadsheet=sample_xlsx,
                body=body_template_file,
                subject="Static subject",
                email_column="email",
                bcc_blast=True,
                bcc_blast_to="noreply@x.com",
                batch_size=10,
            )

    def test_missing_bcc_blast_to_raises(self, sample_xlsx, body_template_file):
        """bcc_blast=True without bcc_blast_to raises ValueError."""
        with pytest.raises(ValueError, match="bcc_blast_to is required"):
            send_merge(
                spreadsheet=sample_xlsx,
                body=body_template_file,
                subject="Static subject",
                email_column="email",
                bcc_blast=True,
            )

    def test_placeholder_in_subject_rejected(self, sample_xlsx, body_template_file):
        """BCC blast mode rejects subjects that contain {{placeholders}}."""
        with pytest.raises(ValueError, match="does not support placeholders"):
            send_merge(
                spreadsheet=sample_xlsx,
                body=body_template_file,
                subject="Hello {{name}}",
                email_column="email",
                bcc_blast=True,
                bcc_blast_to="noreply@x.com",
            )

    def test_placeholder_in_body_rejected(self, sample_xlsx, tmp_path):
        """BCC blast mode rejects bodies that contain {{placeholders}}."""
        body_with_ph = tmp_path / "body.txt"
        body_with_ph.write_text("Dear {{name}},\nHello.", encoding="utf-8")
        with pytest.raises(ValueError, match="does not support placeholders"):
            send_merge(
                spreadsheet=sample_xlsx,
                body=body_with_ph,
                subject="Static subject",
                email_column="email",
                bcc_blast=True,
                bcc_blast_to="noreply@x.com",
            )

    @responses.activate
    def test_dry_run_blast(self, sample_xlsx, tmp_path):
        """Dry-run BCC blast returns per-recipient results without HTTP calls."""
        body = tmp_path / "body.txt"
        body.write_text("Hello everyone.", encoding="utf-8")
        results = send_merge(
            spreadsheet=sample_xlsx,
            body=body,
            subject="Announcement",
            email_column="email",
            bcc_blast=True,
            bcc_blast_to="noreply@x.com",
            send=False,
        )
        # Should have one result per recipient (2 recipients fit in one batch)
        assert len(results) == 2
        assert all(r.success for r in results)
        emails = {r.email for r in results}
        assert "alice@example.com" in emails
        assert "bob@example.com" in emails
        # No real HTTP calls in dry run
        assert len(responses.calls) == 0

    @responses.activate
    def test_live_blast_sends(self, sample_xlsx, tmp_path, monkeypatch):
        """Live BCC blast authenticates and sends batches via HTTP."""
        import mail_merge.auth as auth_module

        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        monkeypatch.setattr(
            auth_module, "acquire_token", lambda *a, **kw: "fake-tok"
        )
        monkeypatch.setattr(
            auth_module, "acquire_token_interactive_flow", lambda *a, **kw: "fake-tok"
        )
        monkeypatch.setattr(
            "mail_merge.auth.token_expires_at", lambda tok: None
        )

        body = tmp_path / "body.txt"
        body.write_text("Hello everyone.", encoding="utf-8")
        results = send_merge(
            spreadsheet=sample_xlsx,
            body=body,
            subject="Announcement",
            email_column="email",
            client_id="fake-client",
            bcc_blast=True,
            bcc_blast_to="noreply@x.com",
            send=True,
            confirm=False,
        )
        assert len(results) == 2
        assert all(r.success for r in results)
        assert {r.email for r in results} == {"alice@example.com", "bob@example.com"}
        assert len(responses.calls) == 1
        payload = json.loads(responses.calls[0].request.body)
        # Recipients should appear as BCC, not To
        bcc_addrs = [b["emailAddress"]["address"] for b in payload["message"]["bccRecipients"]]
        assert "alice@example.com" in bcc_addrs
        assert "bob@example.com" in bcc_addrs

    @responses.activate
    def test_bcc_blast_to_display_name(self, sample_xlsx, tmp_path, monkeypatch):
        """'Name <email>' format in bcc_blast_to sets the To display name."""
        import mail_merge.auth as auth_module

        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        monkeypatch.setattr(auth_module, "acquire_token", lambda *a, **kw: "fake-tok")
        monkeypatch.setattr(auth_module, "acquire_token_interactive_flow", lambda *a, **kw: "fake-tok")
        monkeypatch.setattr("mail_merge.auth.token_expires_at", lambda tok: None)

        body = tmp_path / "body.txt"
        body.write_text("Hello everyone.", encoding="utf-8")
        results = send_merge(
            spreadsheet=sample_xlsx,
            body=body,
            subject="Announcement",
            email_column="email",
            client_id="fake-client",
            bcc_blast=True,
            bcc_blast_to="Undisclosed recipients <noreply@x.com>",
            send=True,
            confirm=False,
        )
        assert results[0].success
        payload = json.loads(responses.calls[0].request.body)
        to_field = payload["message"]["toRecipients"][0]["emailAddress"]
        assert to_field["address"] == "noreply@x.com"
        assert to_field["name"] == "Undisclosed recipients"

    @responses.activate
    def test_bcc_blast_to_plain_address_no_name(self, sample_xlsx, tmp_path, monkeypatch):
        """Plain address in bcc_blast_to sets no display name in the payload."""
        import mail_merge.auth as auth_module

        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        monkeypatch.setattr(auth_module, "acquire_token", lambda *a, **kw: "fake-tok")
        monkeypatch.setattr(auth_module, "acquire_token_interactive_flow", lambda *a, **kw: "fake-tok")
        monkeypatch.setattr("mail_merge.auth.token_expires_at", lambda tok: None)

        body = tmp_path / "body.txt"
        body.write_text("Hello everyone.", encoding="utf-8")
        results = send_merge(
            spreadsheet=sample_xlsx,
            body=body,
            subject="Announcement",
            email_column="email",
            client_id="fake-client",
            bcc_blast=True,
            bcc_blast_to="noreply@x.com",
            send=True,
            confirm=False,
        )
        assert results[0].success
        payload = json.loads(responses.calls[0].request.body)
        to_field = payload["message"]["toRecipients"][0]["emailAddress"]
        assert to_field["address"] == "noreply@x.com"
        assert "name" not in to_field


class TestBccBlastResume:
    """BCC blast supports resume via --output, skipping already-successful recipients."""

    def test_resume_skips_successful_recipients(self, sample_xlsx, tmp_path):
        """Resume skips recipients that previously succeeded in a BCC blast."""

        body = tmp_path / "body.txt"
        body.write_text("Hello everyone.", encoding="utf-8")
        output = tmp_path / "report.csv"

        # Alice succeeded previously
        write_csv([
            SendResult(email="alice@example.com", success=True, status_code=202),
        ], output)

        results = send_merge(
            spreadsheet=sample_xlsx,
            body=body,
            subject="Announcement",
            email_column="email",
            bcc_blast=True,
            bcc_blast_to="noreply@x.com",
            output=output,
            resume=True,
        )
        # Should have Alice (previous) + Bob (this run)
        emails = {r.email for r in results}
        assert "alice@example.com" in emails
        assert "bob@example.com" in emails
        bob = next(r for r in results if r.email == "bob@example.com")
        assert bob.success

    def test_resume_retries_failed_recipients(self, sample_xlsx, tmp_path):
        """Resume retries recipients that previously failed in a BCC blast."""

        body = tmp_path / "body.txt"
        body.write_text("Hello everyone.", encoding="utf-8")
        output = tmp_path / "report.csv"

        write_csv([
            SendResult(email="alice@example.com", success=True, status_code=202),
            SendResult(email="bob@example.com", success=False, status_code=500, error="Server error"),
        ], output)

        results = send_merge(
            spreadsheet=sample_xlsx,
            body=body,
            subject="Announcement",
            email_column="email",
            bcc_blast=True,
            bcc_blast_to="noreply@x.com",
            output=output,
            resume=True,
        )
        bob = next(r for r in results if r.email == "bob@example.com")
        assert bob.success  # dry run always succeeds

    def test_resume_all_sent_returns_previous(self, sample_xlsx, tmp_path):
        """When all recipients already succeeded, return previous results."""

        body = tmp_path / "body.txt"
        body.write_text("Hello everyone.", encoding="utf-8")
        output = tmp_path / "report.csv"

        write_csv([
            SendResult(email="alice@example.com", success=True, status_code=202),
            SendResult(email="bob@example.com", success=True, status_code=202),
        ], output)

        results = send_merge(
            spreadsheet=sample_xlsx,
            body=body,
            subject="Announcement",
            email_column="email",
            bcc_blast=True,
            bcc_blast_to="noreply@x.com",
            output=output,
            resume=True,
        )
        assert len(results) == 2
        assert all(r.success for r in results)

    @responses.activate
    def test_resume_csv_round_trip(self, sample_xlsx, tmp_path, monkeypatch):
        """Full round trip: first send writes CSV, re-run skips successes."""
        import mail_merge.auth as auth_module

        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        monkeypatch.setattr(auth_module, "acquire_token", lambda *a, **kw: "fake-tok")
        monkeypatch.setattr(auth_module, "acquire_token_interactive_flow", lambda *a, **kw: "fake-tok")
        monkeypatch.setattr("mail_merge.auth.token_expires_at", lambda tok: None)

        body = tmp_path / "body.txt"
        body.write_text("Hello everyone.", encoding="utf-8")
        output = tmp_path / "report.csv"

        # First run: sends to both recipients
        results = send_merge(
            spreadsheet=sample_xlsx,
            body=body,
            subject="Announcement",
            email_column="email",
            client_id="fake-client",
            bcc_blast=True,
            bcc_blast_to="noreply@x.com",
            send=True,
            confirm=False,
            output=output,
        )
        assert len(results) == 2
        assert all(r.success for r in results)
        assert output.exists()

        # Second run: resume skips all (already succeeded)
        results2 = send_merge(
            spreadsheet=sample_xlsx,
            body=body,
            subject="Announcement",
            email_column="email",
            client_id="fake-client",
            bcc_blast=True,
            bcc_blast_to="noreply@x.com",
            send=True,
            confirm=False,
            output=output,
        )
        assert len(results2) == 2
        assert all(r.success for r in results2)
        # No additional HTTP calls — everything was already sent
        assert len(responses.calls) == 1  # only the first run's single batch


class TestAddressDisplayNames:
    """CC, BCC, and reply-to accept 'Display Name <email>' format."""

    @responses.activate
    def test_cc_display_name(self, sample_xlsx, body_template_file, monkeypatch):
        """'Name <email>' in --cc sets the display name in the Graph payload."""
        import mail_merge.auth as auth_module

        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        monkeypatch.setattr(auth_module, "acquire_token", lambda *a, **kw: "fake-tok")
        monkeypatch.setattr(auth_module, "acquire_token_interactive_flow", lambda *a, **kw: "fake-tok")
        monkeypatch.setattr("mail_merge.auth.token_expires_at", lambda tok: None)

        send_merge(
            spreadsheet=sample_xlsx,
            body=body_template_file,
            subject="Hi {{name}}",
            email_column="email",
            client_id="fake-client",
            cc="Manager <manager@example.com>",
            send=True,
            confirm=False,
        )
        payload = json.loads(responses.calls[0].request.body)
        cc_field = payload["message"]["ccRecipients"][0]["emailAddress"]
        assert cc_field["address"] == "manager@example.com"
        assert cc_field["name"] == "Manager"

    @responses.activate
    def test_bcc_plain_address_no_name(self, sample_xlsx, body_template_file, monkeypatch):
        """Plain address in --bcc produces no name field in payload."""
        import mail_merge.auth as auth_module

        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        monkeypatch.setattr(auth_module, "acquire_token", lambda *a, **kw: "fake-tok")
        monkeypatch.setattr(auth_module, "acquire_token_interactive_flow", lambda *a, **kw: "fake-tok")
        monkeypatch.setattr("mail_merge.auth.token_expires_at", lambda tok: None)

        send_merge(
            spreadsheet=sample_xlsx,
            body=body_template_file,
            subject="Hi {{name}}",
            email_column="email",
            client_id="fake-client",
            bcc="archive@example.com",
            send=True,
            confirm=False,
        )
        payload = json.loads(responses.calls[0].request.body)
        bcc_field = payload["message"]["bccRecipients"][0]["emailAddress"]
        assert bcc_field["address"] == "archive@example.com"
        assert "name" not in bcc_field

    @responses.activate
    def test_reply_to_display_name(self, sample_xlsx, body_template_file, monkeypatch):
        """'Name <email>' in --reply-to sets the display name in the Graph payload."""
        import mail_merge.auth as auth_module

        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        monkeypatch.setattr(auth_module, "acquire_token", lambda *a, **kw: "fake-tok")
        monkeypatch.setattr(auth_module, "acquire_token_interactive_flow", lambda *a, **kw: "fake-tok")
        monkeypatch.setattr("mail_merge.auth.token_expires_at", lambda tok: None)

        send_merge(
            spreadsheet=sample_xlsx,
            body=body_template_file,
            subject="Hi {{name}}",
            email_column="email",
            client_id="fake-client",
            reply_to="Support Team <support@example.com>",
            send=True,
            confirm=False,
        )
        payload = json.loads(responses.calls[0].request.body)
        rt_field = payload["message"]["replyTo"][0]["emailAddress"]
        assert rt_field["address"] == "support@example.com"
        assert rt_field["name"] == "Support Team"

    @responses.activate
    def test_comma_separated_mixed_formats(self, sample_xlsx, body_template_file, monkeypatch):
        """Comma-separated list can mix plain addresses and 'Name <email>' format."""
        import mail_merge.auth as auth_module

        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        monkeypatch.setattr(auth_module, "acquire_token", lambda *a, **kw: "fake-tok")
        monkeypatch.setattr(auth_module, "acquire_token_interactive_flow", lambda *a, **kw: "fake-tok")
        monkeypatch.setattr("mail_merge.auth.token_expires_at", lambda tok: None)

        send_merge(
            spreadsheet=sample_xlsx,
            body=body_template_file,
            subject="Hi {{name}}",
            email_column="email",
            client_id="fake-client",
            cc="plain@example.com, Named Person <named@example.com>",
            send=True,
            confirm=False,
        )
        payload = json.loads(responses.calls[0].request.body)
        cc_fields = [e["emailAddress"] for e in payload["message"]["ccRecipients"]]
        assert cc_fields[0]["address"] == "plain@example.com"
        assert "name" not in cc_fields[0]
        assert cc_fields[1]["address"] == "named@example.com"
        assert cc_fields[1]["name"] == "Named Person"


class TestNameColumn:
    """--name-column includes recipient display names in the To: header."""

    @responses.activate
    def test_name_column_sets_to_name(self, sample_xlsx, body_template_file, monkeypatch):
        """With name_column, each recipient's To: header includes their name."""
        import mail_merge.auth as auth_module

        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        monkeypatch.setattr(auth_module, "acquire_token", lambda *a, **kw: "fake-tok")
        monkeypatch.setattr(auth_module, "acquire_token_interactive_flow", lambda *a, **kw: "fake-tok")
        monkeypatch.setattr("mail_merge.auth.token_expires_at", lambda tok: None)

        send_merge(
            spreadsheet=sample_xlsx,
            body=body_template_file,
            subject="Hi {{name}}",
            email_column="email",
            client_id="fake-client",
            send=True,
            confirm=False,
            name_column="name",
        )
        # First recipient: Alice
        payload1 = json.loads(responses.calls[0].request.body)
        to1 = payload1["message"]["toRecipients"][0]["emailAddress"]
        assert to1["address"] == "alice@example.com"
        assert to1["name"] == "Alice"
        # Second recipient: Bob
        payload2 = json.loads(responses.calls[1].request.body)
        to2 = payload2["message"]["toRecipients"][0]["emailAddress"]
        assert to2["address"] == "bob@example.com"
        assert to2["name"] == "Bob"

    def test_no_name_column_omits_name(self, sample_xlsx, body_template_file):
        """Without name_column, no display name in To: header (dry run)."""
        results = send_merge(
            spreadsheet=sample_xlsx,
            body=body_template_file,
            subject="Hi {{name}}",
            email_column="email",
        )
        assert len(results) == 2
        assert all(r.success for r in results)

    def test_invalid_name_column_raises(self, sample_xlsx, body_template_file):
        """An invalid name_column raises ValueError."""
        import pytest

        with pytest.raises(ValueError, match="not found"):
            send_merge(
                spreadsheet=sample_xlsx,
                body=body_template_file,
                subject="Hi {{name}}",
                email_column="email",
                name_column="nonexistent",
            )
