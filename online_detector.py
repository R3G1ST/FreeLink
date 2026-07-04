#!/opt/freelink/venv/bin/python3
"""
Online detector — polls Hysteria traffic API, saves snapshots to PostgreSQL.
Online status is determined by comparing consecutive snapshots per (user, node).
Also tracks device count via /online endpoint.
"""
import sys, requests, time, json

sys.path.insert(0, "/opt/freelink")
import db
db.init_db()

HYSTERIA_TRAFFIC = 'http://127.0.0.1:9999/traffic'
HYSTERIA_ONLINE = 'http://127.0.0.1:9999/online'
CHECK_INTERVAL = 2
ONLINE_WINDOW = 30  # 30 polls x 2s = 60s comparison window
ONLINE_FILE = '/opt/freelink/online_status.json'

# Track previous online users to detect disconnects
_prev_online = set()

def get_traffic():
    try:
        r = requests.get(HYSTERIA_TRAFFIC, timeout=3)
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}

def get_online_counts():
    """Get active connection count per user from Hysteria /online."""
    try:
        r = requests.get(HYSTERIA_ONLINE, timeout=3)
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}

def detect_online():
    global _prev_online
    current = get_traffic()
    snapshots = []
    for username, data in current.items():
        snapshots.append({
            "username": username,
            "node_id": "__main__",
            "tx": data.get("tx", 0),
            "rx": data.get("rx", 0)
        })
    if snapshots:
        db.save_traffic_snapshots_batch(snapshots)

    online = db.get_online_users(window_seconds=CHECK_INTERVAL * ONLINE_WINDOW)
    online_count = sum(1 for u in online.values() if u.get("online"))
    online_names = set(u for u, info in online.items() if info.get("online"))
    print(f"[{time.strftime('%H:%M:%S')}] Online: {online_count}/{len(current)} ({', '.join(sorted(online_names)) or 'none'})", flush=True)

    # Detect disconnects — users who were online but aren't anymore
    disconnected = _prev_online - online_names
    for username in disconnected:
        result = db.get_user_by_name(username)
        user_data = result[0] if result and result[0] else None
        if user_data:
            ip = user_data.get("ip", "")
            if ip:
                db.log_disconnect(username, ip)
    _prev_online = online_names

    # Write JSON for backward compatibility (bot.py legacy)
    try:
        with open(ONLINE_FILE, 'w') as f:
            json.dump(online, f, default=str)
    except Exception:
        pass

if __name__ == '__main__':
    print(f'Online detector started (every {CHECK_INTERVAL}s, window={ONLINE_WINDOW} polls)', flush=True)
    # Cleanup old connections on startup
    cleaned = db.cleanup_old_connections(90)
    if cleaned:
        print(f'Cleaned {cleaned} old connection logs', flush=True)
    while True:
        try:
            detect_online()
        except Exception as e:
            print(f'Error: {e}', flush=True)
        time.sleep(CHECK_INTERVAL)
