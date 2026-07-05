"""Xray VLESS Reality management module for FreeLink VPN panel."""
import subprocess
import json
import uuid
import os

XRAY_CONFIG = "/usr/local/etc/xray/config.json"
REALITY_PRIVATE_KEY = "sNrJNce5qYXrErNwCRiOldHyOhQJHnFnkXl_B-UUwGQ"
REALITY_PUBLIC_KEY = "o-1Y8_snQQ_dDaGkzyIexychue-Gm_HyRxezhlV71yI"
REALITY_SHORT_IDS = ["", "0123456789abcdef", "abcdef0123456789"]
DEST_SERVER = "www.microsoft.com"
DEST_PORT = 443
SERVER_NAMES = ["www.microsoft.com", "microsoft.com"]
VLESS_PORT = 443


def _load_config():
    """Load Xray config from file."""
    try:
        with open(XRAY_CONFIG, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_config(config):
    """Save Xray config to file."""
    with open(XRAY_CONFIG, "w") as f:
        json.dump(config, f, indent=2)


def _restart_xray():
    """Restart Xray service."""
    subprocess.run(["/usr/bin/systemctl", "restart", "xray"], capture_output=True, timeout=10)


def generate_user_uuid():
    """Generate a new UUID for a VLESS user."""
    return str(uuid.uuid4())


def add_user(user_uuid, email=""):
    """Add a VLESS user to Xray config."""
    config = _load_config()
    if not config:
        return False

    clients = config["inbounds"][0]["settings"]["clients"]
    # Check if user already exists
    for c in clients:
        if c["id"] == user_uuid:
            return True

    clients.append({
        "id": user_uuid,
        "email": email,
        "flow": "xtls-rprx-vision"
    })
    _save_config(config)
    _restart_xray()
    return True


def remove_user(user_uuid):
    """Remove a VLESS user from Xray config."""
    config = _load_config()
    if not config:
        return False

    clients = config["inbounds"][0]["settings"]["clients"]
    config["inbounds"][0]["settings"]["clients"] = [c for c in clients if c["id"] != user_uuid]
    _save_config(config)
    _restart_xray()
    return True


def get_users():
    """Get all VLESS users from Xray config."""
    config = _load_config()
    if not config:
        return []
    return config.get("inbounds", [{}])[0].get("settings", {}).get("clients", [])


def generate_vless_link(user_uuid, name="FreeLink", server=None, port=None):
    """Generate a vless:// URI for VLESS+WS+TLS."""
    domain = os.environ.get("DOMAIN", "link.qmbox.ru")
    if not server:
        server = domain
    if not port:
        port = 443

    params = f"security=tls&sni={domain}&type=ws&path=/vless&encryption=none"
    link = f"vless://{user_uuid}@{server}:{port}?{params}#{name}"
    return link


def generate_vless_config(user_uuid, name="FreeLink", server=None, port=None):
    """Generate Xray JSON config for a user (for clients that support import)."""
    domain = os.environ.get("DOMAIN", "link.qmbox.ru")
    if not server:
        server = domain
    if not port:
        port = VLESS_PORT

    return {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "listen": "127.0.0.1",
                "port": 1080,
                "protocol": "socks",
                "settings": {"udp": True}
            },
            {
                "listen": "127.0.0.1",
                "port": 1081,
                "protocol": "http"
            }
        ],
        "outbounds": [
            {
                "protocol": "vless",
                "settings": {
                    "vnext": [
                        {
                            "address": server,
                            "port": port,
                            "users": [
                                {
                                    "id": user_uuid,
                                    "encryption": "none",
                                    "flow": "xtls-rprx-vision"
                                }
                            ]
                        }
                    ]
                },
                "streamSettings": {
                    "network": "tcp",
                    "security": "tls",
                    "wsSettings": {
                        "serverName": DEST_SERVER,
                        "fingerprint": "chrome",
                        "publicKey": REALITY_PUBLIC_KEY,
                        "shortId": REALITY_SHORT_IDS[0],
                        "spiderX": ""
                    }
                },
                "tag": "proxy"
            },
            {
                "protocol": "freedom",
                "tag": "direct"
            }
        ],
        "routing": {
            "domainStrategy": "AsIs",
            "rules": [
                {"type": "field", "ip": ["geoip:private"], "outboundTag": "direct"},
                {"type": "field", "protocol": ["dns"], "outboundTag": "direct"}
            ]
        }
    }


def is_running():
    """Check if Xray is running."""
    try:
        r = subprocess.run(["/usr/bin/systemctl", "is-active", "xray"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() == "active"
    except Exception:
        return False


def get_status():
    """Get Xray status."""
    config = _load_config()
    clients = config.get("inbounds", [{}])[0].get("settings", {}).get("clients", [])
    return {
        "running": is_running(),
        "port": VLESS_PORT,
        "dest": DEST_SERVER,
        "public_key": REALITY_PUBLIC_KEY,
        "user_count": len(clients),
    }


def generate_client_config_for_user(user_uuid, name, server=None):
    """Generate full client config for QR/import."""
    domain = os.environ.get("DOMAIN", "link.qmbox.ru")
    if not server:
        server = domain
    config = generate_vless_config(user_uuid, name, server)
    return json.dumps(config, indent=2)


# ==================== SHADOWSOCKS ====================
SS_PORT = 8388
SS_METHOD = "aes-256-gcm"


def generate_ss_password():
    """Generate a Shadowsocks password (32-char hex for 2022-blake3)."""
    import secrets
    return secrets.token_hex(16)


def generate_ss_link(ss_password, name="FreeLink", server=None, port=None, method=None):
    """Generate a ss:// URI for Shadowsocks."""
    import base64
    domain = os.environ.get("DOMAIN", "link.qmbox.ru")
    if not server:
        server = domain
    if not port:
        port = SS_PORT
    if not method:
        method = SS_METHOD

    # Format: base64(method:password)@server:port
    userinfo = f"{method}:{ss_password}"
    userinfo_b64 = base64.urlsafe_b64encode(userinfo.encode()).decode().rstrip("=")
    link = f"ss://{userinfo_b64}@{server}:{port}#{name}"
    return link


def add_ss_user(ss_password, email=""):
    """Add Shadowsocks user to Xray config."""
    config = _load_config()
    if not config:
        return False

    # Check if SS inbound exists
    ss_inbound = None
    for inbound in config.get("inbounds", []):
        if inbound.get("protocol") == "shadowsocks":
            ss_inbound = inbound
            break

    if not ss_inbound:
        # Create SS inbound
        ss_inbound = {
            "listen": "127.0.0.1",
            "port": 10002,
            "protocol": "shadowsocks",
            "settings": {
                "method": SS_METHOD,
                "password": ss_password,
                "network": "tcp,udp"
            },
            "tag": "shadowsocks"
        }
        config["inbounds"].append(ss_inbound)
    else:
        # Update password
        ss_inbound["settings"]["password"] = ss_password

    _save_config(config)
    _restart_xray()
    return True


def remove_ss_user():
    """Remove Shadowsocks inbound from Xray config."""
    config = _load_config()
    if not config:
        return False

    config["inbounds"] = [i for i in config.get("inbounds", []) if i.get("protocol") != "shadowsocks"]
    _save_config(config)
    _restart_xray()
    return True
