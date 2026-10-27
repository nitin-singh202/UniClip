# UniClip — Web Dashboard

The web dashboard is the companion browser interface for **UniClip**, allowing users to view, search, inspect, copy, and delete their synchronized clipboard entries.

---

## 1. Prerequisites

- Python 3.10+ (tested with Python 3.11)
- Modern web browser (Chrome, Edge, Firefox, or Safari) with JavaScript enabled

---

## 2. Setup & Installation

### Step A: Navigate to the `web` directory
```bash
cd C:\Users\Nitin\Documents\Universal-Clipboard\web
```

### Step B: Create & activate a virtual environment (optional but recommended)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### Step C: Install dependencies
```bash
pip install -r requirements.txt
```

### Step D: Configure environment
Copy `.env.example` to `.env`:
```powershell
Copy-Item .env.example .env
```
Key configuration settings in `.env`:
- `SECRET_KEY`: Random string for signing session cookies.
- `DEV_MOCK_AUTH`: Set to `true` to enable fast local test sign-in without external Firebase authentication. Set to `false` for live Google Sign-In.

---

## 3. Running the Dashboard Locally

Start the Flask development server:
```powershell
# From the Universal-Clipboard workspace root:
python -m web.app
```
Or with Flask CLI:
```powershell
$env:FLASK_APP="web.app:create_app"
flask run --port=5000
```
Open your browser at:
`http://127.0.0.1:5000`

---

## 4. Running Automated Tests

Run the complete test suite with `pytest`:
```powershell
pytest web/tests -v
```

All 14 test cases covering authentication, user isolation, 7-day retention, XSS protection, CSRF validation, and error handling will execute.

---

## 5. Live Firebase Configuration

When ready to connect to live Google Sign-In and Cloud Firestore:
1. Ensure **Google Sign-In** is enabled in the [Firebase Console](https://console.firebase.google.com/) for project `universal-clipboard-ai`.
2. Deploy the restrictive Firestore Security Rules from `docs/SECURITY.md`.
3. Set `DEV_MOCK_AUTH=false` in `web/.env`.
