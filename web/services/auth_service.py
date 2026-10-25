from functools import wraps
import time
import requests
from flask import session, redirect, url_for, request, jsonify, abort, current_app


class AuthService:
    """Handles Firebase Authentication verification and session management."""

    @staticmethod
    def verify_firebase_id_token(id_token: str) -> dict:
        """
        Verify a Firebase ID token.
        Uses Google OAuth2 tokeninfo endpoint or mock validator in development/test.
        Returns a dict with user information: {'uid': str, 'email': str, 'name': str, 'picture': str}.
        Raises ValueError if invalid.
        """
        if not id_token:
            raise ValueError("Empty or missing ID token.")

        # Check if in dev/mock testing mode
        if current_app.config.get("DEV_MOCK_AUTH", False):
            if id_token.startswith("mock-valid-token-"):
                uid = id_token.replace("mock-valid-token-", "")
                return {
                    "uid": uid,
                    "email": f"{uid}@example.com",
                    "name": f"User {uid.capitalize()}",
                    "picture": ""
                }
            elif id_token == "mock-expired-token":
                raise ValueError("Token expired.")
            elif id_token.startswith("mock-invalid"):
                raise ValueError("Invalid signature.")

        # In production or live mode with Google Firebase Identity Toolkit:
        try:
            api_key = current_app.config.get("FIREBASE_API_KEY")
            lookup_url = f"https://identitytoolkit.googleapis.com/v1/accounts:lookup?key={api_key}"
            resp = requests.post(lookup_url, json={"idToken": id_token}, timeout=8)

            if resp.status_code != 200:
                err_data = resp.json() if resp.content else {}
                err_msg = err_data.get("error", {}).get("message", f"HTTP {resp.status_code}")
                if "EXPIRED" in err_msg:
                    raise ValueError("Token expired.")
                raise ValueError(f"Firebase verification failed: {err_msg}")

            data = resp.json()
            users = data.get("users", [])
            if not users:
                raise ValueError("No user account associated with this token.")

            user = users[0]
            uid = user.get("localId")
            if not uid:
                raise ValueError("Token does not contain a valid user ID.")

            # Decode and verify project audience from token claims
            claims = AuthService._decode_unverified_claims(id_token)
            expected_project = current_app.config.get("FIREBASE_PROJECT_ID", "universal-clipboard-ai")
            token_aud = claims.get("aud")
            if token_aud and token_aud != expected_project:
                raise ValueError(f"Token audience '{token_aud}' does not match project '{expected_project}'")

            return {
                "uid": uid,
                "email": user.get("email") or claims.get("email", ""),
                "name": user.get("displayName") or claims.get("name", "User"),
                "picture": user.get("photoUrl") or claims.get("picture", "")
            }
        except requests.RequestException as e:
            raise ConnectionError(f"Network error verifying Firebase token: {e}")

    @staticmethod
    def _decode_unverified_claims(token: str) -> dict:
        """Helper to extract claims from JWT without crypto verification."""
        import json, base64
        try:
            parts = token.split(".")
            if len(parts) == 3:
                payload = parts[1]
                payload += "=" * (-len(payload) % 4)
                return json.loads(base64.urlsafe_b64decode(payload.encode("utf-8")))
        except Exception:
            pass
        return {}

    @staticmethod
    def establish_session(user_info: dict):
        """Store verified authenticated user details in Flask session."""
        session.clear()
        session["user"] = {
            "uid": user_info["uid"],
            "email": user_info.get("email", ""),
            "name": user_info.get("name", "User"),
            "picture": user_info.get("picture", ""),
            "auth_time": int(time.time()),
        }
        # Mark session modified
        session.permanent = True

        # Sync active user UID to local SQLite app_state for desktop watcher
        try:
            from desktop_watcher import ClipboardDatabase
            db = ClipboardDatabase()
            db.set_app_state("active_user_id", user_info["uid"])
        except Exception:
            pass

    @staticmethod
    def establish_guest_session() -> dict:
        """Create a temporary local Guest Mode session."""
        session.clear()
        guest_user = {
            "uid": "guest",
            "name": "Guest User",
            "email": "",
            "picture": "",
            "is_guest": True,
            "auth_time": int(time.time()),
        }
        session["user"] = guest_user
        session.permanent = False
        return guest_user

    @staticmethod
    def get_current_user() -> dict | None:
        """Return the currently authenticated user dictionary or None."""
        return session.get("user")

    @staticmethod
    def clear_session():
        """Sign out the user and clear session data."""
        was_guest = session.get("user", {}).get("is_guest", False)
        session.clear()
        if not was_guest:
            try:
                from desktop_watcher import ClipboardDatabase
                db = ClipboardDatabase()
                db.delete_app_state("active_user_id")
            except Exception:
                pass


def login_required(f):
    """Decorator ensuring that authenticated users (or guests for UI views) can access the endpoint."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = AuthService.get_current_user()
        if not user or not user.get("uid"):
            accept_header = request.headers.get("Accept", "")
            if (
                request.is_json
                or "application/json" in accept_header
                or request.path.startswith("/api/")
                or request.path == "/entries"
            ):
                return jsonify({"error": "Unauthorized", "message": "Authentication required"}), 401
            return redirect(url_for("login", next=request.path))

        # Block guest users from invoking authenticated server-side Firestore mutation APIs
        if user.get("is_guest"):
            if request.path.startswith("/api/clipboard/") and request.method in ("POST", "DELETE", "PUT", "PATCH"):
                return jsonify({
                    "error": "Forbidden",
                    "message": "Guest data is stored locally in your browser and cannot be modified via server APIs.",
                }), 403

        return f(*args, **kwargs)
    return decorated_function
