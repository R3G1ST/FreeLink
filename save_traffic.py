#!/opt/vpnbot/venv/bin/python3
import requests, yaml, time, sys

DATA_FILE = '/opt/vpnbot/data.yaml'
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
    with open(DATA_FILE, 'r') as f:
        data = yaml.safe_load(f)
    for uid, user in data.get('users', {}).items():
        username = user.get('name', uid)
        if username in current:
            tx = current[username].get('tx', 0)
            rx = current[username].get('rx', 0)
            user['traffic_saved'] = {
                'tx': tx, 'rx': rx,
                'total_mb': round((tx + rx) / 1024 / 1024, 2),
                'updated': time.strftime('%Y-%m-%d %H:%M:%S')
            }
    with open(DATA_FILE, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
    print(f"[{time.strftime('%H:%M:%S')}] Traffic saved: {len(current)} users", flush=True)

if __name__ == '__main__':
    print('Traffic saver started (every 60 seconds)', flush=True)
    while True:
        try:
            save_traffic()
        except Exception as e:
            print(f'Error: {e}', flush=True)
        time.sleep(60)
