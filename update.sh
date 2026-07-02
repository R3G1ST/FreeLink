#!/bin/bash
set -e

# ============================================
# Hysteria 2 VPN Panel - Update Script
# ============================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Hysteria 2 VPN Panel Updater${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Check root
if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}Error: Run as root (sudo ./update.sh)${NC}"
    exit 1
fi

cd /opt/freelink

echo -e "${YELLOW}Current version:${NC}"
grep -o "VERSION = .*" api.py 2>/dev/null || echo "Unknown"

echo ""
echo -e "${GREEN}Pulling latest changes...${NC}"
git stash 2>/dev/null || true
git pull origin main
git stash pop 2>/dev/null || true

echo -e "${GREEN}Updating Python dependencies...${NC}"
source venv/bin/activate
pip install -r requirements.txt -q

echo -e "${GREEN}Restarting services...${NC}"
systemctl restart freelink-api freelink-auth freelink-bot freelink-online freelink-traffic

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Update complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "New version:"
grep -o "VERSION = .*" api.py 2>/dev/null || echo "Unknown"
echo ""
echo -e "Services status:"
systemctl is-active freelink-api && echo -e "  ${GREEN}✓${NC} API" || echo -e "  ${RED}✗${NC} API"
systemctl is-active freelink-auth && echo -e "  ${GREEN}✓${NC} Auth" || echo -e "  ${RED}✗${NC} Auth"
systemctl is-active freelink-bot && echo -e "  ${GREEN}✓${NC} Bot" || echo -e "  ${RED}✗${NC} Bot"
