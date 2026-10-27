import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from web directory or parent workspace root
BASE_DIR = Path(__file__).resolve().parent
if (BASE_DIR / ".env").exists():
    load_dotenv(BASE_DIR / ".env", override=False)
if (BASE_DIR.parent / ".env").exists():
    load_dotenv(BASE_DIR.parent / ".env", override=False)


def find_service_account_key() -> str:
    """Discover Firebase Admin service account key from env or workspace."""
    env_path = os.environ.get("FIREBASE_SERVICE_ACCOUNT_KEY")
    if env_path and Path(env_path).exists():
        return str(Path(env_path).resolve())
    candidates = [
        BASE_DIR.parent / "universal-clipboard-ai-firebase-adminsdk-fbsvc-f84e2f7c5d.json",
        BASE_DIR.parent / "serviceAccountKey.json",
        BASE_DIR / "serviceAccountKey.json",
    ]
    for c in candidates:
        if c.exists():
            return str(c.resolve())
    for f in BASE_DIR.parent.glob("*adminsdk*.json"):
        if f.is_file():
            return str(f.resolve())
    return ""


class Config:
    """Base application configuration."""
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-key-change-in-production")
    FLASK_ENV = os.environ.get("FLASK_ENV", "development")
    DEBUG = os.environ.get("FLASK_DEBUG", "1").lower() in ("1", "true", "yes")

    # Session security settings
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0").lower() in ("1", "true", "yes")
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 7  # 7 days

    # Firebase Public Web Configuration (matches universal-clipboard-ai)
    FIREBASE_API_KEY = os.environ.get("FIREBASE_API_KEY", "")
    FIREBASE_AUTH_DOMAIN = os.environ.get("FIREBASE_AUTH_DOMAIN", "universal-clipboard-ai.firebaseapp.com")
    FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "universal-clipboard-ai")
    FIREBASE_STORAGE_BUCKET = os.environ.get("FIREBASE_STORAGE_BUCKET", "universal-clipboard-ai.firebasestorage.app")
    FIREBASE_MESSAGING_SENDER_ID = os.environ.get("FIREBASE_MESSAGING_SENDER_ID", "849873882554")
    FIREBASE_APP_ID = os.environ.get("FIREBASE_APP_ID", "1:849873882554:web:universal_clipboard_web")

    # Service Account for server-side Firebase Admin (Cloud Firestore)
    FIREBASE_SERVICE_ACCOUNT_KEY = find_service_account_key()

    # Retention configuration
    CLIPBOARD_RETENTION_DAYS = 7

    # Load testing mode flag (strictly isolated local testing)
    LOAD_TEST_MODE = os.environ.get("LOAD_TEST_MODE", "0").lower() in ("1", "true", "yes")

    # Local SQLite integration
    USE_SQLITE = True
    if LOAD_TEST_MODE:
        DEV_MOCK_AUTH = True
        DISABLE_FIRESTORE = True
        FIREBASE_SERVICE_ACCOUNT_KEY = ""
        SQLITE_DB_PATH = Path(os.environ.get("SQLITE_DB_PATH", str(BASE_DIR.parent / "clipboard_load_test.db"))).resolve()
    else:
        DISABLE_FIRESTORE = os.environ.get("DISABLE_FIRESTORE", "0").lower() in ("1", "true", "yes")
        DEV_MOCK_AUTH = os.environ.get("DEV_MOCK_AUTH", "1" if os.environ.get("FLASK_ENV", "development") == "development" else "0").lower() in ("1", "true", "yes")
        SQLITE_DB_PATH = Path(os.environ.get("SQLITE_DB_PATH", str(BASE_DIR.parent / "clipboard_local.db"))).resolve()

    @classmethod
    def get_firebase_client_config(cls) -> dict:
        """Return the public Firebase configuration needed by the browser SDK."""
        return {
            "apiKey": cls.FIREBASE_API_KEY,
            "authDomain": cls.FIREBASE_AUTH_DOMAIN,
            "projectId": cls.FIREBASE_PROJECT_ID,
            "storageBucket": cls.FIREBASE_STORAGE_BUCKET,
            "messagingSenderId": cls.FIREBASE_MESSAGING_SENDER_ID,
            "appId": cls.FIREBASE_APP_ID,
        }

    @classmethod
    def validate(cls) -> None:
        """Validate critical configuration settings and security constraints."""
        env_lower = (cls.FLASK_ENV or "").lower()

        # Fail-closed guard for Load-Test Mode:
        if getattr(cls, "LOAD_TEST_MODE", False):
            if env_lower == "production":
                raise ValueError("Fail-closed guard: LOAD_TEST_MODE cannot be enabled in production.")
            if getattr(cls, "FIREBASE_SERVICE_ACCOUNT_KEY", ""):
                raise ValueError(
                    "Fail-closed guard: LOAD_TEST_MODE is enabled but FIREBASE_SERVICE_ACCOUNT_KEY "
                    "is populated. Refusing to start to protect live cloud data."
                )
            if not getattr(cls, "DISABLE_FIRESTORE", False):
                raise ValueError(
                    "Fail-closed guard: LOAD_TEST_MODE requires DISABLE_FIRESTORE=True. Refusing to start."
                )
            if not getattr(cls, "USE_SQLITE", False):
                raise ValueError(
                    "Fail-closed guard: LOAD_TEST_MODE requires USE_SQLITE=True with isolated test DB."
                )
            db_str = str(getattr(cls, "SQLITE_DB_PATH", "")).lower()
            if not db_str or "clipboard_local.db" in db_str:
                raise ValueError(
                    "Fail-closed guard: LOAD_TEST_MODE cannot use the production clipboard_local.db database."
                )

        if env_lower == "production":
            if not cls.SECRET_KEY or cls.SECRET_KEY == "dev-insecure-key-change-in-production":
                raise ValueError("Insecure or missing SECRET_KEY: A secure SECRET_KEY must be set in production.")
            if cls.DEV_MOCK_AUTH:
                raise ValueError("DEV_MOCK_AUTH cannot be enabled in production.")
            if not cls.FIREBASE_API_KEY:
                raise ValueError("FIREBASE_API_KEY must be configured for production.")


class LoadTestConfig(Config):
    """Explicit configuration class for local scalability and load testing."""
    LOAD_TEST_MODE = True
    TESTING = False
    DEBUG = False
    DEV_MOCK_AUTH = True
    DISABLE_FIRESTORE = True
    FIREBASE_SERVICE_ACCOUNT_KEY = ""
    USE_SQLITE = True
    SQLITE_DB_PATH = (BASE_DIR.parent / "clipboard_load_test.db").resolve()


class TestConfig(Config):
    """Configuration used for automated testing."""
    TESTING = True
    DEBUG = False
    SECRET_KEY = "test-secret-key-testing-only"
    DEV_MOCK_AUTH = True
    WTF_CSRF_ENABLED = True
    USE_SQLITE = False

