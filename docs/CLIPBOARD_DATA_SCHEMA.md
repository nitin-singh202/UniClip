# UniClip — Canonical Data Schema Contract

**Version:** 1.0.0  
**Status:** Active  
**Scope:** Windows Python Desktop Client, Flutter Android App, and Flask Web Dashboard  

---

## 1. Overview & Path Hierarchy

All synchronized clipboard records are partitioned strictly per-user in Google Cloud Firestore:

```text
users/
  └── {uid}/
        └── clipboardEntries/
              └── {entryId}
```

- `{uid}`: The Firebase Authentication User UID (string).
- `{entryId}`: A client-generated UUIDv4 string (or Firestore Document ID).

---

## 2. Document Fields & Specifications

| Field Name | Type | Required | Description | Constraints |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `string` | **Yes** | Stable unique identifier for the entry. | Must match `{entryId}`. UUIDv4 string. |
| `user_id` | `string` | **Yes** | The owner's Firebase UID. | Must strictly equal `request.auth.uid`. |
| `content` | `string` | **Yes** | The plain-text clipboard payload. | Non-empty string. Max length 65,536 bytes (64 KB). |
| `entry_type` | `string` | **Yes** | Classification of clipboard payload. | Enum: `"text"` or `"url"`. |
| `created_at` | `number` | **Yes** | Creation epoch timestamp in milliseconds. | UTC Unix timestamp (e.g., `1774345200000`). |
| `updated_at` | `number` | **Yes** | Last update epoch timestamp in milliseconds. | UTC Unix timestamp. Must be `>= created_at`. |
| `expires_at` | `number` | **Yes** | Expiration deadline for retention enforcement. | Standard: `created_at + 604800000` (7 days). |
| `schema_version` | `number` | **Yes** | Schema evolution version indicator. | Currently `1`. |

### Example Document Payload
```json
{
  "id": "e9b2c15d-5a67-4f40-8b01-1cfcb2de7829",
  "user_id": "8j3Nkq04mfa8K29smx0Z9PklQ192",
  "content": "https://docs.flutter.dev/get-started",
  "entry_type": "url",
  "created_at": 1774345200000,
  "updated_at": 1774345200000,
  "expires_at": 1774950000000,
  "schema_version": 1
}
```

---

## 3. Cross-Client Compatibility Contract

### A. Windows Python Desktop Client
1. **Local Pre-persistence Filtering**: The desktop client intercepts clipboard changes using `pyperclip` or Windows Win32 API.
2. **Security Gate**: Content matching password regexes, private keys (`-----BEGIN ...`), JWT tokens, or credentials is **blocked** from persisting or uploading.
3. **Local Cache**: Saved to local SQLite database with identical schema columns.
4. **Cloud Sync**: Upserts record into `users/{uid}/clipboardEntries/{entryId}` via Firestore REST API or Firebase Python SDK.

### B. Flutter Android Companion App
1. **Fetch & Display**: Streams queries from `users/{uid}/clipboardEntries` where `expires_at > now()`, ordered by `created_at desc`.
2. **Local Cache**: Retains records in local SQLite/Drift/Isar database.
3. **Copy to System Clipboard**: Tapping Copy uses Android `ClipboardManager` to populate the Android device clipboard.

### C. Flask Web Dashboard
1. **Read & Search**: Fetches user's active entries from Firestore (or in-memory mock during testing). Excludes expired items (`expires_at < now`).
2. **Copy to Browser Clipboard**: Invokes browser `navigator.clipboard.writeText` upon explicit user gesture.
3. **Deletion**: Deletes the specified document from `users/{uid}/clipboardEntries/{entryId}`.

---

## 4. Retention & Deletion Policy
- **Standard Retention**: 7 days (604,800,000 milliseconds).
- **Cleanup Strategy**:
  - Queries on all clients include a filter: `expires_at > current_epoch_ms`.
  - A server-side Firebase Cloud Function or TTL policy may periodically purge expired documents from Firestore to reclaim storage.
  - Deletions are hard deletes: removing the document propagates in real-time to active listeners.
