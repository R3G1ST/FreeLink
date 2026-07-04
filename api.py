#!/usr/bin/env python3
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, Response, HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import yaml, os, subprocess, re, json, requests, time, hashlib, secrets, base64, io, sys, tarfile, hmac
from datetime import datetime, timedelta
import random, string
import psutil
import uvicorn
import bcrypt
from dotenv import load_dotenv
import db

# Load environment variables from .env file
load_dotenv()


# ====== PYDANTIC MODELS (for Swagger docs) ======

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, description="Admin username")
    password: str = Field(..., min_length=1, description="Admin password")

class UserCreate(BaseModel):
    name: str = Field(..., min_length=2, description="Username (latin)")
    days: int = Field(30, ge=1, description="Subscription days")

class UserCreateWithPlan(BaseModel):
    name: str = Field(..., min_length=2)
    plan_id: str = Field(..., description="Plan ID")

class PlanCreate(BaseModel):
    name: str = Field(..., min_length=1)
    days: int = Field(30, ge=1)
    traffic_limit_mb: int = Field(0, ge=0, description="0 = unlimited")
    price: str = Field("")

class SpeedLimitRequest(BaseModel):
    speed_mbps: int = Field(0, ge=0, description="0 = no limit")

class TrafficLimitRequest(BaseModel):
    limit_mb: int = Field(0, ge=0)

class NodeRegister(BaseModel):
    name: str = Field(..., min_length=1)
    ip: str = Field(..., min_length=1)
    region: str = Field("")
    country: str = Field("")
    max_users: int = Field(100)

class NodeDeploy(BaseModel):
    host: str = Field(..., description="SSH host")
    port: int = Field(22)
    username: str = Field(..., description="SSH username")
    password: str = Field("")
    key: str = Field("", description="SSH private key content")
    name: str = Field("")
    region: str = Field("")
    panel_url: str = Field("https://link.qmbox.ru")  # Default, overridden by env

class AdminCreate(BaseModel):
    username: str = Field(..., min_length=3, pattern=r'^[a-zA-Z0-9_]+$')
    password: str = Field(..., min_length=6)
    role: str = Field("viewer", pattern=r'^(admin|editor|viewer)$')

class AdminUpdate(BaseModel):
    password: Optional[str] = Field(None, min_length=6)
    role: Optional[str] = Field(None, pattern=r'^(admin|editor|viewer)$')

class PasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6)

class UsernameChange(BaseModel):
    new_username: str = Field(..., min_length=3, pattern=r'^[a-zA-Z0-9_]+$')
    password: str

class SubscriptionCreate(BaseModel):
    uid: str
    plan_id: str
    trial: bool = False

class SubscriptionRenew(BaseModel):
    days: int = Field(30, ge=1)

class PaymentAdd(BaseModel):
    uid: str = ""
    amount: float = Field(0, ge=0)
    currency: str = "RUB"
    method: str = "manual"
    status: str = "confirmed"
    sub_id: str = ""
    comment: str = ""

class BulkDelete(BaseModel):
    ids: List[str]

class BulkToggle(BaseModel):
    ids: List[str]

class BulkExtend(BaseModel):
    ids: List[str]
    days: int = Field(30, ge=1)

class ConfigSave(BaseModel):
    config: str = Field(..., description="YAML content")

class TelegramToken(BaseModel):
    token: str = Field(..., min_length=1)

class TelegramAdminAdd(BaseModel):
    admin_id: int

class TelegramAdminRemove(BaseModel):
    admin_id: int

class ServiceTokenGen(BaseModel):
    pass
try:
    import qrcode
    HAS_QR = True
except ImportError:
    HAS_QR = False
try:
    import geoip2.database
    import geoip2.errors
    HAS_GEOIP = True
except ImportError:
    HAS_GEOIP = False

app = FastAPI(
    title="FreeLink — Hysteria 2 Management API",
    description="Multi-server VPN panel with subscription system, online detection, and Telegram bot integration.",
    version="3.10.10",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# CORS configuration - restricted to allowed origins
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "https://link.qmbox.ru").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)

# Rate limiting
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

DATA_FILE = "/opt/freelink/data.yaml"
CONFIG_FILE = "/opt/freelink/config.yaml"
ONLINE_FILE = "/opt/freelink/online_status.json"
AUDIT_FILE = "/opt/freelink/audit.log"

# ====== ADMIN AUTH ======

def load_admins():
    admins = db.load_admins()
    if not admins:
        default_pw = secrets.token_urlsafe(16)
        admins = {"admin": {"password_hash": hash_pw(default_pw), "role": "admin", "created": datetime.now().isoformat()}}
        db.save_admin("admin", admins["admin"])
        print(f"!!! Default admin created. Login: admin, Password: {default_pw}")
    return admins

def save_admins(admins):
    for username, data in admins.items():
        db.save_admin(username, data)

def hash_pw(pw):
    """Hash password with bcrypt (12 rounds)."""
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=12)).decode()

def verify_pw(pw, hashed):
    """Verify password against bcrypt or legacy SHA-256 hash."""
    if not hashed or not pw:
        return False
    if is_legacy_hash(hashed):
        return hashlib.sha256(pw.encode()).hexdigest() == hashed
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception:
        return False

def is_legacy_hash(hashed):
    """Check if hash is legacy SHA-256 (64 hex chars, no $ prefix)."""
    return len(hashed) == 64 and not hashed.startswith("$")

def load_sessions():
    return db.load_sessions()

def save_sessions(sessions):
    for token, data in sessions.items():
        db.save_session(token, data)

def audit_log(user, action, details=""):
    db.audit_log(user, action, details)

def create_session(username):
    token = secrets.token_urlsafe(32)
    data = {"user": username, "created": datetime.now().isoformat(),
            "expires": (datetime.now() + timedelta(hours=24)).isoformat()}
    db.save_session(token, data)
    return token

def validate_session(token):
    if not token:
        return None
    sessions = load_sessions()
    s = sessions.get(token)
    if not s:
        return None
    if datetime.fromisoformat(s["expires"]) < datetime.now():
        db.delete_session(token)
        return None
    return s["user"]

API_TOKEN = os.environ.get("API_TOKEN", "")

@app.middleware("http")
async def check_auth(request: Request, call_next):
    path = request.url.path

    # Static files, login page, and docs - always allowed
    if path in ["/favicon.ico", "/login", "/app", "/deploy-test", "/docs", "/redoc"] or path.startswith("/static/") or path.startswith("/api/docs") or path.startswith("/api/redoc") or path.startswith("/api/openapi") or path.startswith("/app/") or path.startswith("/ws/"):
        return await call_next(request)

    # API auth endpoints - always allowed
    if path in ["/api/login", "/api/logout", "/api/auth", "/api/miniapp/auth", "/api/miniapp/login", "/api/miniapp/quick-login", "/form-login"]:
        return await call_next(request)

    # Node endpoints (authenticated via node token in body, not session cookie)
    if path.startswith("/api/node/"):
        return await call_next(request)

    # Truly public endpoints (no auth needed - minimal info only)
    public_api = ["/api/status", "/api/version", "/api/plans", "/api/session-token"]
    if any(path.startswith(p) for p in public_api):
        return await call_next(request)

    # Self-service portal (token-gated, no session auth)
    if path.startswith("/s/"):
        return await call_next(request)

    # Subscription endpoints (token-gated, no session auth)
    if path.startswith("/sub/"):
        return await call_next(request)

    # Client portal
    if path in ["/client", "/c"] or path.startswith("/client/"):
        return await call_next(request)

    # Check session for all other API and page requests
    token = request.cookies.get("session")
    if not token:
        token = request.query_params.get("_t", "")
    user = validate_session(token)
    if not user:
        if path.startswith("/api/"):
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        return RedirectResponse(url="/login", status_code=302)

    return await call_next(request)

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return yaml.safe_load(f)
    except Exception:
        return {}

def load_data():
    users = db.get_all_users()
    return {"servers": {}, "users": users}

def save_data(data):
    for uid, user_data in data.get("users", {}).items():
        db.save_user(uid, user_data)

def gen_id():
    return secrets.token_hex(4)

def get_user(uid):
    return db.get_user(uid)

def get_all_users():
    return db.get_all_users()

def get_aggregated_traffic():
    """Aggregate per-user traffic from all nodes via traffic_snapshots table."""
    return db.get_all_user_traffic()

def save_user(uid, user_data):
    db.save_user(uid, user_data)

def delete_user(uid):
    return db.delete_user(uid)

def get_user_link(uid, user):
    if "link" in user and user["link"]:
        return user["link"]

    config = load_config()
    h = config.get("hysteria", {}) if config else {}
    s = config.get("server", {}) if config else {}
    domain = os.environ.get("DOMAIN", s.get("domain", "link.qmbox.ru"))
    port = 443
    name = user.get("name", uid)
    password = user.get("password", os.environ.get("HYSTERIA_USER_PASSWORD", ""))
    obfs = os.environ.get("HYSTERIA_OBFS_PASSWORD", "")

    if obfs:
        return f"hysteria2://{name}:{password}@{domain}:{port}?sni={domain}&obfs=salamander&obfs-password={obfs}&insecure=0#{name}"
    return f"hysteria2://{name}:{password}@{domain}:{port}?sni={domain}&insecure=0#{name}"

def get_hysteria_stats():
    try:
        response = requests.get("http://127.0.0.1:9999/traffic", timeout=2)
        if response.status_code == 200:
            return response.json()
        return None
    except Exception:
        return None

def find_online_user(online_status, username):
    """Case-insensitive lookup in online_status dict."""
    return online_status.get(username, {}) or online_status.get(username.lower(), {})

def get_online_status():
    """Online status — traffic-change based: online only if tx/rx differs between snapshots."""
    try:
        status = db.get_online_users(window_seconds=60)
        # Merge last_active from remote node heartbeats (don't override online status)
        nodes = load_nodes()
        for nid, node in nodes.items():
            if node.get("is_main"):
                continue
            try:
                last = datetime.fromisoformat(node.get("last_seen", ""))
                is_online = (datetime.now() - last).total_seconds() < 120
            except Exception:
                is_online = False
            if not is_online:
                continue
            node_time = node.get("last_seen", "")
            for username in node.get("online_usernames", []):
                key = username.lower()
                if key in status and node_time > status[key].get("last_active", ""):
                    status[key]["last_active"] = node_time
        return status
    except Exception as e:
        print(f"[online] Error: {e}", flush=True)
        return {}

def get_server_info():
    info = {}
    try:
        info["cpu_percent"] = psutil.cpu_percent(interval=0.5)
        info["cpu_count"] = psutil.cpu_count()
        mem = psutil.virtual_memory()
        info["ram_total_gb"] = round(mem.total / (1024**3), 1)
        info["ram_used_gb"] = round(mem.used / (1024**3), 1)
        info["ram_percent"] = mem.percent
        disk = psutil.disk_usage('/')
        info["disk_total_gb"] = round(disk.total / (1024**3), 1)
        info["disk_used_gb"] = round(disk.used / (1024**3), 1)
        info["disk_percent"] = disk.percent
        net = psutil.net_io_counters()
        info["net_sent_gb"] = round(net.bytes_sent / (1024**3), 2)
        info["net_recv_gb"] = round(net.bytes_recv / (1024**3), 2)
        uptime = subprocess.run(["uptime", "-p"], capture_output=True, text=True, timeout=3)
        info["uptime"] = uptime.stdout.strip().replace("up ", "") if uptime.returncode == 0 else "?"
    except Exception:
        pass
    return info

# ====== AUTH ======

@app.post("/api/auth")
@limiter.limit("5/minute")
async def auth_user(request: Request):
    try:
        data = await request.json()
        auth_password = data.get("auth")

        if ':' in (auth_password or ''):
            username, password = auth_password.split(':', 1)
            users = get_all_users()
            for uid, user in users.items():
                if user.get("name") == username and hmac.compare_digest(user.get("password", ""), password):
                    return JSONResponse(status_code=200, content={"ok": True, "id": username})

        return JSONResponse(status_code=401, content={"error": "Invalid credentials"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "Internal server error"})

# ====== MINI APP ======

@app.get("/app")
async def miniapp_page():
    with open("/opt/freelink/web/miniapp.html", "r") as f:
        content = f.read()
    return HTMLResponse(content=content, headers={
        "Cache-Control": "no-cache, no-store, must-revalidate"
    })

@app.get("/app/{token}")
async def miniapp_page_token(token: str):
    """Mini app with token in URL — validates token and sets cookie."""
    # Validate that the token is a real session before setting cookie
    sessions = load_sessions()
    if token not in sessions:
        return RedirectResponse(url="/app?error=invalid_token", status_code=302)
    with open("/opt/freelink/web/miniapp.html", "r") as f:
        content = f.read()
    resp = HTMLResponse(content=content, headers={
        "Cache-Control": "no-cache, no-store, must-revalidate"
    })
    resp.set_cookie("session", token, max_age=86400, httponly=True, secure=True, samesite="lax")
    return resp

@app.post("/form-login")
@limiter.limit("5/minute")
async def form_login(request: Request):
    """Traditional form POST login — no JS required."""
    from starlette.formparsers import MultiPartParser
    form = await request.form()
    username = form.get("username", "")
    password = form.get("password", "")
    if not username or not password:
        return RedirectResponse(url="/app?error=empty", status_code=302)
    admins = load_admins()
    admin = admins.get(username)
    if not admin or not verify_pw(password, admin["password_hash"]):
        return RedirectResponse(url="/app?error=bad", status_code=302)
    token = create_session(username)
    audit_log(username, "MINIAPP_LOGIN", "method=form")
    resp = RedirectResponse(url=f"/app/{token}", status_code=302)
    resp.set_cookie("session", token, max_age=86400, httponly=True, secure=True, samesite="lax")
    return resp

@app.post("/api/miniapp/auth")
@limiter.limit("5/minute")
async def miniapp_auth(request: Request):
    data = await request.json()
    init_data = data.get("initData", "")
    if not init_data:
        return JSONResponse(status_code=400, content={"error": "Нет данных"})

    # Verify Telegram HMAC signature
    bot_token = os.environ.get("TELEGRAM_TOKEN", "")
    if bot_token:
        from urllib.parse import unquote
        decoded = unquote(init_data)
        pairs = decoded.split("&")
        # Extract hash and build data_check_string
        received_hash = None
        data_check_pairs = []
        for pair in pairs:
            if "=" not in pair:
                continue
            key, val = pair.split("=", 1)
            if key == "hash":
                received_hash = val
            else:
                data_check_pairs.append(pair)
        if not received_hash:
            return JSONResponse(status_code=401, content={"error": "Missing hash"})
        data_check_string = "\n".join(sorted(data_check_pairs))
        secret_key = hmac.new("WebAppData".encode(), bot_token.encode(), hashlib.sha256).digest()
        expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_hash, received_hash):
            audit_log("unknown", "MINIAPP_AUTH_FAILED", "invalid_signature")
            return JSONResponse(status_code=401, content={"error": "Invalid signature"})
        # Parse user data after successful verification
        params = dict(item.split("=", 1) for item in pairs if "=" in item and item.split("=", 1)[0] != "hash")
        user_json = params.get("user", "{}")
    else:
        from urllib.parse import unquote
        decoded = unquote(init_data)
        params = dict(item.split("=", 1) for item in decoded.split("&") if "=" in item)
        user_json = params.get("user", "{}")

    try:
        user_data = json.loads(user_json)
        username = user_data.get("username", "")
        user_id = user_data.get("id", 0)
        first_name = user_data.get("first_name", "")
    except Exception:
        username = ""
        user_id = 0
        first_name = ""
    display_name = username or first_name or f"tg_{user_id}"
    token = create_session(f"tg:{display_name}")
    audit_log(f"tg:{display_name}", "MINIAPP_LOGIN", f"tg_id={user_id}")
    resp = JSONResponse(content={"success": True, "username": display_name, "token": token})
    resp.set_cookie("session", token, max_age=86400, httponly=True, secure=True, samesite="lax")
    return resp

@app.post("/api/miniapp/login")
@limiter.limit("5/minute")
async def miniapp_login(request: Request):
    data = await request.json()
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if not username or not password:
        return JSONResponse(status_code=400, content={"error": "Заполните все поля"})
    admins = load_admins()
    admin = admins.get(username)
    if not admin or not verify_pw(password, admin["password_hash"]):
        audit_log(username or "unknown", "MINIAPP_LOGIN_FAILED")
        return JSONResponse(status_code=401, content={"error": "Неверный логин или пароль"})
    token = create_session(username)
    audit_log(username, "MINIAPP_LOGIN", "method=password")
    resp = JSONResponse(content={"success": True, "username": username, "token": token})
    resp.set_cookie("session", token, max_age=86400, httponly=True, secure=True, samesite="lax")
    return resp

@app.get("/api/miniapp/quick-login")
async def miniapp_quick_login(username: str = "", password: str = ""):
    """Login via GET URL — redirects to /app/{token} with cookie."""
    if not username or not password:
        return RedirectResponse(url="/app")
    admins = load_admins()
    admin = admins.get(username)
    if not admin or not verify_pw(password, admin["password_hash"]):
        return RedirectResponse(url="/app?error=1")
    token = create_session(username)
    audit_log(username, "MINIAPP_LOGIN", "method=quick-login")
    resp = RedirectResponse(url=f"/app/{token}")
    resp.set_cookie("session", token, max_age=86400, httponly=True, secure=True, samesite="lax")
    return resp

@app.get("/api/miniapp/status")
async def miniapp_status():
    try:
        result = subprocess.run(["/usr/bin/systemctl", "is-active", "hysteria-server"], capture_output=True, text=True, timeout=5)
        return {"status": "active" if result.stdout.strip() == "active" else "inactive"}
    except Exception:
        return {"status": "unknown"}

@app.get("/api/miniapp/users")
async def miniapp_users():
    users = get_all_users()
    online_status = get_online_status()
    nodes = load_nodes()
    result = []
    for uid, user in users.items():
        link = get_user_link(uid, user)
        username = user.get("name", uid)
        user_online = find_online_user(online_status, username)
        ts = user.get("traffic_saved", {})
        tx_bytes = ts.get("tx", 0)
        rx_bytes = ts.get("rx", 0)
        # Aggregate traffic from remote nodes
        username_lower = username.lower()
        for nid, node in nodes.items():
            if node.get("is_main"):
                continue
            for node_user, ut in node.get("user_traffic", {}).items():
                if node_user.lower() == username_lower:
                    tx_bytes += ut.get("tx", 0)
                    rx_bytes += ut.get("rx", 0)
        total_mb = round((tx_bytes + rx_bytes) / 1024 / 1024, 2)
        result.append({
            "id": uid, "name": username, "active": user.get("active", True),
            "expire_date": user.get("expire_date", ""), "online": user_online.get("online", False),
            "link": link, "traffic": {"total_mb": total_mb, "tx_mb": round(tx_bytes/1024/1024, 2), "rx_mb": round(rx_bytes/1024/1024, 2), "limit_mb": user.get("traffic_limit", 0)}
        })
    return {"users": result}

@app.get("/api/miniapp/online")
async def miniapp_online():
    online_status = get_online_status()
    users = get_all_users()
    online_count = sum(1 for uid, user in users.items() if online_status.get(user.get("name", uid), {}).get("online", False))
    return {"online": online_count}

_prev_net = {"bytes": 0, "time": 0}

@app.get("/api/miniapp/server-info")
async def miniapp_server_info():
    global _prev_net
    info = {}
    try:
        info["cpu_percent"] = psutil.cpu_percent(interval=0.3)
        info["cpu_count"] = psutil.cpu_count()
        info["load_avg"] = list(psutil.getloadavg())
        info["process_count"] = len(psutil.pids())
        mem = psutil.virtual_memory()
        info["ram_percent"] = mem.percent
        info["ram_used_gb"] = round(mem.used / (1024**3), 1)
        info["ram_total_gb"] = round(mem.total / (1024**3), 1)
        disk = psutil.disk_usage('/')
        info["disk_percent"] = disk.percent
        info["disk_used_gb"] = round(disk.used / (1024**3), 1)
        info["disk_total_gb"] = round(disk.total / (1024**3), 1)
        net = psutil.net_io_counters()
        info["net_sent_gb"] = round(net.bytes_sent / (1024**3), 2)
        info["net_recv_gb"] = round(net.bytes_recv / (1024**3), 2)
        now = time.time()
        total_bytes = net.bytes_sent + net.bytes_recv
        if _prev_net["time"] > 0 and now > _prev_net["time"]:
            dt = now - _prev_net["time"]
            delta = total_bytes - _prev_net["bytes"]
            speed = max(0, delta / dt)
            info["net_speed"] = round(speed / 1024, 1)
        else:
            info["net_speed"] = 0
        _prev_net = {"bytes": total_bytes, "time": now}
        try:
            import subprocess as sp
            r = sp.run(["/usr/bin/cat", "/proc/uptime"], capture_output=True, text=True, timeout=3)
            uptime_secs = float(r.stdout.strip().split()[0])
            days = int(uptime_secs // 86400)
            hours = int((uptime_secs % 86400) // 3600)
            mins = int((uptime_secs % 3600) // 60)
            parts = []
            if days > 0: parts.append(f"{days} дн")
            if hours > 0: parts.append(f"{hours} ч")
            parts.append(f"{mins} мин")
            info["uptime"] = ", ".join(parts)
        except Exception:
            info["uptime"] = "?"
    except Exception as e:
        info["error"] = str(e)
    return JSONResponse(content=info)

@app.get("/api/miniapp/traffic-history")
async def miniapp_traffic_history(hours: int = 1):
    if not os.path.exists(TRAFFIC_HISTORY_FILE):
        return {"history": []}
    try:
        with open(TRAFFIC_HISTORY_FILE, 'r') as f:
            history = json.load(f)
        cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")
        return {"history": [h for h in history if h["time"] >= cutoff]}
    except Exception:
        return {"history": []}

@app.get("/api/miniapp/live-traffic")
async def miniapp_live_traffic():
    online_status = get_online_status()
    users = get_all_users()
    result = []
    for uid, user in users.items():
        username = user.get("name", uid)
        user_online = find_online_user(online_status, username)
        if user_online.get("online"):
            tx_speed = user_online.get("tx_speed", 0)
            rx_speed = user_online.get("rx_speed", 0)
            result.append({
                "user": username,
                "tx_speed_mb": round(tx_speed / 1024 / 1024, 2),
                "rx_speed_mb": round(rx_speed / 1024 / 1024, 2),
                "total_speed_mb": round((tx_speed + rx_speed) / 1024 / 1024, 2),
                "last_active": user_online.get("last_active", "")
            })
    return {"traffic": result, "count": len(result)}

@app.get("/api/miniapp/nodes")
async def miniapp_nodes():
    nodes = load_nodes()
    now = datetime.now()
    result = []
    for nid, node in nodes.items():
        is_main = node.get("is_main", False)
        if is_main:
            is_online = True
        else:
            try:
                last = datetime.fromisoformat(node.get("last_seen", ""))
                is_online = (now - last).total_seconds() < 120
            except Exception:
                is_online = False
        node["id"] = nid
        node["is_online"] = is_online
        result.append(node)
    return {"nodes": result}

@app.post("/api/miniapp/nodes/deploy")
async def miniapp_deploy_node(request: Request):
    data = await request.json()
    host = data.get("host", "").strip()
    port = int(data.get("port", 22))
    username = data.get("username", "").strip()
    password = data.get("password", "")
    node_name = data.get("name", host).strip()
    panel_url = data.get("panel_url", f"https://{os.environ.get('DOMAIN', 'link.qmbox.ru')}")

    if not host or not username:
        return JSONResponse(status_code=400, content={"error": "host и username обязательны"})
    if not password:
        return JSONResponse(status_code=400, content={"error": "Укажите SSH пароль"})

    import paramiko, asyncio, concurrent.futures

    def _do_deploy():
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.WarningPolicy())
        try:
            ssh.connect(hostname=host, port=port, username=username, password=password, timeout=15)
        except Exception as e:
            return {"error": f"SSH: {str(e)}"}

        deploy_script = f"""#!/bin/bash
set -e
echo "=== Предварительные тесты ==="
echo -n "1. OS: "; cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d'"' -f2 || echo "Unknown"
echo -n "2. Root: "; [ "$(id -u)" = "0" ] && echo "✓ OK" || echo "✗ нужен root"
echo -n "3. Python3: "; python3 --version 2>&1 || echo "✗ не установлен"
echo -n "4. curl: "; curl --version >/dev/null 2>&1 && echo "✓ OK" || echo "✗ не установлен"
echo "=== Установка Hysteria 2 ==="
apt-get update -qq
apt-get install -y -qq python3 python3-pip curl certbot
bash <(curl -fsSL https://get.hy2.sh/) || true
echo "=== Установка зависимостей агента ==="
pip3 install psutil pyyaml 2>/dev/null || pip3 install --break-system-packages psutil pyyaml
echo "=== Установка DNS логгера ==="
apt-get install -y -qq dnsmasq 2>/dev/null || true
cat > /etc/dnsmasq.d/freelink.conf << 'DNSCFG'
port=53
bind-interfaces
listen-address=127.0.0.1
log-queries
log-facility=/var/log/dnsmasq.log
server=8.8.8.8
server=8.8.4.4
cache-size=1000
no-resolv
DNSCFG
systemctl enable dnsmasq 2>/dev/null || true
systemctl restart dnsmasq 2>/dev/null || true
echo "=== Создание агента ==="
mkdir -p /opt/hysteria-agent
curl -fsSL "{panel_url}/api/node/agent-script" -o /opt/hysteria-agent/node_agent.py 2>/dev/null || true
echo "=== Загрузка сертификата ==="
mkdir -p /etc/hysteria/certs
curl -fsSL "{panel_url}/api/node/cert" -o /tmp/certs.tar.gz 2>/dev/null && tar -xzf /tmp/certs.tar.gz -C /etc/hysteria/certs/ 2>/dev/null && rm -f /tmp/certs.tar.gz || echo "Cert download failed"
chmod 644 /etc/hysteria/certs/*.pem 2>/dev/null || true
if [ ! -f /etc/hysteria/certs/cert.pem ]; then
    openssl req -x509 -nodes -newkey ec:<(openssl ecparam -name prime256v1) -keyout /etc/hysteria/certs/key.pem -out /etc/hysteria/certs/cert.pem -subj "/CN=placeholder" -days 3650 2>/dev/null
    chmod 644 /etc/hysteria/certs/*.pem
fi
echo "=== Настройка Hysteria ==="
cat > /etc/hysteria/config.yaml << 'HYCFG'
listen: :443
tls:
  cert: /etc/hysteria/certs/cert.pem
  key: /etc/hysteria/certs/key.pem
auth:
  type: userpass
  userpass:
    placeholder: placeholder
dns:
  listen: 0.0.0.0:53
  upstream:
    - 127.0.0.1:53
obfs:
  type: salamander
  salamander:
    password: "{os.environ.get('HYSTERIA_OBFS_PASSWORD', '')}"
trafficStats:
  listen: 127.0.0.1:9999
quic:
  disablePathMTUDiscovery: true
HYCFG
echo "=== Настройка сети ==="
echo 1 > /proc/sys/net/ipv4/ip_forward
sysctl -w net.ipv4.ip_forward=1
grep -q "net.ipv4.ip_forward=1" /etc/sysctl.conf || echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
IFACE=$(ip route | grep default | awk '{{print $5}}' | head -1)
iptables -t nat -C POSTROUTING -s 10.0.0.0/8 -o $IFACE -j MASQUERADE 2>/dev/null || iptables -t nat -A POSTROUTING -s 10.0.0.0/8 -o $IFACE -j MASQUERADE
iptables -C FORWARD -s 10.0.0.0/8 -j ACCEPT 2>/dev/null || iptables -A FORWARD -s 10.0.0.0/8 -j ACCEPT
iptables -C FORWARD -d 10.0.0.0/8 -j ACCEPT 2>/dev/null || iptables -A FORWARD -d 10.0.0.0/8 -j ACCEPT
systemctl enable hysteria-server 2>/dev/null || true
systemctl restart hysteria-server 2>/dev/null || true
echo "=== DONE ==="
"""
        try:
            # Use stdin to avoid shell quoting issues
            transport = ssh.get_transport()
            channel = transport.open_session()
            channel.exec_command("bash")
            channel.sendall(deploy_script.encode())
            channel.shutdown_write()
            exit_code = channel.recv_exit_status()
            output = channel.recv(65536).decode()
            errors = channel.recv_stderr(65536).decode() if channel.recv_stderr_ready() else ""
            errors = stderr.read().decode()
            if exit_code != 0:
                ssh.close()
                return {"error": f"Exit {exit_code}", "output": output[-2000:], "stderr": errors[-2000:]}
            stdin, stdout, stderr = ssh.exec_command("curl -s --max-time 5 ifconfig.me", timeout=10)
            public_ip = stdout.read().decode().strip()
            if not public_ip:
                public_ip = host
            ssh.close()
            return {"success": True, "ip": public_ip, "output": output[-1000:]}
        except Exception as e:
            ssh.close()
            return {"error": str(e)}

    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        result = await loop.run_in_executor(pool, _do_deploy)

    if "error" in result:
        return JSONResponse(status_code=500, content=result)

    # Register node
    nodes = load_nodes()
    nid = gen_id()
    token = gen_node_token()
    nodes[nid] = {
        "name": node_name, "ip": result["ip"], "domain": result["ip"],
        "token": token, "status": "online",
        "created": datetime.now().isoformat(), "last_seen": datetime.now().isoformat(),
        "region": "", "country": "", "max_users": 100,
        "cpu_percent": 0, "ram_percent": 0, "disk_percent": 0,
        "online_users": 0, "total_users": 0,
        "traffic_sent": 0, "traffic_recv": 0,
        "hysteria_status": "unknown", "version": "1.0",
        "assigned_users": [], "deployed": True,
        "ssh_host": host, "ssh_port": port, "ssh_password": password,
        "online_usernames": [], "user_traffic": {}
    }
    save_nodes(nodes)
    audit_log("admin", "NODE_DEPLOYED", f"name={node_name} host={host}")
    return {"success": True, "node_id": nid, "ip": result["ip"], "output": result["output"]}

@app.get("/api/miniapp/services")
async def miniapp_services():
    services = ["hysteria-server", "freelink-api", "freelink-auth", "freelink-traffic", "freelink-bot", "freelink-online", "freelink-history", "freelink-monitor"]
    result = []
    for svc in services:
        try:
            r = subprocess.run(["/usr/bin/systemctl", "is-active", svc], capture_output=True, text=True, timeout=3)
            result.append({"name": svc, "active": r.stdout.strip() == "active"})
        except Exception:
            result.append({"name": svc, "active": False})
    return {"services": result}

@app.post("/api/miniapp/services/{name}/restart")
async def miniapp_restart_service(name: str):
    allowed = ["hysteria-server", "freelink-api", "freelink-auth", "freelink-traffic", "freelink-bot", "freelink-online", "freelink-history", "freelink-monitor"]
    if name not in allowed:
        return JSONResponse(status_code=400, content={"error": "Not allowed"})
    try:
        subprocess.run(["/usr/bin/systemctl", "restart", name], check=True, timeout=30)
        return {"success": True}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/miniapp/user/{uid}")
async def miniapp_user_info(uid: str):
    user = get_user(uid)
    if not user:
        raise HTTPException(status_code=404, detail="Not found")
    link = get_user_link(uid, user)
    ts = user.get("traffic_saved", {})
    online_status = get_online_status()
    username = user.get("name", uid)
    user_online = find_online_user(online_status, username)
    return {
        "id": uid, "name": username, "active": user.get("active", True),
        "expire_date": user.get("expire_date", ""), "created": user.get("created", ""),
        "online": user_online.get("online", False), "link": link,
        "traffic": {"tx_mb": round(ts.get("tx", 0)/1024/1024, 2), "rx_mb": round(ts.get("rx", 0)/1024/1024, 2), "total_mb": round((ts.get("tx", 0)+ts.get("rx", 0))/1024/1024, 2), "limit_mb": user.get("traffic_limit", 0)}
    }

@app.post("/api/miniapp/user/create")
async def miniapp_create_user(name: str, days: int = 30):
    uid = gen_id()
    expire_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
    password = secrets.token_urlsafe(16)
    user_data = {"name": name, "active": True, "created": datetime.now().strftime("%Y-%m-%d %H:%M"), "expire_date": expire_date, "port": 443, "server": "main", "password": password, "traffic_limit": 0, "traffic_used": 0, "devices": [], "total_sessions": 0}
    save_user(uid, user_data)
    link = get_user_link(uid, user_data)
    user_data["link"] = link
    save_user(uid, user_data)
    return {"id": uid, "name": name, "expire_date": expire_date, "link": link}

@app.post("/api/miniapp/user/toggle/{uid}")
async def miniapp_toggle_user(uid: str):
    user = get_user(uid)
    if not user:
        raise HTTPException(status_code=404, detail="Not found")
    user["active"] = not user.get("active", True)
    save_user(uid, user)
    return {"success": True}

@app.post("/api/miniapp/user/extend/{uid}")
async def miniapp_extend_user(uid: str, days: int = 30):
    user = get_user(uid)
    if not user:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        current = datetime.strptime(user["expire_date"], "%Y-%m-%d %H:%M")
    except Exception:
        current = datetime.now()
    user["expire_date"] = (current + timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
    save_user(uid, user)
    return {"success": True, "new_expire": user["expire_date"]}

@app.delete("/api/miniapp/user/{uid}")
async def miniapp_delete_user(uid: str):
    if delete_user(uid):
        return {"success": True}
    raise HTTPException(status_code=404, detail="Not found")

# ====== PAGES ======

@app.post("/api/login")
@limiter.limit("5/minute")
async def login(request: Request):
    data = await request.json()
    username = data.get("username", "")
    password = data.get("password", "")
    admins = load_admins()
    admin = admins.get(username)
    if not admin or not verify_pw(password, admin["password_hash"]):
        audit_log(username or "unknown", "LOGIN_FAILED")
        return JSONResponse(status_code=401, content={"error": "Неверный логин или пароль"})
    token = create_session(username)
    audit_log(username, "LOGIN")
    resp = JSONResponse(content={"success": True, "username": username, "token": token})
    resp.set_cookie("session", token, max_age=86400, httponly=True, secure=True, samesite="lax")
    return resp

@app.get("/api/session-token")
async def get_session_token(request: Request):
    """Return current session token for WebSocket authentication."""
    token = request.cookies.get("session")
    if not token:
        return JSONResponse(status_code=401, content={"error": "No session"})
    user = validate_session(token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Invalid session"})
    return {"token": token}

@app.post("/api/logout")
async def logout(request: Request):
    token = request.cookies.get("session")
    if token:
        sessions = load_sessions()
        user = sessions.get(token, {}).get("user", "?")
        db.delete_session(token)
        audit_log(user, "LOGOUT")
    resp = JSONResponse(content={"success": True})
    resp.delete_cookie("session")
    return resp

@app.get("/api/me")
async def get_me(request: Request):
    token = request.cookies.get("session")
    user = validate_session(token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    admins = load_admins()
    role = admins.get(user, {}).get("role", "admin")
    return {"username": user, "role": role}

@app.post("/api/change-password")
async def change_password(request: Request):
    token = request.cookies.get("session")
    user = validate_session(token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    data = await request.json()
    old_pw = data.get("old_password", "")
    new_pw = data.get("new_password", "")
    if len(new_pw) < 6:
        return JSONResponse(status_code=400, content={"error": "Минимум 6 символов"})
    admins = load_admins()
    admin = admins.get(user)
    if not admin or not verify_pw(old_pw, admin["password_hash"]):
        return JSONResponse(status_code=400, content={"error": "Неверный текущий пароль"})
    admins[user]["password_hash"] = hash_pw(new_pw)
    save_admins(admins)
    audit_log(user, "PASSWORD_CHANGED")
    return {"success": True}

@app.post("/api/admins/change-username")
async def change_username(request: Request):
    token = request.cookies.get("session")
    user = validate_session(token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    data = await request.json()
    new_name = data.get("new_username", "").strip()
    password = data.get("password", "")
    if not new_name or len(new_name) < 3:
        return JSONResponse(status_code=400, content={"error": "Минимум 3 символа"})
    if not re.match(r'^[a-zA-Z0-9_]+$', new_name):
        return JSONResponse(status_code=400, content={"error": "Только латиница, цифры и _"})
    admins = load_admins()
    if new_name in admins:
        return JSONResponse(status_code=400, content={"error": "Логин уже занят"})
    if not admins.get(user) or not verify_pw(password, admins[user]["password_hash"]):
        return JSONResponse(status_code=400, content={"error": "Неверный пароль"})
    admins[new_name] = admins.pop(user)
    save_admins(admins)
    # Update session
    sessions = load_sessions()
    for token_key, session in sessions.items():
        if session["user"] == user:
            session["user"] = new_name
    save_sessions(sessions)
    audit_log(user, f"RENAMED_TO {new_name}")
    return {"success": True, "new_username": new_name}

@app.get("/api/admins")
async def list_admins(request: Request):
    token = request.cookies.get("session")
    user = validate_session(token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    admins = load_admins()
    result = []
    for username, data in admins.items():
        result.append({
            "username": username,
            "role": data.get("role", "admin"),
            "created": data.get("created", "")
        })
    return {"admins": result}

@app.post("/api/admins")
async def create_admin(request: Request):
    token = request.cookies.get("session")
    user = validate_session(token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    admins = load_admins()
    if admins.get(user, {}).get("role") != "admin":
        return JSONResponse(status_code=403, content={"error": "Нет прав"})
    data = await request.json()
    new_user = data.get("username", "").strip()
    new_pass = data.get("password", "")
    new_role = data.get("role", "viewer")
    if not new_user or len(new_user) < 3:
        return JSONResponse(status_code=400, content={"error": "Минимум 3 символа"})
    if not re.match(r'^[a-zA-Z0-9_]+$', new_user):
        return JSONResponse(status_code=400, content={"error": "Только латиница, цифры и _"})
    if len(new_pass) < 6:
        return JSONResponse(status_code=400, content={"error": "Пароль минимум 6 символов"})
    if new_role not in ["admin", "editor", "viewer"]:
        return JSONResponse(status_code=400, content={"error": "Роль: admin, editor, viewer"})
    if new_user in admins:
        return JSONResponse(status_code=400, content={"error": "Логин уже существует"})
    admins[new_user] = {
        "password_hash": hash_pw(new_pass),
        "role": new_role,
        "created": datetime.now().isoformat()
    }
    save_admins(admins)
    audit_log(user, f"CREATED_USER {new_user} role={new_role}")
    return {"success": True}

@app.put("/api/admins/{target_user}")
async def update_admin(target_user: str, request: Request):
    token = request.cookies.get("session")
    user = validate_session(token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    admins = load_admins()
    current = admins.get(user, {})
    if current.get("role") != "admin":
        return JSONResponse(status_code=403, content={"error": "Нет прав"})
    if target_user not in admins:
        return JSONResponse(status_code=404, content={"error": "Пользователь не найден"})
    data = await request.json()
    if "password" in data and data["password"]:
        if len(data["password"]) < 6:
            return JSONResponse(status_code=400, content={"error": "Пароль минимум 6 символов"})
        admins[target_user]["password_hash"] = hash_pw(data["password"])
    if "role" in data:
        if data["role"] in ["admin", "editor", "viewer"]:
            admins[target_user]["role"] = data["role"]
    save_admins(admins)
    audit_log(user, f"UPDATED_USER {target_user}")
    return {"success": True}

@app.delete("/api/admins/{target_user}")
async def delete_admin(target_user: str, request: Request):
    token = request.cookies.get("session")
    user = validate_session(token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    admins = load_admins()
    if admins.get(user, {}).get("role") != "admin":
        return JSONResponse(status_code=403, content={"error": "Нет прав"})
    if target_user == user:
        return JSONResponse(status_code=400, content={"error": "Нельзя удалить себя"})
    if target_user not in admins:
        return JSONResponse(status_code=404, content={"error": "Не найден"})
    del admins[target_user]
    save_admins(admins)
    audit_log(user, f"DELETED_USER {target_user}")
    return {"success": True}

@app.get("/api/audit")
async def get_audit(request: Request):
    try:
        with open(AUDIT_FILE, 'r') as f:
            lines = f.readlines()[-200:]
        return {"logs": "".join(lines)}
    except Exception:
        return {"logs": ""}

@app.get("/")
async def root():
    with open("/opt/freelink/web/index.html", "r") as f:
        content = f.read()
    ts = str(int(time.time()))
    content = content.replace("</head>", f'<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate"><meta name="version" content="{ts}"></head>')
    content = content.replace(".js\"", f".js?v={ts}\"")
    content = content.replace(".css\"", f".css?v={ts}\"")
    content = content.replace("<script>", f'<script>/* v{ts} */')
    return HTMLResponse(content=content, headers={
        "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
        "Pragma": "no-cache", "Expires": "0"
    })

@app.get("/login")
async def login_page():
    with open("/opt/freelink/web/login.html", "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/api/language")
async def get_language():
    try:
        with open(CONFIG_FILE, 'r') as f:
            cfg = yaml.safe_load(f) or {}
        return {"language": cfg.get("language", "ru")}
    except Exception:
        return {"language": "ru"}

@app.get("/api/version")
async def get_version():
    return {"version": get_local_version()}

@app.get("/favicon.ico")
async def favicon():
    return HTMLResponse(content="", status_code=204)

@app.get("/deploy-test")
async def deploy_test_page():
    with open("/opt/freelink/web/deploy-test.html", "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/client")
@app.get("/c")
@app.get("/client/{token}")
async def client_portal(token: str = ""):
    with open("/opt/freelink/web/client.html", "r") as f:
        content = f.read()
    return HTMLResponse(content=content, headers={"Cache-Control": "no-cache"})

# ====== STATUS ======

@app.get("/api/status", summary="Dashboard summary", description="Returns server status, user counts, and online count.")
async def get_status():
    try:
        result = subprocess.run(["/usr/bin/systemctl", "is-active", "hysteria-server"], capture_output=True, text=True)
        status = "active" if result.stdout.strip() == "active" else "inactive"
        users = get_all_users()
        online = get_online_status()
        online_count = sum(1 for u in online.values() if u.get("online"))
        config = load_config()
        return {
            "server": config.get("server", {}).get("name", "Польша") if config else "Польша",
            "domain": os.environ.get("DOMAIN", "link.qmbox.ru"),
            "status": status,
            "total_users": len(users),
            "active_users": sum(1 for u in users.values() if u.get("active", True)),
            "online_users": online_count
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/server-info", summary="System metrics", description="Returns CPU, RAM, disk usage, network stats, and uptime.")
async def server_info():
    return get_server_info()

@app.get("/api/traffic-logs")
async def traffic_logs(request: Request, limit: int = 100):
    """Return recent connection logs with node names and DNS queries."""
    token = request.cookies.get("session")
    user = validate_session(token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    nodes = load_nodes()
    node_names = {nid: node.get("name", nid) for nid, node in nodes.items()}
    
    # Connection logs
    with db.get_conn() as conn:
        from psycopg2.extras import RealDictCursor
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM connection_log ORDER BY connected_at DESC LIMIT %s", (limit,))
        rows = cur.fetchall()
    
    result = []
    for r in rows:
        entry = {
            "username": r["username"],
            "client_ip": r["client_ip"],
            "node_id": r["node_id"],
            "node_name": node_names.get(r["node_id"], r["node_id"]),
            "connected_at": r["connected_at"].strftime("%Y-%m-%d %H:%M:%S") if r["connected_at"] else "",
            "disconnected_at": r["disconnected_at"].strftime("%Y-%m-%d %H:%M:%S") if r["disconnected_at"] else None,
            "duration_seconds": r["duration_seconds"] or 0,
            "type": "connection"
        }
        result.append(entry)
    
    # DNS logs (recent website visits)
    try:
        import dns_logger
        dns_logs = dns_logger.get_recent_dns(50)
        for d in dns_logs:
            result.append({
                "username": d.get("user", ""),
                "client_ip": d.get("ip", ""),
                "node_name": "DNS",
                "domain": d.get("domain", ""),
                "connected_at": d.get("time", ""),
                "type": "dns"
            })
    except Exception:
        pass
    
    # Sort by time descending
    result.sort(key=lambda x: x.get("connected_at", ""), reverse=True)
    return {"logs": result[:limit]}

@app.get("/api/logs/stream")
async def logs_stream(request: Request, log_type: str = None, search: str = None, limit: int = 200):
    """Get structured logs from all sources with filtering."""
    token = request.cookies.get("session")
    user = validate_session(token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    logs = db.get_structured_logs(log_type=log_type, search=search, limit=limit)
    return {"logs": logs, "total": len(logs)}

@app.get("/api/logs/export")
async def logs_export(request: Request, format: str = "csv"):
    """Export logs as CSV."""
    token = request.cookies.get("session")
    user = validate_session(token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    logs = db.get_structured_logs(limit=1000)
    if format == "csv":
        lines = ["time,user,type,action,details,ip,node"]
        for l in logs:
            line = f'"{l["time"]}","{l["user"]}","{l["type"]}","{l["action"]}","{l["details"]}","{l["ip"]}","{l["node"]}"'
            lines.append(line)
        content = "\n".join(lines)
        return Response(content=content, media_type="text/csv",
                       headers={"Content-Disposition": "attachment; filename=logs.csv"})
    return {"logs": logs}

# ====== USERS ======

@app.get("/api/users", summary="List all users", description="Returns all VPN users with online status, traffic stats, and subscription info.")
async def get_users():
    users = get_all_users()
    online_status = get_online_status()

    # Aggregate traffic from traffic_snapshots table (no double-counting)
    aggregated_traffic = db.get_all_user_traffic()

    result = []
    for uid, user in users.items():
        link = get_user_link(uid, user)
        username = user.get("name", uid)
        user_ip = user.get("ip", "")

        user_online = find_online_user(online_status, username)
        is_online = user_online.get("online", False)

        # Traffic from snapshots: latest per node, summed across nodes
        agg = aggregated_traffic.get(username.lower(), {})
        tx_bytes = agg.get("tx", 0)
        rx_bytes = agg.get("rx", 0)
        total_mb = round((tx_bytes + rx_bytes) / 1024 / 1024, 2)

        result.append({
            "id": uid,
            "name": username,
            "active": user.get("active", True),
            "expire_date": user.get("expire_date", "Не указан"),
            "created": user.get("created", "Не указан"),
            "port": user.get("port", 443),
            "server": user.get("server", "Не указан"),
            "link": link,
            "ip": user_ip,
            "online": is_online,
            "last_seen": user_online.get("last_active", ""),
            "tx_speed": user_online.get("tx_speed", 0),
            "rx_speed": user_online.get("rx_speed", 0),
            "inactive_since": user_online.get("inactive_since"),
            "traffic": {
                "total_mb": total_mb,
                "tx_mb": round(tx_bytes / 1024 / 1024, 2),
                "rx_mb": round(rx_bytes / 1024 / 1024, 2),
                "limit_mb": user.get("traffic_limit", 0)
            }
        })
    return {"users": result}

@app.get("/api/user/{uid}", summary="Get user details", description="Returns full details for a single VPN user including traffic and online status.")
async def get_user_endpoint(uid: str):
    user = get_user(uid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    link = get_user_link(uid, user)

    ts = user.get("traffic_saved", {})
    tx_bytes = ts.get("tx", 0)
    rx_bytes = ts.get("rx", 0)

    # Aggregate traffic from remote nodes (case-insensitive, SUM)
    nodes = load_nodes()
    username = user.get("name", uid)
    username_lower = username.lower()
    for nid, node in nodes.items():
        if node.get("is_main"):
            continue
        for node_user, ut in node.get("user_traffic", {}).items():
            if node_user.lower() == username_lower:
                tx_bytes += ut.get("tx", 0)
                rx_bytes += ut.get("rx", 0)

    total_mb = round((tx_bytes + rx_bytes) / 1024 / 1024, 2)
    traffic_limit = user.get("traffic_limit", 0)

    online_status = get_online_status()
    user_online = find_online_user(online_status, username)

    traffic = {
        "tx_mb": round(tx_bytes / 1024 / 1024, 2),
        "rx_mb": round(rx_bytes / 1024 / 1024, 2),
        "total_mb": total_mb,
        "limit_mb": traffic_limit
    }

    return {
        "id": uid,
        "name": username,
        "active": user.get("active", True),
        "expire_date": user.get("expire_date", "Не указан"),
        "created": user.get("created", "Не указан"),
        "port": user.get("port", 443),
        "server": user.get("server", "Не указан"),
        "link": link,
        "online": user_online.get("online", False),
        "last_seen": user_online.get("last_active", ""),
        "ip": user.get("ip", ""),
        "active_devices": db.get_user_device_count(username),
        "max_devices": user.get("max_devices", 0),
        "unique_ips_30d": db.get_user_unique_ips(username, 30),
        "traffic": traffic,
        "traffic_limit": traffic_limit,
        "traffic_used": total_mb,
        "devices": user.get("devices", []),
        "total_sessions": user.get("total_sessions", 0)
    }

@app.get("/api/user/{uid}/connections", summary="User connection history")
async def user_connections(uid: str, request: Request, limit: int = 50):
    token = request.cookies.get("session")
    user = validate_session(token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    target = get_user(uid)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    connections = db.get_user_connections(target.get("name", uid), limit)
    # Resolve node_id to node names
    nodes = load_nodes()
    for conn in connections:
        nid = conn.get("node_id", "")
        if nid == "__main__":
            conn["node_name"] = "Основная"
        elif nid in nodes:
            conn["node_name"] = nodes[nid].get("name", nid)
        else:
            conn["node_name"] = nid
    return {"connections": connections}

@app.post("/api/user/{uid}/max-devices")
async def set_max_devices(uid: str, request: Request):
    token = request.cookies.get("session")
    user = validate_session(token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    target = get_user(uid)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    data = await request.json()
    max_devices = data.get("max_devices", 0)
    if max_devices < 0:
        max_devices = 0
    target["max_devices"] = max_devices
    save_user(uid, target)
    audit_log(user, "MAX_DEVICES_CHANGED", f"uid={uid} max={max_devices}")
    return {"success": True, "max_devices": max_devices}

@app.post("/api/user/create", summary="Create VPN user", description="Create a new VPN user with subscription. Returns user ID, expiry date, and Hysteria2 connection link.")
async def create_user(name: str, days: int = 30):
    uid = gen_id()
    expire_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
    password = secrets.token_urlsafe(16)
    service_token = secrets.token_urlsafe(24)

    user_data = {
        "name": name,
        "active": True,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "expire_date": expire_date,
        "port": 443,
        "server": "main",
        "password": password,
        "traffic_limit": 0,
        "traffic_used": 0,
        "devices": [],
        "total_sessions": 0,
        "service_token": service_token
    }
    save_user(uid, user_data)
    link = get_user_link(uid, user_data)
    user_data["link"] = link
    save_user(uid, user_data)
    return {"id": uid, "name": name, "expire_date": expire_date, "port": 443, "link": link}

@app.post("/api/user/toggle/{uid}")
async def toggle_user(uid: str):
    user = get_user(uid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user["active"] = not user.get("active", True)
    save_user(uid, user)
    return {"success": True, "active": user["active"]}

@app.post("/api/user/extend/{uid}")
async def extend_user(uid: str, days: int = 30):
    user = get_user(uid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        current = datetime.strptime(user["expire_date"], "%Y-%m-%d %H:%M")
    except Exception:
        current = datetime.now()
    new_expire = current + timedelta(days=days)
    user["expire_date"] = new_expire.strftime("%Y-%m-%d %H:%M")
    save_user(uid, user)
    return {"success": True, "new_expire": user["expire_date"]}

@app.delete("/api/user/{uid}")
async def delete_user_endpoint(uid: str):
    if delete_user(uid):
        return {"success": True}
    raise HTTPException(status_code=404, detail="User not found")

@app.post("/api/user/set-limit/{uid}")
async def set_user_limit(uid: str, limit_mb: int = 0):
    user = get_user(uid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user["traffic_limit"] = limit_mb
    save_user(uid, user)
    return {"success": True, "limit_mb": limit_mb}

@app.post("/api/user/reset-traffic/{uid}")
async def reset_user_traffic(uid: str):
    user = get_user(uid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user["traffic_saved"] = {"tx": 0, "rx": 0, "total_mb": 0, "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
    user["traffic_used"] = 0
    save_user(uid, user)
    return {"success": True, "traffic_used": 0}

# ====== BULK OPERATIONS ======

@app.post("/api/users/bulk-delete")
async def bulk_delete(request: Request):
    data = await request.json()
    ids = data.get("ids", [])
    deleted = 0
    for uid in ids:
        if delete_user(uid):
            deleted += 1
    return {"deleted": deleted}

@app.post("/api/users/bulk-toggle")
async def bulk_toggle(request: Request):
    data = await request.json()
    ids = data.get("ids", [])
    toggled = 0
    for uid in ids:
        user = get_user(uid)
        if user:
            user["active"] = not user.get("active", True)
            save_user(uid, user)
            toggled += 1
    return {"toggled": toggled}

@app.post("/api/users/bulk-extend")
async def bulk_extend(request: Request):
    data = await request.json()
    ids = data.get("ids", [])
    days = data.get("days", 30)
    extended = 0
    for uid in ids:
        user = get_user(uid)
        if user:
            try:
                current = datetime.strptime(user["expire_date"], "%Y-%m-%d %H:%M")
            except Exception:
                current = datetime.now()
            user["expire_date"] = (current + timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
            save_user(uid, user)
            extended += 1
    return {"extended": extended}

@app.post("/api/users/bulk-speed-limit")
async def bulk_speed_limit(request: Request):
    """Set speed limit for multiple users at once."""
    data = await request.json()
    ids = data.get("ids", [])
    speed_mbps = data.get("speed_mbps", 0)
    updated = 0
    for uid in ids:
        user = get_user(uid)
        if user:
            user["speed_limit_mbps"] = speed_mbps
            save_user(uid, user)
            updated += 1
    # Apply all speed limits to Hysteria
    if updated > 0:
        try:
            subprocess.Popen(
                ["/opt/freelink/venv/bin/python3", "/opt/freelink/speed_limiter.py"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception:
            pass
    audit_log("admin", "BULK_SPEED_LIMIT", f"users={updated} speed={speed_mbps}Mbps")
    return {"updated": updated}

# ====== PLANS ======

PLANS_FILE = "/opt/freelink/plans.json"

def load_plans():
    plans = db.load_plans()
    if not plans:
        plans = [
            {"id": "basic", "name": "Базовый", "days": 30, "traffic_limit_mb": 10240, "price": ""},
            {"id": "pro", "name": "Про", "days": 30, "traffic_limit_mb": 51200, "price": ""},
            {"id": "unlimited", "name": "Безлимит", "days": 30, "traffic_limit_mb": 0, "price": ""}
        ]
        db.save_plans(plans)
    return plans

def save_plans(plans):
    db.save_plans(plans)

@app.get("/api/plans", summary="List subscription plans", description="Returns all available subscription plans with traffic limits and durations.")
async def get_plans():
    return {"plans": load_plans()}

@app.post("/api/plans")
async def create_plan(request: Request):
    data = await request.json()
    plans = load_plans()
    plan_id = secrets.token_hex(3)
    plan = {
        "id": plan_id,
        "name": data.get("name", "Новый план"),
        "days": data.get("days", 30),
        "traffic_limit_mb": data.get("traffic_limit_mb", 0),
        "price": data.get("price", "")
    }
    plans.append(plan)
    save_plans(plans)
    return plan

@app.put("/api/plans/{plan_id}")
async def update_plan(plan_id: str, request: Request):
    data = await request.json()
    plans = load_plans()
    for p in plans:
        if p["id"] == plan_id:
            p.update({k: v for k, v in data.items() if k != "id"})
            save_plans(plans)
            return p
    raise HTTPException(status_code=404, detail="Plan not found")

@app.delete("/api/plans/{plan_id}")
async def delete_plan(plan_id: str):
    plans = load_plans()
    plans = [p for p in plans if p["id"] != plan_id]
    save_plans(plans)
    return {"success": True}

@app.post("/api/user/create-with-plan")
async def create_user_with_plan(request: Request):
    data = await request.json()
    name = data.get("name", "")
    plan_id = data.get("plan_id", "")
    if not name:
        raise HTTPException(status_code=400, detail="Name required")

    plans = load_plans()
    plan = next((p for p in plans if p["id"] == plan_id), None)
    days = plan["days"] if plan else 30
    traffic_limit = plan["traffic_limit_mb"] if plan else 0

    uid = gen_id()
    expire_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
    password = secrets.token_urlsafe(16)
    service_token = secrets.token_urlsafe(24)

    user_data = {
        "name": name,
        "active": True,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "expire_date": expire_date,
        "port": 443,
        "server": "main",
        "password": password,
        "traffic_limit": traffic_limit,
        "traffic_used": 0,
        "plan": plan_id,
        "devices": [],
        "total_sessions": 0,
        "service_token": service_token
    }
    save_user(uid, user_data)
    link = get_user_link(uid, user_data)
    user_data["link"] = link
    save_user(uid, user_data)
    return {"id": uid, "name": name, "expire_date": expire_date, "plan": plan_id, "link": link}

# ====== EXPORT ======

@app.get("/api/export")
async def export_users(fmt: str = "json"):
    users = get_all_users()
    result = []
    for uid, user in users.items():
        result.append({
            "id": uid,
            "name": user.get("name", ""),
            "active": user.get("active", True),
            "created": user.get("created", ""),
            "expire_date": user.get("expire_date", ""),
            "traffic_limit": user.get("traffic_limit", 0),
            "link": user.get("link", "")
        })
    if fmt == "csv":
        if not result:
            return Response(content="id,name,active,created,expire_date,traffic_limit,link\n", media_type="text/csv")
        headers = result[0].keys()
        lines = [",".join(str(h) for h in headers)]
        for row in result:
            lines.append(",".join(f'"{str(row[h]).replace(chr(34), chr(34)*2)}"' for h in headers))
        csv_content = "\n".join(lines)
        return Response(content=csv_content, media_type="text/csv",
                       headers={"Content-Disposition": "attachment; filename=users.csv"})
    return {"users": result}

# ====== SERVICES STATUS ======

@app.get("/api/services", summary="Service status", description="Returns active/inactive status for all system services.")
async def get_services():
    services = ["hysteria-server", "freelink-api", "freelink-auth", "freelink-traffic", "freelink-bot", "freelink-online", "freelink-history", "freelink-monitor"]
    result = []
    for svc in services:
        try:
            r = subprocess.run(["/usr/bin/systemctl", "is-active", svc], capture_output=True, text=True, timeout=3)
            active = r.stdout.strip() == "active"
        except Exception:
            active = False
        result.append({"name": svc, "active": active})
    return {"services": result}

@app.post("/api/services/{name}/restart")
async def restart_service(name: str):
    allowed = ["hysteria-server", "freelink-api", "freelink-auth", "freelink-traffic", "freelink-bot", "freelink-online", "freelink-history", "freelink-monitor"]
    if name not in allowed:
        raise HTTPException(status_code=400, detail="Service not allowed")
    try:
        subprocess.run(["/usr/bin/systemctl", "restart", name], check=True, timeout=30)
        return {"success": True}
    except Exception as e:
        return {"error": str(e)}

# ====== TRAFFIC HISTORY ======

TRAFFIC_HISTORY_FILE = "/opt/freelink/traffic_history.json"

def record_traffic_snapshot():
    stats = get_hysteria_stats()
    if not stats:
        return
    history = []
    if os.path.exists(TRAFFIC_HISTORY_FILE):
        try:
            with open(TRAFFIC_HISTORY_FILE, 'r') as f:
                history = json.load(f)
        except Exception:
            pass

    entry = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "users": {}
    }
    for username, traffic in stats.items():
        entry["users"][username] = {
            "tx": traffic.get("tx", 0),
            "rx": traffic.get("rx", 0)
        }

    history.append(entry)
    if len(history) > 2880:
        history = history[-2880:]

    with open(TRAFFIC_HISTORY_FILE, 'w') as f:
        json.dump(history, f)

@app.get("/api/traffic-history")
async def traffic_history(hours: int = 24):
    if not os.path.exists(TRAFFIC_HISTORY_FILE):
        return {"history": []}
    try:
        with open(TRAFFIC_HISTORY_FILE, 'r') as f:
            history = json.load(f)
        cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")
        filtered = [h for h in history if h["time"] >= cutoff]
        return {"history": filtered}
    except Exception:
        return {"history": []}

# ====== CLEANUP ======

@app.post("/api/clean")
async def clean_expired(request: Request):
    token = request.cookies.get("session")
    user = validate_session(token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    admins = load_admins()
    if admins.get(user, {}).get("role") not in ("admin", "editor"):
        return JSONResponse(status_code=403, content={"error": "Insufficient permissions"})
    users = get_all_users()
    deleted = 0
    for uid, user_data in list(users.items()):
        expire = user_data.get("expire_date", "")
        if expire and expire != "2099-12-31 23:59":
            try:
                if datetime.strptime(expire, "%Y-%m-%d %H:%M") < datetime.now():
                    delete_user(uid)
                    deleted += 1
            except Exception:
                pass
    audit_log(user, "CLEAN_EXPIRED", f"deleted={deleted}")
    return {"deleted": deleted}

# ====== SERVER ======

@app.get("/api/restart")
async def restart_server(request: Request):
    token = request.cookies.get("session")
    user = validate_session(token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    admins = load_admins()
    if admins.get(user, {}).get("role") != "admin":
        return JSONResponse(status_code=403, content={"error": "Admin only"})
    try:
        subprocess.run(["/usr/bin/systemctl", "restart", "hysteria-server"], check=True)
        audit_log(user, "RESTART_SERVER")
        return {"success": True}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "Restart failed"})

@app.get("/api/logs")
async def get_logs(request: Request):
    token = request.cookies.get("session")
    user = validate_session(token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    admins = load_admins()
    if admins.get(user, {}).get("role") not in ("admin", "editor"):
        return JSONResponse(status_code=403, content={"error": "Insufficient permissions"})
    try:
        result = subprocess.run(["/usr/bin/journalctl", "-u", "hysteria-server", "-n", "100", "--no-pager"], capture_output=True, text=True)
        return {"logs": result.stdout}
    except Exception:
        return JSONResponse(status_code=500, content={"error": "Failed to read logs"})

@app.get("/api/logs/all")
async def get_all_logs(request: Request):
    token = request.cookies.get("session")
    user = validate_session(token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    admins = load_admins()
    if admins.get(user, {}).get("role") != "admin":
        return JSONResponse(status_code=403, content={"error": "Admin only"})
    try:
        lines = int(500)
        result = subprocess.run(["/usr/bin/journalctl", "-u", "hysteria-server", "-n", str(lines), "--no-pager"], capture_output=True, text=True)
        return {"logs": result.stdout}
    except Exception:
        return JSONResponse(status_code=500, content={"error": "Failed to read logs"})

# ====== ONLINE ======

@app.get("/api/online", summary="Online status", description="Returns online status for all users with speed and last active time.")
async def online():
    online_status = get_online_status()
    users = get_all_users()

    users_online = []
    online_count = 0

    for uid, user in users.items():
        username = user.get("name", uid)
        user_status = find_online_user(online_status, username)
        is_online = user_status.get("online", False)
        users_online.append({
            "id": uid,
            "name": username,
            "online": is_online,
            "last_seen": user_status.get("last_active", ""),
            "tx_speed": user_status.get("tx_speed", 0),
            "rx_speed": user_status.get("rx_speed", 0),
            "inactive_since": user_status.get("inactive_since"),
        })
        if is_online:
            online_count += 1

    return {"online": online_count, "users": users_online}

# ====== TRAFFIC ======

@app.get("/api/traffic-v2")
async def traffic_v2():
    stats = get_hysteria_stats()
    if stats:
        return stats
    return {"tx": 0, "rx": 0}

@app.get("/api/hysteria/stats")
async def hysteria_stats():
    stats = get_hysteria_stats()
    if stats:
        return stats
    return {"error": "Traffic Stats API не доступен"}

@app.get("/api/live-traffic", summary="Live traffic", description="Returns currently active users with real-time speed data (bytes/sec).")
async def live_traffic():
    online_status = get_online_status()
    users = get_all_users()

    traffic_data = []
    for uid, user in users.items():
        username = user.get("name", uid)
        user_status = find_online_user(online_status, username)
        if user_status.get("online"):
            tx_speed = user_status.get("tx_speed", 0)
            rx_speed = user_status.get("rx_speed", 0)
            traffic_data.append({
                "user": username,
                "tx_speed_mb": round(tx_speed / 1024 / 1024, 2),
                "rx_speed_mb": round(rx_speed / 1024 / 1024, 2),
                "total_speed_mb": round((tx_speed + rx_speed) / 1024 / 1024, 2),
                "last_active": user_status.get("last_active", "")
            })

    return {"traffic": traffic_data, "count": len(traffic_data)}

# ====== QR CODE ======

@app.get("/api/qr/{uid}")
async def get_qr(uid: str):
    user = get_user(uid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    # QR links to client portal with subscription
    service_token = user.get("service_token", "")
    if not service_token:
        service_token = secrets.token_urlsafe(24)
        db.save_user(uid, {**user, "service_token": service_token})
    domain = os.environ.get("DOMAIN", "link.qmbox.ru")
    portal_url = f"https://{domain}/sub/{service_token}"
    link = get_user_link(uid, user)
    if not HAS_QR:
        return JSONResponse(status_code=500, content={"error": "qrcode not installed"})
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=6, border=2)
    qr.add_data(portal_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#000", back_color="#fff")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return {"qr": f"data:image/png;base64,{b64}", "link": link, "portal_url": portal_url}

@app.get("/api/miniapp/qr/{uid}")
async def miniapp_get_qr(uid: str):
    return await get_qr(uid)

# ====== GEO IP ======

GEOIP_CACHE = {}

def geo_lookup(ip: str) -> dict:
    if not ip or ip in ("127.0.0.1", "::1", ""):
        return {"country": "", "city": "", "org": ""}
    # Validate IP address to prevent SSRF
    import ipaddress
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return {"country": "", "city": "", "org": ""}
    if ip in GEOIP_CACHE:
        return GEOIP_CACHE[ip]
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}?fields=status,country,city,org,isp", timeout=3)
        if r.status_code == 200:
            data = r.json()
            result = {
                "country": data.get("country", ""),
                "city": data.get("city", ""),
                "org": data.get("org", ""),
                "isp": data.get("isp", "")
            }
            GEOIP_CACHE[ip] = result
            return result
    except Exception:
        pass
    return {"country": "", "city": "", "org": ""}

@app.get("/api/geo/{ip}")
async def geoip_lookup(ip: str):
    return geo_lookup(ip)

@app.get("/api/miniapp/geo/{ip}")
async def miniapp_geoip(ip: str):
    return geo_lookup(ip)

# ====== SPEED LIMITS ======

@app.post("/api/user/speed-limit/{uid}")
async def set_speed_limit(uid: str, request: Request):
    user = get_user(uid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    data = await request.json()
    speed_mbps = data.get("speed_mbps", 0)
    user["speed_limit_mbps"] = speed_mbps
    save_user(uid, user)
    # Apply speed limit to Hysteria config
    try:
        subprocess.Popen(
            ["/opt/freelink/venv/bin/python3", "/opt/freelink/speed_limiter.py"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except Exception:
        pass
    audit_log("admin", "SPEED_LIMIT_CHANGED", f"uid={uid} speed={speed_mbps}Mbps")
    return {"success": True, "speed_mbps": speed_mbps}

@app.post("/api/miniapp/user/speed-limit/{uid}")
async def miniapp_set_speed_limit(uid: str, request: Request):
    return await set_speed_limit(uid, request)

# ====== SELF-SERVICE PORTAL ======

@app.get("/s/{token}")
async def self_service(token: str):
    users = get_all_users()
    for uid, user in users.items():
        if user.get("service_token") == token:
            # Check if user is active
            if not user.get("active", True):
                return JSONResponse(status_code=403, content={"error": "Account disabled"})
            # Check if subscription expired
            expire = user.get("expire_date", "")
            if expire:
                try:
                    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                        try:
                            expire_dt = datetime.strptime(expire, fmt)
                            break
                        except ValueError:
                            continue
                    else:
                        expire_dt = None
                    if expire_dt and expire_dt < datetime.now():
                        return JSONResponse(status_code=403, content={"error": "Subscription expired"})
                except Exception:
                    pass
            link = get_user_link(uid, user)
            online_status = get_online_status()
            username = user.get("name", uid)
            user_online = find_online_user(online_status, username)
            ts = user.get("traffic_saved", {})
            return JSONResponse(content={
                "name": username, "active": user.get("active", True),
                "expire_date": user.get("expire_date", ""),
                "online": user_online.get("online", False),
                "link": link,
                "traffic": {
                    "tx_mb": round(ts.get("tx", 0)/1024/1024, 2),
                    "rx_mb": round(ts.get("rx", 0)/1024/1024, 2),
                    "total_mb": round((ts.get("tx",0)+ts.get("rx",0))/1024/1024, 2),
                    "limit_mb": user.get("traffic_limit", 0)
                }
            })
    raise HTTPException(status_code=404, detail="Invalid token")

@app.post("/api/user/gen-service-token/{uid}")
async def gen_service_token(uid: str):
    user = get_user(uid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    token = user.get("service_token", "")
    if not token:
        token = secrets.token_urlsafe(24)
        user["service_token"] = token
        save_user(uid, user)
    return {"success": True, "token": token, "url": f"/s/{token}"}

@app.post("/api/miniapp/user/gen-service-token/{uid}")
async def miniapp_gen_service_token(uid: str):
    return await gen_service_token(uid)

# ====== CONFIG EDITOR ======

@app.get("/api/config")
async def get_config():
    try:
        with open("/etc/hysteria/config.yaml", "r") as f:
            content = f.read()
        return {"config": content, "path": "/etc/hysteria/config.yaml"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/config")
async def save_config(request: Request):
    data = await request.json()
    content = data.get("config", "")
    try:
        test = yaml.safe_load(content)
        if not isinstance(test, dict):
            return JSONResponse(status_code=400, content={"error": "Invalid YAML"})
        backup_path = f"/etc/hysteria/config.yaml.bak.{int(time.time())}"
        subprocess.run(["/usr/bin/cp", "/etc/hysteria/config.yaml", backup_path], timeout=5)
        with open("/etc/hysteria/config.yaml", "w") as f:
            f.write(content)
        audit_log("admin", "CONFIG_SAVE")
        return {"success": True, "backup": backup_path}
    except yaml.YAMLError as e:
        return JSONResponse(status_code=400, content={"error": f"YAML error: {e}"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/config/restart")
async def restart_after_config():
    try:
        subprocess.run(["/usr/bin/systemctl", "restart", "hysteria-server"], check=True, timeout=30)
        return {"success": True}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# ====== TELEGRAM BOT CONFIG ======

@app.get("/api/telegram/config")
async def get_telegram_config():
    config = load_config()
    tg = config.get("telegram", {})
    token = tg.get("token", "")
    admins = tg.get("admins", [])
    return {"token": token, "admins": admins}

@app.post("/api/telegram/token")
async def save_telegram_token(request: Request):
    token = request.cookies.get("session")
    user = validate_session(token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    data = await request.json()
    new_token = data.get("token", "").strip()
    if not new_token:
        return JSONResponse(status_code=400, content={"error": "Токен не может быть пустым"})
    config = load_config()
    if "telegram" not in config:
        config["telegram"] = {}
    config["telegram"]["token"] = new_token
    with open(CONFIG_FILE, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
    audit_log(user, "BOT_TOKEN_CHANGED")
    return {"success": True}

@app.post("/api/telegram/admins/add")
async def add_telegram_admin(request: Request):
    token = request.cookies.get("session")
    user = validate_session(token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    data = await request.json()
    admin_id = data.get("admin_id")
    if admin_id is None:
        return JSONResponse(status_code=400, content={"error": "admin_id required"})
    admin_id = int(admin_id)
    config = load_config()
    if "telegram" not in config:
        config["telegram"] = {}
    admins = config["telegram"].get("admins", [])
    if admin_id in admins:
        return JSONResponse(status_code=400, content={"error": "Уже добавлен"})
    admins.append(admin_id)
    config["telegram"]["admins"] = admins
    with open(CONFIG_FILE, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
    audit_log(user, f"BOT_ADMIN_ADDED id={admin_id}")
    return {"success": True, "admins": admins}

@app.post("/api/telegram/admins/remove")
async def remove_telegram_admin(request: Request):
    token = request.cookies.get("session")
    user = validate_session(token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    data = await request.json()
    admin_id = data.get("admin_id")
    if admin_id is None:
        return JSONResponse(status_code=400, content={"error": "admin_id required"})
    admin_id = int(admin_id)
    config = load_config()
    admins = config.get("telegram", {}).get("admins", [])
    if admin_id not in admins:
        return JSONResponse(status_code=400, content={"error": "Не найден"})
    admins.remove(admin_id)
    config["telegram"]["admins"] = admins
    with open(CONFIG_FILE, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
    audit_log(user, f"BOT_ADMIN_REMOVED id={admin_id}")
    return {"success": True, "admins": admins}

# ====== HYSTERIA VERSION ======

import re as _re

def get_hysteria_local_version():
    try:
        r = subprocess.run(["/usr/local/bin/hysteria", "version"],
                          capture_output=True, text=True, timeout=5)
        m = _re.search(r"Version:\s*v?([\d.]+)", r.stdout)
        if m:
            return "v" + m.group(1)
    except Exception:
        pass
    return None

def get_hysteria_remote_version():
    try:
        r = requests.get("https://api.github.com/repos/apernet/hysteria/releases/latest",
                         timeout=10)
        if r.status_code == 200:
            tag = r.json().get("tag_name", "")
            # tag format: "app/v2.9.3" — extract version part
            if "/" in tag:
                tag = tag.rsplit("/", 1)[-1]
            return tag if tag.startswith("v") else "v" + tag
    except Exception:
        pass
    return None

@app.get("/api/hysteria/version")
async def get_hysteria_version(request: Request):
    token = request.cookies.get("session")
    user = validate_session(token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    local = get_hysteria_local_version()
    remote = get_hysteria_remote_version()
    return {
        "local": local or "unknown",
        "remote": remote or "unknown",
        "update_available": local and remote and local != remote
    }

hysteria_update_status = {"running": False, "log": "", "done": False, "success": False}

def do_hysteria_update():
    global hysteria_update_status
    hysteria_update_status = {"running": True, "log": "", "done": False, "success": False}
    try:
        hysteria_update_status["log"] += "▶ Проверка последней версии...\n"
        remote = get_hysteria_remote_version()
        if not remote:
            hysteria_update_status["log"] += "  ❌ Не удалось получить версию с GitHub\n"
            hysteria_update_status["success"] = False
            return
        hysteria_update_status["log"] += f"  ✓ Найдена: {remote}\n"

        hysteria_update_status["log"] += "▶ Скачивание бинарника...\n"
        url = "https://github.com/apernet/hysteria/releases/latest/download/hysteria-linux-amd64"
        r = requests.get(url, timeout=60, stream=True)
        if r.status_code != 200:
            hysteria_update_status["log"] += f"  ❌ Ошибка скачивания: HTTP {r.status_code}\n"
            hysteria_update_status["success"] = False
            return

        tmp_path = "/tmp/hysteria-new"
        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        with open(tmp_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
                downloaded += len(chunk)
        hysteria_update_status["log"] += f"  ✓ Скачано: {downloaded // 1024 // 1024} MB\n"

        hysteria_update_status["log"] += "▶ Установка...\n"
        subprocess.run(["/usr/bin/chmod", "+x", tmp_path], check=True, timeout=5)

        hysteria_update_status["log"] += "  ▶ Остановка hysteria-server...\n"
        subprocess.run(["/usr/bin/systemctl", "stop", "hysteria-server"], timeout=15)

        subprocess.run(["/usr/bin/cp", "-f", tmp_path, "/usr/local/bin/hysteria"], check=True, timeout=10)
        subprocess.run(["/usr/bin/rm", "-f", tmp_path], timeout=5)
        hysteria_update_status["log"] += "  ✓ Бинарник заменён\n"

        hysteria_update_status["log"] += "▶ Перезапуск hysteria-server...\n"
        r = subprocess.run(["/usr/bin/systemctl", "restart", "hysteria-server"],
                          capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            hysteria_update_status["log"] += f"  ⚠ {r.stderr.strip()[:200]}\n"
        else:
            hysteria_update_status["log"] += "  ✓ Сервис перезапущен\n"

        new_ver = get_hysteria_local_version()
        hysteria_update_status["log"] += f"\n✅ Hysteria обновлена до {new_ver or remote}\n"
        hysteria_update_status["success"] = True
    except Exception as e:
        hysteria_update_status["log"] += f"\n❌ Ошибка: {str(e)}\n"
        hysteria_update_status["success"] = False
    finally:
        hysteria_update_status["done"] = True
        hysteria_update_status["running"] = False

@app.post("/api/hysteria/update")
async def run_hysteria_update(request: Request):
    token = request.cookies.get("session")
    user = validate_session(token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    admins = load_admins()
    if admins.get(user, {}).get("role") != "admin":
        return JSONResponse(status_code=403, content={"error": "Only admin"})
    if hysteria_update_status["running"]:
        return JSONResponse(status_code=409, content={"error": "Already in progress"})
    thread = threading.Thread(target=do_hysteria_update, daemon=True)
    thread.start()
    return {"success": True}

@app.get("/api/hysteria/update/status")
async def hysteria_update_status_ep(request: Request):
    token = request.cookies.get("session")
    user = validate_session(token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    return hysteria_update_status

# ====== BACKUP & RESTORE ======

BACKUP_DIR = "/opt/freelink/backups"

def _validate_backup_name(name: str) -> bool:
    """Validate backup name to prevent path traversal."""
    import re
    return bool(re.match(r'^[a-zA-Z0-9_\-]+\.tar\.gz$', name))
BACKUP_FILES = ["data.yaml", "admins.json", "config.yaml", "nodes.json",
                "plans.json", "subscriptions.json"]

def ensure_backup_dir():
    os.makedirs(BACKUP_DIR, exist_ok=True)

@app.get("/api/backups")
async def list_backups(request: Request):
    token = request.cookies.get("session")
    user = validate_session(token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    ensure_backup_dir()
    backups = []
    for f in sorted(os.listdir(BACKUP_DIR), reverse=True):
        if f.endswith(".tar.gz"):
            path = os.path.join(BACKUP_DIR, f)
            stat = os.stat(path)
            backups.append({
                "name": f,
                "size_mb": round(stat.st_size / 1024 / 1024, 2),
                "created": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            })
    return {"backups": backups}

@app.post("/api/backups/create")
async def create_backup(request: Request):
    token = request.cookies.get("session")
    user = validate_session(token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    ensure_backup_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"backup_{ts}.tar.gz"
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    try:
        with tarfile.open(backup_path, "w:gz") as tar:
            # PostgreSQL dump
            pg_dump_path = f"/tmp/freelink_pg_{ts}.sql"
            pg_user = os.environ.get("PG_USER", "freelink")
            pg_pass = os.environ.get("PG_PASS", "")
            pg_host = os.environ.get("PG_HOST", "127.0.0.1")
            pg_db = os.environ.get("PG_DB", "freelink_db")
            r = subprocess.run(
                ["/usr/bin/pg_dump", "-U", pg_user, "-h", pg_host, pg_db],
                capture_output=True, text=True, timeout=60, env={**os.environ, "PGPASSWORD": pg_pass})
            if r.returncode == 0 and r.stdout:
                with open(pg_dump_path, "w") as f:
                    f.write(r.stdout)
                tar.add(pg_dump_path, arcname="freelink_db.sql")
                os.unlink(pg_dump_path)
            # Config files
            for fname in ["config.yaml"]:
                fpath = os.path.join("/opt/freelink", fname)
                if os.path.exists(fpath):
                    tar.add(fpath, arcname=fname)
            hy_config = "/etc/hysteria/config.yaml"
            if os.path.exists(hy_config):
                tar.add(hy_config, arcname="hysteria_config.yaml")
        size = os.path.getsize(backup_path)
        audit_log(user, "BACKUP_CREATED", f"{backup_name} ({size} bytes)")
        return {"success": True, "name": backup_name, "size_mb": round(size / 1024 / 1024, 2)}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/backups/restore")
async def restore_backup(request: Request):
    token = request.cookies.get("session")
    user = validate_session(token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    data = await request.json()
    name = data.get("name", "")
    if not _validate_backup_name(name):
        return JSONResponse(status_code=400, content={"error": "Invalid backup name"})
    backup_path = os.path.join(BACKUP_DIR, name)
    if not os.path.exists(backup_path):
        return JSONResponse(status_code=404, content={"error": "Backup not found"})
    try:
        # Create a safety backup first
        safety_name = f"pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.tar.gz"
        safety_path = os.path.join(BACKUP_DIR, safety_name)
        with tarfile.open(safety_path, "w:gz") as tar:
            for fname in BACKUP_FILES:
                fpath = os.path.join("/opt/freelink", fname)
                if os.path.exists(fpath):
                    tar.add(fpath, arcname=fname)

        # Restore from backup
        with tarfile.open(backup_path, "r:gz") as tar:
            for member in tar.getmembers():
                basename = member.name
                # Security: reject path traversal attempts in tar members
                if ".." in basename or basename.startswith("/") or "\\" in basename:
                    continue
                if basename == "freelink_db.sql":
                    # Restore PostgreSQL from dump
                    tar.extract(member, "/tmp")
                    sql_path = f"/tmp/freelink_db.sql"
                    # Drop and recreate
                    pg_user = os.environ.get("PG_USER", "freelink")
                    pg_pass = os.environ.get("PG_PASS", "")
                    pg_host = os.environ.get("PG_HOST", "127.0.0.1")
                    pg_db = os.environ.get("PG_DB", "freelink_db")
                    subprocess.run(["/usr/bin/psql", "-U", pg_user, "-h", pg_host, "-d", pg_db,
                                   "-c", "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"],
                                  capture_output=True, timeout=30, env={**os.environ, "PGPASSWORD": pg_pass})
                    r = subprocess.run(["/usr/bin/psql", "-U", pg_user, "-h", pg_host, "-d", pg_db,
                                       "-f", sql_path],
                                      capture_output=True, text=True, timeout=60,
                                      env={**os.environ, "PGPASSWORD": pg_pass})
                    os.unlink(sql_path)
                    if r.returncode != 0:
                        audit_log(user, "BACKUP_RESTORE_WARNING", f"pg_restore: {r.stderr[:200]}")
                elif basename == "config.yaml":
                    tar.extract(member, "/opt/freelink")
                elif basename == "hysteria_config.yaml":
                    member.name = "config.yaml"
                    tar.extract(member, "/etc/hysteria")

        audit_log(user, "BACKUP_RESTORED", f"from {name}")
        return {"success": True, "safety_backup": safety_name}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.delete("/api/backups/{name}")
async def delete_backup(name: str, request: Request):
    token = request.cookies.get("session")
    user = validate_session(token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    if not _validate_backup_name(name):
        return JSONResponse(status_code=400, content={"error": "Invalid backup name"})
    backup_path = os.path.join(BACKUP_DIR, name)
    if not os.path.exists(backup_path):
        return JSONResponse(status_code=404, content={"error": "Not found"})
    os.remove(backup_path)
    audit_log(user, "BACKUP_DELETED", name)
    return {"success": True}

@app.get("/api/backups/{name}/download")
async def download_backup(name: str, request: Request):
    token = request.cookies.get("session")
    user = validate_session(token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    if not _validate_backup_name(name):
        return JSONResponse(status_code=400, content={"error": "Invalid backup name"})
    backup_path = os.path.join(BACKUP_DIR, name)
    if not os.path.exists(backup_path):
        return JSONResponse(status_code=404, content={"error": "Not found"})
    return FileResponse(backup_path, media_type="application/gzip",
                       headers={"Content-Disposition": f"attachment; filename={name}"})
GITHUB_REPO = "R3G1ST/FreeLink"
VERSION_FILE = "/opt/freelink/VERSION"

def get_local_version():
    try:
        with open(VERSION_FILE, "r") as f:
            return f.read().strip()
    except Exception:
        return "unknown"

def get_remote_version():
    try:
        r = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/contents/VERSION",
                         timeout=10, headers={"Accept": "application/vnd.github.v3.raw"})
        if r.status_code == 200:
            return r.text.strip()
    except Exception:
        pass
    return None

def get_remote_changelog():
    try:
        r = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/contents/CHANGELOG.md",
                         timeout=10, headers={"Accept": "application/vnd.github.v3.raw"})
        if r.status_code == 200:
            return r.text[:2000]
    except Exception:
        pass
    return ""

@app.get("/api/update/check")
async def check_update(request: Request):
    token = request.cookies.get("session")
    user = validate_session(token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    local = get_local_version()
    remote = get_remote_version()
    if remote is None:
        return {"local": local, "remote": "?", "behind": 0, "update_available": False,
                "error_detail": "Не удалось получить данные с GitHub"}
    update_available = remote != local
    return {
        "local": local,
        "remote": remote,
        "behind": 1 if update_available else 0,
        "update_available": update_available
    }

import threading

update_status = {"running": False, "log": "", "done": False, "success": False}

def run_update():
    global update_status
    update_status = {"running": True, "log": "", "done": False, "success": False}
    try:
        # Step 1: Git pull
        update_status["log"] += "▶ git pull...\n"
        r = subprocess.run(["git", "-C", "/opt/freelink", "stash"], capture_output=True, text=True, timeout=30)
        r = subprocess.run(["git", "-C", "/opt/freelink", "pull", "origin", "main"],
                          capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            update_status["log"] += f"  ⚠ git pull failed: {r.stderr.strip()}\n"
            update_status["log"] += "  Попытка продолжить...\n"
        else:
            update_status["log"] += f"  ✓ {r.stdout.strip()}\n"

        # Step 2: Update dependencies
        update_status["log"] += "▶ pip install...\n"
        r = subprocess.run(["/opt/freelink/venv/bin/pip", "install", "-r", "/opt/freelink/requirements.txt", "-q"],
                          capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            update_status["log"] += f"  ⚠ {r.stderr.strip()[:200]}\n"
        else:
            update_status["log"] += "  ✓ Done\n"

        # Step 3: Update VERSION file from git
        update_status["log"] += "▶ update version...\n"
        r = subprocess.run(["git", "-C", "/opt/freelink", "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            update_status["log"] += f"  ✓ Version: {r.stdout.strip()}\n"

        # Step 4: Restart all services
        services = ["freelink-api", "freelink-auth", "freelink-bot",
                    "freelink-online", "freelink-traffic", "freelink-history"]
        for svc in services:
            update_status["log"] += f"▶ restart {svc}...\n"
            r = subprocess.run(["/usr/bin/systemctl", "restart", svc],
                              capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                update_status["log"] += f"  ⚠ {r.stderr.strip()[:100]}\n"
            else:
                update_status["log"] += "  ✓ Done\n"

        update_status["log"] += "\n✅ Обновление завершено!\n"
        update_status["log"] += "Страница обновится через 3 секунды...\n"
        update_status["success"] = True
    except Exception as e:
        update_status["log"] += f"\n❌ Ошибка: {str(e)}\n"
        update_status["success"] = False
    finally:
        update_status["done"] = True
        update_status["running"] = False

@app.post("/api/update/run")
async def run_update_endpoint(request: Request):
    token = request.cookies.get("session")
    user = validate_session(token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    admins = load_admins()
    if admins.get(user, {}).get("role") != "admin":
        return JSONResponse(status_code=403, content={"error": "Only admin can update"})
    if update_status["running"]:
        return JSONResponse(status_code=409, content={"error": "Update already in progress"})
    thread = threading.Thread(target=run_update, daemon=True)
    thread.start()
    return {"success": True, "message": "Update started"}

@app.get("/api/update/status")
async def update_status_endpoint(request: Request):
    token = request.cookies.get("session")
    user = validate_session(token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    return update_status

# ====== WEBSOCKET LIVE ======

ws_clients = set()

@app.websocket("/ws/live")
async def websocket_live(websocket: WebSocket):
    # Authenticate WebSocket connection
    token = websocket.query_params.get("token", "")
    user = validate_session(token)
    if not user:
        await websocket.close(code=4001, reason="Unauthorized")
        return
    
    await websocket.accept()
    ws_clients.add(websocket)
    try:
        while True:
            online_status = get_online_status()
            users = get_all_users()
            traffic = []
            for uid, user_data in users.items():
                username = user_data.get("name", uid)
                user_status = find_online_user(online_status, username)
                if user_status.get("online"):
                    traffic.append({
                        "user": username,
                        "tx_speed_mb": round(user_status.get("tx_speed", 0) / 1024 / 1024, 2),
                        "rx_speed_mb": round(user_status.get("rx_speed", 0) / 1024 / 1024, 2),
                        "last_active": user_status.get("last_active", ""),
                        "inactive_since": user_status.get("inactive_since"),
                    })
            online_count = sum(1 for u in online_status.values() if u.get("online"))
            # Server info for dashboard
            server_info = get_server_info()
            # User stats for dashboard
            total_users = len(users)
            active_users = sum(1 for u in users.values() if u.get("active", True))
            now = datetime.now()
            expired = 0
            expiring = 0
            for u in users.values():
                if not u.get("active", True):
                    continue
                try:
                    exp = u.get("expire_date", "")
                    if exp:
                        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                            try:
                                exp_dt = datetime.strptime(exp, fmt)
                                break
                            except ValueError:
                                continue
                        if exp_dt < now:
                            expired += 1
                        elif (exp_dt - now).total_seconds() < 259200:  # 3 days
                            expiring += 1
                except Exception:
                    pass
            # Get recent structured logs for real-time updates
            try:
                recent_logs = db.get_structured_logs(limit=20)
            except Exception:
                recent_logs = []
            await websocket.send_json({
                "traffic": traffic,
                "online": online_count,
                "time": time.strftime("%H:%M:%S"),
                "server": server_info,
                "stats": {
                    "total": total_users,
                    "active": active_users,
                    "expired": expired,
                    "expiring": expiring
                },
                "logs": recent_logs
            })
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        ws_clients.discard(websocket)
    except Exception:
        ws_clients.discard(websocket)

import asyncio

async def broadcast_update():
    if not ws_clients:
        return
    online_status = get_online_status()
    users = get_all_users()
    traffic = []
    for uid, user in users.items():
        username = user.get("name", uid)
        user_status = find_online_user(online_status, username)
        if user_status.get("online"):
            traffic.append({
                "user": username,
                "tx_speed_mb": round(user_status.get("tx_speed", 0) / 1024 / 1024, 2),
                "rx_speed_mb": round(user_status.get("rx_speed", 0) / 1024 / 1024, 2),
                "last_active": user_status.get("last_active", ""),
                "inactive_since": user_status.get("inactive_since"),
            })
    online_count = sum(1 for u in online_status.values() if u.get("online"))
    dead = set()
    for ws in ws_clients:
        try:
            await ws.send_json({"traffic": traffic, "online": online_count, "time": time.strftime("%H:%M:%S")})
        except Exception:
            dead.add(ws)
    ws_clients -= dead

# ====== NOTIFICATIONS ======

NOTIFICATIONS_FILE = "/opt/freelink/notifications.json"

def load_notifications():
    if os.path.exists(NOTIFICATIONS_FILE):
        try:
            with open(NOTIFICATIONS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_notifications(nots):
    with open(NOTIFICATIONS_FILE, "w") as f:
        json.dump(nots[-200:], f, ensure_ascii=False)

def add_notification(ntype, message, details=""):
    nots = load_notifications()
    nots.append({
        "type": ntype,
        "message": message,
        "details": details,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "read": False
    })
    save_notifications(nots)

@app.get("/api/notifications")
async def get_notifications():
    return {"notifications": load_notifications()[-50:]}

@app.get("/api/miniapp/notifications")
async def miniapp_notifications():
    return {"notifications": load_notifications()[-20:]}

@app.post("/api/notifications/read")
async def mark_read():
    nots = load_notifications()
    for n in nots:
        n["read"] = True
    save_notifications(nots)
    return {"success": True}

@app.post("/api/check-expiry")
async def check_expiry():
    users = get_all_users()
    now = datetime.now()
    expiring = []
    for uid, user in users.items():
        expire_str = user.get("expire_date", "")
        if not expire_str:
            continue
        try:
            expire_dt = datetime.strptime(expire_str, "%Y-%m-%d %H:%M")
            days_left = (expire_dt - now).days
            if 0 <= days_left <= 3:
                expiring.append({"uid": uid, "name": user.get("name", uid), "days_left": days_left, "expire_date": expire_str})
                add_notification("warning", f"У {user.get('name', uid)} истекает через {days_left} дн.", f"uid={uid}")
            elif days_left < 0:
                add_notification("danger", f"Подписка {user.get('name', uid)} истекла.", f"uid={uid}")
        except Exception:
            pass
    return {"expiring": expiring}

# ====== REPORT EXPORT ======

@app.get("/api/report")
async def generate_report(fmt: str = "json"):
    users = get_all_users()
    online_status = get_online_status()
    report = {
        "generated": datetime.now().isoformat(),
        "total_users": len(users),
        "active_users": sum(1 for u in users.values() if u.get("active", True)),
        "online_users": sum(1 for u in online_status.values() if u.get("online")),
        "users": []
    }
    for uid, user in users.items():
        username = user.get("name", uid)
        ts = user.get("traffic_saved", {})
        report["users"].append({
            "id": uid, "name": username,
            "active": user.get("active", True),
            "created": user.get("created", ""),
            "expire_date": user.get("expire_date", ""),
            "online": find_online_user(online_status, username).get("online", False),
            "traffic_mb": round((ts.get("tx",0)+ts.get("rx",0))/1024/1024, 2),
            "speed_limit": user.get("speed_limit_mbps", 0)
        })
    if fmt == "csv":
        lines = ["id,name,active,created,expire_date,online,traffic_mb,speed_limit"]
        for u in report["users"]:
            lines.append(f"{u['id']},{u['name']},{u['active']},{u['created']},{u['expire_date']},{u['online']},{u['traffic_mb']},{u['speed_limit']}")
        csv = "\n".join(lines)
        return Response(content=csv, media_type="text/csv",
                       headers={"Content-Disposition": "attachment; filename=report.csv"})
    return report

# ====== SYSTEM WIDGETS (miniapp) ======

@app.get("/api/miniapp/widgets")
async def miniapp_widgets():
    info = get_server_info()
    users = get_all_users()
    online_status = get_online_status()
    online_count = sum(1 for u in online_status.values() if u.get("online"))
    total_users = len(users)
    active_users = sum(1 for u in users.values() if u.get("active", True))
    expired = 0
    now = datetime.now()
    for user in users.values():
        try:
            if user.get("expire_date") and datetime.strptime(user["expire_date"], "%Y-%m-%d %H:%M") < now:
                expired += 1
        except Exception:
            pass
    return {
        "server": info,
        "stats": {"total": total_users, "active": active_users, "online": online_count, "expired": expired},
        "hysteria_status": "active" if check_hysteria_sync() else "inactive"
    }

def check_hysteria_sync():
    try:
        r = subprocess.run(["/usr/bin/systemctl", "is-active", "hysteria-server"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() == "active"
    except Exception:
        return False

# ===================================================================
# ===== NODE AUTO-DEPLOY VIA SSH =====
# ===================================================================

@app.post("/api/nodes/deploy")
async def deploy_node(request: Request):
    data = await request.json()
    host = data.get("host", "").strip()
    port = int(data.get("port", 22))
    username = data.get("username", "").strip()
    password = data.get("password", "")
    key_content = data.get("key", "")
    node_name = data.get("name", host).strip()
    node_region = data.get("region", "")
    panel_url = data.get("panel_url", f"https://{os.environ.get('DOMAIN', 'link.qmbox.ru')}")

    if not host or not username:
        return JSONResponse(status_code=400, content={"error": "host и username обязательны"})
    if not password and not key_content:
        return JSONResponse(status_code=400, content={"error": "Укажите пароль или SSH-ключ"})

    import paramiko, asyncio, concurrent.futures

    def _do_deploy():
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.WarningPolicy())
        try:
            connect_kwargs = {"hostname": host, "port": port, "username": username, "timeout": 15}
            if key_content:
                import io
                pkey = paramiko.RSAKey.from_private_key(io.StringIO(key_content))
                connect_kwargs["pkey"] = pkey
            else:
                connect_kwargs["password"] = password
            ssh.connect(**connect_kwargs)
        except paramiko.AuthenticationException:
            return {"error": "Ошибка аутентификации SSH"}
        except Exception as e:
            return {"error": f"Ошибка подключения: {str(e)}"}

        deploy_script = f"""#!/bin/bash
set -e

echo "=== Предварительные тесты ==="
echo -n "1. OS: "
cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d'"' -f2 || echo "Unknown"

echo -n "2. Root access: "
[ "$(id -u)" = "0" ] && echo "✓ OK" || echo "✗ нужен root"

echo -n "3. Python3: "
python3 --version 2>&1 || echo "✗ не установлен"

echo -n "4. curl: "
curl --version >/dev/null 2>&1 && echo "✓ OK" || echo "✗ не установлен"

echo -n "5. Диск (свободно): "
df -h / | awk 'NR==2{{print $4}}' || echo "?"

echo -n "6. RAM: "
free -h | awk '/Mem/{{print $7}}' || echo "?"

echo -n "7. UDP outbound: "
timeout 2 bash -c 'echo -n "t" | nc -u -w 1 8.8.8.8 443' 2>/dev/null && echo "✓ работает" || echo "⚠ может быть заблокирован"

echo -n "8. Порт 443: "
if ss -tlnp | grep -q ":443"; then
    echo "⚠ занят (nginx/apache?)"
else
    echo "✓ свободен"
fi

echo "=== Тесты пройдены, начало установки ==="

echo "=== Установка Hysteria 2 ==="
apt-get update -qq
apt-get install -y -qq python3 python3-pip curl certbot

# Install Hysteria
bash <(curl -fsSL https://get.hy2.sh/) || true

echo "=== Установка зависимостей агента ==="
pip3 install psutil pyyaml 2>/dev/null || pip3 install --break-system-packages psutil pyyaml

echo "=== Создание агента ==="
mkdir -p /opt/hysteria-agent

# Download agent
curl -fsSL "{panel_url}/api/node/agent-script" -o /opt/hysteria-agent/node_agent.py 2>/dev/null || true

echo "=== Настройка Hysteria ==="
mkdir -p /etc/hysteria/certs

# Download cert from main panel
curl -fsSL "{panel_url}/api/node/cert" -o /tmp/certs.tar.gz 2>/dev/null && tar -xzf /tmp/certs.tar.gz -C /etc/hysteria/certs/ 2>/dev/null && rm -f /tmp/certs.tar.gz || echo "Cert download failed, using self-signed"

# Fallback: generate self-signed if download failed
if [ ! -f /etc/hysteria/certs/cert.pem ]; then
    openssl req -x509 -nodes -newkey ec:<(openssl ecparam -name prime256v1) \
        -keyout /etc/hysteria/certs/key.pem \
        -out /etc/hysteria/certs/cert.pem \
        -subj "/CN=placeholder" -days 3650 2>/dev/null
fi
chmod 644 /etc/hysteria/certs/*.pem

cat > /etc/hysteria/config.yaml << 'HYCFG'
listen: :443
tls:
  cert: /etc/hysteria/certs/cert.pem
  key: /etc/hysteria/certs/key.pem
auth:
  type: userpass
  userpass:
    placeholder: placeholder
obfs:
  type: salamander
  salamander:
    password: "{os.environ.get('HYSTERIA_OBFS_PASSWORD', '')}"
trafficStats:
  listen: 127.0.0.1:9999
quic:
  disablePathMTUDiscovery: true
HYCFG

echo "=== Настройка сети ==="
# Enable IP forwarding
echo 1 > /proc/sys/net/ipv4/ip_forward
sysctl -w net.ipv4.ip_forward=1
grep -q "net.ipv4.ip_forward=1" /etc/sysctl.conf || echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf

# Detect interface and setup NAT
IFACE=$(ip route | grep default | awk '{{print $5}}' | head -1)
iptables -t nat -C POSTROUTING -s 10.0.0.0/8 -o $IFACE -j MASQUERADE 2>/dev/null || iptables -t nat -A POSTROUTING -s 10.0.0.0/8 -o $IFACE -j MASQUERADE
iptables -C FORWARD -s 10.0.0.0/8 -j ACCEPT 2>/dev/null || iptables -A FORWARD -s 10.0.0.0/8 -j ACCEPT
iptables -C FORWARD -d 10.0.0.0/8 -j ACCEPT 2>/dev/null || iptables -A FORWARD -d 10.0.0.0/8 -j ACCEPT

systemctl enable hysteria-server 2>/dev/null || true
systemctl restart hysteria-server 2>/dev/null || true

echo "=== DONE ==="
"""
        try:
            # Use stdin to avoid shell quoting issues with bash -c
            transport = ssh.get_transport()
            channel = transport.open_session()
            channel.exec_command("bash")
            channel.sendall(deploy_script.encode())
            channel.shutdown_write()
            exit_code = channel.recv_exit_status()
            output = channel.recv(65536).decode()
            errors = channel.recv_stderr(65536).decode() if channel.recv_stderr_ready() else ""

            if exit_code != 0:
                ssh.close()
                return {"error": f"Ошибка деплоя (exit {exit_code})", "output": output[-2000:], "stderr": errors[-2000:]}

            # Get public IP
            stdin, stdout, stderr = ssh.exec_command("curl -s --max-time 5 ifconfig.me", timeout=10)
            public_ip = stdout.read().decode().strip()
            if not public_ip:
                public_ip = host

            # Run connectivity tests
            test_script = """#!/bin/bash
echo "=== Тесты подключения ==="

# Test 1: Hysteria running?
echo -n "1. Hysteria service: "
if systemctl is-active hysteria-server >/dev/null 2>&1; then
    echo "✓ работает"
else
    echo "✗ не работает"
fi

# Test 2: UDP 443 listening?
echo -n "2. UDP порт 443: "
if ss -ulnp | grep -q ":443"; then
    echo "✓ слушает"
else
    echo "✗ не слушает"
fi

# Test 3: TLS certificate?
echo -n "3. TLS сертификат: "
if [ -f /etc/hysteria/certs/cert.pem ]; then
    EXPIRY=$(openssl x509 -in /etc/hysteria/certs/cert.pem -noout -enddate 2>/dev/null | cut -d= -f2)
    echo "✓ есть (до: $EXPIRY)"
else
    echo "✗ нет"
fi

# Test 4: Agent running?
echo -n "4. Агент: "
if systemctl is-active hysteria-agent >/dev/null 2>&1; then
    echo "✓ работает"
else
    echo "✗ не работает"
fi

# Test 5: IP forwarding?
echo -n "5. IP forwarding: "
if [ "$(cat /proc/sys/net/ipv4/ip_forward)" = "1" ]; then
    echo "✓ включён"
else
    echo "✗ выключен"
fi

# Test 6: NAT configured?
echo -n "6. NAT (MASQUERADE): "
IFACE=$(ip route | grep default | awk '{{print $5}}' | head -1)
if iptables -t nat -C POSTROUTING -s 10.0.0.0/8 -o $IFACE -j MASQUERADE 2>/dev/null; then
    echo "✓ настроен"
else
    echo "✗ не настроен"
fi

# Test 7: External UDP test (from this server)
echo -n "7. UDP connectivity: "
if timeout 2 bash -c 'echo -n "test" | nc -u -w 1 8.8.8.8 443' 2>/dev/null; then
    echo "✓ работает"
else
    echo "⚠ не могу проверить (это нормально если сервер за NAT)"
fi

echo "=== Тесты завершены ==="
"""
            # Run tests on the new node
            stdin, stdout, stderr = ssh.exec_command(f"bash -c '{test_script}'", timeout=30)
            test_output = stdout.read().decode()
            output += "\n" + test_output

            nodes = load_nodes()
            nid = gen_id()
            token = gen_node_token()
            nodes[nid] = {
                "name": node_name, "ip": public_ip, "domain": public_ip,
                "token": token, "status": "online",
                "created": datetime.now().isoformat(), "last_seen": datetime.now().isoformat(),
                "region": node_region, "country": "", "max_users": 100,
                "cpu_percent": 0, "ram_percent": 0, "disk_percent": 0,
                "online_users": 0, "total_users": 0,
                "traffic_sent": 0, "traffic_recv": 0,
                "hysteria_status": "unknown", "version": "1.0",
                "assigned_users": [], "deployed": True, "ssh_host": host, "ssh_port": port
            }
            save_nodes(nodes)

            agent_setup = f"""#!/bin/bash
set -e
mkdir -p /opt/hysteria-agent
cat > /opt/hysteria-agent/agent.json << 'AGTCFG'
{{"node_id": "{nid}", "token": "{token}"}}
AGTCFG
cat > /etc/systemd/system/hysteria-agent.service << 'SVCEOF'
[Unit]
Description=Hysteria 2 Node Agent
After=network.target
[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/hysteria-agent/node_agent.py --panel {panel_url} --name {node_name} --ip {public_ip} --node-id {nid} --token {token}
Restart=always
RestartSec=10
[Install]
WantedBy=multi-user.target
SVCEOF
systemctl daemon-reload
systemctl enable hysteria-agent 2>/dev/null || true
systemctl restart hysteria-agent 2>/dev/null || true
echo "=== Agent started ==="
"""
            try:
                # Use stdin to avoid shell quoting issues
                transport2 = ssh.get_transport()
                channel2 = transport2.open_session()
                channel2.exec_command("bash")
                channel2.sendall(agent_setup.encode())
                channel2.shutdown_write()
                agent_exit = channel2.recv_exit_status()
                if agent_exit != 0:
                    print(f"Agent setup warning: {channel2.recv(65536).decode()}", file=sys.stderr)
            except Exception as e:
                print(f"Agent setup error: {e}", file=sys.stderr)

            ssh.close()
            audit_log("admin", "NODE_DEPLOYED", f"name={node_name} host={host}")
            return {"success": True, "node_id": nid, "token": token, "ip": public_ip, "output": output[-1000:]}

        except Exception as e:
            ssh.close()
            return {"error": f"Ошибка: {str(e)}"}

    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        result = await loop.run_in_executor(pool, _do_deploy)

    if "error" in result:
        return JSONResponse(status_code=400, content=result)
    return result

# Serve agent script for download
@app.get("/api/node/agent-script")
async def get_agent_script():
    with open("/opt/freelink/node_agent.py", "r") as f:
        return Response(content=f.read(), media_type="text/plain")

# Serve TLS certificates for nodes (requires valid node token)
@app.get("/api/node/cert")
async def get_cert(request: Request, token: str = ""):
    import tarfile, tempfile
    
    # Authenticate: require a valid node token
    nodes = load_nodes()
    valid_tokens = [n.get("token") for n in nodes.values() if n.get("token")]
    if not token or token not in valid_tokens:
        raise HTTPException(status_code=403, detail="Invalid or missing node token")
    
    domain = os.environ.get("DOMAIN", "link.qmbox.ru")
    cert_dir = f"/etc/letsencrypt/live/{domain}"
    if not os.path.exists(cert_dir):
        return JSONResponse(status_code=404, content={"error": "No certs found"})
    tmp = tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False)
    try:
        with tarfile.open(tmp.name, "w:gz") as tar:
            tar.add(f"{cert_dir}/fullchain.pem", arcname="cert.pem")
            tar.add(f"{cert_dir}/privkey.pem", arcname="key.pem")
        with open(tmp.name, "rb") as f:
            content = f.read()
        os.unlink(tmp.name)
        return Response(content=content, media_type="application/gzip",
                       headers={"Content-Disposition": "attachment; filename=certs.tar.gz"})
    except Exception as e:
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)
        return JSONResponse(status_code=500, content={"error": str(e)})

NODES_FILE = "/opt/freelink/nodes.json"
MAIN_NODE_ID = "__main__"

def load_nodes():
    return db.load_nodes()

def load_panel_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}

CERT_HASH_CACHE = ""

def get_cert_hash():
    """Get SHA256 hash of the TLS certificate for pinnedPeerCertSha256"""
    global CERT_HASH_CACHE
    if CERT_HASH_CACHE:
        return CERT_HASH_CACHE
    try:
        import subprocess
        domain = os.environ.get("DOMAIN", "link.qmbox.ru")
        cert_path = f"/etc/letsencrypt/live/{domain}/fullchain.pem"
        cmd = f"openssl x509 -in {cert_path} -noout -pubkey | openssl pkey -pubin -outform der 2>/dev/null | openssl dgst -sha256 -binary | base64"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            CERT_HASH_CACHE = result.stdout.strip()
            return CERT_HASH_CACHE
    except Exception:
        pass
    # Fallback: hardcoded hash
    return "8WTwYZZpI9MjrSYzZkMNItepQn03XsdMZM0hT1iJO2s="

def ensure_main_node():
    nodes = load_nodes()
    cfg = load_panel_config()
    srv = cfg.get("server", {}) if cfg else {}
    # Ensure all nodes have domain field
    for nid, node in nodes.items():
        if "domain" not in node:
            node["domain"] = node.get("ip", "")
    if MAIN_NODE_ID in nodes:
        nodes[MAIN_NODE_ID]["domain"] = os.environ.get("DOMAIN", "link.qmbox.ru")
        nodes[MAIN_NODE_ID]["name"] = srv.get("name", "Основной")
        nodes[MAIN_NODE_ID]["ip"] = srv.get("ip", "127.0.0.1")
        nodes[MAIN_NODE_ID]["last_seen"] = datetime.now().isoformat()
        nodes[MAIN_NODE_ID]["status"] = "online"
        # Get online users from main server Hysteria API
        try:
            import requests
            r = requests.get("http://127.0.0.1:9999/traffic", timeout=3)
            if r.status_code == 200:
                traffic = r.json()
                nodes[MAIN_NODE_ID]["online_usernames"] = list(traffic.keys())
                nodes[MAIN_NODE_ID]["online_users"] = len(traffic)
        except Exception:
            pass
        save_nodes(nodes)
        return
    nodes[MAIN_NODE_ID] = {
        "name": srv.get("name", "Основной"),
        "ip": os.environ.get("SERVER_IP", "127.0.0.1"),
        "domain": os.environ.get("DOMAIN", "link.qmbox.ru"),
        "token": gen_node_token(),
        "status": "online",
        "created": datetime.now().isoformat(),
        "last_seen": datetime.now().isoformat(),
        "region": "Основной сервер",
        "country": "",
        "max_users": 9999,
        "cpu_percent": 0, "ram_percent": 0, "disk_percent": 0,
        "online_users": 0, "total_users": 0,
        "traffic_sent": 0, "traffic_recv": 0,
        "hysteria_status": "active",
        "version": "3.8",
        "assigned_users": [],
        "is_main": True,
        "deployed": True,
        "online_usernames": []
    }
    save_nodes(nodes)
    print(f"[MAIN NODE] Registered main server as node: {srv.get('name', 'Основной')} ({srv.get('ip', '127.0.0.1')})")

def save_nodes(nodes):
    db.save_nodes(nodes)

def gen_node_token():
    return secrets.token_urlsafe(32)

# Node registration — agent calls this on startup
@app.post("/api/node/register")
async def node_register(request: Request):
    data = await request.json()
    name = data.get("name", "").strip()
    ip = data.get("ip", "").strip()
    api_key = data.get("api_key", "")
    # Validate API key
    expected_key = os.environ.get("NODE_API_KEY", "")
    if not expected_key or api_key != expected_key:
        audit_log("node:" + name, "REGISTER_FAILED", "invalid_api_key")
        return JSONResponse(status_code=403, content={"error": "Invalid API key"})
    if not name or not ip:
        return JSONResponse(status_code=400, content={"error": "name and ip required"})
    nodes = load_nodes()
    # Check if node already exists by name
    for nid, node in nodes.items():
        if node["name"] == name:
            node["ip"] = ip
            node["last_seen"] = datetime.now().isoformat()
            node["status"] = "online"
            save_nodes(nodes)
            return {"success": True, "node_id": nid, "token": node["token"]}
    # New node
    nid = gen_id()
    token = gen_node_token()
    nodes[nid] = {
        "name": name,
        "ip": ip,
        "token": token,
        "status": "online",
        "created": datetime.now().isoformat(),
        "last_seen": datetime.now().isoformat(),
        "region": data.get("region", ""),
        "country": data.get("country", ""),
        "max_users": data.get("max_users", 100),
        "cpu_percent": 0,
        "ram_percent": 0,
        "disk_percent": 0,
        "online_users": 0,
        "total_users": 0,
        "traffic_sent": 0,
        "traffic_recv": 0,
        "hysteria_status": "unknown",
        "version": data.get("version", "1.0"),
        "assigned_users": []
    }
    save_nodes(nodes)
    audit_log("node:" + name, "REGISTERED", f"ip={ip}")
    return {"success": True, "node_id": nid, "token": token}

# Node heartbeat — agent calls this every 30s
@app.post("/api/node/heartbeat")
async def node_heartbeat(request: Request):
    data = await request.json()
    node_id = data.get("node_id", "")
    token = data.get("token", "")
    nodes = load_nodes()
    node = nodes.get(node_id)
    if not node or node["token"] != token:
        return JSONResponse(status_code=401, content={"error": "Invalid node credentials"})
    node["last_seen"] = datetime.now().isoformat()
    node["status"] = "online"
    node["cpu_percent"] = data.get("cpu_percent", 0)
    node["ram_percent"] = data.get("ram_percent", 0)
    node["ram_used_gb"] = data.get("ram_used_gb", 0)
    node["ram_total_gb"] = data.get("ram_total_gb", 0)
    node["disk_percent"] = data.get("disk_percent", 0)
    node["disk_used_gb"] = data.get("disk_used_gb", 0)
    node["disk_total_gb"] = data.get("disk_total_gb", 0)
    node["online_users"] = data.get("online_users", 0)
    node["total_users"] = data.get("total_users", 0)
    node["traffic_sent"] = data.get("traffic_sent", 0)
    node["traffic_recv"] = data.get("traffic_recv", 0)
    node["hysteria_status"] = data.get("hysteria_status", "unknown")
    node["online_usernames"] = data.get("online_usernames", [])
    # Store per-user traffic from this node
    node["user_traffic"] = data.get("user_traffic", {})
    save_nodes(nodes)
    # Save traffic snapshots from this node
    user_traffic = data.get("user_traffic", {})
    if user_traffic:
        snapshots = []
        for username, ut in user_traffic.items():
            snapshots.append({
                "username": username,
                "node_id": node_id,
                "tx": ut.get("tx", 0),
                "rx": ut.get("rx", 0)
            })
        db.save_traffic_snapshots_batch(snapshots)
    # Log connections for online users on remote nodes
    online_usernames = data.get("online_usernames", [])
    for username in online_usernames:
        node_ip = node.get("ip", "")
        if node_ip:
            db.log_connection(username, node_ip, node_id)
    # Return users for this node
    # If node has explicit assigned_users, use those; otherwise push ALL active users
    assigned = node.get("assigned_users", [])
    users_data = load_data()
    all_users = users_data.get("users", {})
    users_to_push = []

    if assigned:
        # Explicit assignment mode
        for uid in assigned:
            user = all_users.get(uid)
            if user:
                users_to_push.append({
                    "uid": uid,
                    "name": user.get("name", uid),
                    "password": user.get("password", ""),
                    "active": user.get("active", True),
                    "expire_date": user.get("expire_date", ""),
                    "speed_limit_mbps": user.get("speed_limit_mbps", 0)
                })
    else:
        # Auto-replicate: push all active users to this node
        for uid, user in all_users.items():
            if user.get("active"):
                users_to_push.append({
                    "uid": uid,
                    "name": user.get("name", uid),
                    "password": user.get("password", ""),
                    "active": True,
                    "expire_date": user.get("expire_date", ""),
                    "speed_limit_mbps": user.get("speed_limit_mbps", 0)
                })
    return {"success": True, "users": users_to_push}

# Admin: list all nodes
@app.get("/api/nodes", summary="List all nodes", description="Returns all server nodes with status, metrics, and assigned users.")
async def list_nodes():
    nodes = load_nodes()
    now = datetime.now()
    result = []
    for nid, node in nodes.items():
        if nid == MAIN_NODE_ID:
            # Main server: live metrics from psutil
            try:
                info = {}
                info["cpu_percent"] = psutil.cpu_percent(interval=0)
                info["ram_percent"] = psutil.virtual_memory().percent
                info["disk_percent"] = psutil.disk_usage("/").percent
                info["cpu_count"] = psutil.cpu_count()
                mem = psutil.virtual_memory()
                info["ram_used_gb"] = round(mem.used / (1024**3), 1)
                info["ram_total_gb"] = round(mem.total / (1024**3), 1)
                disk = psutil.disk_usage("/")
                info["disk_used_gb"] = round(disk.used / (1024**3), 1)
                info["disk_total_gb"] = round(disk.total / (1024**3), 1)
                net = psutil.net_io_counters()
                info["traffic_sent"] = round(net.bytes_sent / (1024**2))
                info["traffic_recv"] = round(net.bytes_recv / (1024**2))
                info["hysteria_status"] = "active"
            except Exception:
                info = {}
            # Count users from data.yaml
            users_data = load_data().get("users", {})
            total = len(users_data)
            active = sum(1 for u in users_data.values() if u.get("active"))
            online_status = get_online_status()
            online = sum(1 for uid, u in users_data.items() if online_status.get(u.get("name", uid), {}).get("online", False))
            node.update(info)
            node["total_users"] = total
            node["online_users"] = online
            node["active_users"] = active
            node["is_online"] = True
            node["id"] = nid
            node["last_seen"] = now.isoformat()
            result.append(node)
            continue
        # Remote nodes: check if online (last seen within 2 minutes)
        try:
            last = datetime.fromisoformat(node["last_seen"])
            is_online = (now - last).total_seconds() < 120
        except Exception:
            is_online = False
        node["id"] = nid
        node["is_online"] = is_online
        result.append(node)
    return {"nodes": result}

# Main server live info (for dashboard/widgets)
@app.get("/api/nodes/main-info")
async def main_server_info():
    try:
        info = {}
        info["cpu_percent"] = psutil.cpu_percent(interval=0.3)
        info["cpu_count"] = psutil.cpu_count()
        info["load_avg"] = list(psutil.getloadavg())
        info["process_count"] = len(psutil.pids())
        mem = psutil.virtual_memory()
        info["ram_percent"] = mem.percent
        info["ram_used_gb"] = round(mem.used / (1024**3), 1)
        info["ram_total_gb"] = round(mem.total / (1024**3), 1)
        disk = psutil.disk_usage("/")
        info["disk_percent"] = disk.percent
        info["disk_used_gb"] = round(disk.used / (1024**3), 1)
        info["disk_total_gb"] = round(disk.total / (1024**3), 1)
        net = psutil.net_io_counters()
        info["net_sent_gb"] = round(net.bytes_sent / (1024**3), 2)
        info["net_recv_gb"] = round(net.bytes_recv / (1024**3), 2)
        try:
            import subprocess as sp
            r = sp.run(["/usr/bin/cat", "/proc/uptime"], capture_output=True, text=True, timeout=3)
            uptime_secs = float(r.stdout.strip().split()[0])
            days = int(uptime_secs // 86400)
            hours = int((uptime_secs % 86400) // 3600)
            mins = int((uptime_secs % 3600) // 60)
            parts = []
            if days > 0: parts.append(f"{days} дн")
            if hours > 0: parts.append(f"{hours} ч")
            parts.append(f"{mins} мин")
            info["uptime"] = ", ".join(parts)
        except Exception:
            info["uptime"] = "?"
        users_data = load_data().get("users", {})
        online_status = get_online_status()
        info["total_users"] = len(users_data)
        info["active_users"] = sum(1 for u in users_data.values() if u.get("active"))
        info["online_users"] = sum(1 for uid, u in users_data.items() if online_status.get(u.get("name", uid), {}).get("online", False))
        info["hysteria_status"] = "active"
        return info
    except Exception as e:
        return {"error": str(e)}

# Admin: add node manually
@app.post("/api/nodes/add")
async def add_node(request: Request):
    data = await request.json()
    name = data.get("name", "").strip()
    ip = data.get("ip", "").strip()
    if not name or not ip:
        return JSONResponse(status_code=400, content={"error": "name and ip required"})
    nodes = load_nodes()
    nid = gen_id()
    token = gen_node_token()
    nodes[nid] = {
        "name": name, "ip": ip, "domain": data.get("domain", ip),
        "token": token, "status": "pending",
        "created": datetime.now().isoformat(), "last_seen": "",
        "region": data.get("region", ""), "country": data.get("country", ""),
        "max_users": data.get("max_users", 100),
        "cpu_percent": 0, "ram_percent": 0, "disk_percent": 0,
        "online_users": 0, "total_users": 0,
        "traffic_sent": 0, "traffic_recv": 0,
        "hysteria_status": "unknown", "version": "1.0", "assigned_users": []
    }
    save_nodes(nodes)
    audit_log("admin", "NODE_ADDED", f"name={name} ip={ip}")
    return {"success": True, "node_id": nid, "token": token}

# Admin: delete node
@app.delete("/api/nodes/{node_id}")
async def delete_node(node_id: str):
    if node_id == MAIN_NODE_ID:
        return JSONResponse(status_code=400, content={"error": "Нельзя удалить основной сервер"})
    nodes = load_nodes()
    if node_id in nodes:
        name = nodes[node_id]["name"]
        del nodes[node_id]
        save_nodes(nodes)
        audit_log("admin", "NODE_DELETED", f"name={name}")
        return {"success": True}
    raise HTTPException(status_code=404, detail="Node not found")

# Admin: update node (e.g. domain)
@app.put("/api/nodes/{node_id}")
async def update_node(node_id: str, request: Request):
    nodes = load_nodes()
    if node_id not in nodes:
        raise HTTPException(status_code=404, detail="Node not found")
    data = await request.json()
    for key in ["name", "domain", "ip", "region", "country", "max_users", "ssh_host", "ssh_port", "ssh_username"]:
        if key in data:
            nodes[node_id][key] = data[key]
    # Save SSH password if provided
    if "ssh_password" in data and data["ssh_password"]:
        nodes[node_id]["ssh_password"] = data["ssh_password"]
    save_nodes(nodes)
    audit_log("admin", "NODE_UPDATED", f"node={node_id} fields={list(data.keys())}")
    return {"success": True}

# Admin: fix node config via SSH (fix auth type + update agent)
@app.post("/api/nodes/{node_id}/fix")
async def fix_node(node_id: str, request: Request):
    nodes = load_nodes()
    if node_id not in nodes:
        return JSONResponse(status_code=404, content={"error": "Node not found"})
    node = nodes[node_id]
    if node.get("is_main"):
        return JSONResponse(status_code=400, content={"error": "Основной сервер не требует исправления"})
    data = await request.json()
    host = node.get("ssh_host") or node.get("ip", "")
    port = int(data.get("ssh_port", node.get("ssh_port", 22)))
    username = data.get("username", node.get("ssh_username", "root"))
    password = data.get("password", "") or node.get("ssh_password", "")
    panel_url = data.get("panel_url", f"https://{os.environ.get('DOMAIN', 'link.qmbox.ru')}")
    if not host:
        return JSONResponse(status_code=400, content={"error": "Нет SSH хоста у ноды"})
    if not password:
        return JSONResponse(status_code=400, content={"error": "Укажите SSH пароль"})
    # Save password for future use
    if data.get("password"):
        nodes[node_id]["ssh_password"] = data["password"]
        nodes[node_id]["ssh_username"] = username
        save_nodes(nodes)

    import paramiko, asyncio, concurrent.futures

    def _do_fix():
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.WarningPolicy())
        try:
            ssh.connect(hostname=host, port=port, username=username, password=password, timeout=15)
        except Exception as e:
            return {"error": f"SSH: {str(e)}"}

        fix_script = f"""#!/bin/bash
set -e

echo "=== Загрузка сертификата ==="
mkdir -p /etc/hysteria/certs
curl -fsSL "{panel_url}/api/node/cert" -o /tmp/certs.tar.gz 2>/dev/null && tar -xzf /tmp/certs.tar.gz -C /etc/hysteria/certs/ 2>/dev/null && rm -f /tmp/certs.tar.gz || echo "Cert download failed"
chmod 644 /etc/hysteria/certs/*.pem 2>/dev/null || true

echo "=== Исправление конфига Hysteria ==="
cat > /etc/hysteria/config.yaml << 'HYCFG'
listen: :443
tls:
  cert: /etc/hysteria/certs/cert.pem
  key: /etc/hysteria/certs/key.pem
auth:
  type: userpass
  userpass:
    placeholder: placeholder
obfs:
  type: salamander
  salamander:
    password: "{os.environ.get('HYSTERIA_OBFS_PASSWORD', '')}"
trafficStats:
  listen: 127.0.0.1:9999
quic:
  disablePathMTUDiscovery: true
HYCFG

echo "=== Настройка сети ==="
echo 1 > /proc/sys/net/ipv4/ip_forward
sysctl -w net.ipv4.ip_forward=1
grep -q "net.ipv4.ip_forward=1" /etc/sysctl.conf || echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
IFACE=$(ip route | grep default | awk '{{print $5}}' | head -1)
iptables -t nat -C POSTROUTING -s 10.0.0.0/8 -o $IFACE -j MASQUERADE 2>/dev/null || iptables -t nat -A POSTROUTING -s 10.0.0.0/8 -o $IFACE -j MASQUERADE
iptables -C FORWARD -s 10.0.0.0/8 -j ACCEPT 2>/dev/null || iptables -A FORWARD -s 10.0.0.0/8 -j ACCEPT
iptables -C FORWARD -d 10.0.0.0/8 -j ACCEPT 2>/dev/null || iptables -A FORWARD -d 10.0.0.0/8 -j ACCEPT

echo "=== Обновление агента ==="
mkdir -p /opt/hysteria-agent
curl -fsSL "{panel_url}/api/node/agent-script" -o /opt/hysteria-agent/node_agent.py 2>/dev/null || true

echo "=== Перезапуск Hysteria ==="
systemctl restart hysteria-server 2>/dev/null || true
systemctl restart hysteria-agent 2>/dev/null || true

# Run tests
test_script='#!/bin/bash
echo "=== Тесты после исправления ==="
echo -n "1. Hysteria: "; systemctl is-active hysteria-server >/dev/null 2>&1 && echo "✓ OK" || echo "✗ FAIL"
echo -n "2. UDP 443: "; ss -ulnp | grep -q ":443" && echo "✓ OK" || echo "✗ FAIL"
echo -n "3. Сертификат: "; [ -f /etc/hysteria/certs/cert.pem ] && echo "✓ OK" || echo "✗ FAIL"
echo -n "4. Агент: "; systemctl is-active hysteria-agent >/dev/null 2>&1 && echo "✓ OK" || echo "✗ FAIL"
echo -n "5. IP forwarding: "; [ "$(cat /proc/sys/net/ipv4/ip_forward)" = "1" ] && echo "✓ OK" || echo "✗ FAIL"
echo "=== Конец тестов ==="
'
eval "$test_script"

echo "=== DONE ==="
"""
        try:
            # Use stdin to avoid shell quoting issues
            transport = ssh.get_transport()
            channel = transport.open_session()
            channel.exec_command("bash")
            channel.sendall(fix_script.encode())
            channel.shutdown_write()
            exit_code = channel.recv_exit_status()
            output = channel.recv(65536).decode()
            errors = channel.recv_stderr(65536).decode() if channel.recv_stderr_ready() else ""
            ssh.close()
            if exit_code != 0:
                return {"error": f"Exit {exit_code}", "output": output[-1000:], "stderr": errors[-1000:]}
            return {"success": True, "output": output[-1000:]}
        except Exception as e:
            ssh.close()
            return {"error": str(e)}

    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        result = await loop.run_in_executor(pool, _do_fix)

    if "error" in result:
        return JSONResponse(status_code=500, content=result)
    audit_log("admin", "NODE_FIXED", f"node={node_id}")
    return result

# Admin: assign user to node
@app.post("/api/nodes/{node_id}/assign")
async def assign_user_to_node(node_id: str, request: Request):
    data = await request.json()
    uid = data.get("uid", "")
    nodes = load_nodes()
    if node_id not in nodes:
        raise HTTPException(status_code=404, detail="Node not found")
    if uid not in [u for u in nodes[node_id].get("assigned_users", [])]:
        nodes[node_id].setdefault("assigned_users", []).append(uid)
        save_nodes(nodes)
        audit_log("admin", "USER_ASSIGNED", f"uid={uid} node={nodes[node_id]['name']}")
    return {"success": True}

# Admin: unassign user from node
@app.post("/api/nodes/{node_id}/unassign")
async def unassign_user_from_node(node_id: str, request: Request):
    data = await request.json()
    uid = data.get("uid", "")
    nodes = load_nodes()
    if node_id not in nodes:
        raise HTTPException(status_code=404, detail="Node not found")
    assigned = nodes[node_id].get("assigned_users", [])
    if uid in assigned:
        assigned.remove(uid)
        nodes[node_id]["assigned_users"] = assigned
        save_nodes(nodes)
    return {"success": True}

# Admin: auto-assign users round-robin
@app.post("/api/nodes/auto-assign")
async def auto_assign_users():
    nodes = load_nodes()
    users = load_data().get("users", {})
    online_nodes = {nid: n for nid, n in nodes.items() if n.get("is_online", False) or n.get("status") == "online"}
    if not online_nodes:
        return JSONResponse(status_code=400, content={"error": "No online nodes"})
    # Get unassigned users
    all_assigned = set()
    for n in nodes.values():
        all_assigned.update(n.get("assigned_users", []))
    unassigned = [uid for uid in users if uid not in all_assigned]
    node_ids = list(online_nodes.keys())
    for i, uid in enumerate(unassigned):
        nid = node_ids[i % len(node_ids)]
        nodes[nid].setdefault("assigned_users", []).append(uid)
    save_nodes(nodes)
    return {"assigned": len(unassigned), "nodes": len(node_ids)}

# ===================================================================
# ===== SUBSCRIPTION SYSTEM =====
# ===================================================================

SUBS_FILE = "/opt/freelink/subscriptions.json"
PAYMENTS_FILE = "/opt/freelink/payments.json"

def load_subscriptions():
    if os.path.exists(SUBS_FILE):
        try:
            with open(SUBS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_subscriptions(subs):
    with open(SUBS_FILE, "w") as f:
        json.dump(subs, f, ensure_ascii=False, indent=2)

def load_payments():
    if os.path.exists(PAYMENTS_FILE):
        try:
            with open(PAYMENTS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_payments(payments):
    with open(PAYMENTS_FILE, "w") as f:
        json.dump(payments[-500:], f, ensure_ascii=False, indent=2)

@app.get("/api/subscriptions", summary="List subscriptions", description="Returns all user subscriptions with status, plan info, and traffic usage.")
async def list_subscriptions():
    subs = load_subscriptions()
    users = load_data().get("users", {})
    result = []
    for sid, sub in subs.items():
        user = users.get(sub.get("uid", ""), {})
        sub["id"] = sid
        sub["user_name"] = user.get("name", sub.get("uid", ""))
        result.append(sub)
    return {"subscriptions": result}

@app.post("/api/subscriptions/create")
async def create_subscription(request: Request):
    data = await request.json()
    uid = data.get("uid", "")
    plan_id = data.get("plan_id", "")
    users = load_data().get("users", {})
    if uid not in users:
        return JSONResponse(status_code=400, content={"error": "User not found"})
    plans = load_plans()
    plan = next((p for p in plans if p["id"] == plan_id), None)
    if not plan:
        return JSONResponse(status_code=400, content={"error": "Plan not found"})
    sid = gen_id()
    now = datetime.now()
    subs = load_subscriptions()
    subs[sid] = {
        "uid": uid,
        "plan_id": plan_id,
        "plan_name": plan.get("name", ""),
        "status": "active",
        "created": now.isoformat(),
        "starts": now.isoformat(),
        "expires": (now + timedelta(days=plan.get("days", 30))).isoformat(),
        "traffic_limit_mb": plan.get("traffic_limit_mb", 0),
        "traffic_used_mb": 0,
        "price": plan.get("price", ""),
        "payment_status": "paid",
        "auto_renew": False,
        "trial": data.get("trial", False)
    }
    save_subscriptions(subs)
    # Update user
    user = users[uid]
    user["expire_date"] = subs[sid]["expires"].replace("T", " ")[:16]
    user["traffic_limit"] = plan.get("traffic_limit_mb", 0)
    user["subscription_id"] = sid
    save_data({"servers": {}, "users": users})
    audit_log("admin", "SUBSCRIPTION_CREATED", f"uid={uid} plan={plan.get('name')}")
    return {"success": True, "sub_id": sid}

@app.post("/api/subscriptions/{sid}/renew")
async def renew_subscription(sid: str, request: Request):
    data = await request.json()
    days = data.get("days", 30)
    subs = load_subscriptions()
    sub = subs.get(sid)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    try:
        current = datetime.fromisoformat(sub["expires"])
        if current < datetime.now():
            current = datetime.now()
    except Exception:
        current = datetime.now()
    sub["expires"] = (current + timedelta(days=days)).isoformat()
    sub["status"] = "active"
    save_subscriptions(subs)
    # Update user
    users = load_data().get("users", {})
    uid = sub.get("uid", "")
    if uid in users:
        users[uid]["expire_date"] = sub["expires"].replace("T", " ")[:16]
        save_data({"servers": {}, "users": users})
    return {"success": True, "new_expire": sub["expires"]}

@app.post("/api/subscriptions/{sid}/cancel")
async def cancel_subscription(sid: str):
    subs = load_subscriptions()
    sub = subs.get(sid)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    sub["status"] = "cancelled"
    save_subscriptions(subs)
    return {"success": True}

@app.post("/api/subscriptions/{sid}/toggle-auto-renew")
async def toggle_auto_renew(sid: str):
    subs = load_subscriptions()
    sub = subs.get(sid)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    sub["auto_renew"] = not sub.get("auto_renew", False)
    save_subscriptions(subs)
    return {"success": True, "auto_renew": sub["auto_renew"]}

@app.delete("/api/subscriptions/{sid}")
async def delete_subscription(sid: str):
    subs = load_subscriptions()
    if sid in subs:
        del subs[sid]
        save_subscriptions(subs)
        return {"success": True}
    raise HTTPException(status_code=404, detail="Subscription not found")

# Payments
@app.get("/api/payments")
async def list_payments():
    return {"payments": load_payments()[-50:]}

@app.post("/api/payments/add")
async def add_payment(request: Request):
    data = await request.json()
    payments = load_payments()
    payments.append({
        "id": gen_id(),
        "uid": data.get("uid", ""),
        "amount": data.get("amount", 0),
        "currency": data.get("currency", "RUB"),
        "method": data.get("method", "manual"),
        "status": data.get("status", "confirmed"),
        "sub_id": data.get("sub_id", ""),
        "created": datetime.now().isoformat(),
        "comment": data.get("comment", "")
    })
    save_payments(payments)
    return {"success": True}

# Subscription URL: returns plain text with hysteria2:// URIs for all online nodes
@app.get("/sub/{token}")
async def subscription_urls(token: str, request: Request):
    users = load_data().get("users", {})
    user = None
    uid = None
    for u, data in users.items():
        if data.get("service_token") == token:
            user = data
            uid = u
            break
    if not user:
        return JSONResponse(status_code=404, content={"error": "Invalid token"})
    if not user.get("active"):
        return JSONResponse(status_code=403, content={"error": "User inactive"})
    # Check if subscription expired
    expire = user.get("expire_date", "")
    if expire:
        try:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                try:
                    expire_dt = datetime.strptime(expire, fmt)
                    break
                except ValueError:
                    continue
            else:
                expire_dt = None
            if expire_dt and expire_dt < datetime.now():
                return JSONResponse(status_code=403, content={"error": "Subscription expired"})
        except Exception:
            pass

    config = load_panel_config()
    obfs = os.environ.get("HYSTERIA_OBFS_PASSWORD", "")
    port = 443

    username = user.get("name", uid)
    password = user.get("password", "")

    nodes = load_nodes()
    now = datetime.now()
    proxies = []
    plain_lines = []
    for nid, node in nodes.items():
        is_main = node.get("is_main", False)
        if is_main:
            is_online = True
        else:
            try:
                last = datetime.fromisoformat(node.get("last_seen", ""))
                is_online = (now - last).total_seconds() < 120
            except Exception:
                is_online = False

        if not is_online:
            continue

        domain = node.get("domain") or node.get("ip", "")
        if not domain:
            continue

        name = node.get("name", domain)
        node_port = node.get("port", port)
        sni = os.environ.get("DOMAIN", "link.qmbox.ru")
        from urllib.parse import quote
        cert_hash = get_cert_hash()
        enc_user = quote(username, safe='')
        enc_pass = quote(password, safe='')

        # Clash/Happ proxy config (Clash Meta / Mihomo format)
        proxy = {
            "name": name,
            "type": "hysteria2",
            "server": domain,
            "port": node_port,
            "password": password,
            "sni": sni,
            "skip-cert-verify": False,
        }
        if obfs:
            proxy["obfs"] = "salamander"
            proxy["obfs-password"] = obfs
        proxies.append(proxy)

        # Plain text URI — original format that works with all clients
        if obfs:
            uri = f"hysteria2://{enc_user}:{enc_pass}@{domain}:{node_port}?sni={sni}&obfs=salamander&obfs-password={obfs}&pinnedPeerCertSha256={cert_hash}#{name}"
        else:
            uri = f"hysteria2://{enc_user}:{enc_pass}@{domain}:{node_port}?sni={sni}&pinnedPeerCertSha256={cert_hash}#{name}"
        plain_lines.append(uri)

    if not proxies:
        return Response(content="# No online servers available\n", media_type="text/plain; charset=utf-8")

    ua = request.headers.get("user-agent", "").lower()
    format_param = request.query_params.get("format", "")
    print(f"[SUB] token={token[:8]}... ua={ua[:60]} format={format_param}", flush=True)

    plain_content = "\n".join(plain_lines) + "\n"

    # Clash YAML for Clash/Mihomo
    if format_param == "clash":
        import yaml as _yaml
        import base64 as _b64
        clash_config = {
            "mixed-port": 7890, "allow-lan": False, "mode": "rule", "log-level": "info",
            "proxies": proxies,
            "proxy-groups": [{"name": "PROXY", "type": "select", "proxies": [p["name"] for p in proxies]}],
            "rules": ["MATCH,PROXY"]
        }
        content = _yaml.dump(clash_config, default_flow_style=False, allow_unicode=True)
        return Response(content=content, media_type="text/yaml; charset=utf-8")

    # Default: plain text (same format as before migration — works with all clients)
    return Response(content=plain_content, media_type="text/plain; charset=utf-8")

# Client self-service: view subscription by token
@app.get("/api/client/sub/{token}")
async def client_subscription(token: str):
    users = load_data().get("users", {})
    for uid, user in users.items():
        if user.get("service_token") == token:
            # Check if user is active
            if not user.get("active", True):
                return JSONResponse(status_code=403, content={"error": "Account disabled"})
            # Check if subscription expired
            expire = user.get("expire_date", "")
            if expire:
                try:
                    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                        try:
                            expire_dt = datetime.strptime(expire, fmt)
                            break
                        except ValueError:
                            continue
                    else:
                        expire_dt = None
                    if expire_dt and expire_dt < datetime.now():
                        return JSONResponse(status_code=403, content={"error": "Subscription expired"})
                except Exception:
                    pass
            subs = load_subscriptions()
            sub = None
            for sid, s in subs.items():
                if s.get("uid") == uid:
                    sub = s
                    sub["id"] = sid
            online_status = get_online_status()
            username = user.get("name", uid)
            return {
                "name": username,
                "active": user.get("active", True),
                "expire_date": user.get("expire_date", ""),
                "online": find_online_user(online_status, username).get("online", False),
                "subscription": sub,
                "traffic": {
                    "tx_mb": round(user.get("traffic_saved", {}).get("tx", 0)/1024/1024, 2),
                    "rx_mb": round(user.get("traffic_saved", {}).get("rx", 0)/1024/1024, 2),
                    "total_mb": round((user.get("traffic_saved", {}).get("tx",0)+user.get("traffic_saved", {}).get("rx",0))/1024/1024, 2),
                    "limit_mb": user.get("traffic_limit", 0)
                },
                "plans": load_plans()
            }
    raise HTTPException(status_code=404, detail="Invalid token")

# Check and auto-expire subscriptions
@app.post("/api/subscriptions/check-expiry")
async def check_subscriptions_expiry():
    subs = load_subscriptions()
    now = datetime.now()
    expired = []
    for sid, sub in subs.items():
        if sub.get("status") != "active":
            continue
        try:
            expires = datetime.fromisoformat(sub["expires"])
            if expires < now:
                sub["status"] = "expired"
                expired.append(sid)
                # Deactivate user
                users = load_data().get("users", {})
                uid = sub.get("uid", "")
                if uid in users and not sub.get("auto_renew"):
                    users[uid]["active"] = False
                    save_data({"servers": {}, "users": users})
                add_notification("warning", f"Подписка {sub.get('plan_name','')} для {sub.get('uid','')} истекла")
        except Exception:
            pass
    if expired:
        save_subscriptions(subs)
    return {"expired": len(expired)}

# Auto-deactivate users with expired subscriptions (runs on startup + periodically)
def deactivate_expired_users():
    """Mark users as inactive if their expire_date has passed."""
    users = load_data().get("users", {})
    now = datetime.now()
    deactivated = 0
    for uid, user in users.items():
        if not user.get("active", True):
            continue
        expire = user.get("expire_date", "")
        if not expire:
            continue
        try:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                try:
                    expire_dt = datetime.strptime(expire, fmt)
                    break
                except ValueError:
                    continue
            else:
                continue
            if expire_dt < now:
                users[uid]["active"] = False
                deactivated += 1
        except Exception:
            pass
    if deactivated:
        save_data({"servers": {}, "users": users})
        print(f"[EXPIRY] Deactivated {deactivated} expired users")
    return deactivated

# ===================================================================
# ===== RESOURCE MONITORING =====
# ===================================================================

MONITOR_STATE_FILE = "/opt/freelink/monitor_state.json"

@app.get("/api/monitor/status", summary="Resource monitor status")
async def monitor_status():
    """Returns current resource usage and alert thresholds."""
    info = {}
    try:
        info["cpu_percent"] = psutil.cpu_percent(interval=0.3)
        mem = psutil.virtual_memory()
        info["ram_percent"] = mem.percent
        info["ram_used_gb"] = round(mem.used / (1024**3), 1)
        info["ram_total_gb"] = round(mem.total / (1024**3), 1)
        disk = psutil.disk_usage("/")
        info["disk_percent"] = disk.percent
        info["disk_used_gb"] = round(disk.used / (1024**3), 1)
        info["disk_total_gb"] = round(disk.total / (1024**3), 1)
    except Exception:
        pass
    # Load thresholds
    try:
        with open(MONITOR_STATE_FILE, 'r') as f:
            state = json.load(f)
    except Exception:
        state = {}
    info["thresholds"] = {"cpu_percent": 90, "ram_percent": 85, "disk_percent": 90}
    info["last_alerts"] = {k: v for k, v in state.items() if k.endswith("_alert_time")}
    return info

@app.get("/api/monitor/thresholds")
async def monitor_get_thresholds():
    return {"thresholds": {"cpu_percent": 90, "ram_percent": 85, "disk_percent": 90}}

@app.on_event("startup")
async def startup_event():
    ensure_main_node()
    # Initialize plans.json with defaults if not exists
    if not os.path.exists(PLANS_FILE):
        save_plans([
            {"id": "basic", "name": "Базовый", "days": 30, "traffic_limit_mb": 10240, "price": ""},
            {"id": "pro", "name": "Про", "days": 30, "traffic_limit_mb": 51200, "price": ""},
            {"id": "unlimited", "name": "Безлимит", "days": 30, "traffic_limit_mb": 0, "price": ""}
        ])
        print("[PLANS] Default plans created")
    # Cleanup old connection logs
    cleaned = db.cleanup_old_connections(90)
    if cleaned:
        print(f"[CLEANUP] Removed {cleaned} old connection logs")
    # Deactivate expired users on startup
    deactivated = deactivate_expired_users()
    if deactivated:
        print(f"[EXPIRY] Deactivated {deactivated} expired users on startup")
    # Start background task to check expired users every 5 minutes
    import asyncio
    async def periodic_expiry_check():
        while True:
            await asyncio.sleep(300)  # 5 minutes
            try:
                deactivate_expired_users()
            except Exception as e:
                print(f"[EXPIRY] Error: {e}")
    asyncio.create_task(periodic_expiry_check())

if __name__ == "__main__":
    db.init_db()
    uvicorn.run(app, host="0.0.0.0", port=8000, ws="websockets")
