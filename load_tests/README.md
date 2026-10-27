# 🚀 UniClip — Scalability & Load Testing Suite

This directory contains the automated, repeatable load-testing suite for **UniClip**, built with [Locust](https://locust.io/), a high-performance open-source Python load testing framework.

---

## 📋 Table of Contents
1. [Objectives & Budget Guarantees (₹0 Budget)](#1-objectives--budget-guarantees-0-budget)
2. [Virtual Users vs. Raw Requests vs. Real Customers](#2-virtual-users-vs-raw-requests-vs-real-customers)
3. [Endpoints Selected for Testing](#3-endpoints-selected-for-testing)
4. [Architecture & Safety Controls](#4-architecture--safety-controls)
5. [Prerequisites & Setup](#5-prerequisites--setup)
6. [Gradual Test Progression Plan](#6-gradual-test-progression-plan)
7. [Step-by-Step Execution Guide](#7-step-by-step-execution-guide)
8. [Identifying Performance Bottlenecks](#8-identifying-performance-bottlenecks)
9. [Portfolio Report Template](#9-portfolio-report-template)

---

## 1. Objectives & Budget Guarantees (₹0 Budget)

### Objective
Measure the concurrency and throughput limits of UniClip up to **1,000 concurrent simulated users** (with optional stretch goals of 2,500, 5,000, and 10,000 users), gathering verifiable, evidence-based metrics for system design and engineering portfolio presentation.

### Budget: Strictly ₹0
- **100% Free & Open-Source**: Uses Locust and Python running entirely on your local machine.
- **Zero Firebase Quota Exhaustion**: Tests authenticate using UniClip's built-in `DEV_MOCK_AUTH=true` system. Requests are served against local SQLite or in-memory stores, eliminating external Google Cloud Identity Toolkit or Cloud Firestore billing risks.
- **Safety Guard for Cloud URLs**: If `TARGET_URL` points to a remote domain (such as Render or Firebase), the test suite requires an explicit confirmation variable `CONFIRM_REMOTE_LOAD_TEST=yes` to prevent accidental resource exhaustion.

---

## 2. Virtual Users vs. Raw Requests vs. Real Customers

When presenting scalability metrics in an engineering portfolio, distinguishing between these three concepts is essential for technical credibility:

| Concept | Definition | Example in UniClip |
| :--- | :--- | :--- |
| **Virtual User (VU)** | A stateful simulated client that maintains a session cookie, pauses between actions (think time), and executes a sequence of tasks. | 1,000 users waiting 1 to 4 seconds between actions generate ~250 to 500 requests per second (RPS). |
| **Simultaneous Requests** | The exact number of HTTP connections actively being processed by the web server at the exact same millisecond. | 1,000 *simultaneous* zero-wait requests represents a DDoS-style burst, requiring a multi-worker asynchronous architecture. |
| **Real Daily Customers** | The total user base using the service throughout a day. | Because humans interact intermittently, a system that sustains 1,000 concurrent virtual users can easily support **10,000 to 50,000 active daily users**. |

---

## 3. Endpoints Selected for Testing

Every endpoint in this test suite corresponds to actual routes in `web/app.py`:

| Endpoint | Method | Weight | Description |
| :--- | :---: | :---: | :--- |
| `/api/auth/session` | `POST` | Setup | Validates synthetic mock token and establishes session cookie without external API calls. |
| `/dashboard` | `GET` | Setup / 2 | Loads HTML shell, tests template rendering, and extracts session CSRF token. |
| `/api/clipboard/entries` | `GET` | **6** (Primary) | High-frequency polling endpoint simulating frontend live sync (`startLiveSync()`). |
| `/api/clipboard` | `POST` | 3 | Mutates clipboard with synthetic text/URL payload, requiring valid CSRF header. |
| `/api/clipboard/<id>` | `GET` | 2 | Detailed entry inspection modal fetch. |
| `/api/clipboard/entries?q=...` | `GET` | 2 | Search query execution and in-memory filtering. |
| `/api/clipboard/<id>/delete` | `POST` | 1 | Single item deletion with CSRF validation. |
| `/api/auth/guest-session` | `POST` | Guest | Guest mode initialization for local-only device testing. |

---

## 4. Architecture & Safety Controls
   - In load-test mode, the server operates exclusively on a dedicated test database: `clipboard_load_test.db`.
   - The user's production/development database (`clipboard_local.db`) is never touched.
2. **Fail-Closed Firestore Guard**:
   - `FirestoreService.is_available()` returns `False`.
   - `FirestoreService.get_client()` returns `None`.
   - If any code attempts to write (`sync_entry`) or delete (`delete_entry`, `bulk_delete_entries`) to Firestore in load-test mode, an explicit `RuntimeError` is raised immediately.
   - At startup, `Config.validate()` refuses to start if `LOAD_TEST_MODE` is paired with `FLASK_ENV=production`, if `FIREBASE_SERVICE_ACCOUNT_KEY` is loaded, or if `clipboard_local.db` is selected.
3. **Dedicated Mock Authentication**:
   - Virtual users generate unique synthetic tokens (`sim_<uuid>`).
   - Sessions are isolated with their own session cookies, and synthetic data is partitioned per user.
4. **Synthetic Data Only**:
   - No real names, emails, credentials, or personal clipboard data are used.
   - Synthetic text templates mimic typical developer notes, URLs, and commands.
5. **Safe Automated Teardown**:
   - When a virtual user exits (`on_stop`), synthetic entries created by that user are pruned via `/api/clipboard/bulk-delete` from `clipboard_load_test.db` only.
   - Real data in Cloud Firestore or `clipboard_local.db` is completely unaffected.

---

## 5. Prerequisites & Setup

### 1. Ensure Dependencies Are Installed
Locust is installed in your Python environment:
```cmd
pip install -r load_tests/requirements.txt
```

### 2. Verify Load Test Unit Tests
Ensure the Locust suite logic, isolation, and fail-closed guards are validated:
```cmd
python -m pytest load_tests/test_locustfile.py
```

---

## 6. Gradual Test Progression Plan

Never jump directly to 1,000 concurrent users on a local machine. Follow this staged progression:

```
[Stage 1: 10 Users]  -->  [Stage 2: 100 Users]  -->  [Stage 3: 500 Users]  -->  [Stage 4: 1,000 Users]
    Smoke Test                Baseline                   Moderate Load               Primary Target
```

| Stage | Target Concurrency | Spawn Rate (users/s) | Duration | Primary Focus |
| :---: | :---: | :---: | :---: | :--- |
| **1. Smoke Test** | **10** | 2 | 1 min | Verify authentication, CSRF extraction, and 0% errors. |
| **2. Baseline** | **100** | 10 | 3 mins | Establish baseline p50 and p95 latency under normal load. |
| **3. Moderate Load** | **500** | 25 | 5 mins | Observe system responsiveness and memory stability. |
| **4. Target Concurrency** | **1,000** | 50 | 5 mins | Stress test concurrency limit, measuring throughput and p99. |
| **5. Stretch Goals** | **2,500 – 10,000** | 100 | 5 mins | Optional: Requires multi-worker WSGI server (see Section 8). |

---

## 7. Step-by-Step Execution Guide (Windows CMD)

### Step 1: Start UniClip in Safe Load-Test Mode

Open **Terminal 1** (`cmd.exe`) in `C:\Users\Nitin\Documents\Universal-Clipboard`:

```cmd
python run.py load-test
```
*(Alternative equivalent: `set LOAD_TEST_MODE=1 && python app.py`)*

#### Confirm Safe Startup Banner
Verify that the console displays the safety banner:
```
============================================================
  LOAD_TEST_MODE IS ACTIVE: Isolated test database and mock auth enabled
  DATABASE:  C:\Users\Nitin\Documents\Universal-Clipboard\clipboard_load_test.db
  FIRESTORE: STRICTLY DISABLED (Fail-closed guard active)
============================================================
```
If this banner is present, Firestore writes are physically impossible.

---

### Step 2: Running with Locust Web UI (Interactive & Visual)

Open **Terminal 2** (`cmd.exe`):
```cmd
locust -f load_tests/locustfile.py --host=http://127.0.0.1:5000
```
1. Open your browser at **`http://localhost:8089`**.
2. Enter:
   - **Number of users**: `10` (for Stage 1)
   - **Ramp-up rate**: `2` users/second
   - **Host**: `http://127.0.0.1:5000`
3. Click **Start Swarming**.
4. Observe real-time charts for RPS, Failures, and Latency percentiles (50th, 95th, 99th).

---

### Step 3: Running Headless (Command Line with HTML/CSV Report Export)

To run automated, headless tests and generate portfolio-ready reports:

#### Stage 1: Smoke Test (10 Users)
```cmd
locust -f load_tests/locustfile.py --headless -u 10 -r 2 --run-time 1m --host=http://127.0.0.1:5000 --html load_tests/report_10_users.html --csv load_tests/stats_10_users
```

#### Stage 2: Baseline (100 Users)
```cmd
locust -f load_tests/locustfile.py --headless -u 100 -r 10 --run-time 3m --host=http://127.0.0.1:5000 --html load_tests/report_100_users.html --csv load_tests/stats_100_users
```

#### Stage 3: Moderate Load (500 Users)
```cmd
locust -f load_tests/locustfile.py --headless -u 500 -r 25 --run-time 5m --host=http://127.0.0.1:5000 --html load_tests/report_500_users.html --csv load_tests/stats_500_users
```

#### Stage 4: Primary Target (1,000 Users)
```cmd
locust -f load_tests/locustfile.py --headless -u 1000 -r 50 --run-time 5m --host=http://127.0.0.1:5000 --html load_tests/report_1000_users.html --csv load_tests/stats_1000_users
```

---

## 8. Identifying Performance Bottlenecks

If response times rise or errors appear at higher concurrency, use this guide to identify the exact constraint:

### 1. Flask Development Server vs. Production WSGI Server
- **The Issue**: `python app.py` runs Flask's built-in Werkzeug development server. By default, it is single-process and limited in concurrent thread handling on Windows.
- **The Solution**: For 500+ and 1,000+ users, run UniClip with a multi-threaded production WSGI server such as **Waitress** (Windows-native) or **Gunicorn** (Linux):
  ```powershell
  pip install waitress
  waitress-serve --listen=127.0.0.1:5000 --threads=16 web.app:create_app
  ```

### 2. SQLite Database Concurrency
- **The Issue**: SQLite locks the database file during write operations (`INSERT`, `DELETE`). Under hundreds of concurrent writes, requests may experience `database is locked` timeouts.
- **The Solution**: UniClip utilizes SQLite's Write-Ahead Logging (WAL) mode (`PRAGMA journal_mode=WAL`), allowing concurrent readers without blocking writers.

### 3. Local Machine Resource Limits
- Monitor Windows Task Manager (Ctrl + Shift + Esc):
  - **CPU Usage**: If CPU hits 100%, the bottleneck is local compute capacity (both server and Locust running on the same laptop).
  - **RAM Usage**: Verify memory consumption remains stable without leaks.

---

## 9. Portfolio Report Template

When documenting your scalability results for a portfolio or technical writeup, use this format:

### Test Environment
- **Hardware**: Windows 11, Intel/AMD Multi-core, 16 GB RAM
- **Server Stack**: Python 3.11, Flask 3.1, SQLite WAL / Waitress WSGI
- **Load Tool**: Locust 2.47 (Local, Headless)

### Results Summary Table

| Metric | Stage 1 (10 VUs) | Stage 2 (100 VUs) | Stage 3 (500 VUs) | Stage 4 (1,000 VUs) |
| :--- | :---: | :---: | :---: | :---: |
| **Duration** | 1 min | 3 mins | 5 mins | 5 mins |
| **Requests / Second (RPS)** | *(fill)* | *(fill)* | *(fill)* | *(fill)* |
| **Total Requests** | *(fill)* | *(fill)* | *(fill)* | *(fill)* |
| **Failure Rate (%)** | 0.0% | *(fill)* | *(fill)* | *(fill)* |
| **p50 Latency (ms)** | *(fill)* | *(fill)* | *(fill)* | *(fill)* |
| **p95 Latency (ms)** | *(fill)* | *(fill)* | *(fill)* | *(fill)* |
| **p99 Latency (ms)** | *(fill)* | *(fill)* | *(fill)* | *(fill)* |
| **Server CPU / RAM** | *(fill)* | *(fill)* | *(fill)* | *(fill)* |

### Key Observations
- *At what concurrency level did p95 latency remain under 200ms?*
- *Did polling or write mutations constitute the dominant load?*
- *How did SQLite WAL mode perform compared to in-memory caching?*
