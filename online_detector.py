#!/opt/freelink/venv/bin/python3
"""
Online detector — stores traffic snapshots in PostgreSQL.
A user is "online" if they appeared in any of the last N polls.
Speed is calculated from the difference between two most recent snapshots.
"""
import sys, requests, time

sys.path.insert(0, "/opt/freelink")
import db
db.init_db()

HYSTERIA_API = 'http://127.0.0.1:9999/traffic'
CHECK_INTERVAL = 10
ONLINE_WINDOW = 6  # Consider online if seen in last 6 polls (60 seconds)

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

    # Cleanup old snapshots every 10 minutes
    if int(time.time()) % 600 < CHECK_INTERVAL:
        db.cleanup_old_snapshots()

    online = db.get_online_users()
    print(f"[{time.strftime('%H:%M:%S')}] Online: {len(online)}/{len(current)} users", flush=True)

if __name__ == '__main__':
    print(f'Online detector started (every {CHECK_INTERVAL}s, window={ONLINE_WINDOW} polls)', flush=True)
    while True:
        try:
            detect_online()
        except Exception as e:
            print(f'Error: {e}', flush=True)
        time.sleep(CHECK_INTERVAL)
