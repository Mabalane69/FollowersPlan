"""
==============================================================================
FollowersPlan — Flask Web Server & Firebase REST API
==============================================================================
This module serves the cross-platform frontend application and provides
real-time REST endpoints backed by Google Cloud Firebase Firestore:
- Live Account Authentication (Session ID / Username-Password / JSON Export)
- Firebase Firestore Cloud Sync
- Background Scanning with Real-Time Progress Polling
- Relationship Queries (Not Following Back, Mutuals, Fans, Protected)
- Live Single & Bulk Safe Unfollow Execution with Anti-Ban Pacing
- Automated Weekly Unfollowers Reports

>>> CONFIGURATION:
Configure your Firebase and Instagram keys in `config.py`:
FIREBASE_SERVICE_ACCOUNT_KEY_PATH = "add path to your serviceAccountKey.json here"
FIREBASE_PROJECT_ID = "add your project id here"
INSTAGRAM_SESSION_ID = "add your sessionid here"
==============================================================================
"""

import os
import json
import logging
from datetime import timedelta
from flask import Flask, request, jsonify, render_template, send_from_directory, session as flask_session

# Central configuration and keys
import config
from firebase_service import FirebaseService
from database import init_db, clear_all_data
from instagram_service import InstagramService, bulk_tasks, scan_jobs

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# Initialize Flask application
app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = config.SECRET_KEY
app.config.update(
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax'
)

def get_current_account():
    """
    Retrieves the currently active account record for the SPECIFIC requesting client.
    Guarantees strict isolation across multiple simultaneous clients.
    
    Priority lookup:
    1. Isolated Flask session cookie: flask_session.get('active_username')
    2. Client HTTP Request Header: request.headers.get('X-Account-Username')
    3. Query parameter: request.args.get('account_username')
    """
    username = flask_session.get('active_username')
    
    if not username:
        username = request.headers.get('X-Account-Username')
        
    if not username and request.args.get('account_username'):
        username = request.args.get('account_username')
        
    if username:
        return FirebaseService.get_account_by_username(username)
        
    return None


# ==============================================================================
# SECTION 1: STATIC & PWA APPLICATION ROUTES
# ==============================================================================
@app.route('/')
def index():
    """Serves the main single-page cross-platform web application."""
    return render_template('index.html')

@app.route('/manifest.json')
def manifest():
    """PWA Web App Manifest for mobile installation (iOS / Android / Desktop)."""
    return send_from_directory('static', 'manifest.json', mimetype='application/json')

@app.route('/sw.js')
def service_worker():
    """PWA Service Worker for offline asset caching."""
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')


# ==============================================================================
# SECTION 2: FIREBASE STATUS & CLIENT CONFIGURATION ENDPOINT
# ==============================================================================
@app.route('/api/firebase/config', methods=['GET'])
def api_firebase_config():
    """
    GET /api/firebase/config
    Returns Firebase Web client configuration (for browser SDK sync)
    and current connection status.
    """
    return jsonify({
        "connected": FirebaseService.is_connected(),
        "project_id": config.FIREBASE_PROJECT_ID,
        "database_url": config.FIREBASE_DATABASE_URL,
        "client_config": {
            "apiKey": config.FIREBASE_API_KEY,
            "authDomain": config.FIREBASE_AUTH_DOMAIN,
            "projectId": config.FIREBASE_PROJECT_ID,
            "storageBucket": config.FIREBASE_STORAGE_BUCKET,
            "messagingSenderId": config.FIREBASE_MESSAGING_SENDER_ID,
            "appId": config.FIREBASE_APP_ID
        }
    })


# ==============================================================================
# SECTION 3: LIVE AUTHENTICATION & HEALTH MONITORING ENDPOINTS
# ==============================================================================
@app.route('/api/account/current', methods=['GET'])
def api_current_account():
    """
    GET /api/account/current
    Returns currently connected Instagram account info and calculated live stats.
    """
    acc = get_current_account()
    if not acc:
        return jsonify({"authenticated": False, "account": None})
    stats = FirebaseService.get_stats(acc['id'])
    return jsonify({
        "authenticated": True,
        "account": acc,
        "stats": stats,
        "firebase_active": FirebaseService.is_connected()
    })

@app.route('/api/auth/health', methods=['GET'])
def api_auth_health():
    """
    GET /api/auth/health
    ----------------------------------------------------------------------------
    LIVE API HEALTH VERIFICATION:
    Pings Instagram to check if the active live session is authorized.
    ----------------------------------------------------------------------------
    """
    acc = get_current_account()
    if not acc:
        return jsonify({
            "healthy": False, 
            "message": "No Instagram account connected. Please connect via sessionid or username/password."
        })
    
    health = InstagramService.verify_account_health(acc['username'])
    health['firebase_connected'] = FirebaseService.is_connected()
    return jsonify(health)

@app.route('/api/auth/login-session', methods=['POST'])
def api_login_session():
    """
    POST /api/auth/login-session
    ----------------------------------------------------------------------------
    LIVE SESSION ID LOGIN (RECOMMENDED & 100% BAN-PROOF):
    Payload: {"session_id": "...", "ds_user_id": "...", "csrf_token": "..."}
    ----------------------------------------------------------------------------
    """
    global current_active_username
    data = request.get_json() or {}
    session_id = data.get('session_id', '').strip()
    ds_user_id = data.get('ds_user_id', '').strip() or None
    csrf_token = data.get('csrf_token', '').strip() or None

    if not session_id or session_id == "add your sessionid here":
        return jsonify({"success": False, "error": "Instagram sessionid cookie is required."}), 400

    res = InstagramService.login_with_sessionid(session_id, ds_user_id, csrf_token)
    if res.get('success'):
        flask_session.permanent = True
        flask_session['active_username'] = res['username']
        connected = flask_session.get('connected_accounts', [])
        if res['username'] not in connected:
            connected.append(res['username'])
        flask_session['connected_accounts'] = connected
        
        stats = FirebaseService.get_stats(res['account_id'])
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
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    verification_code = data.get('verification_code', '').strip() or None

    if not username or not password or username == "add your instagram username here":
        return jsonify({"success": False, "error": "Username and password are required."}), 400

    res = InstagramService.login_with_credentials(username, password, verification_code)
    if res.get('success'):
        flask_session.permanent = True
        flask_session['active_username'] = res['username']
        connected = flask_session.get('connected_accounts', [])
        if res['username'] not in connected:
            connected.append(res['username'])
        flask_session['connected_accounts'] = connected
        
        stats = FirebaseService.get_stats(res['account_id'])
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

@app.route('/api/auth/logout', methods=['POST'])
def api_logout():
    """POST /api/auth/logout -> Disconnects active account for this client."""
    disconnected_user = flask_session.pop('active_username', None)
    return jsonify({
        "success": True, 
        "message": f"Disconnected @{disconnected_user}" if disconnected_user else "Logged out"
    })

@app.route('/api/accounts', methods=['GET'])
def api_accounts_list():
    """
    GET /api/accounts
    Returns list of accounts available to the current client session,
    allowing multi-client account switching.
    """
    current = get_current_account()
    session_accounts = flask_session.get('connected_accounts', [])
    all_accounts = FirebaseService.get_all_accounts()
    
    return jsonify({
        "current_username": current['username'] if current else None,
        "accounts": all_accounts,
        "session_accounts": session_accounts,
        "total": len(all_accounts)
    })

@app.route('/api/accounts/switch', methods=['POST'])
def api_accounts_switch():
    """
    POST /api/accounts/switch
    Switches active Instagram profile for the current client's session.
    Payload: {"username": "target_username"}
    """
    data = request.get_json() or {}
    username = data.get('username')
    if not username:
        return jsonify({"success": False, "error": "Username is required"}), 400
        
    acc = FirebaseService.get_account_by_username(username)
    if not acc:
        return jsonify({"success": False, "error": f"Account @{username} not found"}), 404
        
    flask_session.permanent = True
    flask_session['active_username'] = username
    stats = FirebaseService.get_stats(acc['id'])
    return jsonify({
        "success": True, 
        "message": f"Switched active account to @{username}",
        "account": acc,
        "stats": stats
    })


# ==============================================================================
# SECTION 4: DYNAMIC REAL-TIME SCANNING & PROGRESS POLLING
# ==============================================================================
@app.route('/api/scan/start', methods=['POST'])
def api_scan_start():
    """
    POST /api/scan/start
    ----------------------------------------------------------------------------
    TRIGGERS ASYNC BACKGROUND SCAN:
    Queries live Instagram Following & Followers lists and saves diffs to Firebase.
    ----------------------------------------------------------------------------
    """
    acc = get_current_account()
    if not acc:
        return jsonify({
            "success": False, 
            "error": "No Instagram account connected. Please connect your account first."
        }), 401

    job = InstagramService.start_background_scan(acc['id'], acc['username'])
    return jsonify({"success": True, "job": job})

@app.route('/api/scan/progress', methods=['GET'])
def api_scan_progress():
    """
    GET /api/scan/progress
    Real-time progress polling endpoint called by frontend every 1000ms.
    """
    acc = get_current_account()
    if not acc:
        return jsonify({"status": "idle"})

    job = InstagramService.get_scan_progress(acc['id'])
    stats = None
    if job.get('status') == 'completed':
        stats = FirebaseService.get_stats(acc['id'])
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

        stats = FirebaseService.get_stats(acc['id'])
        return jsonify({
            "success": job.get('status') == 'completed',
            "message": job.get('message'),
            "stats": stats
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ==============================================================================
# SECTION 5: RELATIONSHIPS & FILTERING ENDPOINTS
# ==============================================================================
@app.route('/api/relationships', methods=['GET'])
def api_relationships():
    """
    GET /api/relationships
    Retrieves filtered list: 'not_following_back' | 'fans' | 'mutual' | 'all_following' | 'whitelisted'
    """
    acc = get_current_account()
    if not acc:
        return jsonify({"results": [], "total": 0})

    filter_type = request.args.get('filter', 'not_following_back')
    search = request.args.get('search', '').strip() or None
    limit = int(request.args.get('limit', 300))
    offset = int(request.args.get('offset', 0))

    data = FirebaseService.get_relationships(acc['id'], filter_type=filter_type, search=search, limit=limit, offset=offset)
    return jsonify(data)

@app.route('/api/relationships/whitelist', methods=['POST'])
def api_toggle_whitelist():
    """
    POST /api/relationships/whitelist
    Toggles the protection/whitelist flag on a profile in Firebase.
    """
    acc = get_current_account()
    if not acc:
        return jsonify({"success": False, "error": "Not authenticated"}), 401

    data = request.get_json() or {}
    target_username = data.get('username')
    if not target_username:
        return jsonify({"success": False, "error": "Username required"}), 400

    new_val = FirebaseService.toggle_whitelist(acc['id'], target_username)
    return jsonify({
        "success": True,
        "username": target_username,
        "is_whitelisted": bool(new_val)
    })


# ==============================================================================
# SECTION 6: LIVE UNFOLLOW & BULK ENGINE CONTROLS
# ==============================================================================
@app.route('/api/unfollow', methods=['POST'])
def api_unfollow_single():
    """
    POST /api/unfollow
    Calls Instagram API directly to unfollow target profile and logs action to Firebase.
    """
    acc = get_current_account()
    if not acc:
        return jsonify({"success": False, "error": "Not authenticated"}), 401

    data = request.get_json() or {}
    target_username = data.get('username')
    if not target_username:
        return jsonify({"success": False, "error": "Target username required"}), 400

    res = InstagramService.unfollow_single_user(acc['id'], acc['username'], target_username)
    stats = FirebaseService.get_stats(acc['id'])
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
    Safe bulk unfollow sequence with randomized anti-ban human delay.
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
    """GET /api/bulk-unfollow/status -> Returns live countdown and completed accounts."""
    acc = get_current_account()
    if not acc:
        return jsonify({"status": "idle"})

    task_state = bulk_tasks.get(acc['id'])
    if not task_state:
        return jsonify({"status": "idle"})

    return jsonify(task_state)

@app.route('/api/bulk-unfollow/control', methods=['POST'])
def api_bulk_unfollow_control():
    """POST /api/bulk-unfollow/control -> Payload: {"action": "pause" | "resume" | "cancel"}"""
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
# SECTION 7: WEEKLY REPORTS & JSON EXPORT IMPORT
# ==============================================================================
@app.route('/api/reports/weekly', methods=['GET'])
def api_weekly_reports():
    """GET /api/reports/weekly -> Returns accounts that unfollowed over time."""
    acc = get_current_account()
    if not acc:
        return jsonify({"reports": []})

    reports = FirebaseService.get_weekly_reports(acc['id'])
    return jsonify({"reports": reports})

@app.route('/api/import-json', methods=['POST'])
def api_import_json():
    """POST /api/import-json -> Parses official Instagram export JSON files."""
    acc = get_current_account()
    username = request.form.get('username') or (acc['username'] if acc else "imported_user")
    
    account_id = FirebaseService.save_or_update_account(
        username=username,
        user_id="import_" + username,
        full_name=username,
        profile_pic_url=f"https://api.dicebear.com/7.x/identicon/svg?seed={username}",
        mode="export"
    )
    flask_session.permanent = True
    flask_session['active_username'] = username
    connected = flask_session.get('connected_accounts', [])
    if username not in connected:
        connected.append(username)
    flask_session['connected_accounts'] = connected

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
        stats = FirebaseService.get_stats(account_id)
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
# SECTION 8: APPLICATION ENTRY POINT & AUTO-CONNECT
# ==============================================================================
if __name__ == '__main__':
    # Initialize database
    init_db()

    # Automatic Live Connection if real keys are configured in config.py
    if (config.INSTAGRAM_SESSION_ID and 
        config.INSTAGRAM_SESSION_ID != "add your sessionid here"):
        logger.info("Found INSTAGRAM_SESSION_ID in config.py. Auto-connecting live session...")
        res = InstagramService.login_with_sessionid(config.INSTAGRAM_SESSION_ID)
        if res.get('success'):
            logger.info(f"✅ Auto-connected live account @{res['username']} via config.py!")
        else:
            logger.warning(f"Could not auto-connect via config.py sessionid: {res.get('error')}")

    print("=" * 65)
    print("  INSTAGRAM FOLLOWER & UNFOLLOWER SUITE (FIREBASE READY)")
    print(f"  Local Machine:  http://localhost:{config.PORT}")
    print(f"  Mobile/Network: http://{config.HOST}:{config.PORT}")
    print("=" * 65)
    
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG_MODE)
