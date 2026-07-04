#!/bin/bash
set -e

# ============================================
# FreeLink v3.12.0-aurora — Update Script
# ============================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  FreeLink Updater${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Check root
if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}Error: Run as root (sudo ./update.sh)${NC}"
    exit 1
fi

cd /opt/freelink

# Show current version
echo -e "${YELLOW}Current version:${NC}"
cat VERSION 2>/dev/null || echo "Unknown"

# ============================================
# 1. Create backup before update
# ============================================
echo -e "\n${GREEN}[1/5]${NC} Creating backup..."
BACKUP_DIR="/opt/freelink/backups"
mkdir -p "$BACKUP_DIR"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/pre_update_${DATE}.tar.gz"

# PostgreSQL dump
PG_PASS=$(grep PG_PASS /opt/freelink/.env 2>/dev/null | cut -d= -f2)
PG_USER=$(grep PG_USER /opt/freelink/.env 2>/dev/null | cut -d= -f2)
PG_DB=$(grep PG_DB /opt/freelink/.env 2>/dev/null | cut -d= -f2)
if [ -n "$PG_PASS" ]; then
    PGPASSWORD="$PG_PASS" pg_dump -h 127.0.0.1 -U "$PG_USER" "$PG_DB" > /tmp/freelink_update_dump.sql 2>/dev/null || true
fi

# Create backup archive
tar -czf "$BACKUP_FILE" \
    api.py bot.py db.py auth.py migrate.py node_agent.py online_detector.py \
    resource_monitor.py speed_limiter.py traffic_history.py save_traffic.py \
    config.yaml .env .gitignore requirements.txt VERSION \
    web/ scripts/ \
    admins.json nodes.json plans.json sessions.json subscriptions.json \
    data.yaml \
    -C /tmp freelink_update_dump.sql 2>/dev/null || true

rm -f /tmp/freelink_update_dump.sql
echo -e "  ${GREEN}✓${NC} Backup: $BACKUP_FILE"

# ============================================
# 2. Pull latest changes
# ============================================
echo -e "\n${GREEN}[2/5]${NC} Pulling latest changes..."
git stash 2>/dev/null || true
git pull origin main
git stash pop 2>/dev/null || true
echo -e "  ${GREEN}✓${NC} Code updated"

# ============================================
# 3. Update dependencies
# ============================================
echo -e "\n${GREEN}[3/5]${NC} Updating Python dependencies..."
source venv/bin/activate
pip install -r requirements.txt -q 2>/dev/null
deactivate
echo -e "  ${GREEN}✓${NC} Dependencies updated"

# ============================================
# 4. Run migrations if needed
# ============================================
echo -e "\n${GREEN}[4/5]${NC} Running migrations..."
source venv/bin/activate
python3 -c "
import sys; sys.path.insert(0, '/opt/freelink')
import db
db.init_db()
print('Database schema updated')
" 2>/dev/null || echo -e "  ${YELLOW}⚠ Migration skipped${NC}"
deactivate
echo -e "  ${GREEN}✓${NC} Migrations complete"

# ============================================
# 5. Restart services
# ============================================
echo -e "\n${GREEN}[5/5]${NC} Restarting services..."
systemctl daemon-reload

for SVC in api auth bot online traffic history monitor; do
    systemctl restart freelink-${SVC} 2>/dev/null && \
        echo -e "  ${GREEN}✓${NC} freelink-${SVC}" || \
        echo -e "  ${RED}✗${NC} freelink-${SVC}"
done

# ============================================
# Done
# ============================================
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Update complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "New version: ${GREEN}$(cat VERSION 2>/dev/null || echo 'Unknown')${NC}"
echo ""
