#!/usr/bin/env python3
"""
One-time migration: file-based data → PostgreSQL.
Run once: python3 migrate.py
"""
import sys, os, json, yaml

sys.path.insert(0, "/opt/freelink")
os.chdir("/opt/freelink")

import db

DATA_FILE = "data.yaml"
ADMINS_FILE = "admins.json"
SESSIONS_FILE = "sessions.json"
NODES_FILE = "nodes.json"
PLANS_FILE = "plans.json"
SUBS_FILE = "subscriptions.json"

def migrate():
    print("=== FreeLink PostgreSQL Migration ===\n")

    # 1. Init tables
    print("[1/6] Creating tables...")
    db.init_db()

    # 2. Users
    print("[2/6] Migrating users...")
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            data = yaml.safe_load(f) or {}
        users = data.get("users", {})
        count = 0
        for uid, user in users.items():
            db.save_user(uid, user)
            count += 1
        print(f"  ✓ {count} users migrated")
    else:
        print("  ⚠ data.yaml not found, skipping")

    # 3. Admins
    print("[3/6] Migrating admins...")
    if os.path.exists(ADMINS_FILE):
        with open(ADMINS_FILE) as f:
            admins = json.load(f)
        for username, data in admins.items():
            db.save_admin(username, data)
        print(f"  ✓ {len(admins)} admins migrated")
    else:
        print("  ⚠ admins.json not found, creating default admin")
        import hashlib, secrets
        pw = secrets.token_urlsafe(16)
        pw_hash = hashlib.sha256(pw.encode()).hexdigest()
        db.save_admin("admin", {
            "password_hash": pw_hash, "role": "admin",
            "created": "2026-01-01T00:00:00"
        })
        print(f"  ✓ Default admin created. Login: admin, Password: {pw}")

    # 4. Sessions
    print("[4/6] Migrating sessions...")
    if os.path.exists(SESSIONS_FILE):
        with open(SESSIONS_FILE) as f:
            sessions = json.load(f)
        for token, data in sessions.items():
            db.save_session(token, data)
        print(f"  ✓ {len(sessions)} sessions migrated")
    else:
        print("  ⚠ sessions.json not found, skipping")

    # 5. Nodes
    print("[5/6] Migrating nodes...")
    if os.path.exists(NODES_FILE):
        with open(NODES_FILE) as f:
            nodes = json.load(f)
        db.save_nodes(nodes)
        print(f"  ✓ {len(nodes)} nodes migrated")
    else:
        print("  ⚠ nodes.json not found, skipping")

    # 6. Plans
    print("[6/6] Migrating plans...")
    if os.path.exists(PLANS_FILE):
        with open(PLANS_FILE) as f:
            plans = json.load(f)
        db.save_plans(plans)
        print(f"  ✓ {len(plans)} plans migrated")
    else:
        print("  ⚠ plans.json not found, skipping")

    # Subscriptions
    print("  → Migrating subscriptions...")
    if os.path.exists(SUBS_FILE):
        with open(SUBS_FILE) as f:
            subs = json.load(f)
        for sid, data in subs.items():
            db.save_subscription(sid, data)
        print(f"  ✓ {len(subs)} subscriptions migrated")
    else:
        print("  ⚠ subscriptions.json not found, skipping")

    # Verify
    print("\n=== Verification ===")
    users = db.get_all_users()
    admins = db.load_admins()
    nodes = db.load_nodes()
    plans = db.load_plans()
    print(f"Users: {len(users)}")
    print(f"Admins: {len(admins)}")
    print(f"Nodes: {len(nodes)}")
    print(f"Plans: {len(plans)}")
    print("\n✅ Migration complete!")

if __name__ == "__main__":
    migrate()
