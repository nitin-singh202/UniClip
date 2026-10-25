import time
import pytest
from pathlib import Path
from desktop_watcher import SecretDetector, ClipboardDatabase, ClipboardWatcher, detect_entry_type


@pytest.fixture
def temp_db(tmp_path):
    """Provide a temporary SQLite database for testing."""
    db_file = tmp_path / "test_clipboard.db"
    return ClipboardDatabase(db_file)


def test_1_harmless_text_stored_in_sqlite(temp_db):
    """Test 1: Harmless text is detected, validated, and stored in SQLite."""
    watcher = ClipboardWatcher(db=temp_db)
    sample_text = "Shopping list: apples, milk, bread"

    record = watcher.process_clipboard_text(sample_text)
    assert record is not None
    assert record["content"] == sample_text
    assert record["entry_type"] == "text"
    assert record["schema_version"] == 1
    assert record["expires_at"] > record["created_at"]

    # Verify persisted in database
    latest = temp_db.get_latest_entry()
    assert latest is not None
    assert latest["content"] == sample_text
    assert latest["id"] == record["id"]


def test_2_url_detection(temp_db):
    """Test 2: URLs are accurately detected as type 'url'."""
    watcher = ClipboardWatcher(db=temp_db)
    sample_url = "https://flutter.dev/docs/get-started"

    record = watcher.process_clipboard_text(sample_url)
    assert record is not None
    assert record["entry_type"] == "url"


def test_3_duplicate_text_ignored(temp_db):
    """Test 3: Copying the same content consecutively is ignored to prevent duplicates."""
    watcher = ClipboardWatcher(db=temp_db)
    sample_text = "Repeated text block"

    first_record = watcher.process_clipboard_text(sample_text)
    assert first_record is not None
    assert temp_db.count_entries() == 1

    # Second copy of identical text
    second_record = watcher.process_clipboard_text(sample_text)
    assert second_record is None
    assert temp_db.count_entries() == 1  # Still 1 entry


def test_4_secret_detection_rejects_sensitive_data(temp_db):
    """Test 4: Secret detection rejects API keys, passwords, and tokens before persistence."""
    watcher = ClipboardWatcher(db=temp_db)

    secret_samples = [
        ("AWS Key", "AKIAIOSFODNN7EXAMPLE"),
        ("GitHub Token", "ghp_1234567890abcdefghijklmnopqrstuvwxyz"),
        ("Google API Key", "AIzaSyCsoJiLxt8n8g8c-zrPM_ji0L6XuStbMwo"),
        ("OpenAI Key", "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789"),
        ("Private Key", "-----BEGIN RSA PRIVATE KEY-----\nMIIEogIBAAKCAQEA0..."),
        ("Labeled Password", "password = CorrectHorseBatteryStaple123!"),
        ("DB URL with Pass", "postgres://admin:SecretPass999@localhost:5432/db"),
    ]

    for label, secret in secret_samples:
        is_secret, rule = SecretDetector.check(secret)
        assert is_secret is True, f"Failed to identify secret: {label}"

        # Attempt to process through watcher
        record = watcher.process_clipboard_text(secret)
        assert record is None, f"Secret was not rejected by watcher: {label}"

    # Confirm NOTHING was saved to SQLite
    assert temp_db.count_entries() == 0


def test_5_clipboard_access_error_resilience(temp_db, monkeypatch):
    """Test 5: Watcher handles clipboard access errors/locks gracefully without crashing."""
    watcher = ClipboardWatcher(db=temp_db)

    def mock_broken_paste():
        raise OSError("Clipboard temporarily locked by another Windows process")

    import desktop_watcher
    monkeypatch.setattr(desktop_watcher.pyperclip, "paste", mock_broken_paste)

    # Calling read_clipboard should return None and not raise an exception
    result = watcher.read_clipboard()
    assert result is None


def test_6_retention_expiry_and_purging(temp_db):
    """Test 6: Expired items (> 7 days) are excluded and can be purged."""
    now_ms = int(time.time() * 1000)
    eight_days_ago_ms = now_ms - (8 * 24 * 60 * 60 * 1000)

    # Insert an expired record directly
    temp_db.insert_entry(content="Old expired note", created_at=eight_days_ago_ms)

    # Insert a fresh record
    temp_db.insert_entry(content="Active fresh note", created_at=now_ms)

    # Check active entries excludes the expired one
    active_entries = temp_db.list_entries(include_expired=False)
    assert len(active_entries) == 1
    assert active_entries[0]["content"] == "Active fresh note"

    # Purge expired
    purged_count = temp_db.purge_expired(now_ms=now_ms)
    assert purged_count == 1
    assert temp_db.count_entries(include_expired=True) == 1


def test_7_watcher_clean_shutdown(temp_db):
    """Test 7: Watcher terminates loop cleanly when stop() is called."""
    watcher = ClipboardWatcher(db=temp_db)
    watcher._running = True
    watcher.stop()
    assert watcher._running is False
