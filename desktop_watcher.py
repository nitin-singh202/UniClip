"""
Universal Clipboard AI — Windows Desktop Clipboard Watcher
============================================================
A secure, resilient Windows desktop clipboard capture component that:
- Monitors the Windows system clipboard in the background.
- Detects plain text and URLs.
- Filters secrets, API keys, and passwords before persistence.
- Prevents duplicate entries.
- Persists accepted entries to a local SQLite database matching the canonical schema.
- Handles clipboard access errors and locks gracefully without crashing.
- Prepares records for authenticated Cloud Firestore synchronization.
"""

import os
import sys
import time
import re
import uuid
import signal
import sqlite3
import logging
from pathlib import Path
from urllib.parse import urlparse
from typing import Optional, Tuple, Dict, List, Any

# Ensure pyperclip is available
try:
    import pyperclip
except ImportError:
    pyperclip = None

# Configure non-sensitive logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("DesktopWatcher")

# Default paths
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "clipboard_local.db"
LOCK_FILE_PATH = BASE_DIR / ".desktop_watcher.lock"
DEFAULT_POLL_INTERVAL = 0.7  # seconds
SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000
MAX_CONTENT_BYTES = 65536  # 64 KB limit matching Firestore schema


class SingleInstanceLock:
    """
    Prevents multiple instances of desktop_watcher from running simultaneously on Windows.
    Uses native msvcrt file locking.
    """

    def __init__(self, lockfile_path: Path = LOCK_FILE_PATH):
        self.lockfile_path = Path(lockfile_path)
        self.fp = None

    def acquire(self) -> bool:
        try:
            import msvcrt
            self.fp = open(self.lockfile_path, "a+")
            msvcrt.locking(self.fp.fileno(), msvcrt.LK_NBLCK, 1)
            self.fp.seek(0)
            self.fp.truncate()
            self.fp.write(f"{os.getpid()}\n")
            self.fp.flush()
            return True
        except (IOError, OSError, ImportError):
            return False

    def release(self):
        if self.fp:
            try:
                import msvcrt
                self.fp.seek(0)
                msvcrt.locking(self.fp.fileno(), msvcrt.LK_UNLCK, 1)
                self.fp.close()
            except Exception:
                pass
            try:
                if self.lockfile_path.exists():
                    self.lockfile_path.unlink()
            except Exception:
                pass


class SecretDetector:
    """
    Scans clipboard content for API keys, private keys, passwords, and tokens.
    Never logs or persists detected secrets.
    """

    PATTERNS: Dict[str, re.Pattern] = {
        "Private Key": re.compile(r"-----BEGIN\s+([A-Z0-9_-]+\s+)?PRIVATE\s+KEY-----"),
        "AWS Access Key": re.compile(r"\b(AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}\b"),
        "GitHub Token": re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,255}\b|\bgithub_pat_[A-Za-z0-9_]{82}\b"),
        "Google/Firebase API Key": re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b"),
        "OpenAI API Key": re.compile(r"\bsk-[a-zA-Z0-9]{20,}\b|\bsk-proj-[a-zA-Z0-9_\-]{20,}\b"),
        "Anthropic API Key": re.compile(r"\bsk-ant-[a-zA-Z0-9_\-]{20,}\b"),
        "Slack Token": re.compile(r"\bxox[baprs]-[0-9a-zA-Z\-]{10,}\b"),
        "JWT Token": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
        "Database Connection URL": re.compile(r"\b[a-zA-Z0-9+.-]+://[^:\s]+:[^@\s]+@[^/\s]+"),
        "Labeled Password": re.compile(r"(?i)\b(password|passwd|pwd|secret_key)\s*[:=]\s*['\"]?[^\s'\"]{6,}['\"]?"),
    }

    @classmethod
    def check(cls, text: str) -> Tuple[bool, Optional[str]]:
        """
        Check if text contains secret or sensitive content.
        Returns: (is_secret: bool, rule_name: str | None).
        Never returns or logs the secret payload itself.
        """
        if not text or not isinstance(text, str):
            return False, None

        for rule_name, pattern in cls.PATTERNS.items():
            if pattern.search(text):
                return True, rule_name

        return False, None


def detect_entry_type(content: str) -> str:
    """Determine whether a string is a valid URL or plain text."""
    trimmed = content.strip()
    if trimmed.startswith(("http://", "https://")):
        try:
            result = urlparse(trimmed)
            if result.scheme and result.netloc:
                return "url"
        except Exception:
            return "text"
    return "text"


class ClipboardDatabase:
    """
    Local SQLite database storage matching the canonical schema contract.
    """

    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        """Initialize SQLite tables matching canonical schema."""
        with self.get_connection() as conn:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS clipboard_entries (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    entry_type TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    user_id TEXT,
                    sync_status TEXT NOT NULL DEFAULT 'local_only'
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON clipboard_entries(created_at DESC);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_expires_at ON clipboard_entries(expires_at);")

            # App state table for active session user ID
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

            # Tombstone table to prevent offline clients or retries from resurrecting deleted entries
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS deleted_entries (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    deleted_at INTEGER NOT NULL
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_deleted_entries_user ON deleted_entries(user_id);")
            conn.commit()

        # Clean any historical duplicate artifacts
        self.cleanup_duplicates()

    def cleanup_duplicates(self):
        """Clean up transient duplicate records (same content within 2 seconds)."""
        try:
            with self.get_connection() as conn:
                rows = conn.execute(
                    "SELECT id, content, created_at FROM clipboard_entries ORDER BY created_at ASC"
                ).fetchall()
                to_delete = []
                seen = []
                for r in rows:
                    rid, content, ts = r["id"], r["content"], r["created_at"]
                    is_dup = False
                    for s_id, s_content, s_ts in seen:
                        if content == s_content and abs(ts - s_ts) < 2000:
                            to_delete.append(rid)
                            is_dup = True
                            break
                    if not is_dup:
                        seen.append((rid, content, ts))

                for did in to_delete:
                    conn.execute("DELETE FROM clipboard_entries WHERE id = ?", (did,))
                conn.commit()
                if to_delete:
                    logger.info("Cleaned up %d duplicate records on startup.", len(to_delete))
        except Exception as e:
            logger.debug("Deduplication check: %s", e)

    def get_app_state(self, key: str) -> Optional[str]:
        """Get a value from app_state table."""
        try:
            with self.get_connection() as conn:
                row = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
                if row:
                    return row["value"]
        except Exception:
            pass
        return None

    def set_app_state(self, key: str, value: str):
        """Set a value in app_state table."""
        try:
            with self.get_connection() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO app_state (key, value) VALUES (?, ?)",
                    (key, value),
                )
                conn.commit()
        except Exception:
            pass

    def delete_app_state(self, key: str):
        """Delete a key from app_state table."""
        try:
            with self.get_connection() as conn:
                conn.execute("DELETE FROM app_state WHERE key = ?", (key,))
                conn.commit()
        except Exception:
            pass

    def update_sync_status(self, entry_id: str, status: str):
        """Update the sync_status of a clipboard record."""
        try:
            with self.get_connection() as conn:
                conn.execute("UPDATE clipboard_entries SET sync_status = ? WHERE id = ?", (status, entry_id))
                conn.commit()
        except Exception:
            pass

    def is_deleted(self, entry_id: str) -> bool:
        """Check if an entry ID has been tombstoned."""
        if not entry_id:
            return False
        try:
            with self.get_connection() as conn:
                row = conn.execute("SELECT 1 FROM deleted_entries WHERE id = ?", (entry_id,)).fetchone()
                return bool(row)
        except Exception:
            return False

    def record_tombstone(self, entry_id: str, user_id: str):
        """Record a deletion tombstone to prevent resurrection."""
        if not entry_id:
            return
        try:
            now_ms = int(time.time() * 1000)
            with self.get_connection() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO deleted_entries (id, user_id, deleted_at) VALUES (?, ?, ?)",
                    (entry_id, user_id or "", now_ms),
                )
                conn.commit()
        except Exception:
            pass

    def record_tombstones(self, entry_ids: List[str], user_id: str):
        """Batch record deletion tombstones."""
        if not entry_ids:
            return
        try:
            now_ms = int(time.time() * 1000)
            with self.get_connection() as conn:
                conn.executemany(
                    "INSERT OR REPLACE INTO deleted_entries (id, user_id, deleted_at) VALUES (?, ?, ?)",
                    [(eid, user_id or "", now_ms) for eid in entry_ids],
                )
                conn.commit()
        except Exception:
            pass

    def insert_entry(
        self,
        content: str,
        entry_type: Optional[str] = None,
        user_id: Optional[str] = None,
        created_at: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Insert a validated clipboard entry into SQLite."""
        now_ms = created_at or int(time.time() * 1000)
        expires_ms = now_ms + SEVEN_DAYS_MS
        entry_id = str(uuid.uuid4())
        etype = entry_type or detect_entry_type(content)

        record = {
            "id": entry_id,
            "content": content,
            "entry_type": etype,
            "created_at": now_ms,
            "updated_at": now_ms,
            "expires_at": expires_ms,
            "schema_version": 1,
            "user_id": user_id,
            "sync_status": "local_only",
        }

        with self.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO clipboard_entries (
                    id, content, entry_type, created_at, updated_at, expires_at, schema_version, user_id, sync_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["id"],
                    record["content"],
                    record["entry_type"],
                    record["created_at"],
                    record["updated_at"],
                    record["expires_at"],
                    record["schema_version"],
                    record["user_id"],
                    record["sync_status"],
                ),
            )
            conn.commit()

        return record

    def get_latest_entry(self) -> Optional[Dict[str, Any]]:
        """Retrieve the most recently created entry from the database."""
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM clipboard_entries ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if row:
                return dict(row)
        return None

    def list_entries(self, limit: int = 50, include_expired: bool = False) -> List[Dict[str, Any]]:
        """List entries, newest first."""
        now_ms = int(time.time() * 1000)
        query = "SELECT * FROM clipboard_entries"
        params: list = []
        if not include_expired:
            query += " WHERE expires_at > ?"
            params.append(now_ms)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self.get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def count_entries(self, include_expired: bool = False) -> int:
        """Count total entries in the database."""
        now_ms = int(time.time() * 1000)
        query = "SELECT COUNT(*) FROM clipboard_entries"
        params: list = []
        if not include_expired:
            query += " WHERE expires_at > ?"
            params.append(now_ms)

        with self.get_connection() as conn:
            return conn.execute(query, params).fetchone()[0]

    def purge_expired(self, now_ms: Optional[int] = None) -> int:
        """Purge entries older than the 7-day retention period."""
        now = now_ms or int(time.time() * 1000)
        with self.get_connection() as conn:
            cur = conn.execute("DELETE FROM clipboard_entries WHERE expires_at <= ?", (now,))
            conn.commit()
            return cur.rowcount


class ClipboardWatcher:
    """
    Watches the Windows clipboard and persists non-sensitive changes to SQLite.
    """

    def __init__(
        self,
        db: Optional[ClipboardDatabase] = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        user_id: Optional[str] = None,
    ):
        self.db = db or ClipboardDatabase()
        self.poll_interval = poll_interval
        self.user_id = user_id
        self._running = False
        self._last_content: Optional[str] = None

        # Pre-seed last content from database to prevent duplicate on restart
        latest = self.db.get_latest_entry()
        if latest:
            self._last_content = latest.get("content")

    def read_clipboard(self) -> Optional[str]:
        """
        Safely reads the clipboard with exception handling for Windows clipboard locks.
        """
        if pyperclip is None:
            logger.error("pyperclip is not installed. Run: pip install pyperclip")
            return None

        try:
            return pyperclip.paste()
        except Exception as e:
            # Clipboard lock errors happen frequently in Windows when another app is writing.
            logger.debug("Clipboard read lock encountered: %s", type(e).__name__)
            return None

    def process_clipboard_text(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Validates, filters secrets, checks duplicates, and persists accepted content.
        Returns the inserted record dict if accepted, or None if skipped/rejected.
        """
        if not text or not isinstance(text, str):
            return None

        # Check content length (empty or exceeding 64KB)
        trimmed = text.strip()
        if not trimmed:
            return None

        if len(text.encode("utf-8")) > MAX_CONTENT_BYTES:
            logger.warning("[REJECTED] Clipboard entry exceeded 64 KB limit (%d bytes).", len(text.encode("utf-8")))
            self._last_content = text
            return None

        # Check duplicate against last seen in memory
        if text == self._last_content:
            return None

        # Check duplicate against most recent SQLite record
        latest = self.db.get_latest_entry()
        if latest and latest.get("content") == text:
            self._last_content = text
            return None

        # Check for secrets before any persistence
        is_secret, rule_name = SecretDetector.check(text)
        if is_secret:
            logger.warning("[SECURITY] Sensitive content rejected: matched '%s'. Not persisted.", rule_name)
            # Update last content so the same secret is not repeatedly evaluated in every poll
            self._last_content = text
            return None

        # Attribute to active logged-in user if available
        effective_user_id = self.user_id or self.db.get_app_state("active_user_id")

        # Insert accepted entry
        etype = detect_entry_type(text)
        record = self.db.insert_entry(content=text, entry_type=etype, user_id=effective_user_id)
        self._last_content = text

        # Sync to Google Cloud Firestore if authenticated
        if effective_user_id:
            try:
                from web.services.firestore_service import FirestoreService
                if FirestoreService.is_available():
                    if FirestoreService.sync_entry(record):
                        record["sync_status"] = "synced"
                        self.db.update_sync_status(record["id"], "synced")
                        logger.info("[FIRESTORE] Synced entry %s to Cloud Firestore", record["id"])
            except Exception as e:
                logger.debug("Cloud sync deferred: %s", e)

        logger.info(
            "[ACCEPTED] Stored entry id=%s | type=%s | length=%d chars",
            record["id"],
            etype,
            len(text),
        )
        return record

    def poll_once(self) -> Optional[Dict[str, Any]]:
        """Poll the clipboard once and process if changed."""
        text = self.read_clipboard()
        if text:
            return self.process_clipboard_text(text)
        return None

    def start(self):
        """Start the continuous watcher loop."""
        self._running = True
        logger.info("Universal Clipboard AI Desktop Watcher started.")
        logger.info("Local database: %s", self.db.db_path)
        logger.info("Polling every %.2fs. Press Ctrl+C to stop.", self.poll_interval)

        # Set up signal handlers for graceful shutdown
        def handle_signal(sig, frame):
            logger.info("Shutdown signal received. Stopping watcher...")
            self.stop()

        try:
            signal.signal(signal.SIGINT, handle_signal)
            signal.signal(signal.SIGTERM, handle_signal)
        except Exception:
            pass

        consecutive_errors = 0
        while self._running:
            try:
                self.poll_once()
                consecutive_errors = 0
            except Exception as e:
                consecutive_errors += 1
                logger.warning("Unexpected error during clipboard poll: %s", e)
                if consecutive_errors > 10:
                    time.sleep(2.0)  # Back off if consecutive failures
            time.sleep(self.poll_interval)

        logger.info("Desktop Watcher stopped cleanly.")

    def stop(self):
        """Signal the watcher loop to terminate."""
        self._running = False


# ------------------ CLI Management ------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Universal Clipboard AI — Windows Desktop Watcher"
    )
    parser.add_argument("--db", type=str, default=str(DEFAULT_DB_PATH), help="Path to SQLite database")
    parser.add_argument("--interval", type=float, default=DEFAULT_POLL_INTERVAL, help="Polling interval in seconds")
    parser.add_argument("--status", action="store_true", help="Display local database status and stats")
    parser.add_argument("--list", action="store_true", help="List recent entries stored in local SQLite")
    parser.add_argument("--purge", action="store_true", help="Purge expired entries (> 7 days) from local SQLite")
    parser.add_argument("--once", action="store_true", help="Poll clipboard once and exit")
    parser.add_argument("--test-secret", type=str, help="Test secret detection against provided string")

    args = parser.parse_args()
    db = ClipboardDatabase(Path(args.db))

    if args.test_secret:
        is_sec, rule = SecretDetector.check(args.test_secret)
        if is_sec:
            print(f"[REJECTED] Matched security rule: {rule}")
        else:
            print("[ACCEPTED] Content is clean of detected secrets.")
        return

    if args.status:
        total = db.count_entries(include_expired=True)
        active = db.count_entries(include_expired=False)
        latest = db.get_latest_entry()
        print(f"Database File: {db.db_path}")
        print(f"Total Entries: {total} (Active: {active}, Expired: {total - active})")
        if latest:
            created_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(latest["created_at"] / 1000))
            print(f"Latest Entry: ID={latest['id']} | Type={latest['entry_type']} | Created={created_str}")
        return

    if args.list:
        entries = db.list_entries(limit=10)
        print(f"--- Recent Active Entries ({len(entries)}) ---")
        for e in entries:
            created_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e["created_at"] / 1000))
            preview = e["content"].replace("\n", " ")[:60]
            print(f"[{created_str}] ({e['entry_type']}) {e['id'][:8]}... | {preview}")
        return

    if args.purge:
        count = db.purge_expired()
        print(f"Purged {count} expired entries from local SQLite.")
        return

    watcher = ClipboardWatcher(db=db, poll_interval=args.interval)

    if args.once:
        rec = watcher.poll_once()
        if rec:
            print(f"Recorded entry: {rec['id']}")
        else:
            print("No new entry recorded.")
        return

    # Acquire single-instance lock before starting continuous background watcher
    lock = SingleInstanceLock()
    if not lock.acquire():
        logger.warning("Another instance of Desktop Watcher is already running. Exiting.")
        print("[INFO] Another instance of Desktop Watcher is already running.")
        sys.exit(0)

    try:
        watcher.start()
    finally:
        lock.release()


if __name__ == "__main__":
    main()
