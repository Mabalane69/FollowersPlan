"""
==============================================================================
FollowersPlan — Instagram Service Module (Live API Integration)
==============================================================================
This module encapsulates all communications with Instagram:
1. Live Session Management (sessionid cookie / login credentials)
2. Dual-Engine architecture (instagrapi Client + DirectInstagramWebClient)
3. Dynamic Non-Blocking Background Scanner for live Follower/Following lists
4. Single & Bulk Unfollow Execution with anti-ban rate limiting and human jitter
5. Snapshot comparison and weekly unfollower diff detection

>>> WHERE TO CUSTOMIZE:
- To configure proxies or custom rate limits, see `config.py`
- To add custom Instagram Graph API endpoints, see Section 2 & Section 3 below
- To customize live scanning batches or limits, see Section 4 below
==============================================================================
"""

import os
import json
import time
import random
import threading
import logging
import requests
from datetime import datetime, timedelta

# Import central configuration settings
import config
from firebase_service import FirebaseService

save_or_update_account = FirebaseService.save_or_update_account
record_scan_snapshot = FirebaseService.record_scan_snapshot
mark_unfollowed = FirebaseService.mark_unfollowed
get_account_by_username = FirebaseService.get_account_by_username

logger = logging.getLogger(__name__)

# Directory where persistent session files are stored on disk
SESSIONS_DIR = config.SESSIONS_DIR
os.makedirs(SESSIONS_DIR, exist_ok=True)

# In-memory registry of active authenticated clients: {username: instagrapi.Client}
active_clients = {}

# Active background scan jobs: {account_id: dict with progress and status}
scan_jobs = {}

# Active bulk unfollow tasks: {account_id: dict with status, counters, delay}
bulk_tasks = {}

def get_session_file(username):
    """
    Returns the absolute path to the saved session file for a given username.
    This file persists login tokens across application restarts.
    """
    safe_name = "".join([c for c in username if c.isalnum() or c in ('_', '.')])
    return os.path.join(SESSIONS_DIR, f"{safe_name}_session.json")


# ==============================================================================
# SECTION 1: DIRECT INSTAGRAM WEB REST API CLIENT (FALLBACK ENGINE)
# ==============================================================================
class DirectInstagramWebClient:
    """
    Direct HTTP client that communicates with Instagram's Web REST endpoints.
    Uses browser session cookies (sessionid, ds_user_id, csrftoken).
    
    >>> WHERE REAL DATA IS SENT:
    - Headers simulate a genuine Chrome desktop browser session.
    - Uses official Instagram Web Client App ID: 936619743392459.
    - Endpoints called:
        * GET  /api/v1/accounts/current_user/?edit=true (Profile Verification)
        * POST /api/v1/friendships/destroy/{user_id}/   (Unfollow Action)
    """
    def __init__(self, session_id, ds_user_id=None, csrf_token=None):
        self.session_id = session_id
        # Extract ds_user_id from sessionid if formatted as: <user_id>%3A...
        self.ds_user_id = ds_user_id or (session_id.split('%3A')[0] if '%3A' in session_id else None)
        self.csrf_token = csrf_token or "missing"
        
        self.session = requests.Session()
        
        # ----------------------------------------------------------------------
        # PROXY INJECTION POINT:
        # If config.PROXY_URL is set, all direct web requests route through it.
        # ----------------------------------------------------------------------
        if config.PROXY_URL:
            self.session.proxies = {
                'http': config.PROXY_URL,
                'https': config.PROXY_URL
            }

        # Standard Instagram Web browser headers
        self.session.headers.update({
            'User-Agent': config.DEFAULT_USER_AGENT,
            'X-IG-App-ID': config.INSTAGRAM_WEB_APP_ID,
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': 'https://www.instagram.com/',
            'Origin': 'https://www.instagram.com',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
        })
        
        # Ingest session cookies
        self.session.cookies.set('sessionid', self.session_id, domain='.instagram.com')
        if self.ds_user_id:
            self.session.cookies.set('ds_user_id', str(self.ds_user_id), domain='.instagram.com')
        if csrf_token:
            self.session.cookies.set('csrftoken', csrf_token, domain='.instagram.com')
            self.session.headers['X-CSRFToken'] = csrf_token

    def verify_session(self):
        """
        Pings Instagram API to test if the sessionid cookie is valid
        and extracts the current logged-in user's profile details.
        """
        try:
            # Endpoint: Current authenticated user details
            test_url = 'https://www.instagram.com/api/v1/accounts/current_user/?edit=true'
            r = self.session.get(test_url, timeout=12)
            if r.status_code == 200:
                data = r.json()
                user = data.get('user', {})
                return {
                    "valid": True,
                    "user_id": str(user.get('pk') or self.ds_user_id),
                    "username": user.get('username'),
                    "full_name": user.get('full_name'),
                    "profile_pic_url": user.get('profile_pic_url')
                }
            
            # Alternative fallback: inspect root page HTML for session tokens
            r2 = self.session.get('https://www.instagram.com/', timeout=12)
            if 'sessionid' in r2.text or '"username":' in r2.text:
                return {"valid": True, "user_id": self.ds_user_id, "username": None}
            
            return {"valid": False, "error": f"HTTP {r.status_code}: Session cookie rejected by Instagram."}
        except Exception as e:
            return {"valid": False, "error": str(e)}

    def unfollow_user(self, target_user_id):
        """
        Executes a real unfollow request via Instagram Web API endpoint:
        POST https://www.instagram.com/api/v1/friendships/destroy/{target_user_id}/
        """
        url = f'https://www.instagram.com/api/v1/friendships/destroy/{target_user_id}/'
        csrftoken = self.session.cookies.get('csrftoken') or self.csrf_token
        headers = {'X-CSRFToken': csrftoken}
        r = self.session.post(url, headers=headers, timeout=12)
        if r.status_code == 200 and r.json().get('status') == 'ok':
            return True, None
        return False, f"HTTP {r.status_code}: {r.text}"


# ==============================================================================
# SECTION 2: INSTAGRAM SERVICE (PRIMARY API CONTROLLER)
# ==============================================================================
class InstagramService:

    @staticmethod
    def get_client(username):
        """
        Retrieves or restores an active Instagrapi Client session.
        Persistence order:
        1. In-memory cache (active_clients)
        2. Saved JSON session file (sessions/{username}_session.json)
        3. Encrypted session blob in SQLite database
        """
        if username in active_clients:
            return active_clients[username]

        # 1. Attempt to restore from disk file
        s_file = get_session_file(username)
        if os.path.exists(s_file):
            try:
                from instagrapi import Client
                cl = Client()
                if config.PROXY_URL:
                    cl.set_proxy(config.PROXY_URL)
                cl.load_settings(s_file)
                active_clients[username] = cl
                return cl
            except Exception as e:
                logger.warning(f"Could not load session settings file for {username}: {e}")

        # 2. Attempt to restore from Database session_data
        acc = get_account_by_username(username)
        if acc and acc.get('session_data'):
            try:
                from instagrapi import Client
                cl = Client()
                if config.PROXY_URL:
                    cl.set_proxy(config.PROXY_URL)
                cl.set_settings(json.loads(acc['session_data']))
                active_clients[username] = cl
                return cl
            except Exception as e:
                logger.warning(f"Could not load database session for {username}: {e}")

        return None

    @staticmethod
    def verify_account_health(username):
        """
        ========================================================================
        LIVE HEALTH CHECK ENDPOINT
        ========================================================================
        Pings Instagram API to verify that the stored credentials/cookies
        are still authorized and have not expired or triggered a checkpoint.
        """
        acc = get_account_by_username(username)
        if not acc:
            return {"healthy": False, "error": "Account not found in database."}

        # If in Demo mode, return mock health status
        if acc.get('mode') == 'demo':
            return {"healthy": True, "mode": "demo", "message": "Demo mode active (Mock API)"}

        cl = InstagramService.get_client(username)
        if not cl:
            return {"healthy": False, "error": "No active session found. Please reconnect."}

        try:
            # LIVE API CALL: Retrieve authenticated user profile info
            uid = acc.get('user_id') or cl.user_id
            info = cl.user_info(uid)
            return {
                "healthy": True,
                "mode": "live",
                "username": info.username,
                "follower_count": info.follower_count,
                "following_count": info.following_count
            }
        except Exception as e:
            return {"healthy": False, "error": f"Instagram session invalid: {str(e)}"}

    @staticmethod
    def login_with_sessionid(session_id, ds_user_id=None, csrf_token=None):
        """
        ========================================================================
        LIVE SESSION ID AUTHENTICATION
        ========================================================================
        Logs into Instagram using an extracted browser 'sessionid' cookie.
        This is the most reliable, ban-proof method because it does not trigger
        new-device security alerts or automated bot challenges.
        """
        from instagrapi import Client
        cl = Client()
        cl.delay_range = [2, 5]

        # Attach custom proxy if configured in config.py
        if config.PROXY_URL:
            cl.set_proxy(config.PROXY_URL)

        # Extract ds_user_id from sessionid if formatted as: <user_id>%3A...
        if not ds_user_id and '%3A' in session_id:
            ds_user_id = session_id.split('%3A')[0]

        try:
            # LIVE API CALL: Login using session ID
            success = cl.login_by_sessionid(session_id)
            user_id = cl.user_id or ds_user_id
            
            if not user_id:
                raise Exception("Could not extract Instagram User ID from session. Ensure the cookie value is complete.")

            # LIVE API CALL: Fetch authenticated profile details
            try:
                user_info = cl.user_info(user_id)
                username = user_info.username
                full_name = user_info.full_name or username
                profile_pic = str(user_info.profile_pic_url)
                follower_count = user_info.follower_count
                following_count = user_info.following_count
            except Exception:
                # Fallback if user_info endpoint is restricted by rate limits
                username = f"ig_user_{user_id}"
                full_name = username
                profile_pic = f"https://api.dicebear.com/7.x/identicon/svg?seed={user_id}"
                follower_count = 0
                following_count = 0

            # Persist session settings to disk
            s_file = get_session_file(username)
            cl.dump_settings(s_file)

            # Persist account to SQLite Database
            account_id = save_or_update_account(
                username=username,
                user_id=str(user_id),
                full_name=full_name,
                profile_pic_url=profile_pic,
                follower_count=follower_count,
                following_count=following_count,
                session_data=json.dumps(cl.get_settings()),
                mode='live'
            )

            active_clients[username] = cl

            return {
                "success": True,
                "account_id": account_id,
                "username": username,
                "full_name": full_name,
                "profile_pic_url": profile_pic,
                "follower_count": follower_count,
                "following_count": following_count,
                "mode": "live"
            }
        except Exception as e:
            logger.error(f"Instagrapi sessionid login failed: {e}", exc_info=True)
            
            # ------------------------------------------------------------------
            # FALLBACK: Try DirectInstagramWebClient if instagrapi fails
            # ------------------------------------------------------------------
            web_client = DirectInstagramWebClient(session_id, ds_user_id, csrf_token)
            verify = web_client.verify_session()
            if verify.get("valid"):
                u = verify.get("username") or f"user_{verify.get('user_id')}"
                account_id = save_or_update_account(
                    username=u,
                    user_id=str(verify.get('user_id')),
                    full_name=verify.get('full_name') or u,
                    profile_pic_url=verify.get('profile_pic_url') or f"https://api.dicebear.com/7.x/identicon/svg?seed={u}",
                    session_data=json.dumps({"sessionid": session_id, "ds_user_id": verify.get('user_id')}),
                    mode='live'
                )
                return {
                    "success": True,
                    "account_id": account_id,
                    "username": u,
                    "full_name": verify.get('full_name') or u,
                    "profile_pic_url": verify.get('profile_pic_url'),
                    "follower_count": 0,
                    "following_count": 0,
                    "mode": "live"
                }

            return {"success": False, "error": f"Invalid session cookie: {str(e)}"}

    @staticmethod
    def login_with_credentials(username, password, verification_code=None):
        """
        ========================================================================
        LIVE CREDENTIAL LOGIN (USERNAME & PASSWORD)
        ========================================================================
        Direct authentication with support for Two-Factor Authentication (2FA)
        and Instagram challenge checkpoints.
        """
        from instagrapi import Client
        from instagrapi.exceptions import TwoFactorRequired, ChallengeRequired, BadPassword
        
        cl = Client()
        cl.delay_range = [2, 5]

        if config.PROXY_URL:
            cl.set_proxy(config.PROXY_URL)

        try:
            # LIVE API CALL: Attempt login
            if verification_code:
                cl.login(username, password, verification_code=verification_code)
            else:
                cl.login(username, password)
        except TwoFactorRequired:
            # 2FA Prompt: Instruct frontend to render the 6-digit code input
            return {
                "success": False,
                "need_2fa": True,
                "message": "Two-Factor Authentication is enabled on your Instagram account. Enter the 6-digit SMS/App code."
            }
        except ChallengeRequired:
            # Checkpoint: Instagram suspicious login challenge
            return {
                "success": False,
                "need_challenge": True,
                "message": "Instagram requested a checkpoint verification. Recommended: Use Session ID login to bypass."
            }
        except BadPassword:
            return {"success": False, "error": "Incorrect Instagram username or password."}
        except Exception as e:
            return {"success": False, "error": str(e)}

        try:
            # LIVE API CALL: Fetch authenticated profile details
            user_id = cl.user_id
            user_info = cl.user_info(user_id)
            full_name = user_info.full_name or username
            profile_pic = str(user_info.profile_pic_url)
            follower_count = user_info.follower_count
            following_count = user_info.following_count

            # Persist session to disk
            s_file = get_session_file(username)
            cl.dump_settings(s_file)

            # Persist account to database
            account_id = save_or_update_account(
                username=username,
                user_id=str(user_id),
                full_name=full_name,
                profile_pic_url=profile_pic,
                follower_count=follower_count,
                following_count=following_count,
                session_data=json.dumps(cl.get_settings()),
                mode='live'
            )

            active_clients[username] = cl

            return {
                "success": True,
                "account_id": account_id,
                "username": username,
                "full_name": full_name,
                "profile_pic_url": profile_pic,
                "follower_count": follower_count,
                "following_count": following_count,
                "mode": "live"
            }
        except Exception as e:
            return {"success": False, "error": f"Authenticated but failed to retrieve profile details: {str(e)}"}


    # ==========================================================================
    # SECTION 3: DYNAMIC REAL-TIME SCANNING ENGINE
    # ==========================================================================
    @staticmethod
    def start_background_scan(account_id, username):
        """
        ========================================================================
        ASYNC LIVE SCANNER (FETCHING REAL FOLLOWER & FOLLOWING LISTS)
        ========================================================================
        Runs in a background thread so large accounts don't time out the HTTP
        request. Updates `scan_jobs[account_id]` dynamically after every step
        so the frontend UI can stream real-time progress.
        """
        if account_id in scan_jobs and scan_jobs[account_id].get("status") == "running":
            return scan_jobs[account_id]

        scan_job = {
            "account_id": account_id,
            "username": username,
            "status": "running",
            "phase": "starting", # 'following', 'followers', 'analyzing', 'completed', 'failed'
            "progress_percent": 5,
            "message": "Initializing live Instagram connection...",
            "following_count": 0,
            "followers_count": 0,
            "not_following_back": 0,
            "started_at": datetime.now().isoformat(),
            "completed_at": None,
            "error": None
        }
        scan_jobs[account_id] = scan_job

        def worker():
            try:
                acc = get_account_by_username(username)
                if not acc:
                    raise Exception("Account not found in local database.")

                mode = acc.get('mode', 'live')

                # --------------------------------------------------------------
                # LIVE INSTAGRAM API SCAN
                # --------------------------------------------------------------
                cl = InstagramService.get_client(username)
                if not cl:
                    raise Exception("Instagram live session expired. Please reconnect in settings.")

                user_id = acc.get('user_id') or cl.user_id

                # STEP 1: LIVE API CALL -> Fetch all profiles you are FOLLOWING
                # Endpoint queried: /api/v1/friendships/{user_id}/following/
                scan_job["phase"] = "following"
                scan_job["progress_percent"] = 15
                scan_job["message"] = "Querying live Instagram Following API..."

                following_dict = cl.user_following(user_id)
                following_list = []
                for uid, user in following_dict.items():
                    following_list.append({
                        "id": str(user.pk),
                        "username": user.username,
                        "full_name": user.full_name or '',
                        "profile_pic_url": str(user.profile_pic_url) if user.profile_pic_url else '',
                        "is_verified": bool(user.is_verified),
                        "is_private": bool(user.is_private)
                    })

                scan_job["following_count"] = len(following_list)
                scan_job["progress_percent"] = 45
                scan_job["message"] = f"Found {len(following_list)} profiles you follow."

                # STEP 2: LIVE API CALL -> Fetch all profiles who are FOLLOWERS
                # Endpoint queried: /api/v1/friendships/{user_id}/followers/
                scan_job["phase"] = "followers"
                scan_job["progress_percent"] = 55
                scan_job["message"] = "Querying live Instagram Followers API..."

                followers_dict = cl.user_followers(user_id)
                followers_list = []
                for uid, user in followers_dict.items():
                    followers_list.append({
                        "id": str(user.pk),
                        "username": user.username,
                        "full_name": user.full_name or '',
                        "profile_pic_url": str(user.profile_pic_url) if user.profile_pic_url else '',
                        "is_verified": bool(user.is_verified),
                        "is_private": bool(user.is_private)
                    })

                scan_job["followers_count"] = len(followers_list)
                scan_job["progress_percent"] = 80
                scan_job["message"] = f"Found {len(followers_list)} followers."

                # STEP 3: COMPARISON ENGINE & WEEKLY UNFOLLOWER DIFF
                # Compares:
                # - Non-Followers: (Following - Followers)
                # - Mutuals: (Following ∩ Followers)
                # - Lost Followers: (Previous Snapshot Followers - Current Followers)
                scan_job["phase"] = "analyzing"
                scan_job["progress_percent"] = 90
                scan_job["message"] = "Cross-referencing followers & logging weekly diff..."

                snapshot = record_scan_snapshot(account_id, followers_list, following_list)

                # OPTIONAL NOTIFICATION WEBHOOK:
                # If any lost followers were detected and Discord/Telegram webhook is configured
                if snapshot.get("lost_followers_count", 0) > 0 and config.DISCORD_WEBHOOK_URL:
                    try:
                        requests.post(
                            config.DISCORD_WEBHOOK_URL,
                            json={"content": f"🚨 [FollowersPlan] Detected {snapshot['lost_followers_count']} accounts that unfollowed @{username}!"},
                            timeout=5
                        )
                    except Exception as e:
                        logger.warning(f"Could not send Discord webhook alert: {e}")

                scan_job["status"] = "completed"
                scan_job["phase"] = "completed"
                scan_job["progress_percent"] = 100
                scan_job["not_following_back"] = snapshot["not_following_back_count"]
                scan_job["message"] = f"Scan completed! {snapshot['not_following_back_count']} non-followers identified."
                scan_job["completed_at"] = datetime.now().isoformat()

            except Exception as e:
                logger.error(f"Live scan failed for {username}: {e}", exc_info=True)
                scan_job["status"] = "failed"
                scan_job["phase"] = "failed"
                scan_job["error"] = str(e)
                scan_job["message"] = f"Scan failed: {str(e)}"

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        return scan_job

    @staticmethod
    def get_scan_progress(account_id):
        """Returns the current progress dictionary for the active scan."""
        return scan_jobs.get(account_id, {"status": "idle"})


    # ==========================================================================
    # SECTION 4: LIVE UNFOLLOW EXECUTION (SINGLE & BULK ENGINE)
    # ==========================================================================
    @staticmethod
    def unfollow_single_user(account_id, username, target_username):
        """
        ========================================================================
        LIVE SINGLE UNFOLLOW API CALL
        ========================================================================
        Executes a real unfollow action against Instagram API endpoint:
        POST https://i.instagram.com/api/v1/friendships/destroy/{target_pk}/
        """
        acc = get_account_by_username(username)
        if not acc:
            return {"success": False, "error": "Account not found in database"}

        cl = InstagramService.get_client(username)
        if not cl:
            return {"success": False, "error": "Live session expired. Please reconnect Instagram account."}

        try:
            # 1. Resolve numeric Instagram User ID (PK) from username
            target_pk = cl.user_id_from_username(target_username)
            
            # 2. LIVE API CALL: Call unfollow endpoint
            res = cl.user_unfollow(target_pk)
            if res:
                # Update SQLite database to mark as unfollowed
                mark_unfollowed(account_id, target_username, log_status='success')
                return {"success": True, "target_username": target_username}
            else:
                return {"success": False, "error": "Instagram API returned false without an exception."}
        except Exception as e:
            err_msg = str(e)
            logger.error(f"Failed to unfollow {target_username}: {err_msg}")
            
            # Anti-ban error classification
            if 'feedback_required' in err_msg.lower() or 'action blocked' in err_msg.lower():
                err_msg = "Instagram Action Blocked: Instagram has temporarily limited unfollow actions. Please wait a few hours."
            elif 'login_required' in err_msg.lower():
                err_msg = "Instagram session expired. Please reconnect your account."

            mark_unfollowed(account_id, target_username, log_status='failed', err=err_msg)
            return {"success": False, "error": err_msg}

    @staticmethod
    def start_bulk_unfollow(account_id, username, target_usernames, delay_seconds=None):
        """
        ========================================================================
        SAFE BULK UNFOLLOW CONTROLLER (ANTI-BAN ENGINE)
        ========================================================================
        Unfollows a list of profiles with human jitter delays to prevent
        Instagram temporary action limits or shadowbans.
        """
        if delay_seconds is None:
            delay_seconds = config.DEFAULT_UNFOLLOW_DELAY_SECONDS

        # Cap batch size to MAX_UNFOLLOWS_PER_BATCH for security
        if len(target_usernames) > config.MAX_UNFOLLOWS_PER_BATCH:
            logger.info(f"Capping bulk unfollow batch from {len(target_usernames)} to {config.MAX_UNFOLLOWS_PER_BATCH}")
            target_usernames = target_usernames[:config.MAX_UNFOLLOWS_PER_BATCH]

        task_id = f"bulk_{account_id}_{int(time.time())}"
        
        task_state = {
            "task_id": task_id,
            "account_id": account_id,
            "username": username,
            "targets": target_usernames,
            "total": len(target_usernames),
            "current_index": 0,
            "current_target": None,
            "countdown_seconds": 0,
            "completed": [],
            "failed": [],
            "status": "running", # running, paused, cancelled, completed
            "message": "Initializing safe bulk unfollow...",
            "delay": delay_seconds
        }
        bulk_tasks[account_id] = task_state

        def run_worker():
            for idx, target in enumerate(target_usernames):
                # Check for user pause
                while task_state["status"] == "paused":
                    time.sleep(0.5)

                # Check for user cancellation
                if task_state["status"] == "cancelled":
                    task_state["message"] = f"Bulk unfollow stopped by user at {idx}/{len(target_usernames)}."
                    return

                task_state["current_index"] = idx + 1
                task_state["current_target"] = target
                task_state["message"] = f"Unfollowing @{target} ({idx + 1} of {len(target_usernames)})..."

                # LIVE API CALL: Unfollow current target
                res = InstagramService.unfollow_single_user(account_id, username, target)
                if res.get("success"):
                    task_state["completed"].append(target)
                else:
                    task_state["failed"].append({"target": target, "error": res.get("error")})
                    # SAFETY HALT: If Instagram action block is detected, pause immediately!
                    if "action blocked" in str(res.get("error")).lower():
                        task_state["status"] = "paused"
                        task_state["message"] = "PAUSED AUTOMATICALLY: Instagram action block detected. Stopped to protect your account!"
                        return

                # Pacing delay with real-time countdown
                if idx < len(target_usernames) - 1 and task_state["status"] == "running":
                    jitter = random.uniform(1.0 - config.JITTER_RATIO, 1.0 + config.JITTER_RATIO) * delay_seconds
                    wait_steps = int(jitter)
                    for remaining in range(wait_steps, 0, -1):
                        if task_state["status"] != "running":
                            break
                        task_state["countdown_seconds"] = remaining
                        task_state["message"] = f"Safety delay: Waiting {remaining}s before next unfollow..."
                        time.sleep(1)

            task_state["status"] = "completed"
            task_state["message"] = f"Completed! Successfully unfollowed {len(task_state['completed'])} of {len(target_usernames)} accounts."

        thread = threading.Thread(target=run_worker, daemon=True)
        thread.start()
        return task_state


    # ==========================================================================
    # SECTION 5: OFFICIAL JSON EXPORT PARSER (OFFLINE ZERO-RISK MODE)
    # ==========================================================================
    @staticmethod
    def parse_instagram_export(account_id, followers_json_data, following_json_data):
        """
        Parses official Instagram GDPR export JSON files (followers_1.json and following.json).
        Allows 100% offline ban-proof analysis without entering credentials.
        """
        followers_list = []
        following_list = []

        # Parse Followers JSON structure
        if isinstance(followers_json_data, list):
            for item in followers_json_data:
                if isinstance(item, dict):
                    sld = item.get("string_list_data", [])
                    if sld and isinstance(sld, list):
                        u = sld[0].get("value")
                        if u:
                            followers_list.append({"username": u, "full_name": item.get("title", u), "is_verified": False})
                    elif "value" in item:
                        followers_list.append({"username": item["value"], "full_name": item["value"]})
                elif isinstance(item, str):
                    followers_list.append({"username": item, "full_name": item})
        elif isinstance(followers_json_data, dict):
            arr = followers_json_data.get("relationships_followers", [])
            for item in arr:
                sld = item.get("string_list_data", [])
                if sld:
                    followers_list.append({"username": sld[0].get("value"), "full_name": item.get("title", "")})

        # Parse Following JSON structure
        following_items = []
        if isinstance(following_json_data, dict):
            following_items = following_json_data.get("relationships_following", [])
        elif isinstance(following_json_data, list):
            following_items = following_json_data

        for item in following_items:
            if isinstance(item, dict):
                sld = item.get("string_list_data", [])
                if sld and isinstance(sld, list):
                    u = sld[0].get("value")
                    if u:
                        following_list.append({"username": u, "full_name": item.get("title", u), "is_verified": False})
                elif "value" in item:
                    following_list.append({"username": item["value"], "full_name": item["value"]})
            elif isinstance(item, str):
                following_list.append({"username": item, "full_name": item})

        # Record scan snapshot to database
        snapshot = record_scan_snapshot(account_id, followers_list, following_list)
        return snapshot
