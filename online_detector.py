#!/opt/freelink/venv/bin/python3
"""
Online detector — polls Hysteria traffic API, saves snapshots to PostgreSQL.
Online status is determined by comparing consecutive snapshots per (user, node).
"""
import sys, requests, time, json

sys.path.insert(0, "/opt/freelink")
import db
db.init_db()

HYSTERIA_API = 'http://127.0.0.1:9999/traffic'
CHECK_INTERVAL = 2
ONLINE_WINDOW = 30  # 30 polls x 2s = 60s comparison window
ONLINE_FILE = '/opt/freelink/online_status.json'

def get_traffic():
    try:
        r = requests.get(HYSTERIA_API, timeout=3)
        return r.json() if r.status_code == 200 else {}
    except:
        return {}

def detect_online():
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
    online_names = [u for u, info in online.items() if info.get("online")]
    print(f"[{time.strftime('%H:%M:%S')}] Online: {online_count}/{len(current)} ({', '.join(online_names) or 'none'})", flush=True)

    # Write JSON for backward compatibility (bot.py legacy)
    try:
        with open(ONLINE_FILE, 'w') as f:
            json.dump(online, f, default=str)
    except:
        pass

if __name__ == '__main__':
    print(f'Online detector started (every {CHECK_INTERVAL}s, window={ONLINE_WINDOW} polls)', flush=True)
    while True:
        try:
            detect_online()
        except Exception as e:
            print(f'Error: {e}', flush=True)
        time.sleep(CHECK_INTERVAL)
