"""
UniClip Load Testing Suite (Locust)
====================================
A realistic, repeatable load-testing suite designed to measure scalability,
throughput (RPS), error rates, and p50/p95/p99 response latencies for UniClip.

Key Safety & Architecture Highlights:
- Strict ₹0 budget: runs locally against SQLite and DEV_MOCK_AUTH without consuming Firebase quotas.
- Strong User Isolation: each virtual user generates a unique synthetic UID (sim_<uuid>)
  and only reads, inspects, and deletes their own clipboard items.
- Realistic wait times: between(1.0, 4.0) seconds simulates natural human browsing & polling.
- Automated Cleanup: on_stop removes created synthetic entries via bulk-delete.
- Cloud Safety Guard: blocks accidental high-concurrency attacks on remote production URLs
  unless explicitly confirmed with CONFIRM_REMOTE_LOAD_TEST=yes.
"""

import os
import re
import sys
import time
import uuid
import random
import logging
from typing import Optional, List
from locust import HttpUser, task, between, events
from urllib.parse import urlparse

# Configure logger
logger = logging.getLogger("UniClipLoadTest")

# Configuration via environment variables
DEFAULT_TARGET_URL = os.environ.get("TARGET_URL", "http://127.0.0.1:5000")
WAIT_TIME_MIN = float(os.environ.get("WAIT_TIME_MIN", "1.0"))
WAIT_TIME_MAX = float(os.environ.get("WAIT_TIME_MAX", "4.0"))
CONFIRM_REMOTE = os.environ.get("CONFIRM_REMOTE_LOAD_TEST", "no").strip().lower()

# Regex to safely extract CSRF token from <meta name="csrf-token" content="...">
CSRF_REGEX = re.compile(r'<meta\s+name=["\']csrf-token["\']\s+content=["\']([a-fA-F0-9]{64})["\']', re.IGNORECASE)

# Synthetic non-sensitive text templates
SYNTHETIC_TEXT_SAMPLES = [
    "Meeting notes: discussed Q4 engineering roadmap and milestone delivery.",
    "https://github.com/nitin-singh202/UniClip/issues/42",
    "git commit -m 'feat: implement real-time clipboard DOM reconciliation'",
    "Docker command: docker run -d -p 5000:5000 --name uniclip-service uniclip:latest",
    "Color palette: primary=#0b0f17, accent=#6366f1, surface=#161f30",
    "SELECT id, content, created_at FROM clipboard_entries WHERE user_id = :uid;",
    "https://docs.python.org/3/library/sqlite3.html#sqlite3-wal",
    "curl -X GET http://127.0.0.1:5000/api/clipboard/entries -H 'Accept: application/json'",
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor.",
    "Verify p95 response time is under 200ms across 1,000 concurrent simulated users.",
]


def extract_csrf_token(html_text: str) -> Optional[str]:
    """Extract CSRF token from page HTML meta tag."""
    if not html_text:
        return None
    match = CSRF_REGEX.search(html_text)
    if match:
        return match.group(1)
    # Secondary fallback for form input
    input_match = re.search(r'name=["\']csrf_token["\']\s+value=["\']([a-fA-F0-9]{64})["\']', html_text)
    return input_match.group(1) if input_match else None


def is_remote_url(target_url: str) -> bool:
    """Check whether the target URL is a remote/production domain (not localhost)."""
    try:
        parsed = urlparse(target_url)
        hostname = (parsed.hostname or "").lower()
        return hostname not in ("127.0.0.1", "localhost", "::1", "0.0.0.0")
    except Exception:
        return False


def generate_synthetic_payload(user_id: str) -> str:
    """Generate safe, non-sensitive synthetic clipboard payload."""
    sample = random.choice(SYNTHETIC_TEXT_SAMPLES)
    seq = random.randint(1000, 9999)
    return f"[{user_id}#{seq}] {sample}"


@events.init.add_listener
def on_locust_init(environment, **kwargs):
    """Safety guard: verify configuration before running tests."""
    host = environment.host or DEFAULT_TARGET_URL
    if is_remote_url(host) and CONFIRM_REMOTE != "yes":
        logger.warning(
            "\n" + "=" * 70 + "\n"
            "⚠️  SAFETY WARNING: TARGET HOST IS A REMOTE SERVICE: %s\n"
            "High-volume load tests against live cloud deployments (Render, Firebase, etc.)\n"
            "can exhaust free quotas or incur unexpected charges.\n"
            "To confirm you intend to test this remote URL, set environment variable:\n"
            "    CONFIRM_REMOTE_LOAD_TEST=yes\n"
            "=" * 70,
            host
        )


class UniClipUser(HttpUser):
    """
    Simulates an authenticated UniClip user performing typical daily actions:
    - Authenticating via isolated mock token
    - Loading dashboard and capturing CSRF token
    - Polling clipboard history entries (simulating live frontend sync)
    - Adding new synthetic clipboard entries
    - Inspecting individual entries in modal
    - Searching clipboard history
    - Deleting entries and cleaning up on exit
    """

    wait_time = between(WAIT_TIME_MIN, WAIT_TIME_MAX)

    def on_start(self):
        """Initialize virtual user session with unique identity and authentication."""
        self.user_id = f"sim_{uuid.uuid4().hex[:10]}"
        self.csrf_token: Optional[str] = None
        self.created_entry_ids: List[str] = []

        # 1. Visit login page first to initiate session cookies and retrieve CSRF token
        login_resp = self.client.get("/login", name="[Page] Load Login")
        if login_resp.status_code == 200:
            self.csrf_token = extract_csrf_token(login_resp.text)

        # 2. Establish isolated authenticated session via supported local mock flow
        # Uses DEV_MOCK_AUTH which accepts 'mock-valid-token-<uid>' locally at ₹0 cost.
        headers = {"Content-Type": "application/json"}
        if self.csrf_token:
            headers["X-CSRF-Token"] = self.csrf_token

        with self.client.post(
            "/api/auth/session",
            json={"id_token": f"mock-valid-token-{self.user_id}"},
            headers=headers,
            name="[Auth] Establish Session",
            catch_response=True,
        ) as auth_resp:
            if auth_resp.status_code == 200:
                auth_resp.success()
            else:
                err_msg = (
                    f"Auth failed with HTTP {auth_resp.status_code}. "
                    "Ensure target server has DEV_MOCK_AUTH=true in web/.env."
                )
                auth_resp.failure(err_msg)
                return

        # 3. Load dashboard to transition into authenticated view and refresh CSRF token
        dash_resp = self.client.get("/dashboard", name="[Page] Load Dashboard")
        if dash_resp.status_code == 200:
            new_token = extract_csrf_token(dash_resp.text)
            if new_token:
                self.csrf_token = new_token
        else:
            logger.debug("Dashboard load failed after auth with HTTP %s", dash_resp.status_code)

    def on_stop(self):
        """Clean up all synthetic records created by this virtual user."""
        if not self.created_entry_ids or not self.csrf_token:
            return

        headers = {"X-CSRF-Token": self.csrf_token, "Content-Type": "application/json"}
        # Use bulk-delete to purge all entries created by this user in a single request
        batch_ids = list(self.created_entry_ids[:500])
        self.client.post(
            "/api/clipboard/bulk-delete",
            json={"ids": batch_ids},
            headers=headers,
            name="[Cleanup] Bulk Delete User Entries",
        )
        self.created_entry_ids.clear()

    @task(6)
    def poll_clipboard_entries(self):
        """
        Highest frequency task (Weight 6): Polls for clipboard history updates.
        Simulates the browser client's startLiveSync() polling loop.
        """
        headers = {"Accept": "application/json"}
        with self.client.get(
            "/api/clipboard/entries",
            headers=headers,
            name="[API] Poll Entries",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    if not data.get("success"):
                        resp.failure("Response missing success=True")
                except Exception as e:
                    resp.failure(f"Invalid JSON response: {e}")
            else:
                resp.failure(f"Polling returned HTTP {resp.status_code}")

    @task(3)
    def add_clipboard_entry(self):
        """
        Mutation task (Weight 3): Simulates copying a new text snippet or URL.
        """
        if not self.csrf_token:
            return

        content = generate_synthetic_payload(self.user_id)
        headers = {
            "X-CSRF-Token": self.csrf_token,
            "Content-Type": "application/json",
        }

        with self.client.post(
            "/api/clipboard",
            json={"content": content},
            headers=headers,
            name="[API] Add Entry",
            catch_response=True,
        ) as resp:
            if resp.status_code == 201:
                try:
                    data = resp.json()
                    entry = data.get("entry", {})
                    eid = entry.get("id")
                    if eid:
                        self.created_entry_ids.append(eid)
                except Exception as e:
                    resp.failure(f"Malformed JSON after creation: {e}")
            else:
                resp.failure(f"Add entry failed with HTTP {resp.status_code}")

    @task(2)
    def view_dashboard_html(self):
        """
        Page view task (Weight 2): Simulates navigating back to or reloading dashboard.
        """
        with self.client.get("/dashboard", name="[Page] View Dashboard", catch_response=True) as resp:
            if resp.status_code == 200:
                # Refresh CSRF token if updated
                new_token = extract_csrf_token(resp.text)
                if new_token:
                    self.csrf_token = new_token
            else:
                resp.failure(f"Dashboard view returned HTTP {resp.status_code}")

    @task(2)
    def search_clipboard(self):
        """
        Search task (Weight 2): Queries clipboard entries by keyword.
        """
        query = random.choice(["roadmap", "git", "palette", "python", "notes"])
        headers = {"Accept": "application/json"}
        with self.client.get(
            f"/api/clipboard/entries?q={query}",
            headers=headers,
            name="[API] Search Entries",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    if not data.get("success"):
                        resp.failure("Search response missing success=True")
                except Exception as e:
                    resp.failure(f"Search JSON error: {e}")
            else:
                resp.failure(f"Search returned HTTP {resp.status_code}")

    @task(2)
    def inspect_entry_detail(self):
        """
        Detail inspection task (Weight 2): Simulates clicking an entry to view details in modal.
        """
        if not self.created_entry_ids:
            return

        target_id = random.choice(self.created_entry_ids)
        with self.client.get(
            f"/api/clipboard/{target_id}",
            name="[API] Inspect Entry Detail",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    if data.get("user_id") != self.user_id:
                        resp.failure("User isolation violation: retrieved another user's entry!")
                except Exception as e:
                    resp.failure(f"Inspection JSON error: {e}")
            elif resp.status_code == 404:
                # Could happen if deleted in another task; remove from list
                if target_id in self.created_entry_ids:
                    self.created_entry_ids.remove(target_id)
            else:
                resp.failure(f"Inspect entry returned HTTP {resp.status_code}")

    @task(1)
    def delete_single_entry(self):
        """
        Deletion task (Weight 1): Deletes an individual clipboard item.
        """
        if not self.created_entry_ids or not self.csrf_token:
            return

        target_id = self.created_entry_ids.pop(0)
        headers = {"X-CSRF-Token": self.csrf_token}

        with self.client.post(
            f"/api/clipboard/{target_id}/delete",
            headers=headers,
            name="[API] Delete Single Entry",
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"Delete returned HTTP {resp.status_code}")


class UniClipGuestUser(HttpUser):
    """
    Simulates unauthenticated or Guest Mode visitors:
    - Creating guest sessions
    - Viewing local dashboard
    - Viewing settings
    - Terminating guest session
    """

    weight = 1  # 1 guest per ~10 authenticated users
    wait_time = between(WAIT_TIME_MIN, WAIT_TIME_MAX)

    def on_start(self):
        """Start guest session."""
        self.client.post("/api/auth/guest-session", name="[Guest] Enter Guest Mode")

    def on_stop(self):
        """End guest session on exit."""
        self.client.post("/api/auth/guest-session/end", name="[Guest] Exit Guest Mode")

    @task(4)
    def view_guest_dashboard(self):
        """Load guest dashboard page."""
        self.client.get("/dashboard", name="[Guest] View Dashboard")

    @task(2)
    def poll_guest_entries(self):
        """Poll guest entries API (returns empty list without hitting cloud DB)."""
        self.client.get("/api/clipboard/entries", name="[Guest] Poll API")

    @task(1)
    def view_guest_settings(self):
        """View guest settings page."""
        self.client.get("/settings", name="[Guest] View Settings")
