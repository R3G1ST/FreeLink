#!/usr/bin/env python3
"""
Hysteria 2 Node Agent
Run on each remote server to connect to the main panel.

Usage:
    python3 node_agent.py --panel https://link.qmbox.ru --name "Server-Name" --ip 1.2.3.4

Install as systemd service:
    cp node_agent.py /opt/hysteria-agent/
    cp node_agent.service /etc/systemd/system/
    systemctl enable --now hysteria-agent
"""

import argparse, json, os, subprocess, sys, time, hashlib
from urllib.request import Request, urlopen
from urllib.error import URLError

def get_server_info():
    info = {}
    try:
        import psutil
        info["cpu_percent"] = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        info["ram_percent"] = mem.percent
        disk = psutil.disk_usage("/")
        info["disk_percent"] = disk.percent
    except:
        info["cpu_percent"] = 0
        info["ram_percent"] = 0
        info["disk_percent"] = 0

    # Count users from hysteria config (check both user and userpass)
    try:
        with open("/etc/hysteria/config.yaml") as f:
            import yaml
            cfg = yaml.safe_load(f)
            auth = cfg.get("auth", {})
            users = auth.get("user", {}) or auth.get("userpass", {})
            info["total_users"] = len(users)
    except:
        info["total_users"] = 0

    # Get traffic stats from hysteria API
    try:
        r = urlopen("http://127.0.0.1:9999/traffic", timeout=3)
        traffic = json.loads(r.read())
        info["traffic_sent"] = sum(t.get("tx", 0) for t in traffic.values())
        info["traffic_recv"] = sum(t.get("rx", 0) for t in traffic.values())
        info["online_usernames"] = list(traffic.keys())
        info["online_users"] = len(traffic)
        # Per-user traffic for aggregation
        info["user_traffic"] = {user: {"tx": t.get("tx", 0), "rx": t.get("rx", 0)} for user, t in traffic.items()}
    except:
        info["traffic_sent"] = 0
        info["traffic_recv"] = 0
        info["online_usernames"] = []
        info["online_users"] = 0
        info["user_traffic"] = {}

    # Check hysteria status
    try:
        r = subprocess.run(["systemctl", "is-active", "hysteria-server"],
                          capture_output=True, text=True, timeout=5)
        info["hysteria_status"] = "active" if r.stdout.strip() == "active" else "inactive"
    except:
        info["hysteria_status"] = "unknown"

    return info

def api_call(panel_url, endpoint, data=None, token=None):
    url = panel_url.rstrip("/") + endpoint
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data else None
    req = Request(url, data=body, headers=headers, method="POST" if data else "GET")
    try:
        resp = urlopen(req, timeout=10)
        return json.loads(resp.read())
    except URLError as e:
        print(f"API error: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return None

def push_users_to_hysteria(users):
    """Push assigned users to local hysteria config"""
    try:
        import yaml
        config_path = "/etc/hysteria/config.yaml"
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
        auth = cfg.setdefault("auth", {})
        # Ensure auth type is userpass
        auth["type"] = "userpass"
        user_db = auth.setdefault("userpass", {})
        # Build new user map
        new_users = {}
        for u in users:
            name = u.get("name", "")
            if u.get("active", True):
                new_users[name] = u.get("password", "")
        # Check if users actually changed
        old_users = dict(user_db)
        if old_users == new_users:
            return  # No changes, don't restart
        # Update users
        user_db.clear()
        user_db.update(new_users)
        with open(config_path, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
        # Reload hysteria only if users changed
        subprocess.run(["systemctl", "reload-or-restart", "hysteria-server"],
                      capture_output=True, timeout=10)
    except Exception as e:
        print(f"Config push error: {e}", file=sys.stderr)

def main():
    parser = argparse.ArgumentParser(description="Hysteria 2 Node Agent")
    parser.add_argument("--panel", required=True, help="Panel URL (e.g. https://link.qmbox.ru)")
    parser.add_argument("--name", required=True, help="Node name")
    parser.add_argument("--ip", required=True, help="Node public IP")
    parser.add_argument("--region", default="", help="Region/country")
    parser.add_argument("--interval", type=int, default=30, help="Heartbeat interval (seconds)")
    parser.add_argument("--node-id", default="", help="Node ID (from previous registration)")
    parser.add_argument("--token", default="", help="Node token (from previous registration)")
    args = parser.parse_args()

    config_file = f"/opt/hysteria-agent/agent.json"
    os.makedirs(os.path.dirname(config_file), exist_ok=True)

    # Load or register
    node_id = args.node_id
    node_token = args.token
    if not node_id and os.path.exists(config_file):
        try:
            with open(config_file) as f:
                cfg = json.load(f)
                node_id = cfg.get("node_id", "")
                node_token = cfg.get("token", "")
        except:
            pass

    if not node_id:
        print(f"Registering with panel at {args.panel}...")
        resp = api_call(args.panel, "/api/node/register", {
            "name": args.name,
            "ip": args.ip,
            "region": args.region,
            "version": "1.0"
        })
        if not resp or not resp.get("success"):
            print(f"Registration failed: {resp}", file=sys.stderr)
            sys.exit(1)
        node_id = resp["node_id"]
        node_token = resp["token"]
        with open(config_file, "w") as f:
            json.dump({"node_id": node_id, "token": node_token}, f)
        print(f"Registered! Node ID: {node_id}")
    else:
        print(f"Using existing node ID: {node_id}")

    print(f"Agent started. Heartbeat every {args.interval}s to {args.panel}")

    while True:
        try:
            info = get_server_info()
            info["node_id"] = node_id
            info["token"] = node_token
            resp = api_call(args.panel, "/api/node/heartbeat", info)
            if resp and resp.get("success"):
                users = resp.get("users", [])
                if users:
                    push_users_to_hysteria(users)
                print(f"[{time.strftime('%H:%M:%S')}] OK — online:{info['online_users']} cpu:{info['cpu_percent']}% users:{info['total_users']}")
            else:
                print(f"[{time.strftime('%H:%M:%S')}] Heartbeat failed: {resp}", file=sys.stderr)
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] Error: {e}", file=sys.stderr)
        time.sleep(args.interval)

if __name__ == "__main__":
    main()
