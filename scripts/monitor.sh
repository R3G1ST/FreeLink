#!/bin/bash
# Мониторинг VPNBot

LOG="/opt/vpnbot/logs/monitor.log"
mkdir -p /opt/vpnbot/logs

# Проверка Hysteria
if ! systemctl is-active --quiet hysteria-server; then
    echo "$(date): Hysteria down, restarting..." >> $LOG
    systemctl restart hysteria-server
fi

# Проверка API
if ! systemctl is-active --quiet vpnbot-api; then
    echo "$(date): API down, restarting..." >> $LOG
    systemctl restart vpnbot-api
fi

# Проверка, что API отвечает
if ! curl -s -f http://127.0.0.1:8000/ > /dev/null; then
    echo "$(date): API not responding, restarting..." >> $LOG
    systemctl restart vpnbot-api
fi

