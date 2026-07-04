#!/usr/bin/env python3
"""
DNS Watcher for FreeLink
Monitors dnsmasq logs and associates DNS queries with VPN users.
"""
import sys, os, time, json, re
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, "/opt/freelink")
import db
db.init_db()

DNS_LOG = "/var/log/dnsmasq.log"
DNS_CACHE = "/opt/freelink/dns_log.json"
CHECK_INTERVAL = 5
MAX_ENTRIES = 5000

def get_active_connections():
    """Get currently active VPN connections with their IPs."""
    with db.get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT username, client_ip, node_id
            FROM connection_log
            WHERE disconnected_at IS NULL
              AND connected_at > NOW() - INTERVAL '5 minutes'
        """)
        return {r[1]: {"username": r[0], "node_id": r[2]} for r in cur.fetchall()}

def parse_dnsmasq_log():
    """Parse dnsmasq log file for DNS queries."""
    queries = []
    try:
        if not os.path.exists(DNS_LOG):
            return queries
        with open(DNS_LOG, 'r') as f:
            for line in f:
                # dnsmasq log format: "Jul  4 20:54:17 dnsmasq[pid]: query[A] domain from 127.0.0.1"
                m = re.search(r'query\[A+\]\s+(\S+)\s+from\s+(\S+)', line)
                if m:
                    domain = m.group(1)
                    client_ip = m.group(2).split('#')[0]  # Remove port
                    # Skip localhost and DNS server queries
                    if client_ip in ('127.0.0.1', '::1', '8.8.8.8', '8.8.4.4'):
                        continue
                    # Get timestamp from log line
                    ts_match = re.search(r'(\w+\s+\d+\s+\d+:\d+:\d+)', line)
                    ts = ts_match.group(1) if ts_match else ''
                    queries.append({"time": ts, "domain": domain, "ip": client_ip})
    except Exception:
        pass
    return queries

def correlate_with_users(queries, connections):
    """Associate DNS queries with VPN users by IP."""
    results = []
    for q in queries:
        conn = connections.get(q["ip"])
        if conn:
            results.append({
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "user": conn["username"],
                "domain": q["domain"],
                "ip": q["ip"],
                "node_id": conn["node_id"]
            })
    return results

def save_dns_log(entries):
    """Save DNS entries to cache file."""
    try:
        existing = []
        if os.path.exists(DNS_CACHE):
            with open(DNS_CACHE, 'r') as f:
                existing = json.load(f)
        existing.extend(entries)
        # Keep only recent entries
        if len(existing) > MAX_ENTRIES:
            existing = existing[-MAX_ENTRIES:]
        with open(DNS_CACHE, 'w') as f:
            json.dump(existing, f)
    except Exception:
        pass

def watch():
    """Main watch loop."""
    print(f"[dns-watcher] Started (interval={CHECK_INTERVAL}s)", flush=True)
    last_pos = 0
    while True:
        try:
            # Read new lines from dnsmasq log
            if os.path.exists(DNS_LOG):
                with open(DNS_LOG, 'r') as f:
                    f.seek(last_pos)
                    new_lines = f.readlines()
                    last_pos = f.tell()
                
                if new_lines:
                    # Parse DNS queries
                    queries = []
                    for line in new_lines:
                        m = re.search(r'query\[A+\]\s+(\S+)\s+from\s+(\S+)', line)
                        if m:
                            domain = m.group(1)
                            client_ip = m.group(2).split('#')[0]
                            if client_ip not in ('127.0.0.1', '::1', '8.8.8.8', '8.8.4.4'):
                                queries.append({"domain": domain, "ip": client_ip})
                    
                    if queries:
                        # Get active connections
                        connections = get_active_connections()
                        # Correlate
                        entries = []
                        for q in queries:
                            conn = connections.get(q["ip"])
                            if conn:
                                entries.append({
                                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    "user": conn["username"],
                                    "domain": q["domain"],
                                    "ip": q["ip"],
                                    "node_id": conn["node_id"]
                                })
                        if entries:
                            save_dns_log(entries)
                            print(f"[dns-watcher] Logged {len(entries)} DNS queries", flush=True)
        except Exception as e:
            print(f"[dns-watcher] Error: {e}", flush=True)
        time.sleep(CHECK_INTERVAL)

if __name__ == '__main__':
    watch()
