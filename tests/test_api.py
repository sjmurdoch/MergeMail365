import json
from pathlib import Path

import pytest
import responses

from mail_merge.api import send_merge
from mail_merge.sender import GRAPH_SEND_URL


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

        att = tmp_path / "file.txt"
        att.write_text("data")

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
            filter=["company=Acme"],
        )
        assert len(results) == 1
        assert results[0].email == "alice@example.com"

    def test_not_equal_filter(self, sample_xlsx, body_template_file):
        results = send_merge(
            spreadsheet=sample_xlsx,
            body=body_template_file,
            subject="Hello {{name}}",
            email_column="email",
            filter=["company!=Acme"],
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
        body.write_text("Hi {{name}}")

        results = send_merge(
            spreadsheet=path,
            body=body,
            subject="Hello {{name}}",
            email_column="email",
            filter=["role=PhD", "group=Security"],
        )
        assert len(results) == 1
        assert results[0].email == "alice@example.com"

    def test_case_insensitive(self, sample_xlsx, body_template_file):
        results = send_merge(
            spreadsheet=sample_xlsx,
            body=body_template_file,
            subject="Hello {{name}}",
            email_column="email",
            filter=["Company=acme"],
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
                    filter=["company=NonExistent"],
            )

    def test_bad_syntax_raises(self, sample_xlsx, body_template_file):
        with pytest.raises(ValueError, match="Invalid filter syntax"):
            send_merge(
                spreadsheet=sample_xlsx,
                body=body_template_file,
                subject="Hello {{name}}",
                email_column="email",
                    filter=["no-operator-here"],
            )

    def test_unknown_column_raises(self, sample_xlsx, body_template_file):
        with pytest.raises(ValueError, match="Filter column.*not found"):
            send_merge(
                spreadsheet=sample_xlsx,
                body=body_template_file,
                subject="Hello {{name}}",
                email_column="email",
                    filter=["nonexistent=value"],
            )


class TestResume:
    def test_resume_skips_successful(self, sample_xlsx, body_template_file, tmp_path):
        """Resume skips recipients that previously succeeded."""
        from mail_merge.report import write_csv
        from mail_merge.sender import SendResult

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
        from mail_merge.report import write_csv
        from mail_merge.sender import SendResult

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
        from mail_merge.report import write_csv
        from mail_merge.sender import SendResult

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
        from mail_merge.report import write_csv
        from mail_merge.sender import SendResult

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
        cfg.write_text('client-id = "cfg-client"\ntenant-id = "cfg-tenant"\n')
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
