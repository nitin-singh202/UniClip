from flask import url_for


def test_1_application_starts_in_dev_mode(client):
    """Test 1: Application starts and responds to root endpoint."""
    resp = client.get("/")
    # Root redirects to /login for unauthenticated users
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_2_login_page_renders(client):
    """Test 2: Login page renders with branding, sign-in button, and privacy note."""
    resp = client.get("/login")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Universal Clipboard AI" in html
    assert "Sign in with Google" in html
    assert "Privacy Notice" in html


def test_3_unauthenticated_access_to_dashboard_rejected(client):
    """Test 3: Unauthenticated access to dashboard and settings is rejected/redirected."""
    resp_dash = client.get("/dashboard")
    assert resp_dash.status_code == 302
    assert "/login" in resp_dash.headers["Location"]

    resp_settings = client.get("/settings")
    assert resp_settings.status_code == 302
    assert "/login" in resp_settings.headers["Location"]

    # API endpoints return 401 JSON
    resp_api = client.get("/api/clipboard/some-id")
    assert resp_api.status_code == 401
    assert resp_api.get_json()["error"] == "Unauthorized"


def test_4_invalid_or_expired_auth_rejected(client):
    """Test 4: Invalid or expired Firebase authentication token is rejected."""
    # Test missing token
    resp_missing = client.post("/api/auth/session", json={})
    assert resp_missing.status_code == 400

    # Test expired token
    resp_expired = client.post("/api/auth/session", json={"id_token": "mock-expired-token"})
    assert resp_expired.status_code == 401
    assert "expired" in resp_expired.get_json()["error"].lower()

    # Test invalid token
    resp_invalid = client.post("/api/auth/session", json={"id_token": "mock-invalid-signature"})
    assert resp_invalid.status_code == 401


def test_auth_session_creation_success(client):
    """Test valid token sets up session correctly."""
    resp = client.post("/api/auth/session", json={"id_token": "mock-valid-token-alice"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["user"]["uid"] == "alice"

    # Now Alice can access the dashboard
    resp_dash = client.get("/dashboard")
    assert resp_dash.status_code == 200
    assert "Alice" in resp_dash.get_data(as_text=True)


def test_11_csrf_protection_enforced(auth_client):
    """Test 11: CSRF protection is enforced for state-changing requests."""
    # POST without CSRF header or form token
    resp = auth_client.post("/api/clipboard", json={"content": "Sensitive note"})
    assert resp.status_code == 400
    assert "CSRF" in resp.get_data(as_text=True)

    # POST with invalid CSRF token
    resp_bad = auth_client.post(
        "/api/clipboard",
        headers={"X-CSRF-Token": "completely-invalid-csrf-token"},
        json={"content": "Sensitive note"},
    )
    assert resp_bad.status_code == 400

    # POST with valid CSRF token succeeds
    resp_good = auth_client.post(
        "/api/clipboard",
        headers={"X-CSRF-Token": "test-csrf-token-alice"},
        json={"content": "Valid test entry"},
    )
    assert resp_good.status_code == 201


def test_logout_clears_session(auth_client):
    """Test logout invalidates session and redirects to login."""
    resp = auth_client.post(
        "/logout",
        headers={"X-CSRF-Token": "test-csrf-token-alice"},
    )
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]

    # Verify subsequent protected access is blocked
    resp_dash = auth_client.get("/dashboard")
    assert resp_dash.status_code == 302
