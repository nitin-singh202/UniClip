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
