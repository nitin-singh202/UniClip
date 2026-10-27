"""
UniClip - Root Entrypoint Forwarder
Enables running `python app.py` directly from workspace root.
"""
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from web.app import create_app

if __name__ == "__main__":
    app = create_app()
    print("=" * 60)
    print("Starting UniClip...")
    print("URL: http://127.0.0.1:5000")
    print("=" * 60)
    app.run(host="127.0.0.1", port=5000, debug=True)
