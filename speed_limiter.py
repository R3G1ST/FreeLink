#!/opt/freelink/venv/bin/python3
"""
Speed limiter — applies per-user speed limits to Hysteria 2 config.
Called when admin changes a user's speed_limit_mbps.
"""
import sys, os, yaml, subprocess

sys.path.insert(0, "/opt/freelink")
import db

HYSTERIA_CONFIG = "/etc/hysteria/config.yaml"


def apply_speed_limits():
    """Read all users from DB and update Hysteria config with speed limits."""
    users = db.get_all_users()
    if not users:
        print("[speed-limiter] No users found", flush=True)
        return

    try:
        with open(HYSTERIA_CONFIG, 'r') as f:
            config = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"[speed-limiter] Error reading config: {e}", flush=True)
        return

    auth = config.setdefault("auth", {})
    auth_type = auth.get("type", "userpass")
    user_db = auth.setdefault("userpass", {})

    changed = False
    for uid, user in users.items():
        name = user.get("name", uid)
        password = user.get("password", "")
        speed_limit = user.get("speed_limit_mbps", 0)

        if not password:
            continue

        # Get current config for this user
        current = user_db.get(name, {})

        # Build new user config
        if speed_limit > 0:
            new_config = password  # Simple format: just password string
            # Hysteria 2 supports object format with speed limits
            # But for compatibility, we use the simpler approach
            # The speed limit is applied via the "up" and "down" fields
            if isinstance(current, dict):
                new_config = current.copy()
                new_config["password"] = password
                new_config["up"] = speed_limit  # Mbps
                new_config["down"] = speed_limit  # Mbps
            else:
                new_config = {
                    "password": password,
                    "up": speed_limit,
                    "down": speed_limit
                }
        else:
            # No limit — use simple password format
            new_config = password

        if user_db.get(name) != new_config:
            user_db[name] = new_config
            changed = True
            print(f"[speed-limiter] {name}: speed_limit={speed_limit} Mbps", flush=True)

    if changed:
        try:
            # Backup config
            backup_path = f"{HYSTERIA_CONFIG}.bak"
            subprocess.run(["/usr/bin/cp", HYSTERIA_CONFIG, backup_path], timeout=5)

            # Write new config
            with open(HYSTERIA_CONFIG, 'w') as f:
                yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

            # Restart Hysteria
            result = subprocess.run(
                ["/usr/bin/systemctl", "restart", "hysteria-server"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                print("[speed-limiter] Config updated and Hysteria restarted", flush=True)
            else:
                print(f"[speed-limiter] Restart warning: {result.stderr[:200]}", flush=True)
        except Exception as e:
            print(f"[speed-limiter] Error: {e}", flush=True)
    else:
        print("[speed-limiter] No speed limit changes", flush=True)


if __name__ == "__main__":
    db.init_db()
    apply_speed_limits()
