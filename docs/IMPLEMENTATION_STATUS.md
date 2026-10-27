# UniClip — Implementation Status & Architecture

**Last Updated:** October 2026  
**Current Phase:** Web Dashboard Implemented & Test Suite Verified  

---

## 1. Component Architecture & Status

| Component | Stack / Technologies | Status | Notes |
| :--- | :--- | :--- | :--- |
| **Web Dashboard** | Python 3.11, Flask 3.1, Jinja2, Vanilla JS, CSS3 | **Complete & Verified** | Compact high-density table UI, live polling sync, stable-ID reconciliation, 7-day retention, search, copy & delete. |
| **Authentication** | Firebase Auth (Google Sign-In) + Server Token Verification | **Integrated** | Uses project `universal-clipboard-ai`. Includes fast local dev mock mode. |
| **Data Schema** | Cloud Firestore / Canonical Document Contract | **Defined** | Specified in `docs/CLIPBOARD_DATA_SCHEMA.md`. |
| **Security Rules** | Firestore Security Rules v2 | **Documented** | Restrictive per-user rules prepared in `docs/SECURITY.md`. |
| **Windows Desktop Watcher** | Python 3.11, SQLite, `pyperclip` (`desktop_watcher.py`) | **Complete & Verified** | Windows clipboard listener, pre-persistence secret detector, local SQLite storage, 7-day retention. Legacy prototypes (`uniclip.py`, `uniclip_updated.py`) preserved untouched. |
| **Flutter Android App** | Flutter / Dart, `google-services.json` | **Planned** | `google-services.json` is preserved in `android/app/`. |

---

## 2. Tested Capabilities

- **Development Server Startup**: Flask application factory boots cleanly in local mode.
- **Unauthenticated Protection**: Protected routes (`/dashboard`, `/settings`, `/api/clipboard/*`) strictly redirect unauthenticated requests to `/login`.
- **User Segregation**: Entry retrieval, search, and deletion operate strictly within the authenticated user's scope (`users/{uid}/...`).
- **7-Day Retention**: Expired items (`expires_at < current_time`) are excluded from queries.
- **CSRF Protection**: All state-changing operations require valid session CSRF tokens.
- **XSS Prevention**: Clipboard content is escaped and safely presented in cards and modals.
- **Safe Error Handling**: Error pages do not leak exception traces, credentials, or clipboard payloads.

---

## 3. Remaining Manual Steps in Firebase Console

Before live cross-device synchronization with real Google accounts:

1. **Enable Google Provider in Firebase Console**:
   - Go to [Firebase Console](https://console.firebase.google.com/) > `universal-clipboard-ai` > **Authentication** > **Sign-in method**.
   - Enable **Google** and specify your project support email.
2. **Deploy Firestore Security Rules**:
   - Copy the rules from `docs/SECURITY.md` into **Firestore Database** > **Rules** and click **Publish**.
3. **Register Web App**:
   - Under Project Settings > **General**, confirm your Web App registration and update `FIREBASE_APP_ID` in `web/.env` if desired.
