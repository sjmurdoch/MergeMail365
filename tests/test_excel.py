import pytest

from mail_merge.excel import read_preview, read_recipients


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

    def test_ragged_rows_padded(self, tmp_path):
        """Rows shorter than headers are padded with empty strings."""
        import openpyxl
        path = tmp_path / "ragged.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["name", "email", "company"])
        ws.append(["Alice", "alice@example.com"])  # missing company
        wb.save(path)

        recipients = read_recipients(path, "email")
        assert len(recipients) == 1
        assert recipients[0]["name"] == "Alice"
        assert recipients[0]["company"] == ""

    def test_oversized_file_rejected(self, tmp_path, monkeypatch):
        """Files larger than 50 MB are rejected before loading."""
        import openpyxl
        path = tmp_path / "big.xlsx"
        wb = openpyxl.Workbook()
        wb.active.append(["email"])
        wb.save(path)

        # Fake a large file size without writing 50 MB of data
        monkeypatch.setattr("pathlib.Path.stat", lambda self: type("S", (), {"st_size": 51 * 1024 * 1024})())

        with pytest.raises(ValueError, match="too large"):
            read_recipients(path, "email")


class TestReadPreview:
    def test_basic(self, sample_xlsx):
        columns, rows, sheets, total_rows, active_sheet = read_preview(sample_xlsx)
        assert "name" in columns
        assert "email" in columns
        assert total_rows == 3  # Alice, Bob, Charlie
        assert len(rows) == 3
        assert active_sheet == "Sheet"

    def test_truncation(self, tmp_path):
        """read_preview with max_rows limits returned rows."""
        import openpyxl
        path = tmp_path / "many.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["name", "email"])
        for i in range(20):
            ws.append([f"User{i}", f"user{i}@example.com"])
        wb.save(path)

        columns, rows, sheets, total_rows, _active = read_preview(path, max_rows=5)
        assert total_rows == 20
        assert len(rows) == 5
        assert rows[0]["name"] == "User0"

    def test_ragged_rows_padded(self, tmp_path):
        """Preview rows shorter than headers are padded with empty strings."""
        import openpyxl
        path = tmp_path / "ragged.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["name", "email", "company"])
        ws.append(["Alice", "alice@example.com"])  # missing company
        wb.save(path)

        columns, rows, sheets, total_rows, _active = read_preview(path)
        assert len(rows) == 1
        assert rows[0]["company"] == ""

    def test_empty_spreadsheet_raises(self, tmp_path):
        import openpyxl
        path = tmp_path / "empty.xlsx"
        wb = openpyxl.Workbook()
        wb.save(path)

        with pytest.raises(ValueError, match="empty"):
            read_preview(path)

    def test_oversized_file_rejected(self, tmp_path, monkeypatch):
        import openpyxl
        path = tmp_path / "big.xlsx"
        wb = openpyxl.Workbook()
        wb.active.append(["email"])
        wb.save(path)

        monkeypatch.setattr(
            "pathlib.Path.stat",
            lambda self: type("S", (), {"st_size": 51 * 1024 * 1024})(),
        )
        with pytest.raises(ValueError, match="too large"):
            read_preview(path)


# ---------------------------------------------------------------------------
# What a cell becomes in the email (docs/review-fixes-plan.md, F6, D4)
# ---------------------------------------------------------------------------

import datetime as _dt  # noqa: E402

import openpyxl  # noqa: E402

import pytest as _pytest  # noqa: E402

from mail_merge.excel import cell_text, number_format_columns, read_preview  # noqa: E402

CELL_CASES = [
    # (value, Excel number format, text in the email)
    (None, "General", ""),
    ("  Alice  ", "General", "Alice"),
    ("007", "General", "007"),
    ("", "General", ""),
    (_dt.datetime(2026, 12, 1), "yyyy-mm-dd h:mm:ss", "2026-12-01"),
    (_dt.datetime(2026, 12, 1), "dd/mm/yyyy", "2026-12-01"),
    (_dt.datetime(2026, 12, 1, 14, 30), "yyyy-mm-dd h:mm:ss", "2026-12-01 14:30"),
    (_dt.datetime(2026, 12, 1, 14, 30, 15), "General", "2026-12-01 14:30:15"),
    (_dt.datetime(2026, 12, 1, 0, 0, 1), "General", "2026-12-01 00:00:01"),
    (_dt.date(2026, 12, 2), "yyyy-mm-dd", "2026-12-02"),
    (_dt.time(9, 5), "h:mm:ss", "09:05"),
    (_dt.time(23, 59, 59), "h:mm:ss", "23:59:59"),
    (_dt.timedelta(hours=26), "[hh]:mm:ss", "26:00"),
    (_dt.timedelta(minutes=90, seconds=5), "[hh]:mm:ss", "01:30:05"),
    (0.25, "0%", "25%"),
    (0.125, "0.0%", "12.5%"),
    (0.125, "0%", "12%"),
    (1, "0%", "100%"),
    (0.07, "0.00%", "7.00%"),
    (3.0, "General", "3"),
    (3, "General", "3"),
    (-2.50, "General", "-2.5"),
    (0.1 + 0.2, "General", "0.3"),
    (1250.5, "£#,##0.00", "1250.5"),
    (42, "0.00", "42"),
    (12345678901234567890, "General", "12345678901234567890"),
    (1.2345678901234567e19, "General", "12345678901234600000"),
    (1e-7, "General", "0.0000001"),
    (-0.0, "General", "0"),
    (1e21, "General", "1000000000000000000000"),
    (True, "General", "True"),
    (False, "General", "False"),
]


@_pytest.mark.parametrize(("value", "number_format", "expected"), CELL_CASES,
                          ids=[f"{v!r} as {f}" for v, f, _ in CELL_CASES])
def test_cell_text(value, number_format, expected):
    assert cell_text(value, number_format) == expected


def test_no_cell_text_has_an_exponent_or_a_midnight_time():
    for value, number_format, _ in CELL_CASES:
        text = cell_text(value, number_format)
        assert "e+" not in text and "e-" not in text, text
        assert "00:00:00" not in text, text


@_pytest.fixture
def formatted_xlsx(tmp_path):
    path = tmp_path / "formatted.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["email", "due", "share", "amount", "count", "id"])
    ws.append(["a@example.com", _dt.datetime(2026, 12, 1), 0.25, 1250.5, 3, "007"])
    ws.append(["b@example.com", _dt.date(2026, 12, 24), 0.5, 99.0, 4, "008"])
    for row in (2, 3):
        ws.cell(row=row, column=3).number_format = "0%"
        ws.cell(row=row, column=4).number_format = "£#,##0.00"
    wb.save(path)
    return path


def test_recipients_and_preview_get_the_same_readable_text(formatted_xlsx):
    recipients = read_recipients(formatted_xlsx, "email")
    assert recipients[0] == {
        "email": "a@example.com", "due": "2026-12-01", "share": "25%",
        "amount": "1250.5", "count": "3", "id": "007",
    }
    assert recipients[1]["due"] == "2026-12-24" and recipients[1]["amount"] == "99"
    _columns, rows, *_ = read_preview(formatted_xlsx)
    assert rows == recipients, "the preview must show exactly what is sent"


def test_number_format_columns_names_what_is_sent_without_its_format(formatted_xlsx):
    # Dates and percentages are handled; plain numbers have no format to lose.
    assert number_format_columns(formatted_xlsx) == {"amount": "1250.5"}


def test_number_format_columns_of_an_empty_sheet(tmp_path):
    path = tmp_path / "empty.xlsx"
    openpyxl.Workbook().save(path)
    assert number_format_columns(path) == {}
