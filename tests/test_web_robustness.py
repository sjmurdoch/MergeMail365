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
