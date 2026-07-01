# Hysteria 2 VPN Panel

Multi-server VPN management panel with subscription system, Telegram bot, and client support.

## Features

- **Multi-server management** — main server + unlimited remote nodes
- **Subscription URLs** — one link for all servers (Hysteria, Clash, v2rayN, Happ)
- **Telegram Bot** — user management, notifications, VPN links
- **Web Admin Panel** — dashboard, user management, traffic monitoring
- **Telegram Mini App** — mobile panel for iOS/Android
- **Auto-deploy nodes** — one-click server setup via SSH
- **Traffic tracking** — per-user traffic across all nodes
- **Online detection** — real-time user status
- **Plans & Subscriptions** — flexible subscription system

## Quick Start

```bash
git clone https://github.com/YOUR/vpnbot.git /opt/vpnbot
cd /opt/vpnbot
chmod +x install.sh
./install.sh
```

## Requirements

- Ubuntu 20.04+ / Debian 11+
- Python 3.10+
- Domain with DNS pointing to server
- Telegram Bot Token (from @BotFather)

## Update

```bash
cd /opt/vpnbot
./update.sh
```

## License

MIT
