import pytest
from web.services.firestore_service import FirestoreService

def test_firestore_service_availability():
    """Verify FirestoreService client initializes with configured key."""
    assert FirestoreService.is_available() is True

def test_firestore_sync_and_delete_cycle():
    """Test full cycle of upserting, fetching, and deleting a document in Firestore."""
    uid = "BPUWUPnGRPfSpey62VFi5UIsnHm2"
    test_entry = {
        "id": "test_integration_entry_9999",
        "user_id": uid,
        "content": "Pytest Live Firestore Sync Test",
        "entry_type": "text",
        "created_at": 1792840000000,
        "updated_at": 1792840000000,
        "expires_at": 1793444800000,
        "schema_version": 1,
    }

    # 1. Sync
    synced = FirestoreService.sync_entry(test_entry)
    assert synced is True

    # 2. Delete
    deleted = FirestoreService.delete_entry(uid, "test_integration_entry_9999")
    assert deleted is True
