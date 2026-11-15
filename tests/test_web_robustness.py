"""Tests for the web UI robustness features (session stability and state persistence)."""

import hashlib
from html.parser import HTMLParser
from pathlib import Path

import pytest

from mail_merge.web.app import create_app

@pytest.fixture
def client():
    app = create_app(startup_token="test")
    app.config["TESTING"] = True
    return app.test_client()

def get_csrf(client):
    client.get("/") # Initialize session
    with client.session_transaction() as sess:
        return sess.get("csrf_token")

def test_secret_key_stability():
    """Verify that create_app generates a stable secret_key for the same token."""
    token = "stable-token-123"
    app1 = create_app(startup_token=token)
    app2 = create_app(startup_token=token)
    
    assert app1.secret_key == app2.secret_key
    assert app1.secret_key == hashlib.sha256(token.encode()).hexdigest()

def test_secret_key_uniqueness():
    """Verify that different tokens produce different secret keys."""
    app1 = create_app(startup_token="token-a")
    app2 = create_app(startup_token="token-b")
    
    assert app1.secret_key != app2.secret_key

def test_state_persistence_api(client):
    """Verify that /api/state correctly saves wizard progress to the session."""
    # 1. Establish session
    client.get("/?token=test")
    csrf = get_csrf(client)
    
    # 2. Save state
    resp = client.post("/api/state", json={
        "current_step": 3,
        "test_passed": True,
        "verify_passed": False
    }, headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200
    
    # 3. Check config returns saved state
    resp = client.get("/api/config")
    assert resp.status_code == 200
    data = resp.get_json()
    
    assert data["current_step"] == 3
    assert data["test_passed"] is True
    assert data["verify_passed"] is False

def test_state_partial_update(client):
    """Verify that partial state updates work correctly."""
    # Establish session
    client.get("/?token=test")
    csrf = get_csrf(client)
    
    # Set initial state
    client.post("/api/state", json={"current_step": 2, "test_passed": False}, 
                headers={"X-CSRF-Token": csrf})
    
    # Update only one field
    client.post("/api/state", json={"current_step": 4},
                headers={"X-CSRF-Token": csrf})
    
    resp = client.get("/api/config")
    data = resp.get_json()
    assert data["current_step"] == 4
    assert data["test_passed"] is False # Preserved


VOID_ELEMENTS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
})

TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent
    / "src" / "mail_merge" / "web" / "templates" / "index.html"
)


class _TagChecker(HTMLParser):
    """Stack-based checker for unbalanced / misnested HTML tags."""

    def __init__(self):
        super().__init__()
        self.stack: list[tuple[str, int]] = []  # (tag, line)
        self.errors: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID_ELEMENTS:
            self.stack.append((tag, self.getpos()[0]))

    def handle_endtag(self, tag):
        if tag in VOID_ELEMENTS:
            return
        # Walk back to find matching open tag
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                # Report anything between as unclosed
                for j in range(len(self.stack) - 1, i, -1):
                    t, line = self.stack[j]
                    self.errors.append(f"line {line}: <{t}> never closed")
                self.stack.pop(i)
                # Remove the unclosed ones above it
                del self.stack[i:]
                return
        self.errors.append(
            f"line {self.getpos()[0]}: </{tag}> has no matching opening tag"
        )

    def check_remaining(self):
        for tag, line in self.stack:
            self.errors.append(f"line {line}: <{tag}> never closed")


def test_template_tags_balanced():
    """Verify index.html has no unclosed or misnested tags."""
    html = TEMPLATE_PATH.read_text()
    checker = _TagChecker()
    checker.feed(html)
    checker.check_remaining()
    assert checker.errors == [], (
        "Unbalanced tags in index.html:\n  " + "\n  ".join(checker.errors)
    )


# ---- docs/review-fixes-plan.md, B5: robustness seen during the review ----


@pytest.fixture
def signed_in(client):
    client.get("/?token=test")
    return client, {"X-CSRF-Token": get_csrf(client)}


@pytest.fixture
def small_xlsx(tmp_path: Path) -> Path:
    import openpyxl

    path = tmp_path / "people.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["email", "name"])
    ws.append(["alice@example.com", "Alice"])
    wb.save(path)
    return path


def upload(client, headers, xlsx: Path) -> None:
    with xlsx.open("rb") as f:
        assert client.post("/api/upload-spreadsheet", data={"spreadsheet": (f, "people.xlsx")},
                           headers=headers).status_code == 200


def wait_done(client, job_id: str) -> dict:
    import time

    deadline = time.monotonic() + 15
    while True:
        status = client.get(f"/api/job/{job_id}/status").get_json()
        if status["status"] not in ("pending", "running"):
            return status
        assert time.monotonic() < deadline
        time.sleep(0.01)


@pytest.mark.parametrize(("route", "kwargs"), [
    ("/api/state", {"data": "not json", "content_type": "application/json"}),
    ("/api/state", {"data": "[1, 2]", "content_type": "application/json"}),
    ("/api/state", {"data": "null", "content_type": "application/json"}),
    ("/api/state", {"data": "current_step=2"}),
    ("/api/change-sheet", {"data": "{", "content_type": "application/json"}),
    ("/api/change-sheet", {"data": '"Sheet1"', "content_type": "application/json"}),
    ("/api/change-sheet", {"data": '{"sheet": 5}', "content_type": "application/json"}),
    ("/api/preview-template", {"data": "<xml/>", "content_type": "text/xml"}),
    ("/api/preview-template", {"data": "[]", "content_type": "application/json"}),
])
def test_malformed_json_is_a_400_with_a_json_error(signed_in, small_xlsx, route, kwargs):
    """Not a 500, and not werkzeug's HTML error page: the page's fetch()
    callers read every answer as JSON."""
    client, headers = signed_in
    upload(client, headers, small_xlsx)
    resp = client.post(route, headers=headers, **kwargs)
    assert resp.status_code == 400, resp.get_data(as_text=True)
    assert resp.get_json()["error"]


def test_interactive_sign_in_tolerates_a_missing_body():
    from unittest.mock import patch

    app = create_app(startup_token="test", desktop_mode=True, client_id="cid")
    client = app.test_client()
    client.get("/?token=test")
    with patch("mail_merge.auth.acquire_token_interactive_flow", return_value="tok"):
        resp = client.post("/auth/interactive", headers={"X-CSRF-Token": get_csrf(client)})
    assert resp.status_code == 200


def test_oversized_request_is_refused_with_a_json_error(signed_in, monkeypatch):
    import io

    client, headers = signed_in
    client.application.config["MAX_CONTENT_LENGTH"] = 1024
    resp = client.post("/api/upload-spreadsheet", headers=headers,
                       data={"spreadsheet": (io.BytesIO(b"x" * 4096), "big.xlsx")})
    assert resp.status_code == 413
    assert "too large" in resp.get_json()["error"]


def test_request_size_limit_is_set_and_admits_the_largest_spreadsheet():
    from mail_merge.excel import _MAX_SPREADSHEET_SIZE
    from mail_merge.web.app import MAX_REQUEST_BYTES

    app = create_app(startup_token="test")
    assert app.config["MAX_CONTENT_LENGTH"] == MAX_REQUEST_BYTES
    assert MAX_REQUEST_BYTES > _MAX_SPREADSHEET_SIZE


class TestAttachmentCleanup:
    """Each job gets its own copy of the attachments; they used to pile up
    in the session's temp directory until the next upload or exit."""

    def _start(self, client, headers, mode="dry_run"):
        import io

        return client.post("/api/start-job", headers=headers, data={
            "mode": mode, "email_column": "email", "subject": "Hi", "body": "Hello",
            "attachments": [(io.BytesIO(b"one"), "a.txt"), (io.BytesIO(b"two"), "b.txt")],
        })

    def _leftovers(self, client) -> list[str]:
        import os

        with client.session_transaction() as sess:
            tmp_dir = sess["spreadsheet_tmp_dir"]
        return sorted(n for n in os.listdir(tmp_dir) if n != "upload.xlsx")

    def test_attachments_exist_during_the_job_and_are_deleted_after(self, signed_in, small_xlsx, monkeypatch):
        client, headers = signed_in
        upload(client, headers, small_xlsx)
        seen = {}

        def fake_send_merge(**kwargs):
            seen["contents"] = sorted(Path(p).read_bytes() for p in kwargs["attachment"])
            return []

        monkeypatch.setattr("mail_merge.api.send_merge", fake_send_merge)
        for _ in range(3):
            job_id = self._start(client, headers).get_json()["job_id"]
            client.get(f"/api/job/{job_id}/events").get_data()  # until the job's last event
            assert wait_done(client, job_id)["ok"]
        assert seen["contents"] == [b"one", b"two"]
        assert self._leftovers(client) == []

    def test_deleted_when_the_job_fails(self, signed_in, small_xlsx, monkeypatch):
        client, headers = signed_in
        upload(client, headers, small_xlsx)

        def failing(**kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr("mail_merge.api.send_merge", failing)
        job_id = self._start(client, headers).get_json()["job_id"]
        client.get(f"/api/job/{job_id}/events").get_data()
        assert wait_done(client, job_id)["status"] == "failed"
        assert self._leftovers(client) == []

    def test_deleted_when_the_job_is_refused(self, signed_in, small_xlsx, monkeypatch):
        """A send while another runs is answered 409: its files must go too."""
        import threading

        from mail_merge.web.app import _job_store

        client, headers = signed_in
        client.application.config["FIXED_CLIENT_ID"] = "cid"
        upload(client, headers, small_xlsx)
        release = threading.Event()

        def held(**kwargs):
            release.wait(10)
            return []

        monkeypatch.setattr("mail_merge.api.send_merge", held)
        first = self._start(client, headers, mode="send")
        assert first.status_code == 200
        try:
            # Past the early check, so the refusal comes from JobStore.create().
            monkeypatch.setattr("mail_merge.web.app._running_send_job", lambda: None)
            second = self._start(client, headers, mode="send")
            assert second.status_code == 409
            assert len(self._leftovers(client)) == 2, "only the running send's two files should remain"
        finally:
            release.set()
        client.get(f"/api/job/{first.get_json()['job_id']}/events").get_data()
        assert self._leftovers(client) == []
        assert _job_store.running_send() is None


def test_running_send_holds_the_lock_while_it_reads_the_job_table():
    """running_send() iterates the job table while other requests' threads
    add and evict jobs; without the lock that is "dictionary changed size
    during iteration". The table here lets another thread create a job
    half-way through the iteration, so the race happens every time rather
    than now and then."""
    import threading

    from mail_merge.web.jobs import JobStore

    store = JobStore()
    assert store.create("dry_run") is not None
    assert store.create("dry_run") is not None
    created = threading.Event()

    def create_another() -> None:
        store.create("dry_run")
        created.set()

    class PausesHalfWay(dict):  # type: ignore[type-arg]
        def values(self):  # type: ignore[no-untyped-def, override]
            jobs = iter(super().values())
            yield next(jobs)
            threading.Thread(target=create_another).start()
            # With the lock held, create() waits and this times out.
            created.wait(0.2)
            yield from jobs

    store.jobs = PausesHalfWay(store.jobs)
    assert store.running_send() is None
    assert created.wait(5), "the job was never created once the lock was free"
    assert len(store.jobs) == 3
