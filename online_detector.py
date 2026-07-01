#!/opt/vpnbot/venv/bin/python3
import requests, yaml, time, json, os

DATA_FILE = '/opt/vpnbot/data.yaml'
SNAPSHOT_FILE = '/opt/vpnbot/online_snapshot.json'
HYSTERIA_API = 'http://127.0.0.1:9999/traffic'
CHECK_INTERVAL = 10

def get_traffic():
    try:
        r = requests.get(HYSTERIA_API, timeout=3)
        return r.json() if r.status_code == 200 else {}
    except:
        return {}

def load_snapshot():
    if os.path.exists(SNAPSHOT_FILE):
        try:
            with open(SNAPSHOT_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}

def save_snapshot(data):
    with open(SNAPSHOT_FILE, 'w') as f:
        json.dump(data, f)

def detect_online():
    current = get_traffic()
    prev = load_snapshot()
    online_users = {}

    # Users in traffic API = connected (online)
    for username, traffic in current.items():
        tx = traffic.get("tx", 0)
        rx = traffic.get("rx", 0)
        prev_user = prev.get(username, {})
        prev_tx = prev_user.get("tx", 0)
        prev_rx = prev_user.get("rx", 0)

        # User is online if they appear in traffic API (connected to Hysteria)
        online_users[username] = {
            "online": True,
            "tx": tx,
            "rx": rx,
            "tx_speed": max(0, tx - prev_tx),
            "rx_speed": max(0, rx - prev_rx),
            "last_active": time.strftime("%Y-%m-%d %H:%M:%S")
        }

    save_snapshot(current)

    with open('/opt/vpnbot/online_status.json', 'w') as f:
        json.dump(online_users, f)

    online_count = len(online_users)
    print(f"[{time.strftime('%H:%M:%S')}] Online: {online_count}/{len(online_users)}", flush=True)

if __name__ == '__main__':
    print('Online detector started (every 10 seconds)', flush=True)
    while True:
        try:
            detect_online()
        except Exception as e:
            print(f'Error: {e}', flush=True)
        time.sleep(CHECK_INTERVAL)
