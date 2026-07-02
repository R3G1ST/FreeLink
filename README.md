<p align="center">
  <img src="https://img.shields.io/badge/Version-3.10.10-8b5cf6?style=for-the-badge" alt="Version">
  <img src="https://img.shields.io/badge/Status-Alpha-orange?style=for-the-badge" alt="Status">
  <img src="https://img.shields.io/badge/Python-3.10+-3776ab?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Hysteria-2-ff6b35?style=for-the-badge" alt="Hysteria">
  <img src="https://img.shields.io/badge/DB-PostgreSQL-336791?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL">
  <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License">
</p>

<h1 align="center">FreeLink</h1>

<p align="center">
  <b>Multi-server VPN management panel with subscription system</b><br>
  <a href="#features">Features</a> &bull; <a href="#quick-start">Quick Start</a> &bull; <a href="#architecture">Architecture</a> &bull; <a href="#services">Services</a> &bull; <a href="#api">API</a>
</p>

> **ALPHA VERSION** — This project is in active development. APIs, features, and configuration may change without notice.

---

## Features

| Feature | Description |
|---------|-------------|
| **Multi-server** | Main server + unlimited remote nodes via SSH |
| **Subscriptions** | One URL for all servers (Hysteria2, Clash, v2rayN, Happ) |
| **Telegram Bot** | User management, notifications, VPN links |
| **Mini App** | Mobile admin panel for Telegram |
| **Web Panel** | Admin dashboard with real-time metrics |
| **Auto-deploy** | One-click server setup via SSH |
| **Traffic tracking** | Per-user traffic across all nodes (PostgreSQL) |
| **Online detection** | Traffic-change based: compares consecutive snapshots per (user, node) |
| **Plans** | Flexible subscription system with auto-expiry |
| **Speed limits** | Per-user bandwidth control |
| **Auth server** | External Hysteria auth for multi-node setups |
| **Traffic history** | JSON-based charts with period selection |

---

## Quick Start

### Requirements

- Ubuntu 20.04+ / Debian 11+
- Python 3.10+
- PostgreSQL
- Domain with DNS pointing to server
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))

### Installation

```bash
git clone https://github.com/R3G1ST/FreeLink.git /opt/freelink
cd /opt/freelink
chmod +x install.sh
sudo ./install.sh
```

The installer will ask for:
- Domain name
- Server IP
- Telegram Bot Token
- Telegram Admin ID

### After Installation

1. Open `https://your-domain.com`
2. Login: `admin`
3. Password: `admin123`
4. **Change password immediately!**

---

## Update

```bash
cd /opt/freelink
sudo ./update.sh
```

---

## Architecture

```
                         +-----------------+
                         |   Telegram Bot  |
                         |    (bot.py)     |
                         +--------+--------+
                                  |
                         +--------v--------+
                         |    FastAPI       |
          +------------>|    (api.py)      |<------------+
          |             +--------+--------+             |
          |                      |                      |
   +------v------+       +------v------+       +-------v-------+
   |  Auth Server |       |  PostgreSQL  |       |  Online       |
   |  (auth.py)   |       |  (db.py)     |       |  Detector     |
   |  :8001       |       |  snapshots   |       |  (2s poll)    |
   +--------------+       +--------------+       +-------+-------+
          |                      |                      |
   +------v------+       +------v------+       +-------v-------+
   |  Hysteria 2  |       | Node Agent   |       | Traffic Saver |
   |  (main)     |       | (node_agent) |       | (60s poll)    |
   +--------------+       +--------------+       +---------------+
```

### Data Flow (Online Detection)

```
Hysteria API (cumulative tx/rx)
       |
       v (every 2s)
online_detector.py --> PostgreSQL traffic_snapshots
       |
       v
get_online_users() --> Compare rank-1 vs rank-2 per (user, node)
       |               If tx/rx CHANGED => online
       v               Speed = delta_bytes / time_delta (bytes/sec)
api.py get_online_status()
       |
       v
/api/users, /api/online, /ws/live, Telegram Bot
```

---

## Project Structure

```
freelink/
├── api.py                  # FastAPI backend (REST + WebSocket)
├── auth.py                 # External Hysteria auth server
├── bot.py                  # Telegram bot
├── db.py                   # PostgreSQL layer (traffic_snapshots, users, nodes)
├── node_agent.py           # Remote node agent (heartbeat + traffic)
├── online_detector.py      # Online detection (2s poll, traffic-change logic)
├── save_traffic.py         # Traffic recorder (60s poll, durability)
├── traffic_history.py      # Traffic history for charts (5min poll)
├── migrate.py              # DB migration script
├── install.sh              # Installation script
├── update.sh               # Update script
├── start.sh                # Start script
├── requirements.txt        # Python dependencies
├── config.yaml             # Active config
├── config.example.yaml     # Config template
├── admins.json             # Admin accounts
├── nodes.json              # Node registry
├── sessions.json           # User sessions
├── plans.json              # Subscription plans
├── subscriptions.json      # User subscriptions
├── data.yaml               # User data (legacy)
├── data.db                 # SQLite (legacy)
├── traffic_history.json    # Traffic chart data
├── online_status.json      # Online cache (written by detector)
├── web/                    # Frontend
│   ├── index.html          # Admin panel
│   ├── miniapp.html        # Telegram Mini App
│   └── client.html         # Client portal
├── scripts/                # Helper scripts
├── backups/                # Backup directory
├── logs/                   # Log files
└── venv/                   # Python virtualenv
```

---

## Services

| Service | Description | Interval |
|---------|-------------|----------|
| `freelink-api` | Main API + WebSocket server | - |
| `freelink-auth` | External Hysteria auth | - |
| `freelink-bot` | Telegram bot | - |
| `freelink-online` | Online detector (Hysteria poll + DB snapshots) | 2s |
| `freelink-traffic` | Traffic saver (backup durability) | 60s |
| `freelink-history` | Traffic history for charts | 5min |

### Management

```bash
systemctl status freelink-api
systemctl restart freelink-api
journalctl -u freelink-api -f
```

---

## Online Detection

The system determines user online status by comparing consecutive traffic snapshots:

1. **Polling**: Hysteria API returns cumulative `tx`/`rx` for all connected users every 2 seconds
2. **Storage**: Snapshots saved to PostgreSQL `traffic_snapshots` table with `captured_at` timestamp
3. **Comparison**: For each `(user, node)` pair, compare rank-1 and rank-2 snapshots
4. **Decision**: User is online only if `tx` or `rx` **changed** between snapshots
5. **Speed**: Calculated as `delta_bytes / time_delta` in bytes/sec

This handles:
- **Main Hysteria**: Polled every 2s, many snapshots per user
- **Remote nodes**: Heartbeat every ~30s via `node_agent.py`, fewer snapshots
- **Ghost entries**: Users who disconnected but Hysteria still lists with static totals

### API Response

```json
{
  "username": {
    "online": true,
    "tx": 26644909,
    "rx": 890639108,
    "tx_speed": 68,
    "rx_speed": 67,
    "last_active": "2026-07-02T21:32:47.534477",
    "inactive_since": null
  }
}
```

- `tx_speed` / `rx_speed`: bytes/sec (real throughput, not raw delta)
- `last_active`: timestamp of most recent snapshot
- `inactive_since`: set when user stops transferring data (>5 min idle)

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/users` | GET | User list with online, traffic, speed |
| `/api/user/{uid}` | GET | Single user detail |
| `/api/online` | GET | Online status for all users |
| `/api/status` | GET | Dashboard summary |
| `/api/server-info` | GET | System metrics (CPU/RAM/Disk) |
| `/api/live-traffic` | GET | Online users with speed data |
| `/api/traffic-history` | GET | Historical traffic for charts |
| `/api/nodes` | GET | Node list with status |
| `/api/node/heartbeat` | POST | Remote node heartbeat |
| `/api/node/register` | POST | Register new node |
| `/ws/live` | WebSocket | Real-time traffic + online updates |
| `/s/{token}` | GET | Client self-service portal |
| `/api/client/sub/{token}` | GET | Client subscription data |

---

## Roadmap

### High Priority
- [ ] Complete EN/RU translation (remaining modal content)
- [ ] Fix node connectivity issues (UDP firewall handling)
- [ ] Add speed limit enforcement per user
- [ ] Implement traffic history charts with period selection

### Medium Priority
- [ ] Add 2FA authentication for admin panel
- [ ] Implement user session management
- [ ] Add webhook notifications (Discord, Slack)
- [ ] Create REST API documentation (Swagger/OpenAPI)
- [ ] Implement user groups and bulk operations

### Low Priority
- [ ] Add more languages (Chinese, Spanish, Portuguese)
- [ ] Create mobile app (React Native / Flutter)
- [ ] Implement bandwidth monitoring dashboard
- [ ] Add geo-location based server selection
- [ ] Create backup/restore functionality
- [ ] Add system resource alerts (CPU/RAM/Disk thresholds)

---

## License

[MIT License](LICENSE)

---

<p align="center">
  Made with care for the VPN community
</p>
