import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from flask import current_app
from .security import detect_entry_type


class ClipboardEntry:
    """Represents a canonical cross-device clipboard entry."""

    def __init__(
        self,
        entry_id: str,
        user_id: str,
        content: str,
        entry_type: Optional[str] = None,
        created_at: Optional[int] = None,
        updated_at: Optional[int] = None,
        expires_at: Optional[int] = None,
        schema_version: int = 1,
    ):
        self.id = entry_id
        self.user_id = user_id
        self.content = content
        self.entry_type = entry_type or detect_entry_type(content)
        now_ms = int(time.time() * 1000)
        self.created_at = created_at or now_ms
        self.updated_at = updated_at or now_ms
        # 7-day retention in milliseconds: 7 * 24 * 60 * 60 * 1000 = 604800000 ms
        self.expires_at = expires_at or (self.created_at + 7 * 24 * 60 * 60 * 1000)
        self.schema_version = schema_version

    def is_expired(self, current_time_ms: Optional[int] = None) -> bool:
        """Check if the entry has passed its retention deadline."""
        now = current_time_ms or int(time.time() * 1000)
        return now >= self.expires_at

    def to_dict(self) -> dict:
        """Serialize to dictionary representation."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "content": self.content,
            "entry_type": self.entry_type,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ClipboardEntry":
        return cls(
            entry_id=data["id"],
            user_id=data["user_id"],
            content=data["content"],
            entry_type=data.get("entry_type"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            expires_at=data.get("expires_at"),
            schema_version=data.get("schema_version", 1),
        )


class ClipboardService:
    """
    Manages clipboard history operations for authenticated users.
    Supports in-memory test store and prepares for Firestore cloud synchronization.
    Strictly enforces user isolation and 7-day retention.
    """

    # In-memory store for development/testing: dict mapping uid -> dict of {entry_id: ClipboardEntry}
    _memory_store: Dict[str, Dict[str, ClipboardEntry]] = {}

    @classmethod
    def reset_store(cls):
        """Reset the in-memory store (used in test teardown)."""
        cls._memory_store = {}

    @classmethod
    def get_user_store(cls, uid: str) -> Dict[str, ClipboardEntry]:
        """Return the user's isolated in-memory entries."""
        if uid not in cls._memory_store:
            cls._memory_store[uid] = {}
        return cls._memory_store[uid]

    @classmethod
    def _use_sqlite(cls) -> bool:
        from flask import has_app_context, current_app
        if has_app_context():
            return bool(current_app.config.get("USE_SQLITE", False))
        return False

    @classmethod
    def _get_db_path(cls) -> Path:
        return Path(__file__).resolve().parent.parent.parent / "clipboard_local.db"

    @classmethod
    def list_entries(
        cls,
        uid: str,
        search_query: Optional[str] = None,
        limit: int = 50,
        now_ms: Optional[int] = None
    ) -> Tuple[List[dict], str]:
        """
        List clipboard entries for the specified user, newest first.
        Excludes expired items (> 7 days).
        Returns a tuple: (entries_list, sync_status).
        """
        if not uid:
            return [], "unauthenticated"

        now = now_ms or int(time.time() * 1000)

        # Sync status: Indicate status truthfully based on cloud connection
        from .firestore_service import FirestoreService
        is_cloud_connected = FirestoreService.is_available()
        sync_status = "connected" if is_cloud_connected else "local_ready"

        if not cls._use_sqlite():
            user_entries = cls.get_user_store(uid)
            valid_entries = [e for e in user_entries.values() if not e.is_expired(now)]
            if search_query:
                query_lower = search_query.strip().lower()
                valid_entries = [e for e in valid_entries if query_lower in e.content.lower()]
            valid_entries.sort(key=lambda x: x.created_at, reverse=True)
            return [e.to_dict() for e in valid_entries[:limit]], sync_status

        # In live mode: Read directly from local SQLite database (populated by desktop_watcher)
        db_file = cls._get_db_path()
        if not db_file.exists():
            return [], sync_status

        import sqlite3
        with sqlite3.connect(str(db_file), timeout=5) as conn:
            conn.row_factory = sqlite3.Row
            # Claim unassigned local entries for the authenticated user and update active session
            conn.execute("UPDATE clipboard_entries SET user_id = ? WHERE user_id IS NULL OR user_id = ''", (uid,))
            conn.execute("INSERT OR REPLACE INTO app_state (key, value) VALUES ('active_user_id', ?)", (uid,))
            conn.commit()

            # If cloud is connected, upload pending local records to Firestore
            if is_cloud_connected:
                cls._sync_pending_records(conn, uid)

            query = "SELECT * FROM clipboard_entries WHERE expires_at > ? AND user_id = ?"
            params: list = [now, uid]
            if search_query:
                query += " AND content LIKE ?"
                params.append(f"%{search_query.strip()}%")
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows], sync_status

    @classmethod
    def _sync_pending_records(cls, conn, uid: str):
        """Upload un-synced local records to Firestore, excluding any tombstoned records."""
        try:
            from .firestore_service import FirestoreService
            # Purge any lingering records that were tombstoned
            conn.execute("DELETE FROM clipboard_entries WHERE id IN (SELECT id FROM deleted_entries)")
            conn.commit()

            un_synced = conn.execute(
                """
                SELECT * FROM clipboard_entries 
                WHERE user_id = ? 
                  AND (sync_status IS NULL OR sync_status != 'synced')
                  AND id NOT IN (SELECT id FROM deleted_entries)
                LIMIT 25
                """,
                (uid,),
            ).fetchall()
            for r in un_synced:
                data = dict(r)
                if FirestoreService.sync_entry(data):
                    conn.execute("UPDATE clipboard_entries SET sync_status = 'synced' WHERE id = ?", (data["id"],))
            conn.commit()
        except Exception:
            pass

    @classmethod
    def get_entry(cls, uid: str, entry_id: str) -> Optional[dict]:
        """Retrieve a specific entry, verifying user ownership."""
        if not uid or not entry_id:
            return None

        if not cls._use_sqlite():
            user_entries = cls.get_user_store(uid)
            entry = user_entries.get(entry_id)
            if entry and not entry.is_expired():
                return entry.to_dict()
            return None

        db_file = cls._get_db_path()
        if not db_file.exists():
            return None

        import sqlite3
        with sqlite3.connect(str(db_file), timeout=5) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM clipboard_entries WHERE id = ? AND (user_id = ? OR user_id IS NULL)",
                (entry_id, uid),
            ).fetchone()
            if row:
                entry_dict = dict(row)
                now_ms = int(time.time() * 1000)
                if entry_dict.get("expires_at", 0) > now_ms:
                    return entry_dict
        return None

    @classmethod
    def add_entry(
        cls,
        uid: str,
        content: str,
        created_at: Optional[int] = None,
        expires_at: Optional[int] = None,
    ) -> dict:
        """
        Add a new clipboard entry for the user.
        Enforces user ownership, 7-day retention, and schema versioning.
        """
        if not uid:
            raise PermissionError("User ID is required to add entries.")
        if not content or not isinstance(content, str):
            raise ValueError("Content cannot be empty.")

        entry_id = str(uuid.uuid4())
        entry = ClipboardEntry(
            entry_id=entry_id,
            user_id=uid,
            content=content,
            created_at=created_at,
            expires_at=expires_at,
        )

        if not cls._use_sqlite():
            user_entries = cls.get_user_store(uid)
            user_entries[entry_id] = entry
            return entry.to_dict()

        from desktop_watcher import ClipboardDatabase
        db = ClipboardDatabase(cls._get_db_path())
        record = db.insert_entry(content=content, user_id=uid, created_at=created_at)

        # Sync to Cloud Firestore if available
        try:
            from .firestore_service import FirestoreService
            if FirestoreService.is_available():
                if FirestoreService.sync_entry(record):
                    record["sync_status"] = "synced"
                    db.update_sync_status(record["id"], "synced")
        except Exception:
            pass

        return record

    @classmethod
    def delete_entry(cls, uid: str, entry_id: str) -> bool:
        """
        Delete an entry belonging to the user.
        Returns True if deleted, False if entry does not exist or belongs to another user.
        """
        if not uid or not entry_id:
            return False

        if not cls._use_sqlite():
            user_entries = cls.get_user_store(uid)
            if entry_id in user_entries:
                del user_entries[entry_id]
                return True
            return False

        db_file = cls._get_db_path()
        if not db_file.exists():
            return False

        import sqlite3
        with sqlite3.connect(str(db_file), timeout=5) as conn:
            cur = conn.execute(
                "DELETE FROM clipboard_entries WHERE id = ? AND (user_id = ? OR user_id IS NULL)",
                (entry_id, uid),
            )
            deleted = cur.rowcount > 0
            if deleted:
                # Record tombstone to prevent resurrection from stale offline states
                now_ms = int(time.time() * 1000)
                conn.execute(
                    "INSERT OR REPLACE INTO deleted_entries (id, user_id, deleted_at) VALUES (?, ?, ?)",
                    (entry_id, uid, now_ms),
                )
            conn.commit()

        # Propagate deletion to Cloud Firestore
        if deleted:
            try:
                from .firestore_service import FirestoreService
                if FirestoreService.is_available():
                    FirestoreService.delete_entry(uid, entry_id)
            except Exception:
                pass

        return deleted

    @classmethod
    def bulk_delete_entries(cls, uid: str, entry_ids: List[str]) -> Tuple[List[str], List[str]]:
        """
        Bulk delete multiple entries belonging to the user.
        Ensures atomic local removal, tombstone persistence against resurrection,
        and Cloud Firestore batch deletion.
        Returns a tuple: (deleted_ids, failed_ids).
        """
        if not uid or not entry_ids:
            return [], []

        # Sanitize and deduplicate incoming IDs
        unique_ids = list(dict.fromkeys([str(eid).strip() for eid in entry_ids if eid]))
        if not unique_ids:
            return [], []

        # In-memory test store fallback
        if not cls._use_sqlite():
            user_entries = cls.get_user_store(uid)
            authorized = []
            for eid in unique_ids:
                if eid in user_entries:
                    del user_entries[eid]
                    authorized.append(eid)

            try:
                from .firestore_service import FirestoreService
                if FirestoreService.is_available() and authorized:
                    return FirestoreService.bulk_delete_entries(uid, authorized)
            except Exception:
                pass
            return authorized, []

        db_file = cls._get_db_path()
        if not db_file.exists():
            return [], unique_ids

        authorized_deleted: List[str] = []
        now_ms = int(time.time() * 1000)

        import sqlite3
        with sqlite3.connect(str(db_file), timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            # Process in safe chunks of 100 for SQL parameters
            chunk_size = 100
            for i in range(0, len(unique_ids), chunk_size):
                chunk = unique_ids[i:i + chunk_size]
                placeholders = ",".join(["?"] * len(chunk))
                # 1. Verify ownership: Only match entries owned by this user
                query = f"SELECT id FROM clipboard_entries WHERE id IN ({placeholders}) AND user_id = ?"
                rows = conn.execute(query, chunk + [uid]).fetchall()
                chunk_authorized = [r["id"] for r in rows]

                if chunk_authorized:
                    auth_placeholders = ",".join(["?"] * len(chunk_authorized))
                    # 2. Delete authorized records
                    conn.execute(
                        f"DELETE FROM clipboard_entries WHERE id IN ({auth_placeholders}) AND user_id = ?",
                        chunk_authorized + [uid],
                    )
                    # 3. Record tombstones to prevent offline clients or retries from resurrecting
                    conn.executemany(
                        "INSERT OR REPLACE INTO deleted_entries (id, user_id, deleted_at) VALUES (?, ?, ?)",
                        [(eid, uid, now_ms) for eid in chunk_authorized],
                    )
                    conn.commit()
                    authorized_deleted.extend(chunk_authorized)

        # 4. Propagate deletion to Cloud Firestore
        cloud_deleted = list(authorized_deleted)
        cloud_failed: List[str] = []
        try:
            from .firestore_service import FirestoreService
            if FirestoreService.is_available() and authorized_deleted:
                c_del, c_fail = FirestoreService.bulk_delete_entries(uid, authorized_deleted)
                cloud_deleted = c_del
                cloud_failed = c_fail
        except Exception:
            pass

        return cloud_deleted, cloud_failed
