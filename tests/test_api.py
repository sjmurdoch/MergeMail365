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
            dry_run=True,
        )
        assert len(results) == 2
        assert all(r.success for r in results)

    def test_dry_run_test_email(self, sample_xlsx, body_template_file):
        results = send_merge(
            spreadsheet=sample_xlsx,
            body=body_template_file,
            subject="Hello {{name}}",
            email_column="email",
            dry_run=True,
            test_email="me@example.com",
        )
        assert len(results) == 1
        assert results[0].success
        assert results[0].email == "me@example.com"


class TestFileErrors:
    def test_missing_spreadsheet(self, tmp_path, body_template_file):
        with pytest.raises(FileNotFoundError, match="Spreadsheet not found"):
            send_merge(
                spreadsheet=tmp_path / "nonexistent.xlsx",
                body=body_template_file,
                subject="Hi",
                email_column="email",
                dry_run=True,
            )

    def test_missing_body(self, sample_xlsx, tmp_path):
        with pytest.raises(FileNotFoundError, match="Body template not found"):
            send_merge(
                spreadsheet=sample_xlsx,
                body=tmp_path / "nonexistent.txt",
                subject="Hi",
                email_column="email",
                dry_run=True,
            )

    def test_missing_attachment(self, sample_xlsx, body_template_file, tmp_path):
        with pytest.raises(FileNotFoundError, match="Attachment not found"):
            send_merge(
                spreadsheet=sample_xlsx,
                body=body_template_file,
                subject="Hello {{name}}",
                email_column="email",
                dry_run=True,
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
                dry_run=True,
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
                dry_run=True,
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
                dry_run=True,
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
            html=True,
            attachment=[att],
            reply_to=["reply@example.com", "other@example.com"],
        )
        assert len(results) == 1
        assert results[0].success

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
            cc=["a@x.com", "b@x.com"],
            bcc="c@x.com",
        )
        assert results[0].success

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
            dry_run=True,
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
            dry_run=True,
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
            dry_run=True,
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
            dry_run=True,
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
                dry_run=True,
                filter=["company=NonExistent"],
            )

    def test_bad_syntax_raises(self, sample_xlsx, body_template_file):
        with pytest.raises(ValueError, match="Invalid filter syntax"):
            send_merge(
                spreadsheet=sample_xlsx,
                body=body_template_file,
                subject="Hello {{name}}",
                email_column="email",
                dry_run=True,
                filter=["no-operator-here"],
            )

    def test_unknown_column_raises(self, sample_xlsx, body_template_file):
        with pytest.raises(ValueError, match="Filter column.*not found"):
            send_merge(
                spreadsheet=sample_xlsx,
                body=body_template_file,
                subject="Hello {{name}}",
                email_column="email",
                dry_run=True,
                filter=["nonexistent=value"],
            )


class TestConfigResolution:
    def test_client_id_from_config(self, sample_xlsx, body_template_file, tmp_path, monkeypatch):
        cfg = tmp_path / "config.toml"
        cfg.write_text('client-id = "cfg-client"\ntenant-id = "cfg-tenant"\n')
        monkeypatch.setattr("mail_merge.config.DEFAULT_PATH", cfg)
        monkeypatch.delenv("MAIL_MERGE_CLIENT_ID", raising=False)
        monkeypatch.delenv("MAIL_MERGE_TENANT_ID", raising=False)

        # dry_run so no auth needed, but client_id should resolve
        results = send_merge(
            spreadsheet=sample_xlsx,
            body=body_template_file,
            subject="Hello {{name}}",
            email_column="email",
            dry_run=True,
        )
        assert len(results) == 2
