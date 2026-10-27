"""
UniClip - Root Entrypoint Forwarder
Enables running `python app.py` directly from workspace root.
"""
import sys
from pathlib import Path

import os
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from web.app import create_app
from web.config import Config, LoadTestConfig

is_load_test = os.environ.get("LOAD_TEST_MODE", "0").lower() in ("1", "true", "yes")
config_cls = LoadTestConfig if is_load_test else Config
app = application = create_app(config_cls)

if __name__ == "__main__":
    print("=" * 60)
    if is_load_test:
        print("Starting UniClip in LOAD-TEST MODE (Local Isolated SQLite)...")
        print("Database: clipboard_load_test.db")
        print("Firestore: STRICTLY DISABLED (Fail-closed)")
        print("Mock Auth: ACTIVE")
    else:
        print("Starting UniClip...")
    print("URL: http://127.0.0.1:5000")
    print("=" * 60)
    app.run(host="127.0.0.1", port=5000, debug=True)
