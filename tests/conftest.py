from pathlib import Path

import openpyxl
import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir():
    return FIXTURES_DIR


@pytest.fixture
def sample_xlsx(tmp_path):
    """Create a small test spreadsheet and return its path."""
    path = tmp_path / "test.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["name", "email", "company"])
    ws.append(["Alice", "alice@example.com", "Acme"])
    ws.append(["Bob", "bob@example.com", "Widgets"])
    ws.append(["Charlie", "", "NoEmail Inc"])  # empty email row
    wb.save(path)
    return path


@pytest.fixture
def body_template_file(tmp_path):
    """Create a body template file."""
    path = tmp_path / "body.txt"
    path.write_text("Hello {{name}},\n\nWelcome from {{company}}.\n")
    return path
