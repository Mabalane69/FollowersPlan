"""
==============================================================================
FollowersPlan — Central Configuration & API Keys
==============================================================================
Add your real Firebase and Instagram credentials, API tokens, and webhooks below.
Follow the commented format: KEY = "add your token here"
==============================================================================
"""

import os

# ==============================================================================
# 1. FIREBASE CONFIGURATION (PRIMARY CLOUD DATABASE)
# ==============================================================================
# Download your service account key from:
# Firebase Console -> Project Settings -> Service Accounts -> Generate New Private Key
# Place the downloaded .json file in this project folder and specify its path below.
FIREBASE_SERVICE_ACCOUNT_KEY_PATH = os.getenv(
    'FIREBASE_SERVICE_ACCOUNT_KEY_PATH', 
    "add path to your serviceAccountKey.json here"
)

# Firebase Project ID (found in Firebase Project Settings)
FIREBASE_PROJECT_ID = os.getenv('FIREBASE_PROJECT_ID', "add your project id here")

# Firebase Realtime Database URL (optional, if using Realtime Database)
FIREBASE_DATABASE_URL = os.getenv('FIREBASE_DATABASE_URL', "add your firebase database url here")

# Firebase Web Client SDK Configuration (for browser-side sync)
FIREBASE_API_KEY = os.getenv('FIREBASE_API_KEY', "add your firebase api key here")
FIREBASE_AUTH_DOMAIN = os.getenv('FIREBASE_AUTH_DOMAIN', "add your auth domain here")
FIREBASE_STORAGE_BUCKET = os.getenv('FIREBASE_STORAGE_BUCKET', "add your storage bucket here")
FIREBASE_MESSAGING_SENDER_ID = os.getenv('FIREBASE_MESSAGING_SENDER_ID', "add your sender id here")
FIREBASE_APP_ID = os.getenv('FIREBASE_APP_ID', "add your app id here")


# ==============================================================================
# 2. LIVE INSTAGRAM ACCOUNT CREDENTIALS & TOKENS
# ==============================================================================
# OPTION A (RECOMMENDED & 100% BAN-PROOF): Browser sessionid cookie.
# How to get it:
# 1. Open https://www.instagram.com in your browser (Chrome/Edge/Safari).
# 2. Press F12 -> Application (or Storage) -> Cookies -> https://www.instagram.com.
# 3. Copy the value of the cookie named 'sessionid'.
# Example: INSTAGRAM_SESSION_ID = "6481920%3AKJ91823..."
INSTAGRAM_SESSION_ID = os.getenv('INSTAGRAM_SESSION_ID', "add your sessionid here")

# OPTION B: Direct Username & Password
# Used for direct API login if you prefer not to use sessionid.
# If Two-Factor Authentication (2FA) is enabled, enter code when prompted in the UI.
INSTAGRAM_USERNAME = os.getenv('INSTAGRAM_USERNAME', "add your instagram username here")
INSTAGRAM_PASSWORD = os.getenv('INSTAGRAM_PASSWORD', "add your instagram password here")


# ==============================================================================
# 3. META GRAPH API / INSTAGRAM BASIC DISPLAY API KEYS (OPTIONAL)
# ==============================================================================
# If using official Meta Developer Portal (https://developers.facebook.com):
META_APP_ID = os.getenv('META_APP_ID', "add your app id here")
META_APP_SECRET = os.getenv('META_APP_SECRET', "add your app secret here")
META_ACCESS_TOKEN = os.getenv('META_ACCESS_TOKEN', "add your token here")


# ==============================================================================
# 4. EXTERNAL NOTIFICATION ALERTS & WEBHOOKS (OPTIONAL)
# ==============================================================================
# Receive instant alerts whenever someone unfollows your live Instagram account!

# Discord Webhook:
# Server Settings -> Integrations -> Webhooks -> New Webhook -> Copy Webhook URL
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL', "add your discord webhook url here")

# Telegram Bot Alerts:
# Create a bot via @BotFather on Telegram to get your token, and get your Chat ID via @userinfobot
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', "add your telegram bot token here")
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', "add your telegram chat id here")


# ==============================================================================
# 5. PROXY CONFIGURATION (OPTIONAL FOR CLOUD HOSTING)
# ==============================================================================
# If running on cloud VPS (AWS, DigitalOcean, Heroku), use a residential proxy
# to prevent Instagram from challenging server data-center IP addresses.
# Formats: "http://user:pass@ip:port" or "socks5://user:pass@ip:port"
PROXY_URL = os.getenv('INSTAGRAM_PROXY', "add your proxy here (optional)")


# ==============================================================================
# 6. ANTI-BAN RATE LIMIT CONTROLS (SAFETY PACING)
# ==============================================================================
# Base delay in seconds between consecutive unfollow requests in bulk mode:
DEFAULT_UNFOLLOW_DELAY_SECONDS = float(os.getenv('DEFAULT_UNFOLLOW_DELAY_SECONDS', 6.0))

# Maximum accounts to unfollow in a single bulk session (Instagram limits: ~50-80/hour):
MAX_UNFOLLOWS_PER_BATCH = int(os.getenv('MAX_UNFOLLOWS_PER_BATCH', 40))

# Human jitter variance (+/- 25%):
JITTER_RATIO = 0.25


# ==============================================================================
# 7. SERVER & STORAGE CONFIGURATION
# ==============================================================================
HOST = os.getenv('HOST', '0.0.0.0')
PORT = int(os.getenv('PORT', 5000))
SECRET_KEY = os.getenv('SECRET_KEY', 'followersplan-secure-random-key')
DEBUG_MODE = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, 'instafollowers.db')
SESSIONS_DIR = os.path.join(BASE_DIR, 'sessions')
os.makedirs(SESSIONS_DIR, exist_ok=True)

DEFAULT_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'
)
INSTAGRAM_WEB_APP_ID = "936619743392459"
