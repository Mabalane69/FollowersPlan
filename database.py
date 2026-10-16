import sqlite3
import json
import os
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instafollowers.db')

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    c = conn.cursor()
    
    # Accounts table
    c.execute('''
    CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        user_id TEXT,
        full_name TEXT,
        profile_pic_url TEXT,
        follower_count INTEGER DEFAULT 0,
        following_count INTEGER DEFAULT 0,
        session_data TEXT,
        mode TEXT DEFAULT 'demo', -- 'live', 'export', 'demo'
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_scanned_at TIMESTAMP
    )
    ''')
    
    # Scan history snapshots
    c.execute('''
    CREATE TABLE IF NOT EXISTS scans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL,
        scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        followers_count INTEGER DEFAULT 0,
        following_count INTEGER DEFAULT 0,
        not_following_back_count INTEGER DEFAULT 0,
        fans_count INTEGER DEFAULT 0,
        mutual_count INTEGER DEFAULT 0,
        lost_followers_count INTEGER DEFAULT 0,
        FOREIGN KEY (account_id) REFERENCES accounts (id)
    )
    ''')
    
    # Relationships table
    c.execute('''
    CREATE TABLE IF NOT EXISTS relationships (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL,
        target_user_id TEXT,
        target_username TEXT NOT NULL,
        target_full_name TEXT,
        target_profile_pic_url TEXT,
        is_verified INTEGER DEFAULT 0,
        is_private INTEGER DEFAULT 0,
        follows_me INTEGER DEFAULT 0,
        followed_by_me INTEGER DEFAULT 0,
        unfollowed_by_app INTEGER DEFAULT 0,
        is_whitelisted INTEGER DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (account_id, target_username),
        FOREIGN KEY (account_id) REFERENCES accounts (id)
    )
    ''')
    
    # Weekly unfollower reports
    c.execute('''
    CREATE TABLE IF NOT EXISTS weekly_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL,
        week_identifier TEXT NOT NULL,
        target_username TEXT NOT NULL,
        target_full_name TEXT,
        target_profile_pic_url TEXT,
        unfollowed_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        we_unfollowed INTEGER DEFAULT 0,
        FOREIGN KEY (account_id) REFERENCES accounts (id)
    )
    ''')
    
    # Unfollow activity logs
    c.execute('''
    CREATE TABLE IF NOT EXISTS unfollow_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL,
        target_username TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status TEXT, -- 'success', 'failed', 'simulated'
        error_message TEXT,
        FOREIGN KEY (account_id) REFERENCES accounts (id)
    )
    ''')
    
    conn.commit()
    conn.close()

def save_or_update_account(username, user_id=None, full_name=None, profile_pic_url=None,
                           follower_count=0, following_count=0, session_data=None, mode='live'):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
    INSERT INTO accounts (username, user_id, full_name, profile_pic_url, follower_count, following_count, session_data, mode, last_scanned_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(username) DO UPDATE SET
        user_id = COALESCE(excluded.user_id, accounts.user_id),
        full_name = COALESCE(excluded.full_name, accounts.full_name),
        profile_pic_url = COALESCE(excluded.profile_pic_url, accounts.profile_pic_url),
        follower_count = excluded.follower_count,
        following_count = excluded.following_count,
        session_data = COALESCE(excluded.session_data, accounts.session_data),
        mode = excluded.mode,
        last_scanned_at = CURRENT_TIMESTAMP
    ''', (username, user_id, full_name, profile_pic_url, follower_count, following_count, session_data, mode))
    conn.commit()
    account_id = c.execute('SELECT id FROM accounts WHERE username = ?', (username,)).fetchone()['id']
    conn.close()
    return account_id

def get_account_by_username(username):
    conn = get_connection()
    c = conn.cursor()
    account = c.execute('SELECT * FROM accounts WHERE username = ?', (username,)).fetchone()
    conn.close()
    return dict(account) if account else None

def get_latest_account():
    conn = get_connection()
    c = conn.cursor()
    account = c.execute('SELECT * FROM accounts ORDER BY last_scanned_at DESC LIMIT 1').fetchone()
    conn.close()
    return dict(account) if account else None

def record_scan_snapshot(account_id, followers_list, following_list):
    """
    Compares current followers and following with database to:
    1. Detect lost followers (users who followed previously but don't anymore)
    2. Save all current relationships (mutuals, fans, non-followers)
    3. Add lost followers to weekly_reports
    """
    conn = get_connection()
    c = conn.cursor()
    
    # Map sets
    follower_dict = {f['username']: f for f in followers_list}
    following_dict = {f['username']: f for f in following_list}
    
    follower_usernames = set(follower_dict.keys())
    following_usernames = set(following_dict.keys())
    
    # 1. Fetch previous followers for this account to detect who unfollowed
    prev_followers_rows = c.execute('''
        SELECT target_username, target_full_name, target_profile_pic_url 
        FROM relationships 
        WHERE account_id = ? AND follows_me = 1
    ''', (account_id,)).fetchall()
    
    prev_followers = {row['target_username']: dict(row) for row in prev_followers_rows}
    
    # Lost followers = previously followed me, but not in current follower_usernames
    lost_usernames = set(prev_followers.keys()) - follower_usernames
    current_week = datetime.now().strftime('%Y-W%W')
    
    lost_followers_count = len(lost_usernames)
    for lost_user in lost_usernames:
        user_info = prev_followers.get(lost_user, {})
        # Check if already recorded in this week's reports
        exists = c.execute('''
            SELECT id FROM weekly_reports 
            WHERE account_id = ? AND target_username = ? AND week_identifier = ?
        ''', (account_id, lost_user, current_week)).fetchone()
        
        if not exists:
            c.execute('''
                INSERT INTO weekly_reports (account_id, week_identifier, target_username, target_full_name, target_profile_pic_url)
                VALUES (?, ?, ?, ?, ?)
            ''', (account_id, current_week, lost_user, user_info.get('target_full_name', ''), user_info.get('target_profile_pic_url', '')))
    
    # 2. Update relationships table
    all_usernames = follower_usernames.union(following_usernames)
    
    for u in all_usernames:
        f_data = follower_dict.get(u) or following_dict.get(u) or {}
        user_id = f_data.get('id', '')
        full_name = f_data.get('full_name', '')
        pic_url = f_data.get('profile_pic_url', '')
        is_verified = 1 if f_data.get('is_verified') else 0
        is_private = 1 if f_data.get('is_private') else 0
        follows_me = 1 if u in follower_usernames else 0
        followed_by_me = 1 if u in following_usernames else 0
        
        c.execute('''
        INSERT INTO relationships (account_id, target_user_id, target_username, target_full_name, target_profile_pic_url, is_verified, is_private, follows_me, followed_by_me, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(account_id, target_username) DO UPDATE SET
            target_user_id = COALESCE(excluded.target_user_id, relationships.target_user_id),
            target_full_name = excluded.target_full_name,
            target_profile_pic_url = excluded.target_profile_pic_url,
            is_verified = excluded.is_verified,
            is_private = excluded.is_private,
            follows_me = excluded.follows_me,
            followed_by_me = excluded.followed_by_me,
            updated_at = CURRENT_TIMESTAMP
        ''', (account_id, user_id, u, full_name, pic_url, is_verified, is_private, follows_me, followed_by_me))
        
    # Also for any lost follower who isn't following anymore
    c.execute('''
        UPDATE relationships SET follows_me = 0 
        WHERE account_id = ? AND target_username NOT IN ({})
    '''.format(','.join('?' * len(follower_usernames)) if follower_usernames else "''"), 
    ([account_id] + list(follower_usernames)) if follower_usernames else [account_id])
    
    # 3. Calculate category counts
    not_following_back = c.execute('SELECT COUNT(*) FROM relationships WHERE account_id = ? AND followed_by_me = 1 AND follows_me = 0', (account_id,)).fetchone()[0]
    fans = c.execute('SELECT COUNT(*) FROM relationships WHERE account_id = ? AND followed_by_me = 0 AND follows_me = 1', (account_id,)).fetchone()[0]
    mutual = c.execute('SELECT COUNT(*) FROM relationships WHERE account_id = ? AND followed_by_me = 1 AND follows_me = 1', (account_id,)).fetchone()[0]
    
    # 4. Insert scan record
    c.execute('''
        INSERT INTO scans (account_id, followers_count, following_count, not_following_back_count, fans_count, mutual_count, lost_followers_count)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (account_id, len(follower_usernames), len(following_usernames), not_following_back, fans, mutual, lost_followers_count))
    
    # 5. Update account totals
    c.execute('''
        UPDATE accounts SET follower_count = ?, following_count = ?, last_scanned_at = CURRENT_TIMESTAMP
        WHERE id = ?
    ''', (len(follower_usernames), len(following_usernames), account_id))
    
    conn.commit()
    conn.close()
    
    return {
        "followers_count": len(follower_usernames),
        "following_count": len(following_usernames),
        "not_following_back_count": not_following_back,
        "fans_count": fans,
        "mutual_count": mutual,
        "lost_followers_count": lost_followers_count
    }

def get_relationships(account_id, filter_type='not_following_back', search=None, limit=200, offset=0):
    conn = get_connection()
    c = conn.cursor()
    
    query = 'SELECT * FROM relationships WHERE account_id = ?'
    params = [account_id]
    
    if filter_type == 'not_following_back':
        query += ' AND followed_by_me = 1 AND follows_me = 0'
    elif filter_type == 'fans':
        query += ' AND followed_by_me = 0 AND follows_me = 1'
    elif filter_type == 'mutual':
        query += ' AND followed_by_me = 1 AND follows_me = 1'
    elif filter_type == 'all_following':
        query += ' AND followed_by_me = 1'
    elif filter_type == 'all_followers':
        query += ' AND follows_me = 1'
    elif filter_type == 'whitelisted':
        query += ' AND is_whitelisted = 1'
        
    if search:
        query += ' AND (target_username LIKE ? OR target_full_name LIKE ?)'
        params.extend([f'%{search}%', f'%{search}%'])
        
    # Order by whitelisted asc, verified desc, username asc
    query += ' ORDER BY is_whitelisted ASC, is_verified DESC, target_username ASC LIMIT ? OFFSET ?'
    params.extend([limit, offset])
    
    rows = c.execute(query, params).fetchall()
    results = [dict(r) for r in rows]
    
    # Total count for pagination
    count_query = query.replace('SELECT *', 'SELECT COUNT(*)').split(' ORDER BY ')[0]
    total = c.execute(count_query, params[:-2]).fetchone()[0]
    
    conn.close()
    return {"results": results, "total": total}

def mark_unfollowed(account_id, username, log_status='success', err=None):
    conn = get_connection()
    c = conn.cursor()
    
    # Update relationship
    c.execute('''
        UPDATE relationships 
        SET followed_by_me = 0, unfollowed_by_app = 1, updated_at = CURRENT_TIMESTAMP
        WHERE account_id = ? AND target_username = ?
    ''', (account_id, username))
    
    # Also update weekly report if user was in weekly unfollowers
    c.execute('''
        UPDATE weekly_reports
        SET we_unfollowed = 1
        WHERE account_id = ? AND target_username = ?
    ''', (account_id, username))
    
    # Add to unfollow_logs
    c.execute('''
        INSERT INTO unfollow_logs (account_id, target_username, status, error_message)
        VALUES (?, ?, ?, ?)
    ''', (account_id, username, log_status, err))
    
    # Update account following_count
    c.execute('''
        UPDATE accounts SET following_count = MAX(0, following_count - 1)
        WHERE id = ?
    ''', (account_id,))
    
    conn.commit()
    conn.close()

def toggle_whitelist(account_id, username):
    conn = get_connection()
    c = conn.cursor()
    row = c.execute('SELECT is_whitelisted FROM relationships WHERE account_id = ? AND target_username = ?', (account_id, username)).fetchone()
    if row:
        new_val = 0 if row['is_whitelisted'] else 1
        c.execute('UPDATE relationships SET is_whitelisted = ? WHERE account_id = ? AND target_username = ?', (new_val, account_id, username))
        conn.commit()
        conn.close()
        return new_val
    conn.close()
    return 0

def get_weekly_reports(account_id):
    conn = get_connection()
    c = conn.cursor()
    rows = c.execute('''
        SELECT w.*, r.followed_by_me, r.follows_me
        FROM weekly_reports w
        LEFT JOIN relationships r ON w.account_id = r.account_id AND w.target_username = r.target_username
        WHERE w.account_id = ?
        ORDER BY w.unfollowed_date DESC
    ''', (account_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_stats(account_id):
    conn = get_connection()
    c = conn.cursor()
    
    acc = c.execute('SELECT * FROM accounts WHERE id = ?', (account_id,)).fetchone()
    if not acc:
        conn.close()
        return None
        
    followers = acc['follower_count']
    following = acc['following_count']
    
    not_following_back = c.execute('SELECT COUNT(*) FROM relationships WHERE account_id = ? AND followed_by_me = 1 AND follows_me = 0', (account_id,)).fetchone()[0]
    fans = c.execute('SELECT COUNT(*) FROM relationships WHERE account_id = ? AND followed_by_me = 0 AND follows_me = 1', (account_id,)).fetchone()[0]
    mutual = c.execute('SELECT COUNT(*) FROM relationships WHERE account_id = ? AND followed_by_me = 1 AND follows_me = 1', (account_id,)).fetchone()[0]
    unfollowed_by_app = c.execute('SELECT COUNT(*) FROM relationships WHERE account_id = ? AND unfollowed_by_app = 1', (account_id,)).fetchone()[0]
    lost_weekly = c.execute('SELECT COUNT(*) FROM weekly_reports WHERE account_id = ?', (account_id,)).fetchone()[0]
    
    # Recent scans history for sparkline
    scan_history = c.execute('''
        SELECT scanned_at, followers_count, following_count, not_following_back_count, lost_followers_count
        FROM scans WHERE account_id = ?
        ORDER BY scanned_at DESC LIMIT 7
    ''', (account_id,)).fetchall()
    
    conn.close()
    return {
        "account": dict(acc),
        "followers_count": followers,
        "following_count": following,
        "not_following_back_count": not_following_back,
        "fans_count": fans,
        "mutual_count": mutual,
        "unfollowed_by_app": unfollowed_by_app,
        "lost_weekly": lost_weekly,
        "scan_history": [dict(s) for s in scan_history]
    }

# Initialize database tables on load
init_db()
