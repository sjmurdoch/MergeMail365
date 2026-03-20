import json

import responses

from mail_merge.cli import main, parse_args
from mail_merge.sender import GRAPH_SEND_URL


class TestCLIDryRun:
    def test_dry_run_success(self, sample_xlsx, body_template_file):
        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--client-id", "fake-client-id",
        ])
        assert exit_code == 0

    def test_missing_spreadsheet(self, tmp_path, body_template_file):
        exit_code = main([
            "--spreadsheet", str(tmp_path / "nonexistent.xlsx"),
            "--body", str(body_template_file),
            "--subject", "Hello",
            "--email-column", "email",
            "--client-id", "fake",
        ])
        assert exit_code == 1

    def test_bad_placeholder(self, sample_xlsx, body_template_file):
        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{nonexistent}}",
            "--email-column", "email",
            "--client-id", "fake",
        ])
        assert exit_code == 1

    def test_missing_client_id_without_dry_run(self, sample_xlsx, body_template_file, monkeypatch):
        monkeypatch.delenv("MAIL_MERGE_CLIENT_ID", raising=False)
        monkeypatch.setattr("mail_merge.config.DEFAULT_PATH", sample_xlsx.parent / "nonexistent.toml")
        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--send",
            "--yes",
        ])
        assert exit_code == 1

    @responses.activate
    def test_csv_output(self, sample_xlsx, body_template_file, tmp_path, monkeypatch):
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        monkeypatch.setattr("mail_merge.auth.acquire_token", lambda client_id, tenant_id="common": "fake-token")
        monkeypatch.setattr("mail_merge.auth.acquire_token_interactive_flow", lambda *a, **kw: "fake-token")
        report_path = tmp_path / "report.csv"
        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--client-id", "fake",
            "--output", str(report_path),
            "--send", "-y",
        ])
        assert exit_code == 0
        assert report_path.exists()
        lines = report_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3  # header + 2 recipients

    def test_csv_not_written_on_dry_run(self, sample_xlsx, body_template_file, tmp_path):
        report_path = tmp_path / "report.csv"
        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--output", str(report_path),
        ])
        assert exit_code == 0
        assert not report_path.exists()


class TestTestEmail:
    @responses.activate
    def test_test_email_sends_to_correct_address(self, sample_xlsx, body_template_file, monkeypatch):
        """Verify the test email is sent to --test-email address, not the spreadsheet address."""
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        monkeypatch.setattr("mail_merge.auth.acquire_token", lambda client_id, tenant_id="common": "fake-token")
        monkeypatch.setattr("mail_merge.auth.acquire_token_interactive_flow", lambda *a, **kw: "fake-token")

        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--client-id", "fake-client-id",
            "--test-email", "tester@example.com",
            "--send",
        ])
        assert exit_code == 0
        assert len(responses.calls) == 1
        assert isinstance(responses.calls[0].request.body, (str, bytes))
        payload = json.loads(responses.calls[0].request.body)
        actual_to = payload["message"]["toRecipients"][0]["emailAddress"]["address"]
        assert actual_to == "tester@example.com"
        # Subject should be rendered with first recipient's data
        assert payload["message"]["subject"] == "Hello Alice"

    @responses.activate
    def test_test_email_failure(self, sample_xlsx, body_template_file, monkeypatch):
        responses.add(responses.POST, GRAPH_SEND_URL, status=403, body="Forbidden")
        monkeypatch.setattr("mail_merge.auth.acquire_token", lambda client_id, tenant_id="common": "fake-token")
        monkeypatch.setattr("mail_merge.auth.acquire_token_interactive_flow", lambda *a, **kw: "fake-token")

        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--client-id", "fake-client-id",
            "--test-email", "tester@example.com",
            "--send",
        ])
        assert exit_code == 1

    def test_test_email_requires_client_id(self, sample_xlsx, body_template_file, monkeypatch):
        """--test-email always sends, so it requires client-id even without --send."""
        monkeypatch.delenv("MAIL_MERGE_CLIENT_ID", raising=False)
        monkeypatch.setattr("mail_merge.config.DEFAULT_PATH", sample_xlsx.parent / "nonexistent.toml")
        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--test-email", "tester@example.com",
        ])
        assert exit_code == 1


class TestImportanceCcBcc:
    @responses.activate
    def test_importance_cc_bcc_in_payload(self, sample_xlsx, body_template_file, monkeypatch):
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        monkeypatch.setattr("mail_merge.auth.acquire_token", lambda client_id, tenant_id="common": "fake-token")
        monkeypatch.setattr("mail_merge.auth.acquire_token_interactive_flow", lambda *a, **kw: "fake-token")

        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--client-id", "fake-client-id",
            "--test-email", "tester@example.com",
            "--send",
            "--importance", "high",
            "--cc", "a@x.com,b@x.com",
            "--bcc", "c@x.com",
        ])
        assert exit_code == 0
        assert isinstance(responses.calls[0].request.body, (str, bytes))
        payload = json.loads(responses.calls[0].request.body)
        assert payload["message"]["importance"] == "high"
        cc_addrs = [r["emailAddress"]["address"] for r in payload["message"]["ccRecipients"]]
        assert cc_addrs == ["a@x.com", "b@x.com"]
        bcc_addrs = [r["emailAddress"]["address"] for r in payload["message"]["bccRecipients"]]
        assert bcc_addrs == ["c@x.com"]


class TestConfigFilePrecedence:
    """Verify CLI flag → env var → config file → default precedence."""

    @responses.activate
    def test_config_file_provides_client_and_tenant(self, sample_xlsx, body_template_file, tmp_path, monkeypatch):
        """Config file values are used when CLI flags and env vars are absent."""
        cfg = tmp_path / "config.toml"
        cfg.write_text('client-id = "cfg-client"\ntenant-id = "cfg-tenant"\n', encoding="utf-8")
        monkeypatch.setattr("mail_merge.config.DEFAULT_PATH", cfg)
        monkeypatch.delenv("MAIL_MERGE_CLIENT_ID", raising=False)
        monkeypatch.delenv("MAIL_MERGE_TENANT_ID", raising=False)

        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        monkeypatch.setattr("mail_merge.auth.acquire_token", lambda client_id, tenant_id="common": "fake-token")
        monkeypatch.setattr("mail_merge.auth.acquire_token_interactive_flow", lambda *a, **kw: "fake-token")

        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--test-email", "tester@example.com",
            "--send",
        ])
        assert exit_code == 0

    def test_cli_flag_overrides_config_file(self, sample_xlsx, body_template_file, tmp_path, monkeypatch):
        """CLI --client-id should beat config file value."""
        cfg = tmp_path / "config.toml"
        cfg.write_text('client-id = "cfg-client"\ntenant-id = "cfg-tenant"\n', encoding="utf-8")
        monkeypatch.setattr("mail_merge.config.DEFAULT_PATH", cfg)
        monkeypatch.delenv("MAIL_MERGE_CLIENT_ID", raising=False)
        monkeypatch.delenv("MAIL_MERGE_TENANT_ID", raising=False)

        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--client-id", "cli-client",
        ])
        assert exit_code == 0

    def test_env_var_overrides_config_file(self, sample_xlsx, body_template_file, tmp_path, monkeypatch):
        """Env var should beat config file value."""
        cfg = tmp_path / "config.toml"
        cfg.write_text('client-id = "cfg-client"\ntenant-id = "cfg-tenant"\n', encoding="utf-8")
        monkeypatch.setattr("mail_merge.config.DEFAULT_PATH", cfg)
        monkeypatch.setenv("MAIL_MERGE_CLIENT_ID", "env-client")
        monkeypatch.setenv("MAIL_MERGE_TENANT_ID", "env-tenant")

        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
        ])
        assert exit_code == 0

    @responses.activate
    def test_tenant_defaults_to_common(self, sample_xlsx, body_template_file, tmp_path, monkeypatch):
        """When no tenant-id is set anywhere, it defaults to 'common'."""
        monkeypatch.setattr("mail_merge.config.DEFAULT_PATH", tmp_path / "nonexistent.toml")
        monkeypatch.delenv("MAIL_MERGE_TENANT_ID", raising=False)

        captured: dict[str, str] = {}

        def fake_acquire(client_id: str, tenant_id: str = "common") -> str:
            captured["tenant_id"] = tenant_id
            return "fake-token"

        monkeypatch.setattr("mail_merge.auth.acquire_token", fake_acquire)
        monkeypatch.setattr("mail_merge.auth.acquire_token_interactive_flow", fake_acquire)
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)

        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--client-id", "fake-client-id",
            "--test-email", "tester@example.com",
            "--send",
        ])
        assert exit_code == 0
        assert captured["tenant_id"] == "common"

    def test_missing_client_id_with_no_config(self, sample_xlsx, body_template_file, tmp_path, monkeypatch):
        """Without config file, env var, or CLI flag, client-id is None and send fails."""
        monkeypatch.setattr("mail_merge.config.DEFAULT_PATH", tmp_path / "nonexistent.toml")
        monkeypatch.delenv("MAIL_MERGE_CLIENT_ID", raising=False)

        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--send",
            "--yes",
        ])
        assert exit_code == 1


class TestDeviceCodeFlag:
    def test_device_code_default_false(self):
        args = parse_args([
            "--spreadsheet", "x.xlsx",
            "--body", "b.txt",
            "--subject", "s",
            "--email-column", "e",
        ])
        assert args.device_code is False

    def test_device_code_flag_true(self):
        args = parse_args([
            "--spreadsheet", "x.xlsx",
            "--body", "b.txt",
            "--subject", "s",
            "--email-column", "e",
            "--device-code",
        ])
        assert args.device_code is True


class TestDelayDefault:
    def test_delay_default_is_two(self):
        args = parse_args([
            "--spreadsheet", "x.xlsx",
            "--body", "b.txt",
            "--subject", "s",
            "--email-column", "e",
        ])
        assert args.delay == 2.0


class TestHTMLFlag:
    @responses.activate
    def test_html_flag_sets_content_type(self, sample_xlsx, body_template_file, monkeypatch):
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        monkeypatch.setattr("mail_merge.auth.acquire_token", lambda client_id, tenant_id="common": "fake-token")
        monkeypatch.setattr("mail_merge.auth.acquire_token_interactive_flow", lambda *a, **kw: "fake-token")

        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--client-id", "fake-client-id",
            "--test-email", "tester@example.com",
            "--send",
            "--html",
        ])
        assert exit_code == 0
        assert isinstance(responses.calls[0].request.body, (str, bytes))
        payload = json.loads(responses.calls[0].request.body)
        assert payload["message"]["body"]["contentType"] == "HTML"


class TestNoSaveToSent:
    @responses.activate
    def test_no_save_to_sent_flag(self, sample_xlsx, body_template_file, monkeypatch):
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        monkeypatch.setattr("mail_merge.auth.acquire_token", lambda client_id, tenant_id="common": "fake-token")
        monkeypatch.setattr("mail_merge.auth.acquire_token_interactive_flow", lambda *a, **kw: "fake-token")

        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--client-id", "fake-client-id",
            "--test-email", "tester@example.com",
            "--send",
            "--no-save-to-sent",
        ])
        assert exit_code == 0
        assert isinstance(responses.calls[0].request.body, (str, bytes))
        payload = json.loads(responses.calls[0].request.body)
        assert payload["saveToSentItems"] is False


class TestAttachment:
    @responses.activate
    def test_attachment_included_in_payload(self, sample_xlsx, body_template_file, tmp_path, monkeypatch):
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        monkeypatch.setattr("mail_merge.auth.acquire_token", lambda client_id, tenant_id="common": "fake-token")
        monkeypatch.setattr("mail_merge.auth.acquire_token_interactive_flow", lambda *a, **kw: "fake-token")

        att_file = tmp_path / "doc.txt"
        att_file.write_text("hello", encoding="utf-8")

        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--client-id", "fake-client-id",
            "--test-email", "tester@example.com",
            "--send",
            "--attachment", str(att_file),
        ])
        assert exit_code == 0
        assert isinstance(responses.calls[0].request.body, (str, bytes))
        payload = json.loads(responses.calls[0].request.body)
        atts = payload["message"]["attachments"]
        assert len(atts) == 1
        assert atts[0]["name"] == "doc.txt"
        assert atts[0]["@odata.type"] == "#microsoft.graph.fileAttachment"

    def test_missing_attachment_errors(self, sample_xlsx, body_template_file, tmp_path):
        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--client-id", "fake-client-id",
            "--attachment", str(tmp_path / "nonexistent.txt"),
        ])
        assert exit_code == 1


class TestReplyTo:
    @responses.activate
    def test_reply_to_in_payload(self, sample_xlsx, body_template_file, monkeypatch):
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        monkeypatch.setattr("mail_merge.auth.acquire_token", lambda client_id, tenant_id="common": "fake-token")
        monkeypatch.setattr("mail_merge.auth.acquire_token_interactive_flow", lambda *a, **kw: "fake-token")

        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--client-id", "fake-client-id",
            "--test-email", "tester@example.com",
            "--send",
            "--reply-to", "reply@example.com,other@example.com",
        ])
        assert exit_code == 0
        assert isinstance(responses.calls[0].request.body, (str, bytes))
        payload = json.loads(responses.calls[0].request.body)
        reply_addrs = [r["emailAddress"]["address"] for r in payload["message"]["replyTo"]]
        assert reply_addrs == ["reply@example.com", "other@example.com"]


class TestFilter:
    def test_filter_flag_filters_recipients(self, sample_xlsx, body_template_file):
        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--filter", "company=Acme",
        ])
        assert exit_code == 0

    def test_multiple_filter_flags(self, sample_xlsx, body_template_file):
        # Both filters match only Alice (company=Acme AND name=Alice)
        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--filter", "company=Acme",
            "--filter", "name=Alice",
        ])
        assert exit_code == 0

    def test_filter_no_match_exits_1(self, sample_xlsx, body_template_file):
        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--filter", "company=NonExistent",
        ])
        assert exit_code == 1


class TestConfirm:
    def test_confirm_abort_exits_130(self, sample_xlsx, body_template_file, monkeypatch):
        """Declining confirmation returns exit code 130."""
        monkeypatch.setattr("mail_merge.console.console.input", lambda prompt: "n")
        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--client-id", "fake-client-id",
            "--send",
        ])
        assert exit_code == 130

    def test_confirm_eof_aborts(self, sample_xlsx, body_template_file, monkeypatch):
        """EOFError (piped input) is treated as decline."""
        def raise_eof(prompt: str) -> str:
            raise EOFError

        monkeypatch.setattr("mail_merge.console.console.input", raise_eof)
        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--client-id", "fake-client-id",
            "--send",
        ])
        assert exit_code == 130

    @responses.activate
    def test_confirm_yes_proceeds(self, sample_xlsx, body_template_file, monkeypatch):
        """Typing 'y' at the prompt proceeds with sending."""
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        monkeypatch.setattr("mail_merge.auth.acquire_token", lambda client_id, tenant_id="common": "fake-token")
        monkeypatch.setattr("mail_merge.auth.acquire_token_interactive_flow", lambda *a, **kw: "fake-token")
        monkeypatch.setattr("mail_merge.console.console.input", lambda prompt: "y")
        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--client-id", "fake-client-id",
            "--send",
        ])
        assert exit_code == 0
        assert len(responses.calls) == 2  # 2 recipients

    def test_dry_run_skips_confirm(self, sample_xlsx, body_template_file):
        """Default (dry run) should not prompt for confirmation."""
        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
        ])
        assert exit_code == 0

    @responses.activate
    def test_test_email_skips_confirm(self, sample_xlsx, body_template_file, monkeypatch):
        """--test-email should not prompt for confirmation."""
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        monkeypatch.setattr("mail_merge.auth.acquire_token", lambda client_id, tenant_id="common": "fake-token")
        monkeypatch.setattr("mail_merge.auth.acquire_token_interactive_flow", lambda *a, **kw: "fake-token")
        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--client-id", "fake-client-id",
            "--test-email", "tester@example.com",
        ])
        assert exit_code == 0

    @responses.activate
    def test_yes_flag_skips_confirm(self, sample_xlsx, body_template_file, monkeypatch):
        """--yes should skip confirmation and go straight to sending."""
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        monkeypatch.setattr("mail_merge.auth.acquire_token", lambda client_id, tenant_id="common": "fake-token")
        monkeypatch.setattr("mail_merge.auth.acquire_token_interactive_flow", lambda *a, **kw: "fake-token")
        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--client-id", "fake-client-id",
            "--send",
            "--yes",
        ])
        assert exit_code == 0


class TestResumeBatchSize:
    @responses.activate
    def test_resume_batch_size_round_trip(self, sample_xlsx, body_template_file, tmp_path, monkeypatch):
        """--batch-size sends one batch, then auto-resumes on next run."""
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        monkeypatch.setattr("mail_merge.auth.acquire_token", lambda client_id, tenant_id="common": "fake-token")
        monkeypatch.setattr("mail_merge.auth.acquire_token_interactive_flow", lambda *a, **kw: "fake-token")
        report = tmp_path / "report.csv"
        # First run: batch of 1
        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--client-id", "fake-client-id",
            "--output", str(report),
            "--batch-size", "1",
            "--send", "-y",
        ])
        assert exit_code == 0
        lines = report.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2  # header + 1 recipient

        # Second run: auto-resumes, sends next batch of 1
        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--client-id", "fake-client-id",
            "--output", str(report),
            "--batch-size", "1",
            "--send", "-y",
        ])
        assert exit_code == 0
        lines = report.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3  # header + 2 recipients (merged)

    def test_resume_without_output_succeeds(self, sample_xlsx, body_template_file):
        """Resume without --output just runs normally (no error)."""
        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
        ])
        assert exit_code == 0


class TestRecipientCountValidation:
    def test_too_many_recipients_errors(self, sample_xlsx, body_template_file):
        # 1 to + 500 cc = 501 > 500
        cc_addresses = ",".join(f"user{i}@example.com" for i in range(500))
        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--client-id", "fake-client-id",
            "--cc", cc_addresses,
        ])
        assert exit_code == 1


class TestUnexpectedException:
    def test_unexpected_exception_returns_1(self, sample_xlsx, body_template_file, monkeypatch):
        """An unexpected exception (not FileNotFoundError/ValueError/RuntimeError) returns exit code 1."""
        def explode(*args, **kwargs):
            raise TypeError("unexpected internal error")

        import mail_merge.cli as cli_module
        monkeypatch.setattr(cli_module, "send_merge", explode)
        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
        ])
        assert exit_code == 1


class TestBccBlastCLI:
    def test_bcc_blast_dry_run(self, sample_xlsx, tmp_path):
        """--bcc-blast dry run exits with code 0."""
        body = tmp_path / "body.txt"
        body.write_text("Hello everyone.", encoding="utf-8")
        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body),
            "--subject", "Announcement",
            "--email-column", "email",
            "--bcc-blast",
            "--bcc-blast-to", "noreply@x.com",
        ])
        assert exit_code == 0

    def test_bcc_blast_missing_to_errors(self, sample_xlsx, tmp_path):
        """--bcc-blast without --bcc-blast-to exits with code 1."""
        body = tmp_path / "body.txt"
        body.write_text("Hello everyone.", encoding="utf-8")
        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body),
            "--subject", "Announcement",
            "--email-column", "email",
            "--bcc-blast",
        ])
        assert exit_code == 1

    def test_bcc_blast_with_placeholder_errors(self, sample_xlsx, tmp_path):
        """--bcc-blast with a {{placeholder}} subject exits with code 1."""
        body = tmp_path / "body.txt"
        body.write_text("Hello everyone.", encoding="utf-8")
        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--bcc-blast",
            "--bcc-blast-to", "noreply@x.com",
        ])
        assert exit_code == 1

    @responses.activate
    def test_bcc_blast_with_test_email(self, sample_xlsx, tmp_path, monkeypatch):
        """--bcc-blast + --test-email sends a blast to just the test address."""
        import mail_merge.auth as auth_module

        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        monkeypatch.setattr(auth_module, "acquire_token", lambda *a, **kw: "fake-tok")
        monkeypatch.setattr(auth_module, "acquire_token_interactive_flow", lambda *a, **kw: "fake-tok")
        monkeypatch.setattr("mail_merge.auth.token_expires_at", lambda tok: None)

        body = tmp_path / "body.txt"
        body.write_text("Hello everyone.", encoding="utf-8")
        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body),
            "--subject", "Announcement",
            "--email-column", "email",
            "--client-id", "fake-client",
            "--bcc-blast",
            "--bcc-blast-to", "noreply@x.com",
            "--test-email", "me@x.com",
        ])
        assert exit_code == 0
        assert len(responses.calls) == 1
        payload = json.loads(responses.calls[0].request.body)
        bcc_addrs = [b["emailAddress"]["address"] for b in payload["message"]["bccRecipients"]]
        assert bcc_addrs == ["me@x.com"]
