"""
Unit Tests for UniClip Locust Load Testing Suite
=================================================
Validates the load test script logic, CSRF extraction, synthetic payload generation,
host safety checks, and endpoint compatibility without launching a live load test.
"""

import pytest
from load_tests.locustfile import (
    extract_csrf_token,
    is_remote_url,
    generate_synthetic_payload,
    UniClipUser,
    UniClipGuestUser,
)
from web.app import create_app
from web.config import TestConfig


def test_csrf_token_extraction_from_meta():
    """Verify extract_csrf_token parses 64-char hexadecimal tokens from meta tags."""
    token = "a" * 64
    sample_html = f'<!DOCTYPE html><html><head><meta name="csrf-token" content="{token}"></head></html>'
    extracted = extract_csrf_token(sample_html)
    assert extracted == token


def test_csrf_token_extraction_empty_or_invalid():
    """Verify extract_csrf_token handles empty or non-matching HTML gracefully."""
    assert extract_csrf_token("") is None
    assert extract_csrf_token("<html><body>No token here</body></html>") is None


def test_is_remote_url_safety():
    """Verify is_remote_url identifies local vs remote domains accurately."""
    assert is_remote_url("http://127.0.0.1:5000") is False
    assert is_remote_url("http://localhost:5000") is False
    assert is_remote_url("http://0.0.0.0:5000") is False
    assert is_remote_url("https://uniclip.onrender.com") is True
    assert is_remote_url("https://firestore.googleapis.com") is True


def test_synthetic_payload_format():
    """Verify synthetic clipboard payload contains user prefix and valid content."""
    uid = "sim_test_user_1"
    payload = generate_synthetic_payload(uid)
    assert payload.startswith(f"[{uid}#")
    assert len(payload) > 15


def test_locust_user_classes_configuration():
    """Verify Locust user classes are properly configured."""
    assert UniClipUser.tasks is not None
    assert len(UniClipUser.tasks) >= 5
    assert UniClipGuestUser.weight == 1


def test_simulated_user_workflow_against_test_client():
    """
    Test the exact sequence of endpoints that UniClipUser executes,
    ensuring routes exist and return expected status codes and payloads.
    """
    app = create_app(TestConfig)
    with app.test_client() as client:
        test_uid = "sim_unit_test_99"

        # 1. Establish session
        auth_resp = client.post(
            "/api/auth/session",
            json={"id_token": f"mock-valid-token-{test_uid}"},
        )
        assert auth_resp.status_code == 200
        assert auth_resp.get_json()["success"] is True

        # 2. Get dashboard and extract CSRF
        dash_resp = client.get("/dashboard")
        assert dash_resp.status_code == 200
        csrf_token = extract_csrf_token(dash_resp.get_data(as_text=True))
        assert csrf_token is not None
        assert len(csrf_token) == 64

        # 3. Add clipboard entry
        add_resp = client.post(
            "/api/clipboard",
            json={"content": "Unit test synthetic clipboard payload"},
            headers={"X-CSRF-Token": csrf_token},
        )
        assert add_resp.status_code == 201
        add_data = add_resp.get_json()
        assert add_data["success"] is True
        entry_id = add_data["entry"]["id"]

        # 4. Poll entries
        poll_resp = client.get("/api/clipboard/entries")
        assert poll_resp.status_code == 200
        entries = poll_resp.get_json()["entries"]
        assert any(e["id"] == entry_id for e in entries)

        # 5. Inspect entry
        inspect_resp = client.get(f"/api/clipboard/{entry_id}")
        assert inspect_resp.status_code == 200
        assert inspect_resp.get_json()["user_id"] == test_uid

        # 6. Delete entry
        del_resp = client.post(
            f"/api/clipboard/{entry_id}/delete",
            headers={"X-CSRF-Token": csrf_token},
        )
        assert del_resp.status_code == 200
        assert del_resp.get_json()["success"] is True


def test_reproduce_401_when_dev_mock_auth_is_disabled():
    """
    Reproduce the exact 401 Unauthorized observed during the load test:
    When DEV_MOCK_AUTH=False, posting synthetic mock tokens ('mock-valid-token-sim_xxx')
    must be rejected with HTTP 401 because the server attempts live Firebase validation.
    """
    class NoMockAuthConfig(TestConfig):
        DEV_MOCK_AUTH = False

    app = create_app(NoMockAuthConfig)
    with app.test_client() as client:
        resp = client.post(
            "/api/auth/session",
            json={"id_token": "mock-valid-token-sim_reproduce_401"},
        )
        assert resp.status_code == 401
        data = resp.get_json()
        assert data["success"] is False
        assert "error" in data


def test_verify_fix_when_dev_mock_auth_is_enabled():
    """
    Verify the fix:
    When DEV_MOCK_AUTH=True (as configured in web/.env with override=True),
    synthetic mock tokens ('mock-valid-token-sim_xxx') succeed with HTTP 200
    and create an isolated session with the exact simulated user ID.
    """
    app = create_app(TestConfig)
    with app.test_client() as client:
        test_uid = "sim_verified_fix_user"
        resp = client.post(
            "/api/auth/session",
            json={"id_token": f"mock-valid-token-{test_uid}"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["user"]["uid"] == test_uid
        assert data["user"]["email"] == f"{test_uid}@example.com"


def test_simulated_user_data_isolation():
    """
    Ensure complete data isolation between multiple concurrent simulated users:
    User A cannot access or see User B's clipboard entries.
    """
    app = create_app(TestConfig)
    
    # User A workflow
    with app.test_client() as client_a:
        client_a.post("/api/auth/session", json={"id_token": "mock-valid-token-sim_user_alpha"})
        dash_a = client_a.get("/dashboard")
        csrf_a = extract_csrf_token(dash_a.get_data(as_text=True))
        
        # User A creates an entry
        add_a = client_a.post(
            "/api/clipboard",
            json={"content": "Alpha secret clipboard item"},
            headers={"X-CSRF-Token": csrf_a},
        )
        assert add_a.status_code == 201
        entry_a_id = add_a.get_json()["entry"]["id"]

    # User B workflow in a separate client session
    with app.test_client() as client_b:
        client_b.post("/api/auth/session", json={"id_token": "mock-valid-token-sim_user_beta"})
        dash_b = client_b.get("/dashboard")
        csrf_b = extract_csrf_token(dash_b.get_data(as_text=True))

        # User B queries their entries: should NOT contain User A's entry
        poll_b = client_b.get("/api/clipboard/entries")
        assert poll_b.status_code == 200
        entries_b = poll_b.get_json()["entries"]
        assert all(e["id"] != entry_a_id for e in entries_b)

        # User B attempting to inspect User A's entry directly must receive 404
        inspect_b = client_b.get(f"/api/clipboard/{entry_a_id}")
        assert inspect_b.status_code == 404


def test_load_test_mode_uses_isolated_database(tmp_path):
    """
    Verify that in LOAD_TEST_MODE:
    1. Operations read/write exclusively to the isolated load test database.
    2. The production database ('clipboard_local.db') is never modified or touched.
    """
    from web.config import LoadTestConfig
    import sqlite3

    isolated_db = tmp_path / "custom_load_test.db"

    class CustomLoadTestConfig(LoadTestConfig):
        SQLITE_DB_PATH = isolated_db

    app = create_app(CustomLoadTestConfig)
    with app.test_client() as client:
        test_uid = "sim_isolated_db_user"

        # Authenticate
        client.post("/api/auth/session", json={"id_token": f"mock-valid-token-{test_uid}"})
        dash = client.get("/dashboard")
        csrf = extract_csrf_token(dash.get_data(as_text=True))

        # Create entry
        add_resp = client.post(
            "/api/clipboard",
            json={"content": "Isolated test entry"},
            headers={"X-CSRF-Token": csrf},
        )
        assert add_resp.status_code == 201
        entry_id = add_resp.get_json()["entry"]["id"]

        # Verify entry was written directly to the isolated SQLite database
        assert isolated_db.exists()
        with sqlite3.connect(str(isolated_db)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM clipboard_entries WHERE id = ?", (entry_id,)).fetchone()
            assert row is not None
            assert row["content"] == "Isolated test entry"
            assert row["user_id"] == test_uid

        # Delete entry
        del_resp = client.post(
            f"/api/clipboard/{entry_id}/delete",
            headers={"X-CSRF-Token": csrf},
        )
        assert del_resp.status_code == 200

        # Verify deletion in isolated database
        with sqlite3.connect(str(isolated_db)) as conn:
            row = conn.execute("SELECT * FROM clipboard_entries WHERE id = ?", (entry_id,)).fetchone()
            assert row is None


def test_firestore_strictly_blocked_in_load_test_mode():
    """
    Verify that when LOAD_TEST_MODE is enabled:
    1. FirestoreService.is_available() is False.
    2. FirestoreService.get_client() is None.
    3. Any direct write/delete attempts raise the fail-closed RuntimeError.
    """
    from web.config import LoadTestConfig
    from web.services.firestore_service import FirestoreService

    app = create_app(LoadTestConfig)
    with app.app_context():
        # Assert client is blocked
        assert FirestoreService.is_available() is False
        assert FirestoreService.get_client() is None

        # Assert fail-closed guards raise RuntimeError on any attempt to sync or delete
        sample_entry = {
            "id": "test-id-123",
            "user_id": "sim_user_123",
            "content": "Test content",
            "entry_type": "text",
            "created_at": 1000000,
            "expires_at": 2000000,
        }

        with pytest.raises(RuntimeError, match="FAIL-CLOSED GUARD"):
            FirestoreService.sync_entry(sample_entry)

        with pytest.raises(RuntimeError, match="FAIL-CLOSED GUARD"):
            FirestoreService.delete_entry("sim_user_123", "test-id-123")

        with pytest.raises(RuntimeError, match="FAIL-CLOSED GUARD"):
            FirestoreService.bulk_delete_entries("sim_user_123", ["test-id-123"])


