import pytest

from mail_merge.excel import read_recipients


class TestReadRecipients:
    def test_basic(self, sample_xlsx):
        recipients = read_recipients(sample_xlsx, "email")
        assert len(recipients) == 2
        assert recipients[0]["name"] == "Alice"
        assert recipients[0]["email"] == "alice@example.com"
        assert recipients[1]["name"] == "Bob"

    def test_skips_empty_email(self, sample_xlsx):
        recipients = read_recipients(sample_xlsx, "email")
        emails = [r["email"] for r in recipients]
        assert "" not in emails
        assert len(recipients) == 2  # Charlie skipped

    def test_missing_email_column(self, sample_xlsx):
        with pytest.raises(ValueError, match="not found"):
            read_recipients(sample_xlsx, "nonexistent")

    def test_case_insensitive_column(self, sample_xlsx):
        recipients = read_recipients(sample_xlsx, "Email")
        assert len(recipients) == 2

    def test_empty_spreadsheet(self, tmp_path):
        import openpyxl
        path = tmp_path / "empty.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        # Remove default data — leave truly empty
        wb.save(path)

        with pytest.raises(ValueError, match="empty"):
            read_recipients(path, "email")
