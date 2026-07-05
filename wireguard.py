"""WireGuard management module for FreeLink VPN panel."""
import subprocess
import os
import ipaddress

WG_INTERFACE = "wg0"
WG_SUBNET = "10.10.0.0/24"
WG_SERVER_IP = "10.10.0.1"
WG_PORT = 51820
WG_SERVER_PUBKEY_PATH = "/etc/wireguard/server.pub"
WG_SERVER_PRIVKEY_PATH = "/etc/wireguard/server.key"
WG_BIN = "/usr/bin/wg"


def _run(cmd, check=False, input=None):
    """Run a shell command and return stdout."""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10, input=input)
        if check and r.returncode != 0:
            raise RuntimeError(f"Command failed: {cmd}\n{r.stderr}")
        return r.stdout.strip()
    except subprocess.TimeoutExpired:
        return ""


def get_server_public_key():
    """Read the server's public key."""
    try:
        with open(WG_SERVER_PUBKEY_PATH) as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def get_server_private_key():
    """Read the server's private key."""
    try:
        with open(WG_SERVER_PRIVKEY_PATH) as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def generate_keypair():
    """Generate a WireGuard keypair. Returns (private_key, public_key)."""
    try:
        r = subprocess.run(f"{WG_BIN} genkey", shell=True, capture_output=True, text=True, timeout=10)
        privkey = r.stdout.strip()
        if not privkey:
            print(f"[WG] genkey failed: rc={r.returncode} stderr={r.stderr}")
            raise RuntimeError(f"Failed to generate WireGuard private key: {r.stderr}")
        r2 = subprocess.run(f"{WG_BIN} pubkey", shell=True, capture_output=True, text=True, timeout=10, input=privkey)
        pubkey = r2.stdout.strip()
        if not pubkey:
            print(f"[WG] pubkey failed: rc={r2.returncode} stderr={r2.stderr}")
            raise RuntimeError(f"Failed to generate WireGuard public key: {r2.stderr}")
        return privkey, pubkey
    except Exception as e:
        print(f"[WG] generate_keypair error: {e}")
        raise


def get_next_ip(existing_ips):
    """Find the next available IP in the WG_SUBNET, excluding server IP and existing IPs."""
    network = ipaddress.ip_network(WG_SUBNET)
    reserved = {WG_SERVER_IP} | set(existing_ips)
    for ip in network.hosts():
        ip_str = str(ip)
        if ip_str not in reserved:
            return ip_str
    raise RuntimeError("No available IPs in WireGuard subnet")


def add_peer(public_key, allowed_ip):
    """Add a peer to the WireGuard interface."""
    ip_with_mask = f"{allowed_ip}/32"
    result = _run(f"{WG_BIN} set {WG_INTERFACE} peer {public_key} allowed-ips {ip_with_mask}")
    # Save to config file
    _save_config()
    return True


def remove_peer(public_key):
    """Remove a peer from the WireGuard interface."""
    result = _run(f"{WG_BIN} set {WG_INTERFACE} peer {public_key} remove")
    _save_config()
    return True


def get_peers():
    """Get all peers from the WireGuard interface. Returns list of dicts."""
    dump = _run(f"{WG_BIN} show {WG_INTERFACE} dump")
    if not dump:
        return []
    peers = []
    lines = dump.strip().split("\n")
    # First line is interface info, rest are peers
    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) >= 5:
            peers.append({
                "public_key": parts[0],
                "preshared_key": parts[1] if parts[1] != "(none)" else None,
                "allowed_ips": parts[2],
                "endpoint": parts[3] if parts[3] else None,
                "latest_handshake": int(parts[4]) if parts[4] and parts[4] != "0" else 0,
                "transfer_rx": int(parts[5]) if len(parts) > 5 and parts[5] else 0,
                "transfer_tx": int(parts[6]) if len(parts) > 6 and parts[6] else 0,
                "persistent_keepalive": parts[7] if len(parts) > 7 else None,
            })
    return peers


def get_transfer_stats():
    """Get transfer stats for all peers. Returns dict keyed by public_key."""
    transfer = _run(f"{WG_BIN} show {WG_INTERFACE} transfer")
    if not transfer:
        return {}
    stats = {}
    for line in transfer.strip().split("\n"):
        parts = line.split("\t")
        if len(parts) == 3:
            stats[parts[0]] = {"rx": int(parts[1]), "tx": int(parts[2])}
    return stats


def get_handshakes():
    """Get latest handshake times for all peers. Returns dict keyed by public_key."""
    handshakes = _run(f"{WG_BIN} show {WG_INTERFACE} latest-handshakes")
    if not handshakes:
        return {}
    result = {}
    for line in handshakes.strip().split("\n"):
        parts = line.split("\t")
        if len(parts) == 2:
            result[parts[0]] = int(parts[1]) if parts[1] and parts[1] != "0" else 0
    return result


def get_allowed_ips():
    """Get allowed IPs for all peers. Returns dict keyed by public_key."""
    allowed = _run(f"{WG_BIN} show {WG_INTERFACE} allowed-ips")
    if not allowed:
        return {}
    result = {}
    for line in allowed.strip().split("\n"):
        parts = line.split("\t")
        if len(parts) == 2:
            result[parts[0]] = parts[1]
    return result


def is_running():
    """Check if the WireGuard interface is running."""
    result = _run(f"{WG_BIN} show {WG_INTERFACE}")
    return bool(result)


def get_status():
    """Get WireGuard interface status summary."""
    running = is_running()
    peers = get_peers()
    stats = get_transfer_stats()
    total_rx = sum(s["rx"] for s in stats.values())
    total_tx = sum(s["tx"] for s in stats.values())
    return {
        "running": running,
        "interface": WG_INTERFACE,
        "port": WG_PORT,
        "server_ip": WG_SERVER_IP,
        "subnet": WG_SUBNET,
        "peer_count": len(peers),
        "total_rx": total_rx,
        "total_tx": total_tx,
        "server_public_key": get_server_public_key(),
    }


def generate_client_config(client_private_key, client_ip, server_public_key=None):
    """Generate a WireGuard client config text."""
    if not server_public_key:
        server_public_key = get_server_public_key()
    domain = os.environ.get("DOMAIN", "link.qmbox.ru")

    config = f"""[Interface]
PrivateKey = {client_private_key}
Address = {client_ip}/32
DNS = 1.1.1.1, 8.8.8.8

[Peer]
PublicKey = {server_public_key}
Endpoint = {domain}:{WG_PORT}
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
"""
    return config


def generate_client_uri(client_private_key, client_ip, name="FreeLink", server_pubkey=None, endpoint=None):
    """Generate a wireguard:// URI for importing into client apps."""
    if not server_pubkey:
        server_pubkey = get_server_public_key()
    if not endpoint:
        domain = os.environ.get("DOMAIN", "link.qmbox.ru")
        endpoint = f"{domain}:{WG_PORT}"
    import urllib.parse
    params = urllib.parse.urlencode({
        "privateKey": client_private_key,
        "address": f"{client_ip}/32",
        "dns": "1.1.1.1, 8.8.8.8",
        "publicKey": server_pubkey,
        "endpoint": endpoint,
        "allowedIPs": "0.0.0.0/0",
        "persistentKeepalive": "25",
    })
    return f"wireguard://{urllib.parse.quote(params, safe='')}#{name}"


def _save_config():
    """Save current WireGuard state to config file (for persistence across reboots)."""
    peers = get_peers()
    server_privkey = get_server_private_key()

    lines = [
        "[Interface]",
        f"Address = {WG_SERVER_IP}/24",
        f"ListenPort = {WG_PORT}",
        f"PrivateKey = {server_privkey}",
        "PostUp = iptables -A FORWARD -i wg0 -j ACCEPT; iptables -t nat -A POSTROUTING -o ens18 -j MASQUERADE",
        "PostDown = iptables -D FORWARD -i wg0 -j ACCEPT; iptables -t nat -D POSTROUTING -o ens18 -j MASQUERADE",
        "",
    ]

    for peer in peers:
        lines.append("[Peer]")
        lines.append(f"PublicKey = {peer['public_key']}")
        if peer.get("preshared_key"):
            lines.append(f"PresharedKey = {peer['preshared_key']}")
        lines.append(f"AllowedIPs = {peer['allowed_ips']}")
        if peer.get("endpoint"):
            lines.append(f"Endpoint = {peer['endpoint']}")
        if peer.get("persistent_keepalive") and peer["persistent_keepalive"] != "off":
            lines.append(f"PersistentKeepalive = {peer['persistent_keepalive']}")
        lines.append("")

    config_path = f"/etc/wireguard/{WG_INTERFACE}.conf"
    with open(config_path, "w") as f:
        f.write("\n".join(lines))


def restart():
    """Restart the WireGuard interface."""
    _run(f"systemctl restart wg-quick@{WG_INTERFACE}", check=True)
    return True


def setup_user_wg(user_data):
    """Setup WireGuard for a user on ALL nodes: generate keys, assign IP, add peer.
    Returns updated user_data dict."""
    # Main server
    used_ips = _get_used_ips_from_db()
    wg_ip = get_next_ip(used_ips)
    privkey, pubkey = generate_keypair()
    user_data["wg_private_key"] = privkey
    user_data["wg_public_key"] = pubkey
    user_data["wg_address"] = wg_ip
    user_data["wg_port"] = WG_PORT
    add_peer(pubkey, wg_ip)

    # Remote nodes
    node_keys = {}
    try:
        import db
        nodes = db.load_nodes()
        for nid, node in nodes.items():
            if node.get("is_main"):
                continue
            if not node.get("wg_public_key"):
                continue
            node_pubkey = node["wg_public_key"]
            node_subnet = node.get("wg_subnet", "10.10.1.0/24")
            # Generate separate keypair for this node
            node_priv, node_pub = generate_keypair()
            # Assign IP from node's subnet
            node_used = _get_used_ips_from_db_node(nid)
            node_ip = get_next_ip_node(node_used, node_subnet)
            node_keys[nid] = {
                "private_key": node_priv,
                "public_key": node_pub,
                "address": node_ip,
                "server_public_key": node_pubkey,
                "endpoint": node.get("wg_endpoint", ""),
                "subnet": node_subnet,
            }
            # We can't add peer on remote node directly via SSH here
            # The peer will be added when the node syncs via heartbeat
    except Exception as e:
        print(f"[WG] Error setting up remote nodes: {e}")

    user_data["wg_node_keys"] = node_keys
    return user_data


def remove_user_wg(user_data):
    """Remove WireGuard peer for a user."""
    if user_data.get("wg_public_key"):
        remove_peer(user_data["wg_public_key"])


def _get_used_ips_from_db():
    """Get all assigned WG IPs from database."""
    try:
        import db
        return db.get_used_wg_ips()
    except Exception:
        return set()


def _get_used_ips_from_db_node(node_id):
    """Get all assigned WG IPs for a specific node from database."""
    try:
        import db
        return db.get_used_wg_ips_node(node_id)
    except Exception:
        return set()


def get_next_ip_node(existing_ips, subnet="10.10.1.0/24"):
    """Find next available IP in a node's subnet."""
    import ipaddress
    network = ipaddress.ip_network(subnet)
    server_ip = str(list(network.hosts())[0])
    reserved = {server_ip} | set(existing_ips)
    for ip in network.hosts():
        ip_str = str(ip)
        if ip_str not in reserved:
            return ip_str
    raise RuntimeError(f"No available IPs in subnet {subnet}")
