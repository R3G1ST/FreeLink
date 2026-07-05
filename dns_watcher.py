#!/usr/bin/env python3
"""
DNS Watcher for FreeLink
Monitors dnsmasq logs and associates DNS queries with VPN users.
Since Hysteria proxies DNS via localhost, all queries show 127.0.0.1.
We correlate by checking who was connected at the time of each query.
"""
import sys, os, time, json, re
from datetime import datetime, timedelta
from psycopg2.extras import RealDictCursor

sys.path.insert(0, "/opt/freelink")
import db
db.init_db()

DNS_LOG = "/var/log/dnsmasq.log"
DNS_CACHE = "/opt/freelink/dns_log.json"
CHECK_INTERVAL = 3
MAX_ENTRIES = 10000

# Track file position across restarts
_last_pos = 0
_last_date = ""


def parse_dnsmasq_queries(lines):
    """Parse dnsmasq log lines for DNS query entries."""
    queries = []
    for line in lines:
        # Match: query[A] domain from IP  or  query[AAAA] domain from IP
        m = re.search(r'query\[(A+|ANY)\]\s+(\S+)\s+from\s+(\S+)', line)
        if not m:
            continue
        domain = m.group(2)
        client_ip = m.group(3).split('#')[0]  # Remove port suffix if present
        # All queries come from 127.0.0.1 (Hysteria proxies DNS via localhost)
        # We correlate users by timestamp with connection_log, not by IP
        queries.append({"domain": domain, "ip": client_ip})
    return queries


def get_recent_active_users():
    """Find VPN users who were active in the last 60 seconds using connection_log."""
    try:
        with db.get_conn() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT username, client_ip, node_id, connected_at,
                       disconnected_at, 
                       EXTRACT(EPOCH FROM (NOW() - connected_at))::int as age_seconds
                FROM connection_log
                WHERE connected_at > NOW() - INTERVAL '2 minutes'
                  AND (disconnected_at IS NULL 
                       OR disconnected_at > NOW() - INTERVAL '30 seconds')
                ORDER BY connected_at DESC
            """)
            rows = cur.fetchall()
            if not rows:
                return []
            # Return list of (username, node_id) sorted by most recently connected
            return [(r["username"], r["node_id"]) for r in rows]
    except Exception:
        return []


def get_active_user_for_dns():
    """Determine which user most likely made a DNS query right now.

    Since Hysteria proxies DNS through localhost, we can't use client IP.
    Strategy: pick the most recently connected user who is still active.
    If only one user is active, it's definitely them.
    """
    active = get_recent_active_users()
    if len(active) == 1:
        return active[0][0], active[0][1]
    if len(active) > 1:
        # Multiple active users — return the most recently connected
        return active[0][0], active[0][1]
    return "unknown", "__main__"


def save_dns_entries(entries):
    """Append DNS entries to the cache file, keeping only recent ones."""
    if not entries:
        return
    try:
        existing = []
        if os.path.exists(DNS_CACHE):
            with open(DNS_CACHE, 'r') as f:
                existing = json.load(f)
        existing.extend(entries)
        if len(existing) > MAX_ENTRIES:
            existing = existing[-MAX_ENTRIES:]
        with open(DNS_CACHE, 'w') as f:
            json.dump(existing, f)
    except Exception:
        pass


def watch():
    """Main watch loop — tail dnsmasq log and correlate with VPN users."""
    global _last_pos, _last_date

    print(f"[dns-watcher] Started (interval={CHECK_INTERVAL}s)", flush=True)

    # On startup, skip existing log content (don't re-process old entries)
    if os.path.exists(DNS_LOG):
        with open(DNS_LOG, 'r') as f:
            f.seek(0, 2)  # Seek to end
            _last_pos = f.tell()

    while True:
        try:
            if not os.path.exists(DNS_LOG):
                time.sleep(CHECK_INTERVAL)
                continue

            with open(DNS_LOG, 'r') as f:
                f.seek(_last_pos)
                new_lines = f.readlines()
                _last_pos = f.tell()

            if not new_lines:
                time.sleep(CHECK_INTERVAL)
                continue

            queries = parse_dnsmasq_queries(new_lines)
            if not queries:
                time.sleep(CHECK_INTERVAL)
                continue

            # Correlate each DNS query with the active VPN user
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            username, node_id = get_active_user_for_dns()

            entries = []
            for q in queries:
                entries.append({
                    "time": now_str,
                    "user": username,
                    "domain": q["domain"],
                    "ip": q["ip"],
                    "node_id": node_id
                })

            save_dns_entries(entries)
            print(f"[dns-watcher] {len(entries)} queries → user={username}", flush=True)

        except Exception as e:
            print(f"[dns-watcher] Error: {e}", flush=True)

        time.sleep(CHECK_INTERVAL)


if __name__ == '__main__':
    watch()
