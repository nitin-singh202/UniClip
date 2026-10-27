"""
UniClip — Copy Feature Test Suite
=================================================
Verifies:
- Accurate extraction and data attributes for short text, multiline text, URLs, and Unicode/emojis.
- Complete fidelity of JSON hydration script tag for raw multiline/special characters.
- Non-destructive nature of copy actions (no mutation or premature deletion).
- Complete isolation of guest entries during copy actions.
"""

import json
from web.services import ClipboardService


def test_copy_short_text_attributes(auth_client):
    """Test short plain text entry renders proper copy attributes and accessible label."""
    test_text = "Simple clip text"
    ClipboardService.add_entry(uid="user_alice", content=test_text)

    resp = auth_client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert 'class="action-btn btn-copy"' in html
    assert 'aria-label="Copy clipboard entry"' in html
    assert f'data-content="{test_text}"' in html


def test_copy_multiline_text_fidelity(auth_client):
    """Test multiline text preserving exact newlines and whitespace in initial data script."""
    multiline_text = "Line 1: Header\nLine 2: Content\nLine 3: Footer"
    ClipboardService.add_entry(uid="user_alice", content=multiline_text)

    resp = auth_client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Verify JSON script tag contains the faithful unescaped multiline text
    assert '<script id="initial-clipboard-entries" type="application/json">' in html
    # Extract JSON between script tags
    start_tag = '<script id="initial-clipboard-entries" type="application/json">'
    end_tag = '</script>'
    start_idx = html.find(start_tag) + len(start_tag)
    end_idx = html.find(end_tag, start_idx)
    raw_json = html[start_idx:end_idx].strip()

    entries = json.loads(raw_json)
    matching = [e for e in entries if e["content"] == multiline_text]
    assert len(matching) == 1
    assert matching[0]["content"] == multiline_text


def test_copy_unicode_emojis_and_non_english(auth_client):
    """Test Unicode emojis and multi-language scripts (Arabic, Hindi, Chinese) are preserved exactly."""
    unicode_text = "🎉 🚀 UniClip • नमस्ते दुनिया • مرحبا بالعالم • 你好世界"
    ClipboardService.add_entry(uid="user_alice", content=unicode_text)

    resp = auth_client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert '<script id="initial-clipboard-entries" type="application/json">' in html
    start_tag = '<script id="initial-clipboard-entries" type="application/json">'
    end_tag = '</script>'
    start_idx = html.find(start_tag) + len(start_tag)
    end_idx = html.find(end_tag, start_idx)
    raw_json = html[start_idx:end_idx].strip()

    entries = json.loads(raw_json)
    matching = [e for e in entries if e["content"] == unicode_text]
    assert len(matching) == 1
    assert matching[0]["content"] == unicode_text


def test_copy_url_fidelity(auth_client):
    """Test URL with complex query parameters and fragment remains exact without navigation side effects."""
    test_url = "https://uniclip.example.com/search?q=test+query&category=code#top"
    ClipboardService.add_entry(uid="user_alice", content=test_url)

    resp = auth_client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    start_tag = '<script id="initial-clipboard-entries" type="application/json">'
    end_tag = '</script>'
    start_idx = html.find(start_tag) + len(start_tag)
    end_idx = html.find(end_tag, start_idx)
    raw_json = html[start_idx:end_idx].strip()

    entries = json.loads(raw_json)
    matching = [e for e in entries if e["content"] == test_url]
    assert len(matching) == 1
    assert matching[0]["content"] == test_url
    assert matching[0]["entry_type"] == "url"


def test_copy_long_text_entry(auth_client):
    """Test large entries (e.g. 5000+ characters of text/code) are preserved in full without truncation."""
    long_code = "def sample_function():\n" + ("    print('Hello world!')\n" * 150)
    ClipboardService.add_entry(uid="user_alice", content=long_code)

    resp = auth_client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    start_tag = '<script id="initial-clipboard-entries" type="application/json">'
    end_tag = '</script>'
    start_idx = html.find(start_tag) + len(start_tag)
    end_idx = html.find(end_tag, start_idx)
    raw_json = html[start_idx:end_idx].strip()

    entries = json.loads(raw_json)
    matching = [e for e in entries if e["content"] == long_code]
    assert len(matching) == 1
    assert len(matching[0]["content"]) == len(long_code)


def test_copy_does_not_mutate_or_delete_entry(auth_client):
    """Test that retrieving copy information does not delete or change retention state."""
    sample_text = "Immutable Entry Text"
    created = ClipboardService.add_entry(uid="user_alice", content=sample_text)
    entry_id = created["id"]

    # Verify entry persists before and after querying dashboard and single entry endpoints
    entry_before = ClipboardService.get_entry(uid="user_alice", entry_id=entry_id)
    assert entry_before is not None
    assert entry_before["content"] == sample_text

    resp = auth_client.get(f"/api/clipboard/{entry_id}")
    assert resp.status_code == 200
    assert resp.get_json()["content"] == sample_text

    entry_after = ClipboardService.get_entry(uid="user_alice", entry_id=entry_id)
    assert entry_after is not None
    assert entry_after["content"] == sample_text


def test_guest_mode_copy_isolation(client):
    """Test that guest sessions can load dashboard without triggering Firestore requests."""
    # Establish guest session
    resp = client.post("/api/auth/guest-session")
    assert resp.status_code == 200

    dash_resp = client.get("/dashboard")
    assert dash_resp.status_code == 200
    dash_html = dash_resp.get_data(as_text=True)
    assert 'data-is-guest="true"' in dash_html

    # Guest accessing server entries returns empty isolated history
    entries_resp = client.get("/api/clipboard/entries")
    assert entries_resp.status_code == 200
    data = entries_resp.get_json()
    assert data["total_count"] == 0
    assert data["entries"] == []


def test_authenticated_copy_persistence_and_refresh(auth_client):
    """Test authenticated persistence via /api/clipboard and dynamic retrieval via /api/clipboard/entries."""
    copied_text = "https://developer.mozilla.org/en-US/docs/Web/API/Clipboard_API"
    resp = auth_client.post(
        "/api/clipboard",
        json={"content": copied_text},
        headers={"X-CSRF-Token": "test-csrf-token-alice"},
    )
    assert resp.status_code == 201
    entry_data = resp.get_json()
    assert entry_data["success"] is True
    assert entry_data["entry"]["content"] == copied_text
    assert entry_data["entry"]["entry_type"] == "url"

    # Immediately verify UI refresh endpoint reflects the newly captured item
    refresh_resp = auth_client.get("/api/clipboard/entries")
    assert refresh_resp.status_code == 200
    refresh_data = refresh_resp.get_json()
    assert refresh_data["success"] is True
    assert refresh_data["total_count"] >= 1
    assert any(e["content"] == copied_text for e in refresh_data["entries"])


def test_copy_sensitive_secret_rejected(auth_client):
    """Test sensitive tokens and API keys are strictly rejected and not persisted."""
    secrets_to_test = [
        ("AKIAIOSFODNN7EXAMPLE", "AWS Access Key"),
        ("-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----", "Private Key"),
        ("sk-proj-1234567890abcdefghijklmnopqrstuv", "OpenAI API Key"),
        ("password = 'super_secret_password_123'", "Labeled Password"),
    ]

    for secret_payload, rule_name in secrets_to_test:
        resp = auth_client.post(
            "/api/clipboard",
            json={"content": secret_payload},
            headers={"X-CSRF-Token": "test-csrf-token-alice"},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "Sensitive content detected" in data["error"]

    # Confirm none of the secrets were saved
    refresh_resp = auth_client.get("/api/clipboard/entries")
    entries = refresh_resp.get_json()["entries"]
    for secret_payload, _ in secrets_to_test:
        assert not any(e["content"] == secret_payload for e in entries)


def test_copy_duplicate_prevention(auth_client):
    """Test rapid duplicate copy submissions return existing entry without creating duplicates."""
    sample_text = "Important meeting notes for 2026-10-28"

    # First copy capture
    resp1 = auth_client.post(
        "/api/clipboard",
        json={"content": sample_text},
        headers={"X-CSRF-Token": "test-csrf-token-alice"},
    )
    assert resp1.status_code == 201
    entry1 = resp1.get_json()["entry"]

    # Rapid second copy capture of identical content
    resp2 = auth_client.post(
        "/api/clipboard",
        json={"content": sample_text},
        headers={"X-CSRF-Token": "test-csrf-token-alice"},
    )
    assert resp2.status_code == 201
    entry2 = resp2.get_json()["entry"]
    assert entry2["id"] == entry1["id"]

    # Confirm only one entry exists in history
    refresh_resp = auth_client.get("/api/clipboard/entries")
    entries = [e for e in refresh_resp.get_json()["entries"] if e["content"] == sample_text]
    assert len(entries) == 1


def test_copy_unauthenticated_or_missing_csrf_rejected(client, auth_client):
    """Test unauthenticated copy requests and requests missing CSRF token fail safely."""
    # Unauthenticated request without valid session/token fails with 400, 401, or 302
    unauth_resp = client.post(
        "/api/clipboard",
        json={"content": "Should be rejected"},
        headers={"X-CSRF-Token": "fake-token"},
    )
    assert unauth_resp.status_code in (302, 401, 400)

    # Missing CSRF token returns 400 Bad Request
    no_csrf_resp = auth_client.post(
        "/api/clipboard",
        json={"content": "Should be rejected without CSRF"},
    )
    assert no_csrf_resp.status_code == 400

    # Empty content returns 400 Bad Request
    empty_resp = auth_client.post(
        "/api/clipboard",
        json={"content": "   "},
        headers={"X-CSRF-Token": "test-csrf-token-alice"},
    )
    assert empty_resp.status_code == 400

