# FreeLink Security Fixes - Implementation Report

**Date:** 2026-07-04  
**Status:** Phase 1 Complete (Critical Issues)

---

## Summary

Implemented critical security fixes for FreeLink VPN management panel. All changes maintain backward compatibility.

---

## Changes Made

### 1. Secrets Migration to Environment Variables

**Files Modified:**
- `config.yaml` - Removed all secrets (Telegram token, Hysteria passwords, server IP)
- `db.py` - Database credentials now read from env vars, fail if missing
- `api.py` - Added python-dotenv, reads secrets from env vars
- `bot.py` - Added python-dotenv, reads Telegram token from env vars
- `.env.example` - New file with all required environment variables
- `.gitignore` - Already includes .env and config.yaml

**New Environment Variables:**
```
TELEGRAM_TOKEN
TELEGRAM_ADMIN_IDS
HYSTERIA_USER_PASSWORD
HYSTERIA_OBFS_PASSWORD
PG_HOST, PG_PORT, PG_DB, PG_USER, PG_PASS
API_TOKEN
SERVER_IP
DOMAIN
ALLOWED_ORIGINS
SSH_ENCRYPTION_KEY
```

---

### 2. Password Hashing Upgrade

**Files Modified:**
- `api.py` - Replaced SHA-256 with bcrypt (12 rounds)
- `migrate.py` - Updated to use bcrypt

**New Functions:**
- `hash_pw(pw)` - Hash password with bcrypt
- `verify_pw(pw, hashed)` - Verify password against bcrypt hash
- `is_legacy_hash(hashed)` - Detect old SHA-256 hashes

**Migration Notes:**
- Old SHA-256 hashes will still work via verify_pw (backward compatible)
- New passwords are hashed with bcrypt
- Run password migration script to convert old hashes

---

### 3. CORS Configuration

**Files Modified:**
- `api.py` - CORS restricted to allowed origins from env var

**Changes:**
- `allow_origins` now reads from `ALLOWED_ORIGINS` env var
- Removed hardcoded `Access-Control-Allow-Origin: *` headers
- Added `allow_credentials=True`

---

### 4. API Authentication

**Files Modified:**
- `api.py` - Critical endpoints now require authentication

**Endpoints Now Protected:**
- `/api/online` - Online status
- `/api/server-info` - Server metrics
- `/api/traffic-history` - Traffic data
- `/api/services` - Service status
- `/api/nodes` - Node listing (was exposing SSH passwords!)
- `/api/subscriptions` - Subscription data
- `/api/live-traffic` - Live traffic data
- `/api/notifications` - Notifications
- `/api/qr/` - QR codes (was exposing VPN passwords!)
- `/api/geo/` - GeoIP lookup
- `/api/client/` - Client portal
- `/api/node/` - Node operations
- `/api/user/gen-service-token/` - Token generation

**Endpoints Still Public:**
- `/api/status` - Basic status (minimal info)
- `/api/version` - Version info
- `/api/plans` - Subscription plans (read-only)

---

### 5. WebSocket Authentication

**Files Modified:**
- `api.py` - WebSocket now requires session token

**Changes:**
- WebSocket endpoint `/ws/live` now validates session token
- Token passed via query parameter: `?token=xxx`
- Connection rejected with code 4001 if unauthorized

---

### 6. TLS Certificate Protection

**Files Modified:**
- `api.py` - `/api/node/cert` now requires node token

**Changes:**
- Endpoint now validates node token before serving certificates
- Prevents unauthorized download of TLS private keys

---

### 7. Rate Limiting

**Files Modified:**
- `api.py` - Added slowapi rate limiting
- `requirements.txt` - Added slowapi dependency

**Rate Limits Applied:**
- `/api/login` - 5 requests/minute
- `/api/miniapp/login` - 5 requests/minute
- `/form-login` - 5 requests/minute

---

### 8. Cookie Security

**Files Modified:**
- `api.py` - All cookies now use secure flags

**Changes:**
- Added `secure=True` to all set_cookie calls
- Changed `samesite="none"` to `samesite="lax"`

---

## Dependencies Added

```
python-dotenv>=1.0.0
bcrypt>=4.0.0
slowapi>=0.1.8
cryptography>=41.0.0
```

---

## Migration Steps

### 1. Create .env file
```bash
cp .env.example .env
# Edit .env with your actual values
```

### 2. Install new dependencies
```bash
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Restart services
```bash
systemctl restart freelink-api freelink-bot
```

### 4. (Optional) Migrate old password hashes
```bash
python3 migrate_passwords.py
```

---

## Remaining Work (Phase 2)

- [ ] SSH password encryption at rest
- [ ] 2FA implementation
- [ ] Systemd service hardening (User=freelink)
- [ ] Nginx security headers
- [ ] SQL injection fix in update_user_field

---

## Testing

After implementation, verify:

1. **Authentication:**
   - All protected endpoints return 401 without session
   - WebSocket rejects connections without token
   - Rate limiting returns 429 after 5 attempts

2. **CORS:**
   - Requests from unauthorized origins blocked
   - Legitimate origin works correctly

3. **Secrets:**
   - No secrets in config.yaml
   - All secrets loaded from .env
   - .env not committed to git

4. **Cookies:**
   - Secure flag present on all cookies
   - SameSite set to "lax"

---

## Security Improvements

| Issue | Before | After |
|-------|--------|-------|
| Password Hashing | SHA-256 (no salt) | bcrypt (12 rounds) |
| CORS | Allow all origins | Restricted to allowed origins |
| API Auth | 15+ open endpoints | All sensitive endpoints protected |
| WebSocket | No auth | Session token required |
| TLS Keys | Public endpoint | Node token required |
| Rate Limiting | None | 5 req/min on login |
| Cookies | Insecure | Secure + SameSite |
| Secrets | Hardcoded | Environment variables |

---

**Author:** MiMoCode  
**Version:** 1.0  
**License:** MIT
