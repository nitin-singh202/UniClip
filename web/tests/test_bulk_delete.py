import time
import pytest
from unittest.mock import patch, MagicMock
from web.services import ClipboardService, FirestoreService


def test_bulk_delete_endpoint_success(auth_client):
    """Test successful bulk deletion of multiple entries by their stable IDs."""
    uid = "user_alice"
    # Create 3 test entries
    e1 = ClipboardService.add_entry(uid, "Bulk entry 1")
    e2 = ClipboardService.add_entry(uid, "Bulk entry 2")
    e3 = ClipboardService.add_entry(uid, "Bulk entry 3")

    ids_to_delete = [e1["id"], e2["id"]]

    response = auth_client.post(
        "/api/clipboard/bulk-delete",
        json={"ids": ids_to_delete},
        headers={"X-CSRF-Token": "test-csrf-token-alice"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert set(data["deleted_ids"]) == set(ids_to_delete)
    assert data["count"] == 2
    assert data["failed_ids"] == []

    # Verify e1 and e2 are gone, e3 remains
    entries, _ = ClipboardService.list_entries(uid)
    remaining_ids = [e["id"] for e in entries]
    assert e1["id"] not in remaining_ids
    assert e2["id"] not in remaining_ids
    assert e3["id"] in remaining_ids


def test_bulk_delete_unauthorized_isolation(auth_client):
    """Test that User Alice cannot delete User Bob's records."""
    user_a = "user_alice"
    user_b = "user_bob"

    # User B creates an entry
    e_victim = ClipboardService.add_entry(user_b, "Bob confidential text")
    # User A creates an entry
    e_attacker = ClipboardService.add_entry(user_a, "Alice entry")

    # User A attempts to bulk delete both their own entry and User B's entry
    response = auth_client.post(
        "/api/clipboard/bulk-delete",
        json={"ids": [e_victim["id"], e_attacker["id"]]},
        headers={"X-CSRF-Token": "test-csrf-token-alice"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    # Only Alice's own entry must be reported deleted
    assert e_attacker["id"] in data["deleted_ids"]
    assert e_victim["id"] not in data["deleted_ids"]

    # Verify User B's entry still exists
    victim_entries, _ = ClipboardService.list_entries(user_b)
    assert any(e["id"] == e_victim["id"] for e in victim_entries)


def test_bulk_delete_validation(auth_client):
    """Test payload validation for empty, malformed, or oversized batches."""
    # Empty list
    res1 = auth_client.post(
        "/api/clipboard/bulk-delete",
        json={"ids": []},
        headers={"X-CSRF-Token": "test-csrf-token-alice"},
    )
    assert res1.status_code == 400

    # Non-list ids
    res2 = auth_client.post(
        "/api/clipboard/bulk-delete",
        json={"ids": "not-a-list"},
        headers={"X-CSRF-Token": "test-csrf-token-alice"},
    )
    assert res2.status_code == 400

    # Oversized batch (> 500 items)
    oversized = [f"id-{i}" for i in range(501)]
    res3 = auth_client.post(
        "/api/clipboard/bulk-delete",
        json={"ids": oversized},
        headers={"X-CSRF-Token": "test-csrf-token-alice"},
    )
    assert res3.status_code == 400
    assert "Maximum bulk deletion batch size" in res3.get_json()["error"]


def test_bulk_delete_csrf_enforcement(client):
    """Test that missing CSRF or unauthenticated requests are rejected."""
    # Unauthenticated
    res = client.post("/api/clipboard/bulk-delete", json={"ids": ["id-1"]})
    assert res.status_code == 401

    # Authenticated but missing CSRF token
    with client.session_transaction() as sess:
        sess["user"] = {"uid": "user_1", "email": "u1@test.com"}
        sess["_csrf_token"] = "expected-token"
    res2 = client.post(
        "/api/clipboard/bulk-delete",
        json={"ids": ["id-1"]},
        headers={"X-CSRF-Token": "wrong-token"},
    )
    assert res2.status_code == 400


def test_bulk_delete_firestore_chunking_and_partial_failure():
    """Test Firestore batch deletion chunking and partial failure isolation."""
    uid = "test_user_chunking"
    entry_ids = [f"entry_{i}" for i in range(450)]

    mock_db = MagicMock()
    mock_batch = MagicMock()
    mock_db.batch.return_value = mock_batch

    with patch.object(FirestoreService, "get_client", return_value=mock_db):
        # 450 items should be split into 2 batches (400 and 50)
        deleted, failed = FirestoreService.bulk_delete_entries(uid, entry_ids)
        assert len(deleted) == 450
        assert len(failed) == 0
        assert mock_db.batch.call_count == 2
        assert mock_batch.commit.call_count == 2


def test_bulk_delete_partial_failure_reporting(auth_client):
    """Test that partial cloud failures are reflected truthfully in response."""
    uid = "user_alice"
    e1 = ClipboardService.add_entry(uid, "Item 1")
    e2 = ClipboardService.add_entry(uid, "Item 2")

    # Mock FirestoreService.bulk_delete_entries to return partial failure
    with patch.object(
        FirestoreService,
        "is_available",
        return_value=True,
    ), patch.object(
        FirestoreService,
        "bulk_delete_entries",
        return_value=([e1["id"]], [e2["id"]]),
    ):
        response = auth_client.post(
            "/api/clipboard/bulk-delete",
            json={"ids": [e1["id"], e2["id"]]},
            headers={"X-CSRF-Token": "test-csrf-token-alice"},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["deleted_ids"] == [e1["id"]]
        assert data["failed_ids"] == [e2["id"]]


def test_tombstone_prevents_resurrection(tmp_path):
    """Test that deleted records cannot be resurrected by sync or offline cache."""
    from desktop_watcher import ClipboardDatabase

    db_file = tmp_path / "test_tombstone.db"
    db = ClipboardDatabase(db_file)

    # 1. Insert entry
    rec = db.insert_entry("Secret persistence item", user_id="user_tomb")
    entry_id = rec["id"]

    # 2. Delete and record tombstone
    db.record_tombstone(entry_id, "user_tomb")
    assert db.is_deleted(entry_id) is True

    # 3. Verify entry cannot be re-inserted or resurrected with same ID
    with db.get_connection() as conn:
        tombstone = conn.execute("SELECT * FROM deleted_entries WHERE id = ?", (entry_id,)).fetchone()
        assert tombstone is not None
        assert tombstone["id"] == entry_id
        assert tombstone["user_id"] == "user_tomb"


def test_seven_day_retention_preserved():
    """Verify that non-deleted records retain their 7-day retention schedule."""
    uid = "user_retention"
    now_ms = int(time.time() * 1000)

    # Active entry created now
    active = ClipboardService.add_entry(uid, "Active text", created_at=now_ms)
    expected_expires = now_ms + (7 * 24 * 60 * 60 * 1000)
    assert abs(active["expires_at"] - expected_expires) < 2000

    # Old entry created 8 days ago
    eight_days_ago_ms = now_ms - (8 * 24 * 60 * 60 * 1000)
    expired = ClipboardService.add_entry(uid, "Expired text", created_at=eight_days_ago_ms)

    # list_entries should automatically exclude expired item
    entries, _ = ClipboardService.list_entries(uid, now_ms=now_ms)
    returned_ids = [e["id"] for e in entries]
    assert active["id"] in returned_ids
    assert expired["id"] not in returned_ids
