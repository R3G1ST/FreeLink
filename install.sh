#!/bin/bash
# FreeLink VPN Panel — Full Installation Script v3.15.0-aurora
# Supports: Main Server + Remote Nodes
# Protocols: Hysteria2 + WireGuard + VLESS(Xray) + Shadowsocks

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err() { echo -e "${RED}[✗]${NC} $1"; exit 1; }
info() { echo -e "${BLUE}[i]${NC} $1"; }

# ==================== DETECT MODE ====================
if [ -f "/opt/freelink/api.py" ]; then
    MODE="update"
    info "Обнаружена существующая установка — режим обновления"
else
    MODE="install"
    info "Новая установка FreeLink"
fi

echo ""
echo "=========================================="
echo "  FreeLink VPN Panel — $([ "$MODE" = "install" ] && echo "Установка" || echo "Обновление")"
echo "=========================================="
echo ""

# ==================== SYSTEM DEPENDENCIES ====================
install_deps() {
    log "Установка системных зависимостей..."
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        python3 python3-pip python3-venv \
        postgresql postgresql-client \
        nginx certbot python3-certbot-nginx \
        wireguard wireguard-tools \
        curl wget git openssl \
        > /dev/null 2>&1
    log "Системные зависимости установлены"
}

# ==================== INSTALL HYSTERIA ====================
install_hysteria() {
    if command -v hysteria &> /dev/null; then
        log "Hysteria уже установлен"
        return
    fi
    log "Установка Hysteria 2..."
    bash <(curl -fsSL https://get.hy2.sh/) 2>/dev/null
    log "Hysteria установлен: $(hysteria version 2>/dev/null | head -1)"
}

# ==================== INSTALL XRAY ====================
install_xray() {
    if command -v xray &> /dev/null; then
        log "Xray уже установлен"
        return
    fi
    log "Установка Xray..."
    bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ 2>/dev/null
    log "Xray установлен: $(xray version 2>/dev/null | head -1)"
}

# ==================== CONFIGURE WIREGUARD ====================
configure_wireguard() {
    log "Настройка WireGuard..."
    mkdir -p /etc/wireguard

    if [ ! -f /etc/wireguard/server.key ]; then
        wg genkey | tee /etc/wireguard/server.key | wg pubkey > /etc/wireguard/server.pub
        log "WireGuard ключи сгенерированы"
    fi

    SERVER_PRIVKEY=$(cat /etc/wireguard/server.key)
    SERVER_PUBKEY=$(cat /etc/wireguard/server.pub)
    MAIN_IF=$(ip route | grep default | awk '{print $5}' | head -1)

    cat > /etc/wireguard/wg0.conf << EOF
[Interface]
Address = 10.10.0.1/24
ListenPort = 51820
PrivateKey = ${SERVER_PRIVKEY}
PostUp = iptables -A FORWARD -i wg0 -j ACCEPT; iptables -t nat -A POSTROUTING -o ${MAIN_IF} -j MASQUERADE
PostDown = iptables -D FORWARD -i wg0 -j ACCEPT; iptables -t nat -D POSTROUTING -o ${MAIN_IF} -j MASQUERADE
EOF

    echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/wireguard.conf
    sysctl -p /etc/sysctl.d/wireguard.conf > /dev/null 2>&1

    systemctl enable wg-quick@wg0 2>/dev/null
    systemctl restart wg-quick@wg0 2>/dev/null
    log "WireGuard настроен: $SERVER_PUBKEY"
}

# ==================== CONFIGURE XRAY ====================
configure_xray() {
    log "Настройка Xray VLESS+WS + Shadowsocks..."
    KEYS=$(xray x25519 2>/dev/null)
    PRIVKEY=$(echo "$KEYS" | grep "PrivateKey" | awk '{print $2}')
    PUBKEY=$(echo "$KEYS" | grep "PublicKey" | awk '{print $2}')
    SS_PASS=$(python3 -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())")

    cat > /usr/local/etc/xray/config.json << EOF
{
    "log": {"loglevel": "warning", "access": "/var/log/xray/access.log", "error": "/var/log/xray/error.log"},
    "inbounds": [
        {
            "listen": "127.0.0.1", "port": 10001, "protocol": "vless",
            "settings": {"clients": [], "decryption": "none"},
            "streamSettings": {"network": "ws", "wsSettings": {"path": "/vless"}},
            "sniffing": {"enabled": true, "destOverride": ["http", "tls"]}
        },
        {
            "listen": "0.0.0.0", "port": 8388, "protocol": "shadowsocks",
            "settings": {"method": "aes-256-gcm", "password": "${SS_PASS}", "network": "tcp,udp"},
            "tag": "shadowsocks"
        }
    ],
    "outbounds": [{"protocol": "freedom", "tag": "direct"}, {"protocol": "blackhole", "tag": "block"}],
    "routing": {"domainStrategy": "AsIs", "rules": [{"type": "field", "ip": ["geoip:private"], "outboundTag": "block"}]}
}
EOF

    systemctl enable xray 2>/dev/null
    systemctl restart xray 2>/dev/null
    log "Xray настроен: VLESS(10001) + SS(8388)"
    echo "$PUBKEY" > /tmp/xray_pubkey.txt
    echo "$SS_PASS" > /tmp/ss_password.txt
}

# ==================== CONFIGURE HYSTERIA ====================
configure_hysteria() {
    log "Настройка Hysteria 2..."
    OBFS_PASS=$(openssl rand -hex 16)

    cat > /etc/hysteria/config.yaml << EOF
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
    password: "${OBFS_PASS}"
trafficStats:
  listen: 127.0.0.1:9999
quic:
  disablePathMTUDiscovery: true
EOF

    mkdir -p /etc/hysteria/certs
    log "Hysteria настроен (obfs password: $OBFS_PASS)"
    echo "$OBFS_PASS" > /tmp/hysteria_obfs.txt
}

# ==================== CONFIGURE NGINX ====================
configure_nginx() {
    log "Настройка Nginx..."
    DOMAIN=${DOMAIN:-"link.qmbox.ru"}

    cat > /etc/nginx/sites-enabled/freelink << EOF
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
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    charset utf-8;
    add_header Cache-Control "no-cache, no-store, must-revalidate, max-age=0" always;
    add_header X-Frame-Options "ALLOWALL" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    location /vless {
        proxy_pass http://127.0.0.1:10001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_read_timeout 360s;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_cache off;
        proxy_read_timeout 360s;
    }

    location /web/ {
        alias /opt/freelink/web/;
        charset utf-8;
        default_type text/html;
    }
}
EOF

    rm -f /etc/nginx/sites-enabled/default
    nginx -t 2>/dev/null && systemctl reload nginx
    log "Nginx настроен"
}

# ==================== SETUP SSL ====================
setup_ssl() {
    DOMAIN=${DOMAIN:-"link.qmbox.ru"}
    if [ -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]; then
        log "SSL сертификат уже существует"
        return
    fi
    log "Получение SSL сертификата..."
    certbot certonly --nginx -d ${DOMAIN} --non-interactive --agree-tos --email admin@${DOMAIN} 2>/dev/null
    log "SSL сертификат получен"
}

# ==================== SETUP DATABASE ====================
setup_database() {
    log "Настройка PostgreSQL..."
    systemctl enable postgresql 2>/dev/null
    systemctl start postgresql 2>/dev/null

    sudo -u postgres psql -c "CREATE USER freelink WITH PASSWORD 'freelink_pass';" 2>/dev/null || true
    sudo -u postgres psql -c "CREATE DATABASE freelink_db OWNER freelink;" 2>/dev/null || true
    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE freelink_db TO freelink;" 2>/dev/null || true
    log "База данных настроена"
}

# ==================== SETUP FREELINK ====================
setup_freelink() {
    log "Настройка FreeLink..."
    mkdir -p /opt/freelink

    if [ ! -f /opt/freelink/.env ]; then
        TG_TOKEN=${TG_TOKEN:-""}
        DOMAIN=${DOMAIN:-"link.qmbox.ru"}
        cat > /opt/freelink/.env << EOF
PG_HOST=localhost
PG_DB=freelink_db
PG_USER=freelink
PG_PASS=freelink_pass
PG_PORT=5432
DOMAIN=${DOMAIN}
TELEGRAM_TOKEN=${TG_TOKEN}
TELEGRAM_ADMIN_IDS=
HYSTERIA_OBFS_PASSWORD=$([ -f /tmp/hysteria_obfs.txt ] && cat /tmp/hysteria_obfs.txt || echo "")
API_TOKEN=$(openssl rand -hex 32)
EOF
        chmod 600 /opt/freelink/.env
        log ".env создан"
    fi

    # Python venv
    if [ ! -d /opt/freelink/venv ]; then
        python3 -m venv /opt/freelink/venv
        /opt/freelink/venv/bin/pip install -q fastapi uvicorn psycopg2-binary pyyaml requests bcrypt qrcode python-multipart 2>/dev/null
        log "Python venv создан"
    fi

    log "FreeLink настроен"
}

# ==================== SETUP SYSTEMD ====================
setup_systemd() {
    log "Настройка systemd сервисов..."

    cat > /etc/systemd/system/freelink-api.service << EOF
[Unit]
Description=FreeLink API
After=network.target postgresql.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/freelink
EnvironmentFile=/opt/freelink/.env
ExecStart=/opt/freelink/venv/bin/python3 /opt/freelink/api.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    cat > /etc/systemd/system/freelink-bot.service << EOF
[Unit]
Description=FreeLink Telegram Bot
After=network.target postgresql.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/freelink
EnvironmentFile=/opt/freelink/.env
ExecStart=/opt/freelink/venv/bin/python3 /opt/freelink/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable freelink-api freelink-bot 2>/dev/null
    systemctl restart freelink-api freelink-bot 2>/dev/null
    log "Systemd сервисы настроены"
}

# ==================== SETUP FIREWALL ====================
setup_firewall() {
    log "Настройка фаервола..."
    ufw allow 22/tcp 2>/dev/null
    ufw allow 80/tcp 2>/dev/null
    ufw allow 443/tcp 2>/dev/null
    ufw allow 443/udp 2>/dev/null
    ufw allow 8388/tcp 2>/dev/null
    ufw allow 8388/udp 2>/dev/null
    ufw allow 51820/udp 2>/dev/null
    ufw --force enable 2>/dev/null
    log "Фаервол настроен"
}

# ==================== NODE SETUP ====================
setup_node() {
    NODE_IP=$1
    NODE_PASS=$2
    NODE_NAME=${3:-"Node"}
    MAIN_SS_PASS=${4:-""}

    info "Настройка ноды: $NODE_NAME ($NODE_IP)"

    sshpass -p "$NODE_PASS" ssh -o StrictHostKeyChecking=no root@$NODE_IP "
        # Install deps
        apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq wireguard wireguard-tools curl openssl > /dev/null 2>&1

        # Install Xray
        bash -c \"\$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)\" @ 2>/dev/null

        # Install Hysteria
        bash <(curl -fsSL https://get.hy2.sh/) 2>/dev/null

        # Install nginx
        apt-get install -y -qq nginx > /dev/null 2>&1

        # Generate WireGuard keys
        mkdir -p /etc/wireguard
        wg genkey | tee /etc/wireguard/server.key | wg pubkey > /etc/wireguard/server.pub
        WG_PRIVKEY=\$(cat /etc/wireguard/server.key)

        # Configure WireGuard
        cat > /etc/wireguard/wg0.conf << WGEOF
[Interface]
Address = 10.10.1.1/24
ListenPort = 51820
PrivateKey = \${WG_PRIVKEY}
PostUp = iptables -A FORWARD -i wg0 -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i wg0 -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE

[Peer]
PublicKey = $(cat /etc/wireguard/server.pub 2>/dev/null || echo "PENDING")
Endpoint = ${DOMAIN:-link.qmbox.ru}:51820
AllowedIPs = 10.10.0.0/32, 10.10.0.1/32
PersistentKeepalive = 25
WGEOF

        echo 'net.ipv4.ip_forward=1' > /etc/sysctl.d/wireguard.conf
        sysctl -p /etc/sysctl.d/wireguard.conf > /dev/null 2>&1
        systemctl enable wg-quick@wg0 2>/dev/null
        systemctl start wg-quick@wg0 2>/dev/null

        # Generate Xray keys and config
        KEYS=\$(xray x25519 2>/dev/null)
        XRAY_PRIVKEY=\$(echo \"\$KEYS\" | grep PrivateKey | awk '{print \$2}')
        XRAY_PUBKEY=\$(echo \"\$KEYS\" | grep PublicKey | awk '{print \$2}')
        echo \"\$XRAY_PUBKEY\" > /tmp/xray_pubkey_node.txt

        # Use same SS password as main server
        SS_PASS=\"${MAIN_SS_PASS}\"

        cat > /usr/local/etc/xray/config.json << XRAYEOF
{
    \"log\": {\"loglevel\": \"warning\"},
    \"inbounds\": [
        {
            \"listen\": \"127.0.0.1\", \"port\": 10001, \"protocol\": \"vless\",
            \"settings\": {\"clients\": [], \"decryption\": \"none\"},
            \"streamSettings\": {\"network\": \"ws\", \"wsSettings\": {\"path\": \"/vless\"}},
            \"sniffing\": {\"enabled\": true, \"destOverride\": [\"http\", \"tls\"]}
        },
        {
            \"listen\": \"0.0.0.0\", \"port\": 8388, \"protocol\": \"shadowsocks\",
            \"settings\": {\"method\": \"aes-256-gcm\", \"password\": \"\${SS_PASS}\", \"network\": \"tcp,udp\"},
            \"tag\": \"shadowsocks\"
        }
    ],
    \"outbounds\": [{\"protocol\": \"freedom\", \"tag\": \"direct\"}],
    \"routing\": {\"rules\": [{\"type\": \"field\", \"ip\": [\"geoip:private\"], \"outboundTag\": \"direct\"}]}
}
XRAYEOF
        systemctl enable xray 2>/dev/null
        systemctl start xray 2>/dev/null

        # SSL cert (from main server or self-signed)
        mkdir -p /etc/ssl/xray
        openssl req -x509 -nodes -days 3650 -newkey rsa:2048 -keyout /etc/ssl/xray/server.key -out /etc/ssl/xray/server.crt -subj '/CN=${DOMAIN:-link.qmbox.ru}' 2>/dev/null

        # Configure nginx for VLESS WS
        cat > /etc/nginx/sites-enabled/default << NGINXEOF
server {
    listen 443 ssl;
    server_name ${DOMAIN:-link.qmbox.ru};
    ssl_certificate /etc/ssl/xray/server.crt;
    ssl_certificate_key /etc/ssl/xray/server.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    location /vless {
        proxy_pass http://127.0.0.1:10001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \\\$http_upgrade;
        proxy_set_header Connection \"upgrade\";
        proxy_set_header Host \\\$host;
        proxy_read_timeout 360s;
    }
}
NGINXEOF
        systemctl enable nginx 2>/dev/null
        systemctl restart nginx 2>/dev/null

        # Firewall
        ufw allow 443/tcp 2>/dev/null
        ufw allow 443/udp 2>/dev/null
        ufw allow 8388/tcp 2>/dev/null
        ufw allow 8388/udp 2>/dev/null
        ufw allow 51820/udp 2>/dev/null

        echo \"NODE_COMPLETE:WG_PUB=\$(cat /etc/wireguard/server.pub):XRAY_PUB=\$XRAY_PUBKEY\"
    " 2>/dev/null

    log "Нода $NODE_NAME настроена"
}

# ==================== MAIN ====================
case "${1:-install}" in
    install)
        install_deps
        install_hysteria
        install_xray
        setup_database
        setup_freelink
        setup_ssl
        configure_hysteria
        configure_xray
        configure_wireguard
        configure_nginx
        setup_systemd
        setup_firewall

        echo ""
        echo "=========================================="
        log "Установка завершена!"
        echo "=========================================="
        info "Панель: https://${DOMAIN:-link.qmbox.ru}"
        info "WG ключ: $(cat /etc/wireguard/server.pub)"
        info "Xray ключ: $(cat /tmp/xray_pubkey.txt 2>/dev/null || echo 'см. /tmp/xray_pubkey.txt')"
        echo ""
        ;;

    node)
        if [ -z "$2" ] || [ -z "$3" ]; then
            err "Использование: $0 node <IP> <SSH_PASSWORD> [имя_ноды] [ss_password]"
        fi
        DOMAIN=${DOMAIN:-"link.qmbox.ru"}
        MAIN_SS_PASS=${5:-""}
        if [ -z "$MAIN_SS_PASS" ] && [ -f /tmp/ss_password.txt ]; then
            MAIN_SS_PASS=$(cat /tmp/ss_password.txt)
        fi
        setup_node "$2" "$3" "${4:-Node}" "$MAIN_SS_PASS"
        ;;

    update)
        log "Обновление FreeLink..."
        setup_freelink
        systemctl restart freelink-api freelink-bot 2>/dev/null
        log "Обновление завершено"
        ;;

    *)
        echo "Использование:"
        echo "  $0 install          — Полная установка на сервер"
        echo "  $0 node IP PASS     — Настройка удалённой ноды"
        echo "  $0 update           — Обновление FreeLink"
        echo ""
        echo "Переменные окружения:"
        echo "  DOMAIN=link.qmbox.ru  — Домен сервера"
        echo "  TG_TOKEN=...          — Токен Telegram бота"
        ;;
esac
