import logging
from pathlib import Path

import openpyxl

logger = logging.getLogger(__name__)


def read_preview(
    path: str | Path,
    sheet_name: str | None = None,
    max_rows: int = 5,
) -> tuple[list[str], list[dict[str, str]]]:
    """Read column headers and first N rows. Returns (columns, rows).

    Does not require an email_column — used for spreadsheet preview in the web UI.
    """
    path = Path(path)
    max_size = 50 * 1024 * 1024  # 50 MB
    file_size = path.stat().st_size
    if file_size > max_size:
        raise ValueError(
            f"Spreadsheet too large: {file_size / (1024 * 1024):.0f} MB "
            f"(limit: {max_size // (1024 * 1024)} MB)"
        )
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet_name] if sheet_name else wb.active

        rows_iter = ws.iter_rows()
        header_row = next(rows_iter, None)
        if header_row is None:
            raise ValueError("Spreadsheet is empty")

        headers = [str(cell.value).strip() if cell.value is not None else "" for cell in header_row]
        columns = [h for h in headers if h]

        preview_rows: list[dict[str, str]] = []
        for _, row in zip(range(max_rows), rows_iter):
            values = [str(cell.value).strip() if cell.value is not None else "" for cell in row]
            while len(values) < len(headers):
                values.append("")
            record = {headers[i]: values[i] for i in range(len(headers)) if headers[i]}
            preview_rows.append(record)
    finally:
        wb.close()
    return columns, preview_rows


def read_recipients(
    path: str | Path,
    email_column: str,
    sheet_name: str | None = None,
) -> list[dict[str, str]]:
    """Read recipients from an Excel spreadsheet.

    Returns a list of dicts mapping column header -> cell value.
    Rows with an empty email cell are skipped with a warning.
    Raises ValueError if the email column is not found.
    """
    path = Path(path)
    max_size = 50 * 1024 * 1024  # 50 MB
    file_size = path.stat().st_size
    if file_size > max_size:
        raise ValueError(
            f"Spreadsheet too large: {file_size / (1024 * 1024):.0f} MB "
            f"(limit: {max_size // (1024 * 1024)} MB)"
        )
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet_name] if sheet_name else wb.active

        rows = ws.iter_rows()
        header_row = next(rows, None)
        if header_row is None:
            raise ValueError("Spreadsheet is empty")

        headers = [str(cell.value).strip() if cell.value is not None else "" for cell in header_row]

        # Find the email column (case-insensitive)
        email_col_idx = None
        for i, h in enumerate(headers):
            if h.lower() == email_column.lower():
                email_col_idx = i
                break

        if email_col_idx is None:
            raise ValueError(
                f"Email column '{email_column}' not found. "
                f"Available columns: {', '.join(h for h in headers if h)}"
            )

        recipients = []
        for row_num, row in enumerate(rows, start=2):
            values = [str(cell.value).strip() if cell.value is not None else "" for cell in row]
            # Pad values if row is shorter than headers
            while len(values) < len(headers):
                values.append("")

            # Skip entirely empty rows silently; warn only for partial rows
            email_value = values[email_col_idx]
            if not email_value:
                if any(v for v in values):
                    logger.warning("Row %d: empty email, skipping", row_num)
                continue

            record = {headers[i]: values[i] for i in range(len(headers)) if headers[i]}
            recipients.append(record)
    finally:
        wb.close()
    return recipients
