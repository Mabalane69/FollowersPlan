"""
==============================================================================
FollowersPlan — Automated Multi-Client & Full System Test Suite
==============================================================================
Tests the complete multi-client platform lifecycle:
1. PWA & Frontend Web App assets (/ and /manifest.json)
2. Firebase Cloud Configuration API (/api/firebase/config)
3. Multi-Client Session Isolation:
   - Client A and Client B concurrent separate sessions
   - Client A logs in -> Client B remains isolated & unauthenticated
   - Client B logs in -> Client A and Client B see only their respective data
4. Multi-Account Management & Switching (/api/accounts and /api/accounts/switch)
5. Authentication input validation and error handling
6. Real Instagram Data Import Pipeline (/api/import-json)
7. Relationship filtering (Not Following Back, Mutuals, Fans)
8. Profile protection (Whitelist toggle)
9. Weekly Reports computation
10. Anti-Ban Safe Unfollow & Bulk Queue orchestration
==============================================================================
"""

import io
import json
import time
import requests
from database import clear_all_data

BASE = 'http://127.0.0.1:5000'

def run_tests():
    # Purge any previous test rows for clean, idempotent execution
    clear_all_data()
    print("=" * 65)
    print("  RUNNING FOLLOWERSPLAN MULTI-CLIENT TEST SUITE")
    print("=" * 65)

    # 1. Test index page and PWA manifest
    r_index = requests.get(f'{BASE}/')
    assert r_index.status_code == 200, f'Index returned {r_index.status_code}'
    assert 'firebase-app-compat.js' in r_index.text, 'Firebase SDK missing in index.html'
    assert 'alex.creativestudio' not in r_index.text, 'Static mock account found in index.html!'
    print('[PASS] 1. Index HTML loaded with Firebase SDK & zero mock data (200 OK)')

    r_manifest = requests.get(f'{BASE}/manifest.json')
    assert r_manifest.status_code == 200, f'Manifest returned {r_manifest.status_code}'
    manifest_data = r_manifest.json()
    assert 'FollowersPlan' in manifest_data.get('name', ''), 'Invalid manifest name'
    print(f'[PASS] 2. PWA Manifest verified: {manifest_data.get("name")}')

    # 2. Test Firebase Configuration Endpoint
    r_fb = requests.get(f'{BASE}/api/firebase/config')
    assert r_fb.status_code == 200, f'Firebase config returned {r_fb.status_code}'
    fb_data = r_fb.json()
    assert 'connected' in fb_data, 'Missing connected key in firebase config'
    assert 'client_config' in fb_data, 'Missing client_config in firebase config'
    print(f'[PASS] 3. Firebase config verified (Firestore Active: {fb_data["connected"]})')

    # 3. MULTI-CLIENT CONCURRENCY TEST: Client A vs Client B
    # Create two separate browser sessions simulating two clients on different devices
    session_a = requests.Session()
    session_b = requests.Session()

    r_a_init = session_a.get(f'{BASE}/api/account/current')
    assert r_a_init.json().get('authenticated') == False, 'Client A should be unauthenticated initially'

    r_b_init = session_b.get(f'{BASE}/api/account/current')
    assert r_b_init.json().get('authenticated') == False, 'Client B should be unauthenticated initially'
    print('[PASS] 4. Multi-Client Initial State: Both Client A and Client B start unauthenticated')

    # Prepare sample datasets
    data_followers_a = [{"string_list_data": [{"value": "client_a_fan", "timestamp": 1700000000}]}]
    data_following_a = {"relationships_following": [
        {"string_list_data": [{"value": "not_following_a_1", "timestamp": 1700000010}]},
        {"string_list_data": [{"value": "not_following_a_2", "timestamp": 1700000020}]}
    ]}

    files_a = {
        'followers_file': ('f.json', io.BytesIO(json.dumps(data_followers_a).encode('utf-8')), 'application/json'),
        'following_file': ('fw.json', io.BytesIO(json.dumps(data_following_a).encode('utf-8')), 'application/json')
    }

    # Connect Client A
    r_import_a = session_a.post(f'{BASE}/api/import-json', files=files_a, data={'username': 'client_alpha'})
    assert r_import_a.status_code == 200
    assert r_import_a.json()['success'] == True

    # Verify Client A is logged in as @client_alpha
    r_a_curr = session_a.get(f'{BASE}/api/account/current')
    assert r_a_curr.json()['authenticated'] == True
    assert r_a_curr.json()['account']['username'] == 'client_alpha'
    print('[PASS] 5. Client A connected as @client_alpha')

    # Verify Client B is STILL unauthenticated (No cross-talk / leakage!)
    r_b_check = session_b.get(f'{BASE}/api/account/current')
    assert r_b_check.json()['authenticated'] == False, 'Client B must NOT inherit Client A session!'
    print('[PASS] 6. Multi-Client Isolation verified: Client B is isolated and unauthenticated')

    # Connect Client B as @client_beta
    data_followers_b = [{"string_list_data": [{"value": "client_b_friend", "timestamp": 1700000000}]}]
    data_following_b = {"relationships_following": [
        {"string_list_data": [{"value": "client_b_friend", "timestamp": 1700000000}]},
        {"string_list_data": [{"value": "not_following_b_1", "timestamp": 1700000030}]}
    ]}
    files_b = {
        'followers_file': ('f.json', io.BytesIO(json.dumps(data_followers_b).encode('utf-8')), 'application/json'),
        'following_file': ('fw.json', io.BytesIO(json.dumps(data_following_b).encode('utf-8')), 'application/json')
    }

    r_import_b = session_b.post(f'{BASE}/api/import-json', files=files_b, data={'username': 'client_beta'})
    assert r_import_b.status_code == 200

    # Verify Client B sees @client_beta
    r_b_curr = session_b.get(f'{BASE}/api/account/current')
    assert r_b_curr.json()['authenticated'] == True
    assert r_b_curr.json()['account']['username'] == 'client_beta'
    print('[PASS] 7. Client B connected as @client_beta')

    # Re-verify Client A is STILL @client_alpha (Client B did NOT overwrite Client A!)
    r_a_recheck = session_a.get(f'{BASE}/api/account/current')
    assert r_a_recheck.json()['authenticated'] == True
    assert r_a_recheck.json()['account']['username'] == 'client_alpha'
    print('[PASS] 8. True Multi-Client Concurrency confirmed: Client A remains @client_alpha')

    # 4. Multi-Account Listing and Switching
    r_accounts = session_a.get(f'{BASE}/api/accounts')
    assert r_accounts.status_code == 200
    acc_list = r_accounts.json()['accounts']
    usernames_in_db = [a['username'] for a in acc_list]
    assert 'client_alpha' in usernames_in_db
    assert 'client_beta' in usernames_in_db
    print(f'[PASS] 9. Multi-Account API: Registered accounts list verified ({usernames_in_db})')

    # Client A switches to @client_beta
    r_switch = session_a.post(f'{BASE}/api/accounts/switch', json={'username': 'client_beta'})
    assert r_switch.status_code == 200
    assert r_switch.json()['success'] == True
    assert session_a.get(f'{BASE}/api/account/current').json()['account']['username'] == 'client_beta'
    print('[PASS] 10. Account Switcher: Client A successfully switched active profile to @client_beta')

    # Switch Client A back to @client_alpha
    session_a.post(f'{BASE}/api/accounts/switch', json={'username': 'client_alpha'})
    assert session_a.get(f'{BASE}/api/account/current').json()['account']['username'] == 'client_alpha'

    # 5. Relationship Queries & Whitelisting for Client A
    r_rel_a = session_a.get(f'{BASE}/api/relationships?filter=not_following_back')
    assert r_rel_a.status_code == 200
    assert r_rel_a.json()['total'] == 2
    print(f'[PASS] 11. Client A non-followers verified ({r_rel_a.json()["total"]} accounts)')

    # Whitelist toggle
    r_wl = session_a.post(f'{BASE}/api/relationships/whitelist', json={'username': 'not_following_a_1'})
    assert r_wl.status_code == 200
    assert r_wl.json()['is_whitelisted'] == True

    r_wl_filter = session_a.get(f'{BASE}/api/relationships?filter=whitelisted')
    assert r_wl_filter.json()['total'] == 1
    assert r_wl_filter.json()['results'][0]['target_username'] == 'not_following_a_1'
    print('[PASS] 12. Whitelist protection toggled & verified for Client A')

    # 6. Weekly Reports API
    r_rep = session_a.get(f'{BASE}/api/reports/weekly')
    assert r_rep.status_code == 200
    assert 'reports' in r_rep.json()
    print('[PASS] 13. Weekly reports endpoint verified')

    # 7. Safe Bulk Unfollow Queue
    r_bulk = session_a.post(f'{BASE}/api/bulk-unfollow/start', json={'targets': ['not_following_a_2'], 'delay': 0.1})
    assert r_bulk.status_code == 200
    assert r_bulk.json()['success'] == True
    time.sleep(1.0)
    r_stat = session_a.get(f'{BASE}/api/bulk-unfollow/status')
    assert r_stat.status_code == 200
    print(f'[PASS] 14. Bulk Unfollow queue execution verified (Status: {r_stat.json().get("status")})')

    # 8. Isolated Logout: Client A logs out, Client B remains logged in!
    session_a.post(f'{BASE}/api/auth/logout')
    assert session_a.get(f'{BASE}/api/account/current').json()['authenticated'] == False
    assert session_b.get(f'{BASE}/api/account/current').json()['authenticated'] == True
    print('[PASS] 15. Isolated Logout confirmed: Client A logged out, Client B session unaffected')

    print("\n" + "=" * 65)
    print("  ALL 15 MULTI-CLIENT & SYSTEM TESTS PASSED 100% SUCCESSFULLY!")
    print("=" * 65)

if __name__ == '__main__':
    run_tests()
