import responses

from mail_merge.cli import main
from mail_merge.sender import GRAPH_SEND_URL


class TestCLIDryRun:
    def test_dry_run_success(self, sample_xlsx, body_template_file):
        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--client-id", "fake-client-id",
            "--dry-run",
        ])
        assert exit_code == 0

    def test_missing_spreadsheet(self, tmp_path, body_template_file):
        exit_code = main([
            "--spreadsheet", str(tmp_path / "nonexistent.xlsx"),
            "--body", str(body_template_file),
            "--subject", "Hello",
            "--email-column", "email",
            "--client-id", "fake",
            "--dry-run",
        ])
        assert exit_code == 1

    def test_bad_placeholder(self, sample_xlsx, body_template_file):
        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{nonexistent}}",
            "--email-column", "email",
            "--client-id", "fake",
            "--dry-run",
        ])
        assert exit_code == 1

    def test_missing_client_id_without_dry_run(self, sample_xlsx, body_template_file, monkeypatch):
        monkeypatch.delenv("MAIL_MERGE_CLIENT_ID", raising=False)
        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
        ])
        assert exit_code == 1

    def test_csv_output(self, sample_xlsx, body_template_file, tmp_path):
        report_path = tmp_path / "report.csv"
        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--client-id", "fake",
            "--dry-run",
            "--output", str(report_path),
        ])
        assert exit_code == 0
        assert report_path.exists()
        lines = report_path.read_text().strip().split("\n")
        assert len(lines) == 3  # header + 2 recipients


class TestTestEmail:
    @responses.activate
    def test_test_email_sends_to_correct_address(self, sample_xlsx, body_template_file, monkeypatch):
        """Verify the test email is sent to --test-email address, not the spreadsheet address."""
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        monkeypatch.setattr("mail_merge.auth.acquire_token", lambda client_id: "fake-token")

        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--client-id", "fake-client-id",
            "--test-email", "tester@example.com",
        ])
        assert exit_code == 0
        assert len(responses.calls) == 1
        import json
        payload = json.loads(responses.calls[0].request.body)
        actual_to = payload["message"]["toRecipients"][0]["emailAddress"]["address"]
        assert actual_to == "tester@example.com"
        # Subject should be rendered with first recipient's data
        assert payload["message"]["subject"] == "Hello Alice"

    @responses.activate
    def test_test_email_failure(self, sample_xlsx, body_template_file, monkeypatch):
        responses.add(responses.POST, GRAPH_SEND_URL, status=403, body="Forbidden")
        monkeypatch.setattr("mail_merge.auth.acquire_token", lambda client_id: "fake-token")

        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--client-id", "fake-client-id",
            "--test-email", "tester@example.com",
        ])
        assert exit_code == 1

    def test_test_email_requires_client_id(self, sample_xlsx, body_template_file, monkeypatch):
        monkeypatch.delenv("MAIL_MERGE_CLIENT_ID", raising=False)
        exit_code = main([
            "--spreadsheet", str(sample_xlsx),
            "--body", str(body_template_file),
            "--subject", "Hello {{name}}",
            "--email-column", "email",
            "--test-email", "tester@example.com",
        ])
        assert exit_code == 1
