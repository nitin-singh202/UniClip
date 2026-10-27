import pytest
from flask import session


def test_guest_session_creation(client):
    """Test entering guest mode creates a local guest session without Firebase."""
    resp = client.post("/api/auth/guest-session")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["user"]["is_guest"] is True
    assert data["user"]["uid"] == "guest"


def test_guest_session_can_access_dashboard_and_settings(client):
    """Test guest mode allows viewing the dashboard and settings shell."""
    client.post("/api/auth/guest-session")

    resp_dash = client.get("/dashboard")
    assert resp_dash.status_code == 200
    assert "UniClip" in resp_dash.get_data(as_text=True)

    resp_settings = client.get("/settings")
    assert resp_settings.status_code == 200
    assert "Guest Mode" in resp_settings.get_data(as_text=True) or "Guest" in resp_settings.get_data(as_text=True)


def test_guest_session_entries_api_returns_empty_and_no_firestore(client):
    """Test guest session returns empty entries without touching Firestore."""
    client.post("/api/auth/guest-session")
    resp = client.get("/api/clipboard/entries")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["entries"] == []
    assert data["is_guest"] is True
    assert data["sync_status"] == "guest_ready"


def test_guest_cannot_invoke_server_delete_apis(client):
    """Test guest mode is strictly blocked from invoking cloud deletion APIs."""
    client.post("/api/auth/guest-session")
    resp_del = client.post("/api/clipboard/entry-123/delete")
    assert resp_del.status_code == 403
    assert "locally" in resp_del.get_json()["error"] or "locally" in resp_del.get_json()["message"]


def test_guest_session_end(client):
    """Test ending guest session clears the session cleanly."""
    client.post("/api/auth/guest-session")
    resp_end = client.post("/api/auth/guest-session/end")
    assert resp_end.status_code == 200
    assert resp_end.get_json()["success"] is True

    # Access to dashboard should now redirect to login
    resp_dash = client.get("/dashboard")
    assert resp_dash.status_code == 302
    assert "/login" in resp_dash.headers["Location"]


def test_guest_transition_to_authenticated_session(client):
    """Test transitioning from guest mode to authenticated session cleans up guest state."""
    client.post("/api/auth/guest-session")
    # Now user signs in with Google ID token
    resp_auth = client.post("/api/auth/session", json={"id_token": "mock-valid-token-alice"})
    assert resp_auth.status_code == 200
    data = resp_auth.get_json()
    assert data["success"] is True
    assert data["user"]["uid"] == "alice"

    # Dashboard now serves authenticated Alice
    resp_dash = client.get("/dashboard")
    assert resp_dash.status_code == 200
    assert "Alice" in resp_dash.get_data(as_text=True)
