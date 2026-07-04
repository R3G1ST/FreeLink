#!/usr/bin/env python3
"""
DNS Logger for FreeLink
Logs DNS queries to track which websites users visit.
Runs alongside the VPN to capture DNS requests.
"""
import sys, time, json, os
from datetime import datetime

sys.path.insert(0, "/opt/freelink")
import db
db.init_db()

LOG_FILE = "/opt/freelink/dns_log.json"
MAX_ENTRIES = 10000

def log_dns_query(username, domain, client_ip):
    """Log a DNS query for a user."""
    try:
        entries = []
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'r') as f:
                entries = json.load(f)
        
        entries.append({
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "user": username,
            "domain": domain,
            "ip": client_ip
        })
        
        # Keep only last MAX_ENTRIES
        if len(entries) > MAX_ENTRIES:
            entries = entries[-MAX_ENTRIES:]
        
        with open(LOG_FILE, 'w') as f:
            json.dump(entries, f)
    except Exception:
        pass

def get_recent_dns(limit=100):
    """Get recent DNS queries."""
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'r') as f:
                entries = json.load(f)
            return entries[-limit:]
    except Exception:
        pass
    return []

if __name__ == '__main__':
    print("DNS Logger started")
    # This would need to be integrated with a DNS server
    # For now, it's a placeholder for future implementation
