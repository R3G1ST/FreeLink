#!/opt/vpnbot/venv/bin/python3
import requests, json, os, time
from datetime import datetime

HYSTERIA_API = 'http://127.0.0.1:9999/traffic'
HISTORY_FILE = '/opt/vpnbot/traffic_history.json'
MAX_ENTRIES = 2880

def record():
    try:
        r = requests.get(HYSTERIA_API, timeout=3)
        stats = r.json() if r.status_code == 200 else {}
    except:
        stats = {}

    history = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                history = json.load(f)
        except:
            pass

    entry = {"time": datetime.now().strftime("%Y-%m-%d %H:%M"), "users": {}}
    for username, traffic in stats.items():
        entry["users"][username] = {"tx": traffic.get("tx", 0), "rx": traffic.get("rx", 0)}

    history.append(entry)
    if len(history) > MAX_ENTRIES:
        history = history[-MAX_ENTRIES:]

    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f)

if __name__ == '__main__':
    print('Traffic history recorder started (every 5 min)', flush=True)
    while True:
        try:
            record()
        except Exception as e:
            print(f'Error: {e}', flush=True)
        time.sleep(300)
