# FollowersPlan — Live Instagram Follower & Unfollower Suite

A modern, responsive, cross-platform platform designed to connect directly with live Instagram accounts, scan followers & following in real-time, identify users who don't follow back, perform single and safe rate-limited bulk unfollows, and generate weekly reports of people who unfollowed you.

---

## 🌟 Real-Live API Features & Dynamics

### 1. 🔄 Real-Time Streaming Scanner
- **Non-blocking Background Worker**: Scans large follower and following lists asynchronously without HTTP timeouts.
- **Dynamic Progress Banner**: Real-time progress bar (`0% -> 100%`) with live counters (`Following: 340`, `Followers: 280`, `Non-followers identified: 60`).
- **Relationship Matrix**: Checks everyone in your "Following" list, cross-references with "Followers", and detects who doesn't follow back.

### 2. 🔐 4-Step Live Connection System
- **Session ID Cookie Login (Safest & 100% Ban-Proof)**:
  Connects using your browser's existing authorized session cookie (`sessionid`). Instagram sees the requests originating from your already authenticated session without triggering suspicious login alerts or password changes.
- **Direct Login with 2FA Handling**: Standard username & password login with 2-Factor Authentication prompt.
- **Session Persistence (`sessions/`)**: Saves session dumps in `sessions/{username}_session.json` so you stay logged in even after computer restarts.
- **Live Health Monitoring**: Constant session health verification displaying a live status indicator (`🟢 Live API Active`).

### 3. 🛡️ Safe Bulk Unfollow Control Room
- **Randomized Human Jitter**: Configurable delay (default 6–8 seconds) between each unfollow action to stay within Instagram's rate limits.
- **Live Countdown Display**: Shows countdown timer between actions (`"Waiting 6s before next unfollow to protect account..."`).
- **Interactive Controls**: One-click **Pause**, **Resume**, and **Cancel** controls anytime.
- **Instant UI Updates**: When a profile is unfollowed, the profile card immediately updates to `"Unfollowed"`, the counter decrements, and your following count updates live.

### 4. 📅 Automated Weekly Unfollower Reports
- Compares previous scan snapshots against current scans.
- Detects users who previously followed you but have unfollowed since your last scan.
- Includes exact timestamps and an **Unfollow Back** button next to each lost follower.
- Export to CSV for historical tracking.

---

## 🚀 Step-by-Step Live Setup Guide

### Step 1: Start FollowersPlan
Double-click `start.bat` or run:
```bash
python app.py
```
Open **`http://localhost:5000`** in any browser (or `http://<your-ip>:5000` on your mobile phone / tablet).

### Step 2: Connect Your Real Instagram Account
1. Open [instagram.com](https://instagram.com) in Chrome, Edge, or Safari and make sure you are logged in.
2. Press `F12` (Developer Tools) &rarr; Go to **Application** (or **Storage**) &rarr; **Cookies** &rarr; `https://www.instagram.com`.
3. Locate the cookie named **`sessionid`** and copy its value.
4. In FollowersPlan, click **Connect Live**, paste the `sessionid`, and click **Connect Live Session**.

### Step 3: Run Live Profile Scan
- Click **Scan Profiles** in the top bar.
- Watch the live progress banner stream the scan in real-time as it pulls your live Following and Followers list and calculates non-followers.

### Step 4: Manage & Unfollow
- **Single Unfollow**: Click the red **Unfollow** button next to any non-follower.
- **Bulk Unfollow**: Click **Select All** (or select individual profiles), choose your safety delay, and click **Start Safe Unfollow**.
- **Protect Friends**: Click the shield icon next to friends or family to whitelist them from ever being unfollowed in bulk.
