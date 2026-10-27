import logging
import os
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger("firestore_service")

_app_lock = threading.Lock()
_firestore_client = None
_initialized = False


class FirestoreService:
    """
    Manages synchronization with Google Cloud Firestore.
    Stores and retrieves cross-device clipboard entries strictly partitioned under:
    users/{uid}/clipboardEntries/{entryId}
    """

    @classmethod
    def get_client(cls):
        """Lazy-initialize and return the Firestore client singleton."""
        global _firestore_client, _initialized

        # Fail-closed guard: Never initialize or access Firestore client in load test mode
        if os.environ.get("LOAD_TEST_MODE", "0").lower() in ("1", "true", "yes") or \
           os.environ.get("DISABLE_FIRESTORE", "0").lower() in ("1", "true", "yes"):
            logger.debug("Firestore client access strictly blocked by env LOAD_TEST_MODE / DISABLE_FIRESTORE.")
            return None

        try:
            from flask import current_app, has_app_context
            if has_app_context():
                if current_app.config.get("LOAD_TEST_MODE", False) or current_app.config.get("DISABLE_FIRESTORE", False):
                    logger.debug("Firestore client access strictly blocked by LOAD_TEST_MODE / DISABLE_FIRESTORE.")
                    return None
        except Exception:
            pass

        if _firestore_client is not None:
            return _firestore_client

        with _app_lock:
            if _firestore_client is not None:
                return _firestore_client

            try:
                import firebase_admin
                from firebase_admin import credentials, firestore
            except ImportError:
                logger.debug("firebase-admin package not available.")
                return None

            # Resolve service account key path
            key_path = ""
            try:
                from flask import current_app, has_app_context
                if has_app_context():
                    key_path = current_app.config.get("FIREBASE_SERVICE_ACCOUNT_KEY", "")
            except Exception:
                pass

            if not key_path:
                from ..config import Config
                key_path = Config.FIREBASE_SERVICE_ACCOUNT_KEY

            if not key_path or not Path(key_path).exists():
                logger.debug("Service account key not found at: %s", key_path)
                return None

            try:
                # Check if default app is already initialized
                if not firebase_admin._apps:
                    cred = credentials.Certificate(key_path)
                    firebase_admin.initialize_app(cred)
                _firestore_client = firestore.client()
                _initialized = True
                logger.info("Cloud Firestore client initialized successfully.")
                return _firestore_client
            except Exception as e:
                logger.warning("Failed to initialize Firebase Admin: %s", e)
                return None

    @classmethod
    def is_available(cls) -> bool:
        """Return True if Firestore client is available and connected."""
        if os.environ.get("LOAD_TEST_MODE", "0").lower() in ("1", "true", "yes") or \
           os.environ.get("DISABLE_FIRESTORE", "0").lower() in ("1", "true", "yes"):
            return False
        try:
            from flask import current_app, has_app_context
            if has_app_context():
                if current_app.config.get("LOAD_TEST_MODE", False) or current_app.config.get("DISABLE_FIRESTORE", False):
                    return False
        except Exception:
            pass
        return cls.get_client() is not None

    @classmethod
    def sync_entry(cls, entry: Dict[str, Any]) -> bool:
        """
        Upsert a clipboard entry into Firestore under users/{uid}/clipboardEntries/{id}.
        Returns True on success, False on failure.
        """
        # Fail-closed guard
        try:
            from flask import current_app, has_app_context
            if has_app_context() and current_app.config.get("LOAD_TEST_MODE", False):
                raise RuntimeError("FAIL-CLOSED GUARD: Prohibited attempt to sync with Cloud Firestore while LOAD_TEST_MODE is active!")
        except RuntimeError:
            raise
        except Exception:
            pass

        db = cls.get_client()
        if not db:
            return False

        uid = entry.get("user_id")
        entry_id = entry.get("id")
        if not uid or not entry_id:
            return False

        # Format document strictly according to CLIPBOARD_DATA_SCHEMA.md
        doc_data = {
            "id": entry_id,
            "user_id": uid,
            "content": entry.get("content", ""),
            "entry_type": entry.get("entry_type", "text"),
            "created_at": int(entry.get("created_at", 0)),
            "updated_at": int(entry.get("updated_at", entry.get("created_at", 0))),
            "expires_at": int(entry.get("expires_at", 0)),
            "schema_version": int(entry.get("schema_version", 1)),
        }

        try:
            doc_ref = (
                db.collection("users")
                .document(uid)
                .collection("clipboardEntries")
                .document(entry_id)
            )
            doc_ref.set(doc_data)
            logger.info("Successfully synced entry %s to Firestore for user %s", entry_id, uid)
            return True
        except Exception as e:
            logger.warning("Failed to sync entry %s to Firestore: %s", entry_id, e)
            return False

    @classmethod
    def delete_entry(cls, uid: str, entry_id: str) -> bool:
        """
        Delete an entry from Firestore.
        """
        # Fail-closed guard
        try:
            from flask import current_app, has_app_context
            if has_app_context() and current_app.config.get("LOAD_TEST_MODE", False):
                raise RuntimeError("FAIL-CLOSED GUARD: Prohibited attempt to delete from Cloud Firestore while LOAD_TEST_MODE is active!")
        except RuntimeError:
            raise
        except Exception:
            pass

        db = cls.get_client()
        if not db or not uid or not entry_id:
            return False

        try:
            doc_ref = (
                db.collection("users")
                .document(uid)
                .collection("clipboardEntries")
                .document(entry_id)
            )
            doc_ref.delete()
            logger.info("Deleted entry %s from Firestore for user %s", entry_id, uid)
            return True
        except Exception as e:
            logger.warning("Failed to delete entry %s from Firestore: %s", entry_id, e)
            return False

    @classmethod
    def bulk_delete_entries(cls, uid: str, entry_ids: List[str]) -> Tuple[List[str], List[str]]:
        """
        Bulk delete entries from Firestore in batches conforming to the 500-operation limit.
        Returns a tuple: (deleted_ids, failed_ids).
        """
        # Fail-closed guard
        try:
            from flask import current_app, has_app_context
            if has_app_context() and current_app.config.get("LOAD_TEST_MODE", False):
                raise RuntimeError("FAIL-CLOSED GUARD: Prohibited attempt to bulk delete from Cloud Firestore while LOAD_TEST_MODE is active!")
        except RuntimeError:
            raise
        except Exception:
            pass
        db = cls.get_client()
        if not db or not uid or not entry_ids:
            return [], list(entry_ids)

        deleted_ids: List[str] = []
        failed_ids: List[str] = []

        # Chunk into batches of up to 400 (safely below Firestore's 500-operation limit)
        batch_size = 400
        for i in range(0, len(entry_ids), batch_size):
            chunk = entry_ids[i:i + batch_size]
            try:
                batch = db.batch()
                user_coll = db.collection("users").document(uid).collection("clipboardEntries")
                for entry_id in chunk:
                    doc_ref = user_coll.document(entry_id)
                    batch.delete(doc_ref)
                batch.commit()
                deleted_ids.extend(chunk)
                logger.info("Batch deleted %d entries from Firestore for user %s", len(chunk), uid)
            except Exception as e:
                logger.warning("Firestore batch delete failure for chunk of %d items: %s", len(chunk), e)
                # On batch failure, attempt fallback single deletes for remaining items in chunk to isolate errors
                for entry_id in chunk:
                    try:
                        doc_ref = db.collection("users").document(uid).collection("clipboardEntries").document(entry_id)
                        doc_ref.delete()
                        deleted_ids.append(entry_id)
                    except Exception:
                        failed_ids.append(entry_id)

        return deleted_ids, failed_ids

    @classmethod
    def fetch_entries(cls, uid: str, limit: int = 50, now_ms: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Fetch active (non-expired) entries from Firestore for the given user, newest first.
        """
        db = cls.get_client()
        if not db or not uid:
            return []

        try:
            import time
            now = now_ms or int(time.time() * 1000)
            coll = db.collection("users").document(uid).collection("clipboardEntries")
            # Query non-expired entries ordered by creation date
            query = (
                coll.where("expires_at", ">", now)
                .order_by("expires_at")
                .order_by("created_at", direction="DESCENDING")
                .limit(limit)
            )
            docs = query.get()
            results = []
            for doc in docs:
                data = doc.to_dict()
                if data:
                    results.append(data)
            # Ensure newest first
            results.sort(key=lambda x: x.get("created_at", 0), reverse=True)
            return results
        except Exception as e:
            logger.warning("Firestore fetch error for user %s: %s", uid, e)
            return []
