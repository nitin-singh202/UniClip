import secrets
import re
from urllib.parse import urlparse
from flask import session, request, abort


def generate_csrf_token() -> str:
    """Generate or retrieve a CSRF token stored in the user's session."""
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(32)
    return session["_csrf_token"]


def validate_csrf_token(token: str) -> bool:
    """Validate a submitted CSRF token against the session token."""
    expected_token = session.get("_csrf_token")
    if not expected_token or not token:
        return False
    return secrets.compare_digest(str(expected_token), str(token))


def verify_csrf():
    """Verify CSRF token for state-changing HTTP requests."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        # Check header first (for fetch / AJAX), then form data
        token = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
        if not token or not validate_csrf_token(token):
            abort(400, description="Invalid or missing CSRF token.")


def detect_entry_type(content: str) -> str:
    """Determine whether a clipboard string is a valid URL or plain text."""
    if not content or not isinstance(content, str):
        return "text"
    trimmed = content.strip()
    if trimmed.startswith(("http://", "https://")):
        try:
            result = urlparse(trimmed)
            if result.scheme and result.netloc:
                return "url"
        except Exception:
            return "text"
    return "text"
