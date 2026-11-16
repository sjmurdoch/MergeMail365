import datetime
import logging
import re
from decimal import Decimal
from pathlib import Path

import openpyxl

logger = logging.getLogger(__name__)

_MAX_SPREADSHEET_SIZE = 50 * 1024 * 1024  # 50 MB


def _check_file_size(path: Path) -> None:
    try:
        file_size = path.stat().st_size
    except FileNotFoundError:
        raise FileNotFoundError(f"Spreadsheet not found: {path}")
    if file_size > _MAX_SPREADSHEET_SIZE:
        raise ValueError(
            f"Spreadsheet too large: {file_size / (1024 * 1024):.0f} MB "
            f"(limit: {_MAX_SPREADSHEET_SIZE // (1024 * 1024)} MB)"
        )


def _clock(hours: int, minutes: int, seconds: int) -> str:
    return f"{hours:02d}:{minutes:02d}" + (f":{seconds:02d}" if seconds else "")


def _plain_number(value: float) -> str:
    """A float as a person would write it: no exponent, no ".0", and none of
    the digits binary floating point adds (0.30000000000000004). Excel keeps
    15 significant digits, so nothing real is lost."""
    if value != value or value in (float("inf"), float("-inf")):
        return str(value)
    text = format(Decimal(format(value, ".15g")), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


_PERCENT_DECIMALS_RE = re.compile(r"\.(0+)")


def cell_text(value: object, number_format: str = "General") -> str:
    """The text a cell's value becomes in an email, and in every preview.

    Excel stores dates, times and percentages as numbers with a display
    format; str() of the stored value is not what the user sees in Excel
    ("2026-12-01 00:00:00", "0.25"). The rules (docs/review-fixes-plan.md,
    D4):

    * A date is ISO, ``2026-12-01``; with a time of day, ``2026-12-01 14:30``
      (seconds only when they aren't zero). A time alone is ``14:30``; a
      duration is hours and minutes, ``26:00``.
    * A number with a percent format is shown as a percentage, with the
      decimals the format asks for: ``25%``, ``12.5%``.
    * Other numbers are written plainly: ``3`` not ``3.0``, no exponent.
      Currency symbols, thousands separators and fixed decimals from the
      Excel format are NOT applied (number_format_columns() finds the
      columns this affects, so the user can be told).
    * Text is stripped of surrounding space; an empty cell is "".
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, datetime.datetime):
        day = value.date().isoformat()
        if (value.hour, value.minute, value.second) == (0, 0, 0):
            return day
        return f"{day} {_clock(value.hour, value.minute, value.second)}"
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, datetime.time):
        return _clock(value.hour, value.minute, value.second)
    if isinstance(value, datetime.timedelta):
        total = int(value.total_seconds())
        sign = "-" if total < 0 else ""
        total = abs(total)
        return sign + _clock(total // 3600, total % 3600 // 60, total % 60)
    if isinstance(value, (int, float)):
        if "%" in number_format:
            decimals = _PERCENT_DECIMALS_RE.search(number_format)
            return f"{value * 100:.{len(decimals[1]) if decimals else 0}f}%"
        return str(value) if isinstance(value, int) else _plain_number(value)
    return str(value).strip()


def _sheet(wb: "openpyxl.Workbook", sheet_name: str | None):  # type: ignore[no-untyped-def]
    """The named worksheet, or the active one."""
    if not sheet_name:
        return wb.active
    if sheet_name not in wb.sheetnames:
        raise ValueError(
            f"Sheet {sheet_name!r} not found (available: {', '.join(wb.sheetnames)})"
        )
    return wb[sheet_name]


def _cell_str(cell: object) -> str:
    """A cell's text (see cell_text)."""
    return cell_text(cell.value, getattr(cell, "number_format", None) or "General")  # type: ignore[attr-defined]


def _has_unapplied_format(value: object, number_format: str) -> bool:
    """A number whose Excel format (currency, separators, fixed decimals)
    cell_text() does not apply."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return number_format not in ("General", "@") and "%" not in number_format


def number_format_columns(
    path: str | Path, sheet_name: str | None = None, max_rows: int = 200,
) -> dict[str, str]:
    """Columns holding numbers that Excel shows with a format this tool
    does not apply, mapped to an example: {"Amount": "1250.5"}.

    The email (and every preview) has the plain number, so the user should
    know which columns differ from what they see in Excel.
    """
    path = Path(path)
    _check_file_size(path)
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = _sheet(wb, sheet_name)
        rows = ws.iter_rows()
        header_row = next(rows, None)
        if header_row is None:
            return {}
        headers = _parse_headers(header_row)
        found: dict[str, str] = {}
        for _, row in zip(range(max_rows), rows):
            for header, cell in zip(headers, row):
                if header and header not in found and _has_unapplied_format(
                    cell.value, getattr(cell, "number_format", None) or "General",
                ):
                    found[header] = _cell_str(cell)
    finally:
        wb.close()
    return found


def _parse_headers(header_row: tuple) -> list[str]:  # type: ignore[type-arg]
    return [_cell_str(cell) for cell in header_row]


def read_preview(
    path: str | Path,
    sheet_name: str | None = None,
    max_rows: int = 99,
) -> tuple[list[str], list[dict[str, str]], list[str], int, str]:
    """Read column headers, first N rows, sheet names, and total row count.

    Returns (columns, rows, sheet_names, total_rows, active_sheet).
    Does not require an email_column — used for spreadsheet preview in the web UI.
    """
    path = Path(path)
    _check_file_size(path)
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheet_names = wb.sheetnames
        ws = _sheet(wb, sheet_name)
        sheet_name = ws.title

        # Count total rows (excluding header)
        total_rows = ws.max_row - 1 if ws.max_row else 0

        rows_iter = ws.iter_rows()
        header_row = next(rows_iter, None)
        if header_row is None:
            raise ValueError("Spreadsheet is empty")

        headers = _parse_headers(header_row)
        columns = [h for h in headers if h]

        preview_rows: list[dict[str, str]] = []
        for _, row in zip(range(max_rows), rows_iter):
            values = [_cell_str(cell) for cell in row]
            while len(values) < len(headers):
                values.append("")
            record = {headers[i]: values[i] for i in range(len(headers)) if headers[i]}
            preview_rows.append(record)
    finally:
        wb.close()
    return columns, preview_rows, sheet_names, total_rows, sheet_name


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
    _check_file_size(path)
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = _sheet(wb, sheet_name)

        rows = ws.iter_rows()
        header_row = next(rows, None)
        if header_row is None:
            raise ValueError("Spreadsheet is empty")

        headers = _parse_headers(header_row)

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
            values = [_cell_str(cell) for cell in row]
            while len(values) < len(headers):
                values.append("")

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
