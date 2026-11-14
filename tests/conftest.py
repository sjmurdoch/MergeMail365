from pathlib import Path

import openpyxl
import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


@pytest.fixture(autouse=True)
def _no_external_http(monkeypatch: pytest.MonkeyPatch):
    """Fail any test that makes a real HTTP request to a non-local host.

    Requests mocked with ``responses`` never reach urllib3, so they are
    unaffected.  Attempts are recorded as well as blocked, because some code
    under test (e.g. ``diagnose_auth``) swallows all exceptions.
    """
    import urllib3.connectionpool

    attempts: list[str] = []
    real_urlopen = urllib3.connectionpool.HTTPConnectionPool.urlopen

    def guarded_urlopen(self, method, url, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.host not in _LOCAL_HOSTS:
            attempts.append(f"{method} {self.scheme}://{self.host}{url}")
            raise ConnectionError(f"External HTTP blocked in tests: {self.host}{url}")
        return real_urlopen(self, method, url, *args, **kwargs)

    monkeypatch.setattr(urllib3.connectionpool.HTTPConnectionPool, "urlopen", guarded_urlopen)
    yield
    assert not attempts, f"Test attempted external HTTP requests: {attempts}"


@pytest.fixture(autouse=True)
def _cookies_stay_small(monkeypatch: pytest.MonkeyPatch):
    """Fail any test in which the web app sets a cookie over 2 KB.

    A browser silently drops a cookie over about 4 KB, which loses the
    session. Session data therefore lives on the server (web/sessions.py);
    this notices if any of it finds its way back into a cookie.
    """
    try:
        import flask
    except ImportError:  # the web extra isn't installed
        yield
        return

    oversized: list[str] = []
    real = flask.Flask.process_response

    def checking(self, response):  # type: ignore[no-untyped-def]
        response = real(self, response)
        for cookie in response.headers.getlist("Set-Cookie"):
            if len(cookie) > 2048:
                oversized.append(f"{len(cookie)} bytes: {cookie[:60]}...")
        return response

    monkeypatch.setattr(flask.Flask, "process_response", checking)
    yield
    assert not oversized, f"the web app set a cookie over 2 KB: {oversized}"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def sample_xlsx(tmp_path: Path) -> Path:
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
def body_template_file(tmp_path: Path) -> Path:
    """Create a body template file."""
    path = tmp_path / "body.txt"
    path.write_text("Hello {{name}},\n\nWelcome from {{company}}.\n", encoding="utf-8")
    return path
