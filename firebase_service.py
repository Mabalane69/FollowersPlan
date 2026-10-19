"""
==============================================================================
FollowersPlan — Firebase Firestore Integration Service
==============================================================================
This module manages cloud persistence using Google Cloud Firestore / Firebase.
It stores and syncs:
1. Instagram Accounts (profile pic, followers/following counts, session)
2. Relationships (who follows you, who you follow, mutuals, non-followers, whitelist)
3. Scan History & Snapshots
4. Weekly Unfollower Reports (with timestamps and unfollow-back status)
5. Unfollow Execution Logs

>>> CONFIGURATION:
Provide your Firebase keys in `config.py` or `.env`:
FIREBASE_SERVICE_ACCOUNT_KEY_PATH = "add path to your serviceAccountKey.json here"
FIREBASE_PROJECT_ID = "add your project id here"
==============================================================================
"""

import os
import json
import logging
from datetime import datetime
import config

logger = logging.getLogger(__name__)

# Global Firebase Firestore client handle
firestore_db = None
is_firebase_active = False

def init_firebase():
    """
    Initializes Firebase Admin SDK and Firestore client.
    Gracefully falls back to local SQLite if service account key is not provided.
    """
    global firestore_db, is_firebase_active
    
    key_path = config.FIREBASE_SERVICE_ACCOUNT_KEY_PATH
    
    # Check if a real key path is provided and file exists
    if (key_path and 
        key_path != "add path to your serviceAccountKey.json here" and 
        os.path.exists(key_path)):
        try:
            import firebase_admin
            from firebase_admin import credentials, firestore
            
            # Prevent re-initialization if already initialized
            if not firebase_admin._apps:
                cred = credentials.Certificate(key_path)
                options = {}
                if config.FIREBASE_DATABASE_URL and config.FIREBASE_DATABASE_URL != "add your firebase database url here":
                    options['databaseURL'] = config.FIREBASE_DATABASE_URL
                if config.FIREBASE_PROJECT_ID and config.FIREBASE_PROJECT_ID != "add your project id here":
                    options['projectId'] = config.FIREBASE_PROJECT_ID
                    
                firebase_admin.initialize_app(cred, options)
                
            firestore_db = firestore.client()
            is_firebase_active = True
            logger.info("🔥 Firebase Firestore connected successfully!")
            return True
        except Exception as e:
            logger.warning(f"Failed to initialize Firebase Admin SDK: {e}. Falling back to local storage.")
            is_firebase_active = False
            return False
    else:
        logger.info("ℹ️ Firebase service account key not yet configured. Operating on local storage. (Add keys in config.py)")
        is_firebase_active = False
        return False

# Initialize on module load
init_firebase()


# ==============================================================================
# FIREBASE FIRESTORE DATA ADAPTERS
# ==============================================================================
class FirebaseService:
    
    @staticmethod
    def is_connected():
        return is_firebase_active and firestore_db is not None

    @staticmethod
    def save_or_update_account(username, user_id=None, full_name=None, profile_pic_url=None,
                               follower_count=0, following_count=0, session_data=None, mode='live'):
        """
        Saves or updates an Instagram account in Firestore collection 'accounts'.
        """
        if not FirebaseService.is_connected():
            import database
            return database.save_or_update_account(
                username, user_id, full_name, profile_pic_url,
                follower_count, following_count, session_data, mode
            )
            
        try:
            doc_ref = firestore_db.collection('accounts').document(username)
            account_data = {
                'username': username,
                'user_id': str(user_id) if user_id else '',
                'full_name': full_name or username,
                'profile_pic_url': profile_pic_url or '',
                'follower_count': int(follower_count),
                'following_count': int(following_count),
                'mode': mode,
                'last_scanned_at': datetime.utcnow().isoformat()
            }
            if session_data:
                account_data['session_data'] = session_data

            doc_ref.set(account_data, merge=True)
            
            # Mirror to local DB for offline access
            import database
            database.save_or_update_account(
                username, user_id, full_name, profile_pic_url,
                follower_count, following_count, session_data, mode
            )
            return username
        except Exception as e:
            logger.error(f"Firestore save_or_update_account error: {e}")
            import database
            return database.save_or_update_account(
                username, user_id, full_name, profile_pic_url,
                follower_count, following_count, session_data, mode
            )

    @staticmethod
    def get_account_by_username(username):
        """Retrieves account document from Firestore 'accounts' collection."""
        if not FirebaseService.is_connected():
            import database
            return database.get_account_by_username(username)
            
        try:
            doc = firestore_db.collection('accounts').document(username).get()
            if doc.exists:
                data = doc.to_dict()
                data['id'] = username
                return data
        except Exception as e:
            logger.error(f"Firestore get_account_by_username error: {e}")
            
        import database
        return database.get_account_by_username(username)

    @staticmethod
    def get_latest_account():
        """Retrieves most recently scanned account."""
        if not FirebaseService.is_connected():
            import database
            return database.get_latest_account()
            
        try:
            docs = firestore_db.collection('accounts').order_by(
                'last_scanned_at', direction=firestore.Query.DESCENDING
            ).limit(1).stream()
            for doc in docs:
                data = doc.to_dict()
                data['id'] = doc.id
                return data
        except Exception as e:
            logger.error(f"Firestore get_latest_account error: {e}")
            
        import database
        return database.get_latest_account()

    @staticmethod
    def get_all_accounts():
        """Retrieves all registered accounts across Firebase / local database."""
        if not FirebaseService.is_connected():
            import database
            return database.get_all_accounts()
            
        try:
            docs = firestore_db.collection('accounts').stream()
            results = []
            for doc in docs:
                data = doc.to_dict()
                data['id'] = doc.id
                results.append(data)
            if results:
                return results
        except Exception as e:
            logger.error(f"Firestore get_all_accounts error: {e}")
            
        import database
        return database.get_all_accounts()

    @staticmethod
    def record_scan_snapshot(account_id, followers_list, following_list):
        """
        Calculates relationship diffs (Non-followers, Fans, Mutuals, Lost Followers)
        and persists the snapshot into Firestore and local database.
        """
        # Always run calculation and local mirror via database.py
        import database
        snapshot = database.record_scan_snapshot(account_id, followers_list, following_list)
        
        if not FirebaseService.is_connected():
            return snapshot
            
        try:
            # Sync scan snapshot to Firestore
            acc = database.get_account_by_username(str(account_id)) or database.get_latest_account()
            username = acc['username'] if acc else str(account_id)
            
            scan_doc = firestore_db.collection('accounts').document(username).collection('scans').document()
            scan_data = {
                'scanned_at': datetime.utcnow().isoformat(),
                'followers_count': len(followers_list),
                'following_count': len(following_list),
                'not_following_back_count': snapshot['not_following_back_count'],
                'fans_count': snapshot['fans_count'],
                'mutual_count': snapshot['mutual_count'],
                'lost_followers_count': snapshot['lost_followers_count']
            }
            scan_doc.set(scan_data)
            
            # Batch update relationships in Firestore
            batch = firestore_db.batch()
            rel_coll = firestore_db.collection('accounts').document(username).collection('relationships')
            
            follower_set = {f['username'] for f in followers_list}
            following_set = {f['username'] for f in following_list}
            all_users = {f['username']: f for f in followers_list + following_list}
            
            count = 0
            for u, data in all_users.items():
                doc_ref = rel_coll.document(u)
                rel_data = {
                    'target_username': u,
                    'target_full_name': data.get('full_name', ''),
                    'target_profile_pic_url': data.get('profile_pic_url', ''),
                    'is_verified': bool(data.get('is_verified')),
                    'is_private': bool(data.get('is_private')),
                    'follows_me': (u in follower_set),
                    'followed_by_me': (u in following_set),
                    'updated_at': datetime.utcnow().isoformat()
                }
                batch.set(doc_ref, rel_data, merge=True)
                count += 1
                if count >= 450: # Firestore batch limit is 500
                    batch.commit()
                    batch = firestore_db.batch()
                    count = 0
            if count > 0:
                batch.commit()
                
            logger.info("🔥 Firestore snapshot and relationships synchronized successfully.")
        except Exception as e:
            logger.error(f"Firestore record_scan_snapshot sync error: {e}")
            
        return snapshot

    @staticmethod
    def get_relationships(account_id, filter_type='not_following_back', search=None, limit=300, offset=0):
        """Retrieves relationships matching the active filter and search query."""
        import database
        return database.get_relationships(account_id, filter_type=filter_type, search=search, limit=limit, offset=offset)

    @staticmethod
    def mark_unfollowed(account_id, username, log_status='success', err=None):
        """Marks profile as unfollowed in Firestore and local database."""
        import database
        database.mark_unfollowed(account_id, username, log_status=log_status, err=err)
        
        if not FirebaseService.is_connected():
            return
            
        try:
            acc = database.get_account_by_username(str(account_id)) or database.get_latest_account()
            acc_name = acc['username'] if acc else str(account_id)
            
            # Update relationship in Firestore
            rel_ref = firestore_db.collection('accounts').document(acc_name).collection('relationships').document(username)
            rel_ref.set({'followed_by_me': False, 'unfollowed_by_app': True, 'updated_at': datetime.utcnow().isoformat()}, merge=True)
            
            # Add to unfollow_logs collection
            log_ref = firestore_db.collection('accounts').document(acc_name).collection('unfollow_logs').document()
            log_ref.set({
                'target_username': username,
                'status': log_status,
                'error_message': str(err) if err else '',
                'timestamp': datetime.utcnow().isoformat()
            })
        except Exception as e:
            logger.error(f"Firestore mark_unfollowed error: {e}")

    @staticmethod
    def toggle_whitelist(account_id, username):
        """Toggles whitelist protection in Firestore and local database."""
        import database
        new_val = database.toggle_whitelist(account_id, username)
        
        if FirebaseService.is_connected():
            try:
                acc = database.get_account_by_username(str(account_id)) or database.get_latest_account()
                acc_name = acc['username'] if acc else str(account_id)
                rel_ref = firestore_db.collection('accounts').document(acc_name).collection('relationships').document(username)
                rel_ref.set({'is_whitelisted': bool(new_val)}, merge=True)
            except Exception as e:
                logger.error(f"Firestore toggle_whitelist error: {e}")
                
        return new_val

    @staticmethod
    def get_weekly_reports(account_id):
        """Retrieves weekly unfollower reports."""
        import database
        return database.get_weekly_reports(account_id)

    @staticmethod
    def get_stats(account_id):
        """Retrieves follower, following, non-follower, and mutual counts."""
        import database
        return database.get_stats(account_id)
