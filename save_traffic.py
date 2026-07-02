#!/opt/freelink/venv/bin/python3
import sys, requests, time

sys.path.insert(0, "/opt/freelink")
import db
db.init_db()

HYSTERIA_API = 'http://127.0.0.1:9999/traffic'

def get_current_traffic():
    try:
        r = requests.get(HYSTERIA_API, timeout=3)
        return r.json() if r.status_code == 200 else None
    except:
        return None

def save_traffic():
    current = get_current_traffic()
    if current is None:
        return
    db.update_user_traffic_batch(current)
    print(f"[{time.strftime('%H:%M:%S')}] Traffic saved: {len(current)} users", flush=True)

if __name__ == '__main__':
    print('Traffic saver started (every 60 seconds)', flush=True)
    while True:
        try:
            save_traffic()
        except Exception as e:
            print(f'Error: {e}', flush=True)
        time.sleep(60)
