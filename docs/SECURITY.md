# UniClip — Security Architecture & Firestore Rules

---

## 1. Cloud Firestore Security Rules

To enforce strict per-user segregation and prevent tampering, deploy the following security rules in Firebase Console under **Firestore Database** > **Rules**:

```javascript
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {

    // Helper functions
    function isAuthenticated() {
      return request.auth != null && request.auth.uid != null;
    }

    function isOwner(userId) {
      return isAuthenticated() && request.auth.uid == userId;
    }

    function isValidEntry(userId) {
      let data = request.resource.data;
      return data.keys().hasAll(['id', 'user_id', 'content', 'entry_type', 'created_at', 'updated_at', 'expires_at', 'schema_version'])
        && data.keys().hasOnly(['id', 'user_id', 'content', 'entry_type', 'created_at', 'updated_at', 'expires_at', 'schema_version'])
        && data.user_id == userId
        && data.user_id == request.auth.uid
        && data.content is string
        && data.content.size() > 0
        && data.content.size() <= 65536
        && data.entry_type in ['text', 'url']
        && data.created_at is int
        && data.updated_at is int
        && data.expires_at is int
        && data.expires_at > data.created_at
        && data.schema_version == 1;
    }

    // Per-user clipboard entries collection
    match /users/{userId}/clipboardEntries/{entryId} {
      // 1. Read: User can only read their own entries
      allow read: if isOwner(userId);

      // 2. Create: User can only create entries within their own collection with valid fields
      allow create: if isOwner(userId)
                    && request.resource.id == entryId
                    && isValidEntry(userId);

      // 3. Update: User can update timestamp, preserving original ownership and creation
      allow update: if isOwner(userId)
                    && isValidEntry(userId)
                    && request.resource.data.created_at == resource.data.created_at
                    && request.resource.data.user_id == resource.data.user_id;

      // 4. Delete: User can only delete their own entries
      allow delete: if isOwner(userId);
    }

    // Default deny all other paths
    match /{document=**} {
      allow read, write: if false;
    }
  }
}
```

---

## 2. Web Application Security Controls

### A. Authentication & ID Token Verification
- Client-side browser signs in via Firebase Google Sign-In popup.
- The resulting JWT ID token is transmitted over TLS to `/api/auth/session`.
- The Flask server verifies the token against Google's public key endpoint (`https://oauth2.googleapis.com/tokeninfo`).
- The user's UID is extracted strictly from the cryptographic token claims—never from a client-supplied body parameter.

### B. Session Cookies & CSRF Protection
- **HttpOnly Cookies**: Session cookies cannot be accessed or stolen via JavaScript `document.cookie`.
- **SameSite**: Enforced as `Lax` to prevent cross-site request forgery in top-level navigations.
- **CSRF Tokens**: All state-changing endpoints (`POST /logout`, `POST /api/clipboard`, `POST /api/clipboard/<id>/delete`) require a cryptographically secure 32-byte hexadecimal token verified with constant-time string comparison (`secrets.compare_digest`).

### C. XSS Prevention & Safe Output Rendering
- All user-supplied clipboard texts are escaped by Jinja2 templates by default.
- Modern security headers are attached to every HTTP response:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: SAMEORIGIN`
  - `X-XSS-Protection: 1; mode=block`
  - `Referrer-Policy: strict-origin-when-cross-origin`

### D. Zero-Content Logging Policy
- Plain-text clipboard data is **never** printed to Flask console logs, application log files, or unhandled exception tracebacks.
- Search queries are evaluated in-memory without persistent telemetry or logging.

---

## 3. Secret Detection Guarantees & Limitations

The Windows desktop client enforces local pre-persistence secret detection:
- Regex checks identify API keys (e.g., `AIza...`, `sk-ant...`, `ghp_...`), private keys (`-----BEGIN PRIVATE KEY...`), database connection strings, and credential patterns.
- Matching clipboard events are discarded before reaching the local SQLite cache or Cloud Firestore.

> [!WARNING]
> **Limitations**: No regex or heuristic filter can guarantee 100% detection of all sensitive tokens, passphrases, or custom secrets. Users should exercise caution when copying raw credentials on any synchronized workstation.
