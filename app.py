"""
==============================================================================
FollowersPlan — Flask Web Server & REST API
==============================================================================
This module serves the frontend application and provides REST API endpoints for:
- Live Account Authentication (Session ID / Credentials / Demo / JSON Export)
- Background Scanning with Real-Time Progress Polling
- Relationship Queries (Not Following Back, Mutuals, Fans, Protected)
- Live Single & Bulk Unfollow Execution with Safety Controls
- Automated Weekly Unfollowers Reports

>>> WHERE TO CONFIGURE:
- Server Port, Host, and Debug options are loaded from `config.py`.
- To attach automated cron jobs or recurring weekly scans, see Section 5 below.
==============================================================================
"""

import os
import json
import logging
from flask import Flask, request, jsonify, render_template, send_from_directory

# Import central configuration settings
import config
from database import (
    init_db, get_account_by_username, get_latest_account,
    get_relationships, get_weekly_reports, get_stats,
    toggle_whitelist, mark_unfollowed
)
from instagram_service import InstagramService, bulk_tasks, scan_jobs
from demo_data import seed_demo_account

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# Initialize Flask application
app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = config.SECRET_KEY

# Tracks current active username in local single-user mode
current_active_username = None

def get_current_account():
    """
    Retrieves the currently active account record from the database.
    Falls back to the most recently updated account if not explicitly set.
    """
    global current_active_username
    if current_active_username:
        acc = get_account_by_username(current_active_username)
        if acc:
            return acc
    acc = get_latest_account()
    if acc:
        current_active_username = acc['username']
        return acc
    return None


# ==============================================================================
# SECTION 1: STATIC & PWA APPLICATION ROUTES
# ==============================================================================
@app.route('/')
def index():
    """Serves the main single-page web & mobile application."""
    return render_template('index.html')

@app.route('/manifest.json')
def manifest():
    """PWA Web App Manifest for mobile installation (iOS / Android)."""
    return send_from_directory('static', 'manifest.json', mimetype='application/json')

@app.route('/sw.js')
def service_worker():
    """PWA Service Worker for offline asset caching."""
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')


# ==============================================================================
# SECTION 2: LIVE AUTHENTICATION & HEALTH MONITORING ENDPOINTS
# ==============================================================================
@app.route('/api/account/current', methods=['GET'])
def api_current_account():
    """
    GET /api/account/current
    Returns currently connected Instagram account info and calculated stats.
    """
    acc = get_current_account()
    if not acc:
        return jsonify({"authenticated": False, "account": None})
    stats = get_stats(acc['id'])
    return jsonify({
        "authenticated": True,
        "account": acc,
        "stats": stats
    })

@app.route('/api/auth/health', methods=['GET'])
def api_auth_health():
    """
    GET /api/auth/health
    ----------------------------------------------------------------------------
    LIVE API HEALTH VERIFICATION:
    Pings Instagram to check if the active live session is still valid.
    Returns: {"healthy": true/false, "mode": "live"|"demo", ...}
    ----------------------------------------------------------------------------
    """
    acc = get_current_account()
    if not acc:
        return jsonify({"healthy": False, "message": "No account connected"})
    
    health = InstagramService.verify_account_health(acc['username'])
    return jsonify(health)

@app.route('/api/auth/login-session', methods=['POST'])
def api_login_session():
    """
    POST /api/auth/login-session
    ----------------------------------------------------------------------------
    LIVE SESSION ID LOGIN (RECOMMENDED):
    Payload: {"session_id": "...", "ds_user_id": "...", "csrf_token": "..."}
    Connects without triggering 2FA or suspicious login checkpoints.
    ----------------------------------------------------------------------------
    """
    global current_active_username
    data = request.get_json() or {}
    session_id = data.get('session_id', '').strip()
    ds_user_id = data.get('ds_user_id', '').strip() or None
    csrf_token = data.get('csrf_token', '').strip() or None

    if not session_id:
        return jsonify({"success": False, "error": "Instagram sessionid cookie is required."}), 400

    res = InstagramService.login_with_sessionid(session_id, ds_user_id, csrf_token)
    if res.get('success'):
        current_active_username = res['username']
        stats = get_stats(res['account_id'])
        return jsonify({
            "success": True,
            "message": f"Successfully connected live Instagram account @{res['username']}",
            "account": res,
            "stats": stats
        })
    else:
        return jsonify({"success": False, "error": res.get('error', 'Authentication failed')}), 400

@app.route('/api/auth/login-credentials', methods=['POST'])
def api_login_credentials():
    """
    POST /api/auth/login-credentials
    ----------------------------------------------------------------------------
    LIVE USERNAME/PASSWORD LOGIN:
    Payload: {"username": "...", "password": "...", "verification_code": "..."}
    ----------------------------------------------------------------------------
    """
    global current_active_username
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    verification_code = data.get('verification_code', '').strip() or None

    if not username or not password:
        return jsonify({"success": False, "error": "Username and password are required."}), 400

    res = InstagramService.login_with_credentials(username, password, verification_code)
    if res.get('success'):
        current_active_username = res['username']
        stats = get_stats(res['account_id'])
        return jsonify({
            "success": True,
            "message": f"Successfully connected @{res['username']}",
            "account": res,
            "stats": stats
        })
    elif res.get('need_2fa') or res.get('need_challenge'):
        return jsonify(res), 200
    else:
        return jsonify({"success": False, "error": res.get('error', 'Login failed')}), 400

@app.route('/api/auth/demo', methods=['POST'])
def api_auth_demo():
    """POST /api/auth/demo -> Seeds and switches to the mock demo account."""
    global current_active_username
    try:
        acc_id = seed_demo_account()
        acc = get_account_by_username("alex.creativestudio")
        current_active_username = "alex.creativestudio"
        stats = get_stats(acc_id)
        return jsonify({
            "success": True,
            "message": "Connected to Demo Instagram Account",
            "account": acc,
            "stats": stats
        })
    except Exception as e:
        logger.error(f"Error seeding demo: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/auth/logout', methods=['POST'])
def api_logout():
    """POST /api/auth/logout -> Disconnects the active session."""
    global current_active_username
    current_active_username = None
    return jsonify({"success": True, "message": "Disconnected current account"})


# ==============================================================================
# SECTION 3: DYNAMIC REAL-TIME SCANNING & PROGRESS POLLING
# ==============================================================================
@app.route('/api/scan/start', methods=['POST'])
def api_scan_start():
    """
    POST /api/scan/start
    ----------------------------------------------------------------------------
    TRIGGERS ASYNC BACKGROUND SCAN:
    Kicks off a background thread querying live Instagram Followers/Following.
    Returns: {"success": true, "job": {"status": "running", ...}}
    ----------------------------------------------------------------------------
    """
    acc = get_current_account()
    if not acc:
        return jsonify({"success": False, "error": "No Instagram account connected"}), 401

    job = InstagramService.start_background_scan(acc['id'], acc['username'])
    return jsonify({"success": True, "job": job})

@app.route('/api/scan/progress', methods=['GET'])
def api_scan_progress():
    """
    GET /api/scan/progress
    ----------------------------------------------------------------------------
    REAL-TIME PROGRESS POLLING ENDPOINT:
    Frontend calls this endpoint every 1000ms while scanning to receive:
    - percent: 0 to 100
    - phase: 'following' | 'followers' | 'analyzing' | 'completed' | 'failed'
    - message: live status text
    - following_count, followers_count, not_following_back
    ----------------------------------------------------------------------------
    """
    acc = get_current_account()
    if not acc:
        return jsonify({"status": "idle"})

    job = InstagramService.get_scan_progress(acc['id'])
    stats = None
    if job.get('status') == 'completed':
        stats = get_stats(acc['id'])
    return jsonify({"job": job, "stats": stats})

@app.route('/api/scan', methods=['POST'])
def api_scan_sync():
    """POST /api/scan -> Fallback synchronous scan endpoint."""
    acc = get_current_account()
    if not acc:
        return jsonify({"success": False, "error": "No account connected"}), 401

    try:
        job = InstagramService.start_background_scan(acc['id'], acc['username'])
        import time
        for _ in range(30):
            if job.get('status') in ('completed', 'failed'):
                break
            time.sleep(0.5)

        stats = get_stats(acc['id'])
        return jsonify({
            "success": job.get('status') == 'completed',
            "message": job.get('message'),
            "stats": stats
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ==============================================================================
# SECTION 4: RELATIONSHIPS & FILTERING ENDPOINTS
# ==============================================================================
@app.route('/api/relationships', methods=['GET'])
def api_relationships():
    """
    GET /api/relationships
    ----------------------------------------------------------------------------
    Query params:
    - filter: 'not_following_back' | 'fans' | 'mutual' | 'all_following' | 'whitelisted'
    - search: string filter for username or full name
    - limit: max records per page (default: 300)
    - offset: pagination offset
    ----------------------------------------------------------------------------
    """
    acc = get_current_account()
    if not acc:
        return jsonify({"results": [], "total": 0})

    filter_type = request.args.get('filter', 'not_following_back')
    search = request.args.get('search', '').strip() or None
    limit = int(request.args.get('limit', 300))
    offset = int(request.args.get('offset', 0))

    data = get_relationships(acc['id'], filter_type=filter_type, search=search, limit=limit, offset=offset)
    return jsonify(data)

@app.route('/api/relationships/whitelist', methods=['POST'])
def api_toggle_whitelist():
    """
    POST /api/relationships/whitelist
    Payload: {"username": "target_user"}
    Toggles the protection/whitelist flag on a profile to shield it from bulk unfollows.
    """
    acc = get_current_account()
    if not acc:
        return jsonify({"success": False, "error": "Not authenticated"}), 401

    data = request.get_json() or {}
    target_username = data.get('username')
    if not target_username:
        return jsonify({"success": False, "error": "Username required"}), 400

    new_val = toggle_whitelist(acc['id'], target_username)
    return jsonify({
        "success": True,
        "username": target_username,
        "is_whitelisted": bool(new_val)
    })


# ==============================================================================
# SECTION 5: LIVE UNFOLLOW & BULK ENGINE CONTROLS
# ==============================================================================
@app.route('/api/unfollow', methods=['POST'])
def api_unfollow_single():
    """
    POST /api/unfollow
    ----------------------------------------------------------------------------
    LIVE SINGLE UNFOLLOW:
    Payload: {"username": "target_username"}
    Calls Instagram API directly to unfollow the target account.
    ----------------------------------------------------------------------------
    """
    acc = get_current_account()
    if not acc:
        return jsonify({"success": False, "error": "Not authenticated"}), 401

    data = request.get_json() or {}
    target_username = data.get('username')
    if not target_username:
        return jsonify({"success": False, "error": "Target username required"}), 400

    res = InstagramService.unfollow_single_user(acc['id'], acc['username'], target_username)
    stats = get_stats(acc['id'])
    return jsonify({
        "success": res.get('success', False),
        "target_username": target_username,
        "error": res.get('error'),
        "stats": stats
    })

@app.route('/api/bulk-unfollow/start', methods=['POST'])
def api_bulk_unfollow_start():
    """
    POST /api/bulk-unfollow/start
    ----------------------------------------------------------------------------
    SAFE BULK UNFOLLOW SEQUENCE:
    Payload: {"targets": ["user1", "user2"], "delay": 6.0}
    Starts background rate-limited unfollow loop with human jitter delay.
    ----------------------------------------------------------------------------
    """
    acc = get_current_account()
    if not acc:
        return jsonify({"success": False, "error": "Not authenticated"}), 401

    data = request.get_json() or {}
    targets = data.get('targets', [])
    delay = float(data.get('delay', config.DEFAULT_UNFOLLOW_DELAY_SECONDS))

    if not targets:
        return jsonify({"success": False, "error": "No target profiles provided"}), 400

    task_state = InstagramService.start_bulk_unfollow(acc['id'], acc['username'], targets, delay_seconds=delay)
    return jsonify({
        "success": True,
        "task_id": task_state["task_id"],
        "total": len(targets)
    })

@app.route('/api/bulk-unfollow/status', methods=['GET'])
def api_bulk_unfollow_status():
    """
    GET /api/bulk-unfollow/status
    Returns live progress, remaining countdown seconds, and completed list.
    """
    acc = get_current_account()
    if not acc:
        return jsonify({"status": "idle"})

    task_state = bulk_tasks.get(acc['id'])
    if not task_state:
        return jsonify({"status": "idle"})

    return jsonify(task_state)

@app.route('/api/bulk-unfollow/control', methods=['POST'])
def api_bulk_unfollow_control():
    """
    POST /api/bulk-unfollow/control
    Payload: {"action": "pause" | "resume" | "cancel"}
    """
    acc = get_current_account()
    if not acc:
        return jsonify({"success": False, "error": "Not authenticated"}), 401

    task_state = bulk_tasks.get(acc['id'])
    if not task_state:
        return jsonify({"success": False, "error": "No active bulk unfollow task"}), 400

    action = request.get_json().get('action')
    if action == 'pause':
        task_state['status'] = 'paused'
        task_state['message'] = 'Bulk unfollow paused.'
    elif action == 'resume':
        task_state['status'] = 'running'
        task_state['message'] = 'Resumed bulk unfollow...'
    elif action == 'cancel':
        task_state['status'] = 'cancelled'
        task_state['message'] = 'Cancelling bulk unfollow...'

    return jsonify({"success": True, "status": task_state['status']})


# ==============================================================================
# SECTION 6: WEEKLY REPORTS & JSON EXPORT IMPORT
# ==============================================================================
@app.route('/api/reports/weekly', methods=['GET'])
def api_weekly_reports():
    """
    GET /api/reports/weekly
    Returns the list of accounts that have unfollowed the user over time.
    """
    acc = get_current_account()
    if not acc:
        return jsonify({"reports": []})

    reports = get_weekly_reports(acc['id'])
    return jsonify({"reports": reports})

@app.route('/api/import-json', methods=['POST'])
def api_import_json():
    """
    POST /api/import-json
    Parses uploaded followers_1.json and following.json files for offline analysis.
    """
    acc = get_current_account()
    username = request.form.get('username') or (acc['username'] if acc else "imported_user")
    
    from database import save_or_update_account
    account_id = save_or_update_account(
        username=username,
        user_id="import_" + username,
        full_name=username,
        profile_pic_url=f"https://api.dicebear.com/7.x/identicon/svg?seed={username}",
        mode="export"
    )
    global current_active_username
    current_active_username = username

    followers_file = request.files.get('followers_file')
    following_file = request.files.get('following_file')

    followers_data = []
    following_data = []

    if followers_file:
        try:
            followers_data = json.load(followers_file)
        except Exception as e:
            return jsonify({"success": False, "error": f"Invalid followers JSON: {e}"}), 400

    if following_file:
        try:
            following_data = json.load(following_file)
        except Exception as e:
            return jsonify({"success": False, "error": f"Invalid following JSON: {e}"}), 400

    try:
        snapshot = InstagramService.parse_instagram_export(account_id, followers_data, following_data)
        stats = get_stats(account_id)
        return jsonify({
            "success": True,
            "message": "Imported data successfully",
            "snapshot": snapshot,
            "stats": stats
        })
    except Exception as e:
        logger.error(f"Error parsing export: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


# ==============================================================================
# SECTION 7: APPLICATION ENTRY POINT
# ==============================================================================
if __name__ == '__main__':
    # Initialize SQLite database tables
    init_db()
    
    # Check if any account exists; if empty, seed demo account for immediate evaluation
    latest = get_latest_account()
    if not latest:
        seed_demo_account()

    print("=" * 65)
    print("  INSTAGRAM FOLLOWER & UNFOLLOWER SUITE (LIVE API READY)")
    print(f"  Local Machine:  http://localhost:{config.PORT}")
    print(f"  Mobile/Network: http://{config.HOST}:{config.PORT}")
    print("=" * 65)
    
    # Run server using configuration settings
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG_MODE)
