#!/bin/bash
set -e

# ============================================
# Hysteria 2 VPN Panel - Install Script
# ============================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Hysteria 2 VPN Panel Installer${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Check root
if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}Error: Run as root (sudo ./install.sh)${NC}"
    exit 1
fi

# Collect configuration
echo -e "${YELLOW}Enter configuration:${NC}"
read -p "Domain (e.g. vpn.example.com): " DOMAIN
read -p "Server IP: " SERVER_IP
read -p "Telegram Bot Token: " TG_TOKEN
read -p "Telegram Admin ID: " TG_ADMIN
read -p "Panel port [8000]: " PANEL_PORT
PANEL_PORT=${PANEL_PORT:-8000}

echo ""
echo -e "${GREEN}Installing dependencies...${NC}"
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv nginx certbot curl git

echo -e "${GREEN}Cloning project...${NC}"
if [ -d "/opt/vpnbot" ]; then
    echo "Directory /opt/vpnbot exists, updating..."
    cd /opt/vpnbot
    git pull
else
    git clone https://github.com/R3G1ST/FreeLink.git /opt/vpnbot
    cd /opt/vpnbot
fi

echo -e "${GREEN}Setting up Python environment...${NC}"
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt -q

echo -e "${GREEN}Generating obfs password...${NC}"
OBFS_PASS=$(openssl rand -hex 16)

echo -e "${GREEN}Creating config...${NC}"
cat > /opt/vpnbot/config.yaml << EOF
domain: "${DOMAIN}"
server_ip: "${SERVER_IP}"
obfs_password: "${OBFS_PASS}"

telegram:
  token: "${TG_TOKEN}"
  admins:
    - ${TG_ADMIN}

hysteria:
  port: 443
  config_path: "/etc/hysteria/config.yaml"
EOF

echo -e "${GREEN}Setting up SSL certificate...${NC}"
# Check if cert already exists
if [ ! -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]; then
    certbot certonly --nginx -d ${DOMAIN} --non-interactive --agree-tos --email admin@${DOMAIN} || {
        echo -e "${YELLOW}Certbot failed, using self-signed cert...${NC}"
        mkdir -p /etc/hysteria/certs
        openssl req -x509 -nodes -newkey rsa:2048 \
            -keyout /etc/hysteria/certs/privkey.pem \
            -out /etc/hysteria/certs/fullchain.pem \
            -subj "/CN=${DOMAIN}" -days 3650
    }
fi

echo -e "${GREEN}Configuring Nginx...${NC}"
cat > /etc/nginx/sites-available/vpnbot << EOF
server {
    listen 80;
    server_name ${DOMAIN};
    return 301 https://\$server_name\$request_uri;
}

server {
    listen 443 ssl http2;
    server_name ${DOMAIN};

    ssl_certificate /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    charset utf-8;

    add_header Cache-Control "no-cache, no-store, must-revalidate, max-age=0" always;

    location / {
        proxy_pass http://127.0.0.1:${PANEL_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_cache off;
        proxy_read_timeout 360s;
    }

    location /web/ {
        alias /opt/vpnbot/web/;
        charset utf-8;
    }
}
EOF

ln -sf /etc/nginx/sites-available/vpnbot /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo -e "${GREEN}Creating systemd services...${NC}"

# API service
cat > /etc/systemd/system/vpnbot-api.service << EOF
[Unit]
Description=VPNBot API
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/vpnbot
ExecStart=/opt/vpnbot/venv/bin/python3 api.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Auth service
cat > /etc/systemd/system/vpnbot-auth.service << EOF
[Unit]
Description=VPNBot Auth
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/vpnbot
ExecStart=/opt/vpnbot/venv/bin/python3 auth.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Bot service
cat > /etc/systemd/system/vpnbot-bot.service << EOF
[Unit]
Description=VPNBot Telegram Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/vpnbot
ExecStart=/opt/vpnbot/venv/bin/python3 bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Online detector
cat > /etc/systemd/system/vpnbot-online.service << EOF
[Unit]
Description=VPNBot Online Detector
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/vpnbot
ExecStart=/opt/vpnbot/venv/bin/python3 online_detector.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Traffic recorder
cat > /opt/vpnbot/traffic_recorder.py << 'EOF'
#!/opt/vpnbot/venv/bin/python3
import requests, yaml, time, json, os

DATA_FILE = '/opt/vpnbot/data.yaml'
HISTORY_FILE = '/opt/vpnbot/traffic_history.json'
HYSTERIA_API = 'http://127.0.0.1:9999/traffic'

def record():
    try:
        r = requests.get(HYSTERIA_API, timeout=3)
        if r.status_code != 200:
            return
        traffic = r.json()

        with open(DATA_FILE, 'r') as f:
            data = yaml.safe_load(f) or {}

        users = data.get('users', {})
        for uid, user in users.items():
            name = user.get('name', uid)
            if name in traffic:
                t = traffic[name]
                user['traffic_saved'] = {
                    'tx': t.get('tx', 0),
                    'rx': t.get('rx', 0),
                    'total_mb': round((t.get('tx', 0) + t.get('rx', 0)) / 1024 / 1024, 2),
                    'updated': time.strftime('%Y-%m-%d %H:%M:%S')
                }

        with open(DATA_FILE, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

        # Save history
        history = []
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r') as f:
                history = json.load(f)

        entry = {
            'time': time.strftime('%Y-%m-%d %H:%M'),
            'users': {name: {'tx': t.get('tx', 0), 'rx': t.get('rx', 0)} for name, t in traffic.items()}
        }
        history.append(entry)
        history = history[-2880:]  # Keep ~2 days

        with open(HISTORY_FILE, 'w') as f:
            json.dump(history, f)

    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    print("Traffic recorder started (every 60s)")
    while True:
        record()
        time.sleep(60)
EOF

cat > /etc/systemd/system/vpnbot-traffic.service << EOF
[Unit]
Description=VPNBot Traffic Recorder
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/vpnbot
ExecStart=/opt/vpnbot/venv/bin/python3 traffic_recorder.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo -e "${GREEN}Starting services...${NC}"
systemctl daemon-reload
systemctl enable vpnbot-api vpnbot-auth vpnbot-bot vpnbot-online vpnbot-traffic
systemctl start vpnbot-api vpnbot-auth vpnbot-bot vpnbot-online vpnbot-traffic

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Installation complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "Panel URL: ${YELLOW}https://${DOMAIN}${NC}"
echo -e "Admin login: ${YELLOW}admin${NC}"
echo -e "Admin password: ${YELLOW}admin123${NC}"
echo ""
echo -e "${YELLOW}Change admin password after first login!${NC}"
echo ""
echo -e "Services status:"
systemctl is-active vpnbot-api && echo -e "  ${GREEN}✓${NC} API" || echo -e "  ${RED}✗${NC} API"
systemctl is-active vpnbot-auth && echo -e "  ${GREEN}✓${NC} Auth" || echo -e "  ${RED}✗${NC} Auth"
systemctl is-active vpnbot-bot && echo -e "  ${GREEN}✓${NC} Bot" || echo -e "  ${RED}✗${NC} Bot"
