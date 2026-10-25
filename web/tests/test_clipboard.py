import time
from web.services import ClipboardService


def test_5_user_isolation_cannot_read_or_delete_other_user(auth_client, bob_client):
    """Test 5: One user's entries cannot be read or deleted by another user."""
    # Alice adds an entry
    alice_entry = ClipboardService.add_entry(
        uid="user_alice",
        content="Alice confidential data",
    )
    entry_id = alice_entry["id"]

    # Bob attempts to read Alice's entry via API
    resp_bob_read = bob_client.get(f"/api/clipboard/{entry_id}")
    assert resp_bob_read.status_code == 404

    # Bob attempts to delete Alice's entry via API
    resp_bob_delete = bob_client.post(
        f"/api/clipboard/{entry_id}/delete",
        headers={"X-CSRF-Token": "test-csrf-token-bob"},
    )
    assert resp_bob_delete.status_code == 404

    # Confirm Alice's entry is still completely intact
    alice_check = ClipboardService.get_entry("user_alice", entry_id)
    assert alice_check is not None
    assert alice_check["content"] == "Alice confidential data"


def test_7_invalid_entry_identifiers_handled_safely(auth_client):
    """Test 7: Invalid or nonexistent entry identifiers return 404 cleanly without crashing."""
    resp = auth_client.get("/api/clipboard/non-existent-uuid-99999")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "Entry not found or access denied"

    resp_del = auth_client.post(
        "/api/clipboard/non-existent-uuid-99999/delete",
        headers={"X-CSRF-Token": "test-csrf-token-alice"},
    )
    assert resp_del.status_code == 404


def test_8_empty_history_renders_correctly(auth_client):
    """Test 8: Empty history renders gracefully with empty state banner."""
    resp = auth_client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "No clipboard history yet" in html
    assert "0 items" in html


def test_9_search_does_not_return_another_users_data(auth_client, bob_client):
    """Test 9: Search does not leak another user's matching entries."""
    # Alice has entry with keyword 'secretcode'
    ClipboardService.add_entry(uid="user_alice", content="Alice secretcode 12345")
    # Bob has entry with keyword 'secretcode'
    ClipboardService.add_entry(uid="user_bob", content="Bob secretcode 98765")

    # Bob searches for 'secretcode' on dashboard
    resp = bob_client.get("/dashboard?q=secretcode")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Bob secretcode 98765" in html
    assert "Alice secretcode 12345" not in html


def test_10_retention_filtering_excludes_expired_entries(auth_client):
    """Test 10: Retention filtering excludes entries past their 7-day expiration deadline."""
    now_ms = int(time.time() * 1000)
    eight_days_ago_ms = now_ms - (8 * 24 * 60 * 60 * 1000)
    expired_deadline_ms = eight_days_ago_ms + (7 * 24 * 60 * 60 * 1000)

    # Add expired entry
    ClipboardService.add_entry(
        uid="user_alice",
        content="Old expired note from 8 days ago",
        created_at=eight_days_ago_ms,
        expires_at=expired_deadline_ms,
    )

    # Add active entry
    ClipboardService.add_entry(
        uid="user_alice",
        content="Fresh active note from today",
    )

    # List entries through service
    entries, _ = ClipboardService.list_entries("user_alice", now_ms=now_ms)
    assert len(entries) == 1
    assert entries[0]["content"] == "Fresh active note from today"

    # Verify on dashboard rendering
    resp = auth_client.get("/dashboard")
    html = resp.get_data(as_text=True)
    assert "Fresh active note from today" in html
    assert "Old expired note from 8 days ago" not in html


def test_entries_sorted_newest_first(auth_client):
    """Test that multiple entries are displayed newest first."""
    now_ms = int(time.time() * 1000)
    ClipboardService.add_entry(uid="user_alice", content="First Older Entry", created_at=now_ms - 2000)
    ClipboardService.add_entry(uid="user_alice", content="Second Newer Entry", created_at=now_ms)

    entries, _ = ClipboardService.list_entries("user_alice")
    assert entries[0]["content"] == "Second Newer Entry"
    assert entries[1]["content"] == "First Older Entry"


def test_api_clipboard_entries_endpoint(auth_client):
    """Test the live polling API endpoint returns formatted entries and supports search."""
    ClipboardService.add_entry(uid="user_alice", content="Alpha document entry")
    ClipboardService.add_entry(uid="user_alice", content="Beta link entry")

    # Fetch all
    resp = auth_client.get("/api/clipboard/entries")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["total_count"] == 2
    assert len(data["entries"]) == 2
    assert "formatted_time" in data["entries"][0]
    assert "time_left" in data["entries"][0]

    # Test search filtering via API
    resp_search = auth_client.get("/api/clipboard/entries?q=Alpha")
    assert resp_search.status_code == 200
    data_search = resp_search.get_json()
    assert data_search["total_count"] == 1
    assert data_search["entries"][0]["content"] == "Alpha document entry"


def test_api_unauthenticated_rejected(client):
    """Test unauthenticated access to the live polling API returns 401."""
    resp = client.get("/api/clipboard/entries")
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "Unauthorized"

    # Also test the /entries alias
    resp_alias = client.get("/entries?q=")
    assert resp_alias.status_code == 401
    assert resp_alias.get_json()["error"] == "Unauthorized"


def test_entries_alias_endpoint(auth_client):
    """Test the /entries alias route is accessible to authenticated users."""
    ClipboardService.add_entry(uid="user_alice", content="Alias test entry")
    resp = auth_client.get("/entries?q=Alias")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["total_count"] == 1
    assert data["entries"][0]["content"] == "Alias test entry"

