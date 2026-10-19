# FollowersPlan — Live Multi-Client Instagram Follower & Unfollower Platform

A cross-platform (Web & PWA) application built with **Flask**, **Google Cloud Firebase Firestore**, and **Instagrapi**. FollowersPlan enables multiple clients and users to connect live Instagram accounts simultaneously, scan followers & following in real-time, identify profiles that do not follow back, execute rate-limited safe bulk unfollows with anti-ban human jitter, and generate weekly unfollower reports.

---

## 🏗️ Multi-Client Support Architecture & Structure

FollowersPlan is designed to serve **multiple concurrent clients** across different devices (desktops, iPhones, Android phones, tablets) without session leakage or data cross-talk.

```mermaid
flowchart TD
    subgraph Clients["Multi-Client Frontends (All Devices)"]
        ClientA["📱 Client A (iPhone PWA)<br/>Cookie: Session A<br/>Header: X-Account-Username: @brand_alpha"]
        ClientB["💻 Client B (Desktop Web)<br/>Cookie: Session B<br/>Header: X-Account-Username: @agency_beta"]
        ClientC["📱 Client C (Android)<br/>Cookie: Session C<br/>Header: X-Account-Username: @personal_charlie"]
    end

    subgraph Server["Flask Application Server (app.py)"]
        SessionMgr["Per-Client Session Isolation & Router<br/>(flask_session + X-Account-Username)"]
        AccountSwitcher["Multi-Account Controller<br/>GET /api/accounts<br/>POST /api/accounts/switch"]
        
        subgraph Workers["Independent Background Workers (instagram_service.py)"]
            WorkerA["Scan / Bulk Thread: @brand_alpha<br/>delay=6s + jitter"]
            WorkerB["Scan / Bulk Thread: @agency_beta<br/>delay=7s + jitter"]
            WorkerC["Scan / Bulk Thread: @personal_charlie<br/>delay=6s + jitter"]
        end
    end

    subgraph CloudStorage["Persistence Layer (Multi-Tenant Partitioned)"]
        Firestore[("🔥 Google Cloud Firebase Firestore<br/>accounts/{username}/relationships<br/>accounts/{username}/scans<br/>accounts/{username}/weekly_reports")]
        SQLiteMirror[("💾 Local Cache Mirror (database.py)<br/>WHERE account_id = ?")]
    end

    ClientA -->|Requests| SessionMgr
    ClientB -->|Requests| SessionMgr
    ClientC -->|Requests| SessionMgr

    SessionMgr --> AccountSwitcher
    SessionMgr --> Workers

    Workers -->|Live Sync| Firestore
    Workers -->|Local Mirror| SQLiteMirror
```

### 1. Strict Session Isolation (No Cross-Talk)
- **Cryptographic Flask Cookies**: Each browser/device receives an isolated, encrypted `flask_session` cookie signed by `SECRET_KEY`.
- **`X-Account-Username` Header & `apiFetch` Wrapper**: Every client request includes an explicit `X-Account-Username` header synchronized with `localStorage`, ensuring rock-solid isolation on mobile PWAs, WebViews, and desktop browsers.
- When **Client A** logs into `@brand_alpha`, **Client B** visiting from another computer or phone is unauthenticated and cannot view Client A's data.

### 2. Multi-Account Management & Switcher
- Agencies and social media managers managing multiple client profiles can connect multiple accounts within one dashboard.
- **Account Switcher Modal (`modal-account-switcher`)**:
  - Click your `@username` pill or **Switch Account** in the hero banner.
  - View all registered client profiles.
  - Switch active workspace with 1 click via `POST /api/accounts/switch`.
  - Add another client profile anytime via `+ Connect Another Account`.
  - Disconnect the active profile via `POST /api/auth/logout` without affecting other users.

### 3. Cloud Data Partitioning (Firebase Firestore)
Data in Google Cloud Firestore is structured hierarchically per Instagram username:
```text
accounts/
 └── {username}/
      ├── relationships/
      │    └── {target_username}  (follows_me, followed_by_me, is_whitelisted)
      ├── scans/
      │    └── {scan_id}          (snapshot metrics & timestamps)
      ├── weekly_reports/
      │    └── {report_id}        (lost followers & unfollow-back status)
      └── unfollow_logs/
           └── {log_id}           (action timestamp & status)
```
*(If Firebase credentials are not yet supplied, FollowersPlan automatically falls back to its local SQLite mirror partitioned by `account_id`).*

### 4. Concurrent Background Task Execution
- Background scans and bulk unfollow loops run in dedicated asynchronous daemon threads keyed by `account_id`.
- Multiple clients can run live scans or bulk unfollows simultaneously:
  - Client 1 can bulk unfollow with an 8-second delay on `@brand_alpha`.
  - Client 2 can scan `@agency_beta` at the same time without thread contention or blocking.

---

## 🌟 Key Features

### 🔄 Real-Time Live Profile Scanner
- Streams live follower and following lists from Instagram.
- Instant progress polling bar (`0% -> 100%`) with live counters.
- Computes four distinct relationship matrices:
  - **Not Following Back**: People you follow who do not follow you back.
  - **Mutual Friends**: Accounts that follow each other.
  - **Fans**: Accounts that follow you, but you don't follow back.
  - **Protected / Whitelisted**: Friends and family protected from bulk unfollows.

### 🛡️ Safe Anti-Ban Bulk Unfollow Engine
- **Randomized Human Jitter Delay**: Configurable 5–8 second delay with jitter (`DEFAULT_UNFOLLOW_DELAY_SECONDS = 6.0`, `JITTER_RATIO = 0.25`).
- **Batch Capping**: Automatically caps batch sizes to `MAX_UNFOLLOWS_PER_BATCH = 40` to comply with Instagram action safety limits.
- **Live Countdown Display & Controls**: Interactive **Pause**, **Resume**, and **Cancel** buttons anytime during bulk runs.

### 📅 Automated Weekly Lost Follower Reports
- Tracks changes across consecutive scans.
- Flags accounts that unfollowed you over time with timestamps.
- One-click **Unfollow Back** button next to each lost follower.
- CSV Export utility for offline audit logs.

### 📱 Installable PWA (Progressive Web App)
- Works natively across all devices: iOS Safari, Android Chrome, Windows, and macOS.
- Web App Manifest (`/manifest.json`) and Service Worker (`/sw.js`) for offline UI caching.

---

## ⚙️ Configuration & Key Placeholders

All credentials and API keys are centralized in [`config.py`](file:///c:/Users/maphane/Downloads/FollowersPlan/config.py) and [`.env.example`](file:///c:/Users/maphane/Downloads/FollowersPlan/.env.example) with clear placeholder syntax:

### 1. Google Cloud Firebase Keys (`config.py`)
```python
# Path to your Firebase service account private key JSON
FIREBASE_SERVICE_ACCOUNT_KEY_PATH = "add path to your serviceAccountKey.json here"

# Firebase Cloud Project Configuration
FIREBASE_PROJECT_ID        = "add your firebase project id here"
FIREBASE_DATABASE_URL      = "add your firebase database url here"
FIREBASE_STORAGE_BUCKET    = "add your firebase storage bucket here"

# Frontend Web Client SDK Settings
FIREBASE_API_KEY           = "add your firebase web api key here"
FIREBASE_AUTH_DOMAIN       = "add your auth domain here"
FIREBASE_MESSAGING_SENDER_ID = "add your messaging sender id here"
FIREBASE_APP_ID            = "add your firebase app id here"
```

### 2. Instagram Credentials (`config.py`)
```python
# Session Cookie Authentication (Safest & 100% Ban-Proof)
INSTAGRAM_SESSION_ID = "add your sessionid here"
INSTAGRAM_DS_USER_ID = "add your numeric instagram user id here" # Optional

# Direct Username / Password Authentication
INSTAGRAM_USERNAME   = "add your instagram username here"
INSTAGRAM_PASSWORD   = "add your instagram password here"

# Meta Graph API (Optional for Professional / Business accounts)
META_APP_ID          = "add your meta app id here"
META_APP_SECRET      = "add your meta app secret here"
META_ACCESS_TOKEN    = "add your meta graph user access token here"
```

### 3. Notification Webhooks & Proxies (`config.py`)
```python
# Webhooks alert you when an account unfollows you
DISCORD_WEBHOOK_URL  = "add your discord webhook url here"
TELEGRAM_BOT_TOKEN   = "add your telegram bot token here"
TELEGRAM_CHAT_ID     = "add your telegram chat id here"

# Proxy (Recommended for cloud datacenter deployments)
PROXY_URL            = "add your proxy here"  # e.g., "http://user:pass@host:port"
```

---

## 🚀 Quickstart Guide

### 1. Clone & Install Dependencies
```bash
git clone https://github.com/Mabalane69/FollowersPlan.git
cd FollowersPlan
pip install -r requirements.txt
```

### 2. Launch the Application
```bash
python app.py
```
Open **`http://localhost:5000`** in your browser (or `http://<your-ip>:5000` on mobile).

### 3. Connecting an Instagram Account
- **Option A (Safest & Recommended)**: Log in to Instagram on your desktop browser &rarr; Press `F12` &rarr; Application &rarr; Cookies &rarr; copy `sessionid` &rarr; Paste into the **Connect Live** modal.
- **Option B**: Log in directly with username and password (with 2FA verification support).
- **Option C**: Upload your official Instagram Data Export JSON files (`followers_1.json` and `following.json`) for 100% offline analysis.

---

## 🧪 Automated Test Suite

Run the comprehensive 15-point automated multi-client test suite:
```bash
python test_app.py
```

### Test Coverage:
1. Index HTML & zero mock data verification
2. PWA Manifest structure
3. Firebase configuration endpoint
4. Multi-Client initial unauthenticated isolation
5. Client A session login
6. Client B isolation (Client B unaffected by Client A)
7. Client B session login
8. Concurrent multi-client session persistence
9. Multi-account listing endpoint
10. Account switching workflow
11. Relationship filtering (Not following back, mutuals, fans)
12. Whitelist toggle protection
13. Weekly lost followers report generation
14. Anti-ban bulk unfollow queue orchestration
15. Isolated client logout (Client A logs out, Client B session remains intact)
