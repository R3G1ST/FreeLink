<p align="center">
  <img src="https://img.shields.io/badge/Version-3.15.0--aurora-8b5cf6?style=for-the-badge" alt="Version">
  <img src="https://img.shields.io/badge/Status-Beta-green?style=for-the-badge" alt="Status">
  <img src="https://img.shields.io/badge/Python-3.10+-3776ab?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Multi--Protocol-4-ff6b35?style=for-the-badge" alt="Protocols">
  <img src="https://img.shields.io/badge/DB-PostgreSQL-336791?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL">
  <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License">
</p>

<h1 align="center">FreeLink</h1>

<p align="center">
  <b>Multi-protocol VPN management panel with subscription system</b><br>
  <small>Hysteria2 • WireGuard • VLESS • Shadowsocks</small><br><br>
  <a href="#english"><img src="https://img.shields.io/badge/English-blue?style=for-the-badge" alt="English"></a>
  <a href="#русский"><img src="https://img.shields.io/badge/Русский-red?style=for-the-badge" alt="Русский"></a>
</p>

---

<a id="english"></a>

# English

> **BETA** — Active development. APIs and features may change.

## Features

| Feature | Description |
|---------|-------------|
| **Multi-protocol** | Hysteria2 + WireGuard + VLESS + Shadowsocks in one subscription |
| **Multi-server** | Main server + unlimited remote nodes |
| **Subscriptions** | Single URL with all protocols across all nodes |
| **Telegram Bot** | User management, protocol selection, VPN links |
| **Mini App** | Mobile admin panel (PWA) for Telegram |
| **Web Panel** | Admin dashboard with real-time metrics |
| **Auto-deploy** | One-click server + node setup via SSH |
| **Traffic tracking** | Per-user traffic across all nodes |
| **Online detection** | Traffic-change based monitoring |
| **Plans** | Subscription plans with auto-expiry |
| **Speed limits** | Per-user bandwidth control |
| **Backups** | Create, restore, download backups |

### Protocols

| Protocol | Transport | Port | Clients |
|----------|-----------|------|---------|
| **Hysteria2** | UDP + obfs | 443 | Hiddify, Clash, v2rayN, NekoBox |
| **WireGuard** | UDP | 51820 | All WireGuard clients |
| **VLESS** | WS + TLS | 443 (nginx) | V2rayNG, NekoBox, Streisand, Hiddify |
| **Shadowsocks** | TCP/UDP | 8388 | Clash, v2rayN, NekoBox, V2rayNG, Hiddify |

Users can enable multiple protocols simultaneously. Subscription auto-includes all enabled protocols across online nodes with country labels.

---

## Quick Start

### Requirements
- Ubuntu 20.04+ / Debian 11+
- Python 3.10+
- PostgreSQL
- Domain with DNS → server
- Telegram Bot Token (from @BotFather)

### Install Main Server
```bash
git clone https://github.com/R3G1ST/FreeLink.git /opt/freelink
cd /opt/freelink
sudo DOMAIN=link.qmbox.ru TG_TOKEN=your_token ./install.sh install
```

### Add Remote Node
```bash
sudo ./install.sh node 217.147.15.11 root_password "Latvia"
```

### Update
```bash
sudo ./install.sh update
```

---

## Architecture

```
                    ┌─────────────────┐
                    │   Telegram Bot  │
                    │    (bot.py)     │
                    └────────┬────────┘
                             │
                    ┌────────v────────┐
                    │     FastAPI      │
     ┌──────────────│    (api.py)     │──────────────┐
     │              └────────┬────────┘              │
     │                       │                       │
┌────v─────┐          ┌──────v──────┐         ┌──────v──────┐
│ WireGuard│          │  PostgreSQL  │         │    Xray     │
│  :51820  │          │   (db.py)    │         │ VLESS :10001│
│          │          │              │         │ SS    :8388 │
└────┬─────┘          └──────┬──────┘         └──────┬──────┘
     │                       │                       │
     │              ┌────────v────────┐              │
     │              │   Hysteria 2    │              │
     │              │     :443 UDP    │              │
     │              └────────┬────────┘              │
     │                       │                       │
┌────v───────────────────────v───────────────────────v────┐
│                     Nginx :443                           │
│           Panel + VLESS WS Proxy + SSL                   │
└─────────────────────────────────────────────────────────┘
```

## Services

| Service | Protocol | Port | Description |
|---------|----------|------|-------------|
| `freelink-api` | TCP | 8000 | FastAPI backend |
| `freelink-bot` | - | - | Telegram bot |
| `hysteria-server` | UDP | 443 | Hysteria2 VPN |
| `xray` | TCP | 10001 (local) | VLESS+WS + Shadowsocks |
| `wg-quick@wg0` | UDP | 51820 | WireGuard VPN |
| `nginx` | TCP | 443 | Panel + VLESS proxy |

## Project Structure

```
freelink/
├── api.py              # FastAPI backend (REST + WebSocket)
├── bot.py              # Telegram bot (user CRUD, protocol selection)
├── db.py               # PostgreSQL layer
├── wireguard.py        # WireGuard management (keys, peers, configs)
├── xray.py             # Xray management (VLESS, Shadowsocks)
├── auth.py             # External Hysteria auth server
├── node_agent.py       # Remote node heartbeat + traffic
├── online_detector.py  # Online detection (2s poll)
├── install.sh          # Full install + node setup
├── config.yaml         # Panel config
├── .env                # Secrets (not in git)
├── web/
│   ├── index.html      # Admin panel (full features)
│   ├── miniapp.html    # Telegram Mini App (PWA)
│   └── client.html     # Client portal
└── venv/               # Python virtualenv
```

## API Endpoints (Key)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/user/create?protocols=hysteria2,wireguard,vless,shadowsocks` | POST | Create user with protocols |
| `/api/user/{uid}/protocols?protocols=...` | POST | Change user protocols |
| `/sub/{token}` | GET | Subscription (all protocols, all nodes) |
| `/api/wireguard/status` | GET | WireGuard status |
| `/api/wireguard/sync` | POST | Sync WireGuard peers |
| `/api/wireguard/config/{uid}` | GET | User WireGuard config |

## Changelog

### v3.15.0-aurora (2026-07-05)

**Multi-Protocol Support:**
- Shadowsocks (aes-256-gcm, port 8388)
- WireGuard (port 51820, per-user keys, per-node keys)
- VLESS+WS+TLS (port 443 via nginx)
- Multiple protocols per user simultaneously

**Multi-Node:**
- WireGuard: per-node key pairs
- VLESS: shared UUID, per-node endpoints
- Shadowsocks: shared password, per-node config
- Subscription: all protocols × all online nodes

**Frontend:**
- Protocol checkboxes (create + user card)
- Links modal with protocol/country groups + QR
- Splash screen, PWA, SVG logo
- Bottom navigation (mobile)

**Backend:**
- `wireguard.py` — WireGuard management
- `xray.py` — VLESS + Shadowsocks management
- `db.py` — protocols, wg_*, vless_*, ss_* columns
- Subscription generates links for all protocols and nodes

**Infrastructure:**
- Xray: VLESS+WS on :10001 proxied by nginx on :443
- Shadowsocks: direct on :8388
- WireGuard: :51820, subnets 10.10.0.0/24 + 10.10.1.0/24
- Install script: server + node setup with SS sync

### v3.13.0-nexus (2026-07-04)

- Hysteria2 multi-node support
- Admin panel with full CRUD
- Telegram bot with conversation handlers
- Online detection via traffic snapshots
- Traffic history charts
- Backup system

---

## License

[MIT License](LICENSE)

---

<p align="center">Made with care for the VPN community</p>
