import time
import pyperclip
import requests
import json

# 🔗 Your Firebase Realtime Database URL (no trailing slash)
FIREBASE_DB_URL = "https://universal-clipboard-22603-default-rtdb.firebaseio.com/"

# Path where we'll store the latest clipboard text
CLIPBOARD_PATH = "/clipboard/latest.json"  # .json is required for REST API

def update_clipboard_in_firebase(text: str):
    """Send clipboard text to Firebase."""
    url = FIREBASE_DB_URL + CLIPBOARD_PATH
    data = {
        "text": text,
        "timestamp": int(time.time() * 1000)
    }
    try:
        response = requests.put(url, data=json.dumps(data))
        if response.status_code == 200:
            print(f"[OK] Updated Firebase clipboard: {text[:50]!r}")
        else:
            print(f"[ERR] Firebase responded with {response.status_code}: {response.text}")
    except Exception as e:
        print(f"[ERR] Failed to update Firebase: {e}")

def main():
    print("📋 Clipboard watcher started. Copy any text on your PC...")
    last_text = None

    while True:
        try:
            current_text = pyperclip.paste()
        except Exception as e:
            print(f"[ERR] Could not read clipboard: {e}")
            current_text = None

        # Only send if it's non-empty and changed
        if current_text and current_text != last_text:
            print(f"[INFO] Detected new clipboard text: {current_text[:50]!r}")
            update_clipboard_in_firebase(current_text)
            last_text = current_text

        time.sleep(0.7)  # Check ~every 700 ms

if __name__ == "__main__":
    main()
