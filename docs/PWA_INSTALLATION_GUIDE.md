# UniClip — Progressive Web App (PWA) Guide

**App Name:** UniClip  
**Short Name:** UniClip  
**Display Mode:** `standalone` (fullscreen app-like window without browser address bar)  
**Theme & Background:** `#0b0f17` (Dark Slate)  
**Scope & Start URL:** Scope `/`, Start URL `/dashboard`  
**Icons:** 192×192, 512×512, plus Android maskable adaptive icons

---

## 1. How to Test and Run Locally

### A. Start the Local Flask Server
From the project root:
```powershell
python run.py web
# Or alternatively:
python -m web.app
```
The application will boot at `http://127.0.0.1:5000`.

### B. Testing PWA on Desktop Chrome / Edge
1. Open Chrome or Edge and navigate to `http://127.0.0.1:5000`.
2. Open DevTools (F12) -> **Application** tab.
3. Under **Application -> Manifest**, verify:
   - Name: `UniClip`
   - Short name: `UniClip`
   - Start URL: `/dashboard`
   - Theme color: `#0b0f17`
   - Icons: All 4 icons render cleanly without 404s.
4. Under **Application -> Service Workers**:
   - Status: Activated and running (`/sw.js`).
5. An **Install App** icon will appear in the Chrome address bar, or in the sidebar menu.

---

## 2. Installing on Android Phone (Chrome)

### Why Android Chrome Requires HTTPS (or USB Port Forwarding)
Google Chrome on Android strictly enforces that PWAs can only be installed from a **secure origin (HTTPS)**, with an exception for `localhost`.

You have two zero-cost methods to run and install it on your physical Android phone:

### Option 1: Chrome USB Port Forwarding (Free & Instant Local Testing)
Because your phone is connected via USB:
1. Ensure your phone has USB debugging enabled (already verified: `RMX3782` / `MFJVE6HMVSRKIN9D`).
2. Open Chrome on your Windows PC and navigate to:
   `chrome://inspect/#devices`
3. Click **Port forwarding...**:
   - Port: `5000`
   - IP address and port: `localhost:5000`
   - Check **Enable port forwarding** and click **Done**.
4. On your Android phone, open Chrome and type:
   `http://localhost:5000`
5. Chrome treats `localhost` as a secure origin!
6. Tap the **⋮ (three dots menu)** in Android Chrome and select **Add to Home screen** or **Install app**.
7. The app icon will be added to your Android app drawer and home screen. When launched, it opens in a standalone window with its own splash screen and no browser URL bar!

---

### Option 2: Free HTTPS Hosting (Zero-Cost Production Setup)

Since UniClip is built with Python Flask + Cloud Firestore, it requires a Python execution environment (it cannot be hosted on static-only hosting like raw Firebase Hosting without a Cloud Function or Cloud Run container).

#### Recommended Zero-Cost Hosting Platforms:
1. **Render.com (Free Web Service Tier)**:
   - 100% Free tier for Python web services.
   - Automatically provides a free custom HTTPS domain (e.g. `https://universal-clipboard-ai.onrender.com`).
   - Setup: Connect your GitHub repository, choose Python environment, build command `pip install -r requirements.txt`, start command `gunicorn web.app:application`.
2. **Google Cloud Run (Free Tier)**:
   - Free tier includes 2 million requests/month and 360,000 vCPU-seconds/month.
   - Built-in HTTPS with automatic TLS certificates.
3. **Cloudflare Tunnel (Zero-Trust Free)**:
   - Exposes your local Flask development server securely to the internet over HTTPS (e.g. `cloudflared tunnel`) without port forwarding or costs.

#### Critical: Firebase Authentication Authorized Domains
Whenever you deploy to an HTTPS domain (e.g., `universal-clipboard-ai.onrender.com`):
1. Go to the [Firebase Console](https://console.firebase.google.com/) -> Project `universal-clipboard-ai`.
2. Navigate to **Authentication -> Settings -> Authorized Domains**.
3. Click **Add domain** and enter your deployed hostname (e.g., `universal-clipboard-ai.onrender.com`).
4. This ensures Google Sign-In popups succeed on mobile without origin mismatch errors.

---

## 3. Privacy & Security Constraints Enforced

1. **Zero Credential / Clipboard Caching**:
   - The Service Worker (`/sw.js`) **strictly intercepts and excludes** all `/api/*` endpoints from Cache Storage.
   - Authenticated HTML responses (`/dashboard`, `/settings`) are strictly **Network-First** and never saved to persistent browser caches.
   - Only non-sensitive visual assets (`style.css`, `app.js`, manifest, icons) and the safe `/offline` shell are cached.
2. **Offline Fallback**:
   - If the mobile device loses network connection while navigating, the service worker renders `/offline` explaining that clipboard synchronization requires internet connectivity.
   - Automatically reloads the moment connectivity is restored.
3. **Mobile-First Touch Architecture**:
   - Touch targets are expanded to at least 40-44px.
   - Long text wraps safely (`word-break: break-word; overflow-wrap: anywhere;`).
   - Tapping an entry opens the detailed inspection modal with a one-tap copy button.
   - Mobile selection banner allows individual check, **Select All**, **Deselect All**, and bulk deletion with confirmation.
