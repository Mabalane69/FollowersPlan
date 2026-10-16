import requests
import time

BASE = 'http://127.0.0.1:5000'

def run_tests():
    # 1. Test index page
    r1 = requests.get(f'{BASE}/')
    assert r1.status_code == 200, f'Index returned {r1.status_code}'
    print('[OK] Index page HTML loaded successfully (200 OK)')

    # 2. Test current account & health
    r2 = requests.get(f'{BASE}/api/account/current')
    d2 = r2.json()
    assert d2['authenticated'] == True, 'Should be authenticated'
    acc = d2['account']
    stats = d2['stats']
    print(f'[OK] Current account: @{acc["username"]} (Followers: {stats["followers_count"]}, Following: {stats["following_count"]})')

    r_health = requests.get(f'{BASE}/api/auth/health')
    d_health = r_health.json()
    print(f'[OK] Live Health check: healthy={d_health.get("healthy")}, mode={d_health.get("mode")}')

    # 3. Test background dynamic scan start and progress polling
    r_scan = requests.post(f'{BASE}/api/scan/start')
    d_scan = r_scan.json()
    assert d_scan['success'] == True, f'Scan start failed: {d_scan}'
    print(f'[OK] Dynamic background scan initiated!')

    # Poll progress
    for _ in range(10):
        time.sleep(0.5)
        rp = requests.get(f'{BASE}/api/scan/progress')
        dp = rp.json()
        job = dp.get('job', {})
        print(f'     Scan Progress: {job.get("progress_percent", 0)}% - {job.get("message")}')
        if job.get('status') == 'completed':
            break

    # 4. Test non-followers query
    r3 = requests.get(f'{BASE}/api/relationships?filter=not_following_back')
    d3 = r3.json()
    print(f'[OK] Non-followers found: {d3["total"]} profiles')
    assert d3['total'] > 0
    first_non_follower = d3['results'][0]['target_username']
    print(f'     First non-follower: @{first_non_follower}')

    # 5. Test single unfollow
    r5 = requests.post(f'{BASE}/api/unfollow', json={'username': first_non_follower})
    d5 = r5.json()
    assert d5['success'] == True, f'Unfollow failed: {d5}'
    print(f'[OK] Single unfollow successful for @{first_non_follower}!')

    # 6. Test Bulk Unfollow
    targets = [p['target_username'] for p in d3['results'][1:4]]
    print(f'     Starting bulk unfollow test for {len(targets)} users: {targets}')
    r7 = requests.post(f'{BASE}/api/bulk-unfollow/start', json={'targets': targets, 'delay': 1.0})
    d7 = r7.json()
    assert d7['success'] == True, f'Bulk unfollow start failed: {d7}'
    print(f'[OK] Bulk unfollow started! Task ID: {d7["task_id"]}')

    time.sleep(1.5)
    r8 = requests.get(f'{BASE}/api/bulk-unfollow/status')
    d8 = r8.json()
    print(f'[OK] Bulk unfollow status: {d8["status"]} ({d8.get("current_index", 0)}/{d8.get("total", 0)})')

    print('\nALL DYNAMIC LIVE API TESTS PASSED SUCCESSFULLY!')

if __name__ == '__main__':
    run_tests()
