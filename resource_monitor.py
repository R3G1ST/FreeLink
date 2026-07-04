#!/opt/freelink/venv/bin/python3
"""
Resource monitor — checks CPU/RAM/Disk and sends Telegram alerts when thresholds exceeded.
Runs as a systemd service (freelink-monitor).
"""
import sys, os, time, json, requests
from datetime import datetime

sys.path.insert(0, "/opt/freelink")
import db

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

CONFIG_FILE = "/opt/freelink/config.yaml"
STATE_FILE = "/opt/freelink/monitor_state.json"
CHECK_INTERVAL = 60  # seconds
ALERT_COOLDOWN = 1800  # 30 min between same alerts

THRESHOLDS = {
    "cpu_percent": 90,
    "ram_percent": 85,
    "disk_percent": 90,
}


def load_config():
    try:
        import yaml
        with open(CONFIG_FILE, 'r') as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def load_state():
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)


def send_telegram_message(token, admin_ids, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for admin_id in admin_ids:
        try:
            requests.post(url, json={
                "chat_id": admin_id,
                "text": text,
                "parse_mode": "HTML"
            }, timeout=10)
        except Exception:
            pass


def check_resources():
    if not HAS_PSUTIL:
        return {}

    info = {}
    info["cpu_percent"] = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    info["ram_percent"] = mem.percent
    info["ram_used_gb"] = round(mem.used / (1024**3), 1)
    info["ram_total_gb"] = round(mem.total / (1024**3), 1)
    disk = psutil.disk_usage("/")
    info["disk_percent"] = disk.percent
    info["disk_used_gb"] = round(disk.used / (1024**3), 1)
    info["disk_total_gb"] = round(disk.total / (1024**3), 1)
    return info


def format_bar(pct):
    filled = int(pct / 10)
    return "█" * filled + "░" * (10 - filled)


def main():
    print("[resource-monitor] Started (interval=%ds)" % CHECK_INTERVAL, flush=True)
    token = os.environ.get("TELEGRAM_TOKEN", "")
    admins_str = os.environ.get("TELEGRAM_ADMIN_IDS", "")
    admins = [int(x.strip()) for x in admins_str.split(",") if x.strip().isdigit()]

    if not token:
        print("[resource-monitor] WARNING: No Telegram token, alerts disabled", flush=True)

    while True:
        try:
            info = check_resources()
            state = load_state()
            now = time.time()
            alerts = []

            # CPU
            cpu = info.get("cpu_percent", 0)
            if cpu >= THRESHOLDS["cpu_percent"]:
                last_alert = state.get("cpu_alert_time", 0)
                if now - last_alert > ALERT_COOLDOWN:
                    alerts.append(f"CPU: {cpu}% (порог {THRESHOLDS['cpu_percent']}%)")
                    state["cpu_alert_time"] = now

            # RAM
            ram = info.get("ram_percent", 0)
            if ram >= THRESHOLDS["ram_percent"]:
                last_alert = state.get("ram_alert_time", 0)
                if now - last_alert > ALERT_COOLDOWN:
                    alerts.append(f"RAM: {ram}% — {info['ram_used_gb']}/{info['ram_total_gb']} GB (порог {THRESHOLDS['ram_percent']}%)")
                    state["ram_alert_time"] = now

            # Disk
            disk = info.get("disk_percent", 0)
            if disk >= THRESHOLDS["disk_percent"]:
                last_alert = state.get("disk_alert_time", 0)
                if now - last_alert > ALERT_COOLDOWN:
                    alerts.append(f"Disk: {disk}% — {info['disk_used_gb']}/{info['disk_total_gb']} GB (порог {THRESHOLDS['disk_percent']}%)")
                    state["disk_alert_time"] = now

            save_state(state)

            if alerts and token and admins:
                now_str = datetime.now().strftime("%H:%M:%S")
                text = (
                    f"🔴 <b>FreeLink — Алерт ресурсов</b>\n"
                    f"⏰ {now_str}\n\n"
                    + "\n".join(f"• {a}" for a in alerts)
                    + f"\n\n"
                    f"CPU:  <code>{format_bar(cpu)}</code> {cpu}%\n"
                    f"RAM:  <code>{format_bar(ram)}</code> {ram}%\n"
                    f"Disk: <code>{format_bar(disk)}</code> {disk}%"
                )
                send_telegram_message(token, admins, text)
                print(f"[resource-monitor] Alert sent: {', '.join(alerts)}", flush=True)
            else:
                print(f"[{time.strftime('%H:%M:%S')}] CPU:{cpu}% RAM:{ram}% Disk:{disk}%", flush=True)

        except Exception as e:
            print(f"[resource-monitor] Error: {e}", flush=True)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
