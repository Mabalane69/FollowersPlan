import random
from datetime import datetime, timedelta
from database import save_or_update_account, record_scan_snapshot, get_connection

DEMO_USER = {
    "username": "alex.creativestudio",
    "user_id": "8492049182",
    "full_name": "Alex Vance | Visual Designer",
    "profile_pic_url": "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=200&h=200&fit=crop&crop=faces",
    "follower_count": 528,
    "following_count": 612
}

SAMPLE_PROFILES = [
    # Non-followers (We follow them, they do NOT follow us back)
    {"username": "travel_with_elena", "full_name": "Elena Rostova", "pic": "https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=150&h=150&fit=crop", "verified": True, "private": False, "category": "non_follower"},
    {"username": "tech_minimalist", "full_name": "David Chen", "pic": "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=150&h=150&fit=crop", "verified": False, "private": False, "category": "non_follower"},
    {"username": "vogue_daily_vibes", "full_name": "Vogue Curators", "pic": "https://images.unsplash.com/photo-1517841905240-472988babdf9?w=150&h=150&fit=crop", "verified": True, "private": False, "category": "non_follower"},
    {"username": "urban_architects", "full_name": "Søren Kjeldsen", "pic": "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=150&h=150&fit=crop", "verified": False, "private": True, "category": "non_follower"},
    {"username": "crypto_alpha_insights", "full_name": "Marcus Aurelius Tech", "pic": "https://images.unsplash.com/photo-1472099645785-5658abf4ff4e?w=150&h=150&fit=crop", "verified": False, "private": False, "category": "non_follower"},
    {"username": "coffee_and_code", "full_name": "Sophia Zhang", "pic": "https://images.unsplash.com/photo-1544005313-94ddf0286df2?w=150&h=150&fit=crop", "verified": False, "private": False, "category": "non_follower"},
    {"username": "hyper_aesthetic", "full_name": "Studio Hyperion", "pic": "https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=150&h=150&fit=crop", "verified": False, "private": False, "category": "non_follower"},
    {"username": "lucas_nomad", "full_name": "Lucas Morales", "pic": "https://images.unsplash.com/photo-1519085360753-af0119f7cbe7?w=150&h=150&fit=crop", "verified": False, "private": False, "category": "non_follower"},
    {"username": "neo_tokyo_drifter", "full_name": "Kenji Sato", "pic": "https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?w=150&h=150&fit=crop", "verified": False, "private": False, "category": "non_follower"},
    {"username": "emerald_interior", "full_name": "Emma Wright Design", "pic": "https://images.unsplash.com/photo-1531746020798-e6953c6e8e04?w=150&h=150&fit=crop", "verified": False, "private": False, "category": "non_follower"},
    {"username": "fit_fuel_coaching", "full_name": "Liam Henderson", "pic": "https://images.unsplash.com/photo-1522075469751-3a6694fb2f61?w=150&h=150&fit=crop", "verified": False, "private": True, "category": "non_follower"},
    {"username": "pixel_craft_studio", "full_name": "Clara Dupont", "pic": "https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?w=150&h=150&fit=crop", "verified": False, "private": False, "category": "non_follower"},

    # Mutual followers (We follow each other)
    {"username": "maya_creative", "full_name": "Maya Lin", "pic": "https://images.unsplash.com/photo-1580489944761-15a19d654956?w=150&h=150&fit=crop", "verified": True, "private": False, "category": "mutual"},
    {"username": "sam_developer", "full_name": "Samuel Reed", "pic": "https://images.unsplash.com/photo-1539571696357-5a69c17a67c6?w=150&h=150&fit=crop", "verified": False, "private": False, "category": "mutual"},
    {"username": "chloe_visuals", "full_name": "Chloe Bennett", "pic": "https://images.unsplash.com/photo-1517841905240-472988babdf9?w=150&h=150&fit=crop", "verified": False, "private": False, "category": "mutual"},
    {"username": "oliver_film", "full_name": "Oliver Hansen", "pic": "https://images.unsplash.com/photo-1492562080023-ab3db95bfbce?w=150&h=150&fit=crop", "verified": False, "private": False, "category": "mutual"},
    {"username": "natalie_ux", "full_name": "Natalie Cruz", "pic": "https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=150&h=150&fit=crop", "verified": False, "private": False, "category": "mutual"},
    {"username": "jordan_beats", "full_name": "Jordan Mills", "pic": "https://images.unsplash.com/photo-1463453091185-61582044d556?w=150&h=150&fit=crop", "verified": False, "private": False, "category": "mutual"},

    # Fans (They follow us, but we don't follow them back)
    {"username": "art_lover_99", "full_name": "Hannah Abbott", "pic": "https://images.unsplash.com/photo-1529626455594-4ff0802cfb7e?w=150&h=150&fit=crop", "verified": False, "private": False, "category": "fan"},
    {"username": "gadgets_geek", "full_name": "Felix Baum", "pic": "https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?w=150&h=150&fit=crop", "verified": False, "private": False, "category": "fan"},
    {"username": "flora_botanicals", "full_name": "Flora Green", "pic": "https://images.unsplash.com/photo-1544005313-94ddf0286df2?w=150&h=150&fit=crop", "verified": False, "private": False, "category": "fan"},
]

def get_demo_followers_and_following():
    followers = []
    following = []

    for p in SAMPLE_PROFILES:
        user_obj = {
            "id": str(abs(hash(p['username'])) % 100000000),
            "username": p['username'],
            "full_name": p['full_name'],
            "profile_pic_url": p['pic'],
            "is_verified": p['verified'],
            "is_private": p['private']
        }

        if p['category'] == 'non_follower':
            # We follow them, they do NOT follow us
            following.append(user_obj)
        elif p['category'] == 'mutual':
            # Both follow each other
            followers.append(user_obj)
            following.append(user_obj)
        elif p['category'] == 'fan':
            # They follow us, we do not follow them
            followers.append(user_obj)

    # Add realistic padding
    for i in range(1, 25):
        u = f"creator_hub_{i}"
        user_obj = {
            "id": str(100000 + i),
            "username": u,
            "full_name": f"Creator Hub {i}",
            "profile_pic_url": f"https://api.dicebear.com/7.x/identicon/svg?seed={u}",
            "is_verified": (i % 5 == 0),
            "is_private": False
        }
        if i % 3 == 0:
            following.append(user_obj) # non-follower
        elif i % 2 == 0:
            followers.append(user_obj)
            following.append(user_obj) # mutual
        else:
            followers.append(user_obj) # fan

    return followers, following

def seed_demo_account():
    """
    Creates demo account in database with scan snapshot and weekly reports.
    """
    account_id = save_or_update_account(
        username=DEMO_USER['username'],
        user_id=DEMO_USER['user_id'],
        full_name=DEMO_USER['full_name'],
        profile_pic_url=DEMO_USER['profile_pic_url'],
        follower_count=DEMO_USER['follower_count'],
        following_count=DEMO_USER['following_count'],
        session_data="{}",
        mode="demo"
    )

    followers, following = get_demo_followers_and_following()
    record_scan_snapshot(account_id, followers, following)

    # Seed weekly unfollowers reports for the last 2-3 weeks
    conn = get_connection()
    c = conn.cursor()
    
    # Check if reports already seeded
    existing_reports = c.execute('SELECT COUNT(*) FROM weekly_reports WHERE account_id = ?', (account_id,)).fetchone()[0]
    if existing_reports == 0:
        current_date = datetime.now()
        lost_samples = [
            {"username": "dan_photographer", "full_name": "Daniel Kim", "pic": "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=150&h=150&fit=crop", "days_ago": 2},
            {"username": "sarah_travels_world", "full_name": "Sarah Jenkins", "pic": "https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=150&h=150&fit=crop", "days_ago": 4},
            {"username": "fitness_with_mike", "full_name": "Mike Vance", "pic": "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=150&h=150&fit=crop", "days_ago": 6},
            {"username": "nordic_minimalism", "full_name": "Freja Lindqvist", "pic": "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150&h=150&fit=crop", "days_ago": 10},
            {"username": "streetwear_daily", "full_name": "Marcus Kane", "pic": "https://images.unsplash.com/photo-1519085360753-af0119f7cbe7?w=150&h=150&fit=crop", "days_ago": 13},
        ]

        for s in lost_samples:
            unf_date = current_date - timedelta(days=s['days_ago'])
            week_id = unf_date.strftime('%Y-W%W')
            c.execute('''
                INSERT INTO weekly_reports (account_id, week_identifier, target_username, target_full_name, target_profile_pic_url, unfollowed_date, we_unfollowed)
                VALUES (?, ?, ?, ?, ?, ?, 0)
            ''', (account_id, week_id, s['username'], s['full_name'], s['pic'], unf_date.strftime('%Y-%m-%d %H:%M:%S')))

            # Ensure they exist in relationships with followed_by_me = 1 so the user can unfollow them
            c.execute('''
                INSERT INTO relationships (account_id, target_user_id, target_username, target_full_name, target_profile_pic_url, follows_me, followed_by_me)
                VALUES (?, ?, ?, ?, ?, 0, 1)
                ON CONFLICT(account_id, target_username) DO UPDATE SET followed_by_me = 1, follows_me = 0
            ''', (account_id, str(abs(hash(s['username']))), s['username'], s['full_name'], s['pic']))

        conn.commit()

    conn.close()
    return account_id
