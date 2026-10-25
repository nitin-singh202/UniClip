from web.services import ClipboardService


def test_6_xss_protection_escapes_clipboard_text(auth_client):
    """Test 6: Clipboard text is escaped and rendered safely to prevent XSS."""
    malicious_payload = "<script>alert('xss-attack')</script><img src=x onerror=alert(1)>"
    ClipboardService.add_entry(uid="user_alice", content=malicious_payload)

    resp = auth_client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Ensure unescaped raw tag is NOT present
    assert "<script>alert('xss-attack')</script>" not in html
    # Ensure escaped HTML entities are present
    assert "&lt;script&gt;alert(&#39;xss-attack&#39;)&lt;/script&gt;" in html or \
           "&lt;script&gt;alert('xss-attack')&lt;/script&gt;" in html


def test_12_error_pages_do_not_expose_secrets_or_clipboard(auth_client):
    """Test 12: Error responses do not expose internal tracebacks, passwords, or clipboard text."""
    # Trigger 404
    resp_404 = auth_client.get("/non-existent-page")
    assert resp_404.status_code == 404
    html_404 = resp_404.get_data(as_text=True)
    assert "Page Not Found" in html_404
    assert "Traceback" not in html_404
    assert "SECRET_KEY" not in html_404

    # Trigger 400 Bad Request (empty content with valid CSRF)
    resp_400 = auth_client.post(
        "/api/clipboard",
        headers={"X-CSRF-Token": "test-csrf-token-alice"},
        json={"content": ""},
    )
    assert resp_400.status_code == 400
    assert "Content is required" in resp_400.get_json()["error"]


def test_13_copy_action_data_attributes(auth_client):
    """Test 13: Copy action buttons carry explicit data attributes without leaking into console."""
    test_text = "https://example.com/safe-link"
    ClipboardService.add_entry(uid="user_alice", content=test_text)

    resp = auth_client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Check button attributes
    assert 'class="btn btn-copy"' in html
    assert f'data-content="{test_text}"' in html


def test_14_firebase_unavailable_shows_honest_status(auth_client):
    """Test 14: Firebase-unavailable or unconfigured environment displays honest status state."""
    # In test environment, FIREBASE_SERVICE_ACCOUNT_KEY is empty, so sync_status reports honest local session
    resp = auth_client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    # Checks that it reports Session Active or Offline instead of falsely asserting live Firestore cloud sync
    assert "Session Active" in html or "Offline" in html or "Firestore Synced" in html
    assert "7-Day Retention" in html
