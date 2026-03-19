"""Tests for the web UI robustness features (session stability and state persistence)."""

import pytest
import hashlib
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
