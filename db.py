#!/usr/bin/env python3
"""
PostgreSQL database layer for FreeLink.
Provides CRUD functions replacing file-based storage.
"""
import json, os, time, secrets
from datetime import datetime
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor, Json

DB_CONFIG = {
    "host": os.environ.get("PG_HOST", "127.0.0.1"),
    "port": int(os.environ.get("PG_PORT", 5432)),
    "dbname": os.environ.get("PG_DB", "freelink_db"),
    "user": os.environ.get("PG_USER", "freelink"),
    "password": os.environ.get("PG_PASS", "freelink_pass"),
}

_pool = None

def _get_pool():
    global _pool
    if _pool is None or _pool.closed:
        import psycopg2.pool
        _pool = psycopg2.pool.ThreadedConnectionPool(1, 10, **DB_CONFIG)
    return _pool

@contextmanager
def get_conn():
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)

def init_db():
    """Create tables if they don't exist."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                uid TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                active BOOLEAN DEFAULT TRUE,
                created TEXT,
                expire_date TEXT,
                port INTEGER DEFAULT 443,
                server TEXT DEFAULT 'main',
                password TEXT,
                traffic_limit BIGINT DEFAULT 0,
                traffic_used REAL DEFAULT 0,
                traffic_saved_tx BIGINT DEFAULT 0,
                traffic_saved_rx BIGINT DEFAULT 0,
                traffic_saved_total_mb REAL DEFAULT 0,
                traffic_saved_updated TEXT,
                devices JSONB DEFAULT '[]',
                total_sessions INTEGER DEFAULT 0,
                link TEXT,
                service_token TEXT,
                plan TEXT,
                speed_limit_mbps INTEGER DEFAULT 0,
                subscription_id TEXT,
                ip TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                role TEXT DEFAULT 'admin',
                created TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                created TEXT,
                expires TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY,
                data JSONB NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS plans (
                id TEXT PRIMARY KEY,
                name TEXT,
                days INTEGER,
                traffic_limit_mb INTEGER,
                price TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id TEXT PRIMARY KEY,
                uid TEXT,
                plan_id TEXT,
                plan_name TEXT,
                status TEXT,
                created TEXT,
                starts TEXT,
                expires TEXT,
                traffic_limit_mb INTEGER,
                traffic_used_mb REAL DEFAULT 0,
                price TEXT,
                payment_status TEXT,
                auto_renew BOOLEAN DEFAULT FALSE,
                trial BOOLEAN DEFAULT FALSE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id SERIAL PRIMARY KEY,
                time TEXT,
                user_name TEXT,
                action TEXT,
                details TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS traffic_snapshots (
                id SERIAL PRIMARY KEY,
                username TEXT NOT NULL,
                node_id TEXT NOT NULL DEFAULT '__main__',
                tx BIGINT DEFAULT 0,
                rx BIGINT DEFAULT 0,
                captured_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_traffic_user_node ON traffic_snapshots (username, node_id, captured_at DESC)")
        print("[DB] Tables initialized")

# ===== USERS =====

def get_user(uid):
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM users WHERE uid=%s", (uid,))
        row = cur.fetchone()
        return _row_to_user(row) if row else None

def get_user_by_name(name):
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM users WHERE name=%s", (name,))
        row = cur.fetchone()
        return (_row_to_user(row), row["uid"]) if row else (None, None)

def get_user_by_credentials(username, password):
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM users WHERE name=%s AND password=%s", (username, password))
        row = cur.fetchone()
        return (_row_to_user(row), row["uid"]) if row else (None, None)

def get_user_by_service_token(token):
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM users WHERE service_token=%s", (token,))
        row = cur.fetchone()
        return (_row_to_user(row), row["uid"]) if row else (None, None)

def get_all_users():
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM users")
        rows = cur.fetchall()
        result = {}
        for row in rows:
            uid = row["uid"]
            result[uid] = _row_to_user(row)
        return result

def save_user(uid, user_data):
    with get_conn() as conn:
        cur = conn.cursor()
        ts = user_data.get("traffic_saved", {})
        cur.execute("""
            INSERT INTO users (uid, name, active, created, expire_date, port, server, password,
                traffic_limit, traffic_used, traffic_saved_tx, traffic_saved_rx,
                traffic_saved_total_mb, traffic_saved_updated, devices, total_sessions,
                link, service_token, plan, speed_limit_mbps, subscription_id, ip)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (uid) DO UPDATE SET
                name=EXCLUDED.name, active=EXCLUDED.active, created=EXCLUDED.created,
                expire_date=EXCLUDED.expire_date, port=EXCLUDED.port, server=EXCLUDED.server,
                password=EXCLUDED.password, traffic_limit=EXCLUDED.traffic_limit,
                traffic_used=EXCLUDED.traffic_used,
                traffic_saved_tx=EXCLUDED.traffic_saved_tx, traffic_saved_rx=EXCLUDED.traffic_saved_rx,
                traffic_saved_total_mb=EXCLUDED.traffic_saved_total_mb,
                traffic_saved_updated=EXCLUDED.traffic_saved_updated,
                devices=EXCLUDED.devices, total_sessions=EXCLUDED.total_sessions,
                link=EXCLUDED.link, service_token=EXCLUDED.service_token,
                plan=EXCLUDED.plan, speed_limit_mbps=EXCLUDED.speed_limit_mbps,
                subscription_id=EXCLUDED.subscription_id, ip=EXCLUDED.ip
        """, (
            uid, user_data.get("name", uid), user_data.get("active", True),
            user_data.get("created", ""), user_data.get("expire_date", ""),
            user_data.get("port", 443), user_data.get("server", "main"),
            user_data.get("password", ""), user_data.get("traffic_limit", 0),
            user_data.get("traffic_used", 0),
            ts.get("tx", 0), ts.get("rx", 0), ts.get("total_mb", 0), ts.get("updated", ""),
            Json(user_data.get("devices", [])), user_data.get("total_sessions", 0),
            user_data.get("link", ""), user_data.get("service_token", ""),
            user_data.get("plan", ""), user_data.get("speed_limit_mbps", 0),
            user_data.get("subscription_id", ""), user_data.get("ip", "")
        ))

def delete_user(uid):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE uid=%s", (uid,))
        return cur.rowcount > 0

def update_user_field(uid, field, value):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE users SET {field}=%s WHERE uid=%s", (value, uid))

def update_user_traffic_batch(traffic_dict):
    """Batch update traffic for all users from Hysteria stats."""
    with get_conn() as conn:
        cur = conn.cursor()
        for username, t in traffic_dict.items():
            tx = t.get("tx", 0)
            rx = t.get("rx", 0)
            total_mb = round((tx + rx) / 1024 / 1024, 2)
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            cur.execute("""
                UPDATE users SET traffic_saved_tx=%s, traffic_saved_rx=%s,
                    traffic_saved_total_mb=%s, traffic_saved_updated=%s
                WHERE name=%s
            """, (tx, rx, total_mb, now, username))

# ===== ADMINS =====

def load_admins():
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM admins")
        rows = cur.fetchall()
        return {r["username"]: {"password_hash": r["password_hash"],
                                "role": r["role"], "created": r["created"]} for r in rows}

def save_admin(username, data):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO admins (username, password_hash, role, created)
            VALUES (%s,%s,%s,%s)
            ON CONFLICT (username) DO UPDATE SET
                password_hash=EXCLUDED.password_hash, role=EXCLUDED.role, created=EXCLUDED.created
        """, (username, data["password_hash"], data.get("role", "admin"), data.get("created", "")))

def delete_admin(username):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM admins WHERE username=%s", (username,))
        return cur.rowcount > 0

def rename_admin(old_name, new_name):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE admins SET username=%s WHERE username=%s", (new_name, old_name))

# ===== SESSIONS =====

def load_sessions():
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM sessions")
        rows = cur.fetchall()
        return {r["token"]: {"user": r["username"], "created": r["created"],
                             "expires": r["expires"]} for r in rows}

def save_session(token, data):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO sessions (token, username, created, expires)
            VALUES (%s,%s,%s,%s)
            ON CONFLICT (token) DO UPDATE SET
                username=EXCLUDED.username, created=EXCLUDED.created, expires=EXCLUDED.expires
        """, (token, data["user"], data["created"], data["expires"]))

def delete_session(token):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM sessions WHERE token=%s", (token,))

def clean_expired_sessions():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM sessions WHERE expires < %s", (datetime.now().isoformat(),))

# ===== NODES =====

def load_nodes():
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM nodes")
        rows = cur.fetchall()
        return {r["id"]: r["data"] for r in rows}

def save_nodes(nodes):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM nodes")
        for nid, data in nodes.items():
            cur.execute("INSERT INTO nodes (id, data) VALUES (%s, %s)", (nid, Json(data)))

def save_node(nid, data):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO nodes (id, data) VALUES (%s, %s)
            ON CONFLICT (id) DO UPDATE SET data=EXCLUDED.data
        """, (nid, Json(data)))

# ===== PLANS =====

def load_plans():
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM plans")
        rows = cur.fetchall()
        return [{"id": r["id"], "name": r["name"], "days": r["days"],
                 "traffic_limit_mb": r["traffic_limit_mb"], "price": r["price"]} for r in rows]

def save_plans(plans):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM plans")
        for p in plans:
            cur.execute("""
                INSERT INTO plans (id, name, days, traffic_limit_mb, price)
                VALUES (%s,%s,%s,%s,%s)
            """, (p["id"], p["name"], p["days"], p["traffic_limit_mb"], p.get("price", "")))

# ===== SUBSCRIPTIONS =====

def load_subscriptions():
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM subscriptions")
        rows = cur.fetchall()
        return {r["id"]: {k: v for k, v in r.items() if k != "id"} for r in rows}

def save_subscription(sid, data):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO subscriptions (id, uid, plan_id, plan_name, status, created,
                starts, expires, traffic_limit_mb, traffic_used_mb, price,
                payment_status, auto_renew, trial)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET
                uid=EXCLUDED.uid, plan_id=EXCLUDED.plan_id, plan_name=EXCLUDED.plan_name,
                status=EXCLUDED.status, created=EXCLUDED.created, starts=EXCLUDED.starts,
                expires=EXCLUDED.expires, traffic_limit_mb=EXCLUDED.traffic_limit_mb,
                traffic_used_mb=EXCLUDED.traffic_used_mb, price=EXCLUDED.price,
                payment_status=EXCLUDED.payment_status, auto_renew=EXCLUDED.auto_renew,
                trial=EXCLUDED.trial
        """, (
            sid, data.get("uid", ""), data.get("plan_id", ""), data.get("plan_name", ""),
            data.get("status", ""), data.get("created", ""), data.get("starts", ""),
            data.get("expires", ""), data.get("traffic_limit_mb", 0),
            data.get("traffic_used_mb", 0), data.get("price", ""),
            data.get("payment_status", ""), data.get("auto_renew", False),
            data.get("trial", False)
        ))

# ===== AUDIT LOG =====

def audit_log(user_name, action, details=""):
    with get_conn() as conn:
        cur = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("INSERT INTO audit_log (time, user_name, action, details) VALUES (%s,%s,%s,%s)",
                    (now, user_name, action, details))

def get_audit_log(limit=200):
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT %s", (limit,))
        rows = cur.fetchall()
        lines = [f"[{r['time']}] {r['user_name']}: {r['action']} {r['details']}" for r in rows]
        return "\n".join(reversed(lines))

# ===== HELPERS =====

def _row_to_user(row):
    return {
        "name": row["name"], "active": row["active"],
        "created": row["created"] or "", "expire_date": row["expire_date"] or "",
        "port": row["port"] or 443, "server": row["server"] or "main",
        "password": row["password"] or "",
        "traffic_limit": row["traffic_limit"] or 0,
        "traffic_used": row["traffic_used"] or 0,
        "traffic_saved": {
            "tx": row["traffic_saved_tx"] or 0,
            "rx": row["traffic_saved_rx"] or 0,
            "total_mb": row["traffic_saved_total_mb"] or 0,
            "updated": row["traffic_saved_updated"] or ""
        },
        "devices": row["devices"] if isinstance(row["devices"], list) else [],
        "total_sessions": row["total_sessions"] or 0,
        "link": row["link"] or "", "service_token": row["service_token"] or "",
        "plan": row["plan"] or "", "speed_limit_mbps": row["speed_limit_mbps"] or 0,
        "subscription_id": row["subscription_id"] or "",
        "ip": row["ip"] or ""
    }

# ===== TRAFFIC SNAPSHOTS =====

def save_traffic_snapshot(username, node_id, tx, rx):
    """Save a cumulative traffic snapshot from a specific node."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO traffic_snapshots (username, node_id, tx, rx, captured_at)
            VALUES (%s, %s, %s, %s, NOW())
        """, (username.lower(), node_id, tx, rx))

def save_traffic_snapshots_batch(snapshots):
    """Batch save traffic snapshots. snapshots = [{username, node_id, tx, rx}, ...]"""
    if not snapshots:
        return
    with get_conn() as conn:
        cur = conn.cursor()
        from psycopg2.extras import execute_values
        execute_values(cur,
            "INSERT INTO traffic_snapshots (username, node_id, tx, rx) VALUES %s",
            [(s["username"].lower(), s.get("node_id", "__main__"), s["tx"], s["rx"]) for s in snapshots],
            template=None, page_size=500
        )

def get_user_traffic_per_node(username):
    """Get the latest traffic snapshot per node for a user (last 10 min)."""
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT node_id, tx, rx, captured_at
            FROM traffic_snapshots
            WHERE username = %s AND captured_at > NOW() - INTERVAL '10 minutes'
            AND id IN (
                SELECT MAX(id) FROM traffic_snapshots
                WHERE username = %s AND captured_at > NOW() - INTERVAL '10 minutes'
                GROUP BY node_id
            )
        """, (username.lower(), username.lower()))
        return {r["node_id"]: {"tx": r["tx"], "rx": r["rx"]} for r in cur.fetchall()}

def get_all_user_traffic():
    """Get aggregated traffic for ALL users across all nodes (latest snapshot per node per user)."""
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT username, node_id, tx, rx
            FROM traffic_snapshots t1
            WHERE captured_at > NOW() - INTERVAL '10 minutes'
            AND id = (
                SELECT MAX(id) FROM traffic_snapshots t2
                WHERE t2.username = t1.username AND t2.node_id = t1.node_id
                AND t2.captured_at > NOW() - INTERVAL '10 minutes'
            )
        """)
        result = {}
        for r in cur.fetchall():
            u = r["username"]
            if u not in result:
                result[u] = {"tx": 0, "rx": 0}
            result[u]["tx"] += r["tx"]
            result[u]["rx"] += r["rx"]
        return result

def cleanup_old_snapshots():
    """Remove snapshots older than 1 hour."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM traffic_snapshots WHERE captured_at < NOW() - INTERVAL '1 hour'")

def get_online_users(window_seconds=30):
    """
    Online detection — Marzban style:
    User is online if they appear in ANY traffic snapshot within the window.
    No traffic change required — connected = online.
    """
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Latest snapshot per user (any node) within window
        cur.execute("""
            SELECT username,
                   SUM(tx) as tx, SUM(rx) as rx,
                   MAX(captured_at) as last_active
            FROM (
                SELECT DISTINCT ON (username, node_id)
                       username, node_id, tx, rx, captured_at
                FROM traffic_snapshots
                WHERE captured_at > NOW() - make_interval(secs => %s)
                ORDER BY username, node_id, captured_at DESC
            ) sub
            GROUP BY username
        """, (window_seconds,))
        latest = {r["username"]: r for r in cur.fetchall()}

        # Previous snapshot for speed calculation
        cur.execute("""
            SELECT username,
                   SUM(tx) as tx, SUM(rx) as rx
            FROM (
                SELECT DISTINCT ON (username, node_id)
                       username, node_id, tx, rx
                FROM traffic_snapshots
                WHERE captured_at > NOW() - make_interval(secs => %s)
                ORDER BY username, node_id, captured_at DESC
            ) sub
            GROUP BY username
        """, (window_seconds * 3,))
        prev = {r["username"]: r for r in cur.fetchall()}

        result = {}
        for username, snap in latest.items():
            p = prev.get(username, {})
            tx_speed = max(0, snap["tx"] - p.get("tx", snap["tx"]))
            rx_speed = max(0, snap["rx"] - p.get("rx", snap["rx"]))
            result[username] = {
                "online": True,
                "tx": snap["tx"],
                "rx": snap["rx"],
                "tx_speed": tx_speed,
                "rx_speed": rx_speed,
                "last_active": str(snap["last_active"]),
            }
        return result
