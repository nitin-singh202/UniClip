import time
from datetime import datetime, timezone
from flask import (
    Flask,
    render_template,
    redirect,
    url_for,
    request,
    jsonify,
    session,
    abort,
    send_from_directory,
)
import os
import sys
import threading
from pathlib import Path

# Support running directly via `python app.py` or as package `python -m web.app`
if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from config import Config
    from services import (
        AuthService,
        ClipboardService,
        login_required,
        generate_csrf_token,
        validate_csrf_token,
        verify_csrf,
    )
else:
    from .config import Config
    from .services import (
        AuthService,
        ClipboardService,
        login_required,
        generate_csrf_token,
        validate_csrf_token,
        verify_csrf,
    )


def format_timestamp(ts_ms: int) -> str:
    """Format millisecond timestamp into a human-readable local/UTC string."""
    if not ts_ms:
        return "Unknown"
    dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
    return dt.strftime("%b %d, %Y • %H:%M UTC")


def format_time_remaining(expires_ms: int) -> str:
    """Format time remaining before expiration."""
    if not expires_ms:
        return "Unknown"
    now_ms = int(time.time() * 1000)
    diff_ms = expires_ms - now_ms
    if diff_ms <= 0:
        return "Expired"
    hours = int(diff_ms / (1000 * 60 * 60))
    days = int(hours / 24)
    if days > 0:
        return f"{days} day{'s' if days != 1 else ''} left"
    return f"{hours} hour{'s' if hours != 1 else ''} left"


def create_app(config_class=Config) -> Flask:
    """Application factory for Universal Clipboard AI Web Dashboard."""
    if hasattr(config_class, "validate"):
        config_class.validate()
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Register template filters
    app.jinja_env.filters["format_ts"] = format_timestamp
    app.jinja_env.filters["time_left"] = format_time_remaining

    # Context processor to expose common variables across all templates
    @app.context_processor
    def inject_common_context():
        return {
            "csrf_token": generate_csrf_token(),
            "current_user": AuthService.get_current_user(),
            "firebase_config": config_class.get_firebase_client_config(),
            "retention_days": config_class.CLIPBOARD_RETENTION_DAYS,
            "dev_mock_auth": app.config.get("DEV_MOCK_AUTH", False),
        }

    # Security headers hook
    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    # ------------------ PWA Routes ------------------

    @app.route("/manifest.webmanifest")
    def pwa_manifest():
        """Serve PWA web app manifest with correct MIME type."""
        return send_from_directory(
            os.path.join(app.root_path, "static"),
            "manifest.webmanifest",
            mimetype="application/manifest+json",
        )

    @app.route("/sw.js")
    @app.route("/service-worker.js")
    def pwa_service_worker():
        """Serve PWA Service Worker script with root scope authority."""
        response = send_from_directory(
            os.path.join(app.root_path, "static", "js"),
            "sw.js",
            mimetype="application/javascript",
        )
        response.headers["Service-Worker-Allowed"] = "/"
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response

    @app.route("/offline")
    def pwa_offline():
        """Serve safe offline fallback page shell."""
        return render_template("offline.html")

    # ------------------ Routes ------------------

    @app.route("/")
    def index():
        """Root route: redirect to dashboard if authenticated, else login."""
        user = AuthService.get_current_user()
        if user and user.get("uid"):
            return redirect(url_for("dashboard"))
        return redirect(url_for("login"))

    @app.route("/login")
    @app.route("/auth/login")
    def login():
        """Render the login page."""
        user = AuthService.get_current_user()
        if user and user.get("uid"):
            return redirect(url_for("dashboard"))
        return render_template("login.html")

    @app.route("/api/auth/session", methods=["POST"])
    def auth_session():
        """
        Verify Firebase ID token sent from browser and establish authenticated session.
        Never trust a user-provided user ID directly.
        """
        data = request.get_json(silent=True) or {}
        id_token = data.get("id_token")

        if not id_token:
            return jsonify({"success": False, "error": "Missing id_token"}), 400

        try:
            user_info = AuthService.verify_firebase_id_token(id_token)
            AuthService.establish_session(user_info)
            return jsonify({
                "success": True,
                "user": {
                    "uid": user_info["uid"],
                    "email": user_info.get("email", ""),
                    "name": user_info.get("name", "User"),
                }
            })
        except ValueError as e:
            app.logger.warning("Auth session verification rejected: %s", e)
            return jsonify({"success": False, "error": str(e)}), 401
        except Exception as e:
            app.logger.error("Auth session unexpected error: %s", e)
            return jsonify({"success": False, "error": "Authentication verification failed"}), 500

    @app.route("/api/auth/guest-session", methods=["POST"])
    def guest_session_create():
        """Create a temporary guest session for local-only device testing."""
        guest_user = AuthService.establish_guest_session()
        return jsonify({
            "success": True,
            "user": guest_user,
            "message": "Guest session created. Data is stored locally on this device.",
        })

    @app.route("/api/auth/guest-session/end", methods=["POST"])
    def guest_session_end():
        """End the guest session and clear server session."""
        AuthService.clear_session()
        return jsonify({"success": True, "message": "Guest session ended."})

    @app.route("/logout", methods=["POST"])
    def logout():
        """Log out the user, validate CSRF, and clear session."""
        verify_csrf()
        AuthService.clear_session()
        return redirect(url_for("login"))

    @app.route("/dashboard")
    @login_required
    def dashboard():
        """Main clipboard history dashboard for authenticated users or guest mode."""
        user = AuthService.get_current_user()
        if user.get("is_guest"):
            return render_template(
                "dashboard.html",
                entries=[],
                total_count=0,
                search_query="",
                sync_status="guest_ready",
                is_guest=True,
            )

        uid = user["uid"]
        search_query = request.args.get("q", "").strip()
        entries, sync_status = ClipboardService.list_entries(uid, search_query=search_query)

        return render_template(
            "dashboard.html",
            entries=entries,
            total_count=len(entries),
            search_query=search_query,
            sync_status=sync_status,
            is_guest=False,
        )

    @app.route("/settings")
    @login_required
    def settings():
        """Settings and sync status overview."""
        user = AuthService.get_current_user()
        return render_template("settings.html", is_guest=user.get("is_guest", False))

    @app.route("/api/clipboard/entries", methods=["GET"])
    @app.route("/entries", methods=["GET"])
    @login_required
    def get_clipboard_entries_api():
        """Lightweight endpoint for polling sync and auto-refresh."""
        user = AuthService.get_current_user()
        if user.get("is_guest"):
            return jsonify({
                "success": True,
                "entries": [],
                "total_count": 0,
                "sync_status": "guest_ready",
                "is_guest": True,
            })

        uid = user["uid"]
        search_query = request.args.get("q", "").strip()

        entries, sync_status = ClipboardService.list_entries(uid, search_query=search_query)

        formatted_entries = []
        for e in entries:
            formatted_entries.append({
                "id": e["id"],
                "content": e["content"],
                "entry_type": e.get("entry_type", "text"),
                "created_at": e.get("created_at"),
                "formatted_time": format_timestamp(e.get("created_at", 0)),
                "time_left": format_time_remaining(e.get("expires_at", 0)),
                "expires_at": e.get("expires_at"),
            })

        return jsonify({
            "success": True,
            "entries": formatted_entries,
            "total_count": len(formatted_entries),
            "sync_status": sync_status,
            "server_time": int(time.time() * 1000),
        })

    @app.route("/api/clipboard/<entry_id>", methods=["GET"])
    @login_required
    def get_clipboard_entry(entry_id: str):
        """Get a single clipboard entry's full details (for inspection modal)."""
        user = AuthService.get_current_user()
        entry = ClipboardService.get_entry(user["uid"], entry_id)
        if not entry:
            return jsonify({"error": "Entry not found or access denied"}), 404
        return jsonify(entry)

    @app.route("/api/clipboard/<entry_id>/delete", methods=["POST"])
    @login_required
    def delete_clipboard_entry(entry_id: str):
        """Delete an individual entry belonging to the authenticated user."""
        verify_csrf()
        user = AuthService.get_current_user()
        deleted = ClipboardService.delete_entry(user["uid"], entry_id)
        if not deleted:
            return jsonify({"error": "Entry not found or unauthorized"}), 404
        return jsonify({"success": True, "id": entry_id})

    @app.route("/api/clipboard/bulk-delete", methods=["POST"])
    @login_required
    def bulk_delete_clipboard_entries():
        """Bulk delete multiple entries belonging to the authenticated user."""
        verify_csrf()
        user = AuthService.get_current_user()
        data = request.get_json(silent=True) or {}
        entry_ids = data.get("ids", [])

        if not isinstance(entry_ids, list) or not entry_ids:
            return jsonify({"error": "A non-empty list of 'ids' is required"}), 400

        # Maximum batch size limit to prevent resource abuse
        if len(entry_ids) > 500:
            return jsonify({"error": "Maximum bulk deletion batch size is 500 items"}), 400

        sanitized_ids = [str(eid).strip() for eid in entry_ids if eid and isinstance(eid, str)]
        if not sanitized_ids:
            return jsonify({"error": "No valid entry IDs provided"}), 400

        deleted_ids, failed_ids = ClipboardService.bulk_delete_entries(user["uid"], sanitized_ids)
        return jsonify({
            "success": True,
            "deleted_ids": deleted_ids,
            "failed_ids": failed_ids,
            "count": len(deleted_ids),
        })

    @app.route("/api/clipboard", methods=["POST"])
    @login_required
    def create_clipboard_entry():
        """Add an entry for the authenticated user (tested in local flow)."""
        verify_csrf()
        user = AuthService.get_current_user()
        data = request.get_json(silent=True) or request.form
        content = data.get("content")

        if not content or not isinstance(content, str) or not content.strip():
            return jsonify({"error": "Content is required"}), 400

        entry = ClipboardService.add_entry(user["uid"], content=content.strip())
        return jsonify({"success": True, "entry": entry}), 201

    # ------------------ Error Handlers ------------------

    @app.errorhandler(400)
    def bad_request_error(e):
        if request.is_json:
            return jsonify({"error": "Bad Request", "description": getattr(e, "description", "")}), 400
        return render_template("error.html", code=400, title="Bad Request", message=getattr(e, "description", "The request was invalid.")), 400

    @app.errorhandler(401)
    def unauthorized_error(e):
        if request.is_json:
            return jsonify({"error": "Unauthorized"}), 401
        return redirect(url_for("login"))

    @app.errorhandler(403)
    def forbidden_error(e):
        if request.is_json:
            return jsonify({"error": "Forbidden"}), 403
        return render_template("error.html", code=403, title="Forbidden", message="You do not have permission to perform this action."), 403

    @app.errorhandler(404)
    def not_found_error(e):
        if request.is_json:
            return jsonify({"error": "Not Found"}), 404
        return render_template("error.html", code=404, title="Page Not Found", message="The requested resource was not found."), 404

    @app.errorhandler(500)
    def internal_error(e):
        # Never log or expose raw exception details or user clipboard text in response
        if request.is_json:
            return jsonify({"error": "Internal Server Error"}), 500
        return render_template("error.html", code=500, title="Server Error", message="An unexpected error occurred. Please try again later."), 500

    # Start the desktop clipboard watcher in background if live and not already running
    if app.config.get("USE_SQLITE", False) and not app.config.get("TESTING", False):
        if not app.config.get("DEBUG", False) or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
            _start_embedded_watcher()

    return app


def _start_embedded_watcher():
    """Start desktop clipboard watcher in a daemon thread guarded by SingleInstanceLock."""
    def _worker():
        try:
            import desktop_watcher
            lock = desktop_watcher.SingleInstanceLock()
            if not lock.acquire():
                return
            watcher = desktop_watcher.ClipboardWatcher()
            watcher.start()
        except Exception:
            pass

    thread = threading.Thread(target=_worker, name="DesktopWatcherDaemon", daemon=True)
    thread.start()


if __name__ == "__main__":
    application = create_app()
    application.run(host="127.0.0.1", port=5000, debug=True)
