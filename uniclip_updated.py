import time
import pyperclip
import requests
import json

FIREBASE_DB_URL = "https://universal-clipboard-22603-default-rtdb.firebaseio.com"

LATEST_PATH = "/clipboard/latest.json"
HISTORY_PATH = "/clipboard/history.json"

def update_latest(text: str):
    """Update latest clipboard text"""
    url = FIREBASE_DB_URL + LATEST_PATH
    data = {
        "text": text,
        "timestamp": int(time.time() * 1000)
    }
    requests.put(url, json=data)

def add_to_history(text: str):
    """Append clipboard text to history"""
    url = FIREBASE_DB_URL + HISTORY_PATH
    data = {
        "text": text,
        "timestamp": int(time.time() * 1000)
    }
    requests.post(url, json=data)  # POST creates unique key

def main():
    print("📋 Clipboard watcher started (with history)...")
    last_text = None

    while True:
        try:
            current_text = pyperclip.paste()
        except Exception as e:
            print(f"[ERR] Clipboard read failed: {e}")
            current_text = None

        if current_text and current_text != last_text:
            print(f"[INFO] New clipboard text detected: {current_text[:50]!r}")

            update_latest(current_text)
            add_to_history(current_text)

            print("[OK] Saved to Firebase (latest + history)")
            last_text = current_text

        time.sleep(0.7)

if __name__ == "__main__":
    main()
