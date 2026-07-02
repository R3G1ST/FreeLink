#!/bin/bash
# Скрипт бэкапа FreeLink

BACKUP_DIR="/opt/freelink/backups"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/backup_$DATE.tar.gz"

# Создаём бэкап
tar -czf "$BACKUP_FILE" \
    /opt/freelink/data.yaml \
    /opt/freelink/config.yaml \
    /etc/hysteria/config.yaml \
    /etc/letsencrypt/live/link.qmbox.ru/ \
    2>/dev/null

# Удаляем бэкапы старше 7 дней
find "$BACKUP_DIR" -name "backup_*.tar.gz" -mtime +7 -delete

echo "Backup created: $BACKUP_FILE"
