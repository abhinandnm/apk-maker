#!/usr/bin/env bash

# ==============================================================================
# Kuttans App Builder - Auto-Update Setup Script
# ==============================================================================
# This script configures a background cron job that checks GitHub every minute.
# If it detects new code, it automatically pulls and restarts the server.
# ==============================================================================

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

if [ "$EUID" -ne 0 ]; then
  echo -e "Please run with sudo: sudo ./setup_autoupdate.sh"
  exit 1
fi

ACTUAL_USER=${SUDO_USER:-$USER}
APP_DIR="/home/${ACTUAL_USER}/apk-maker"

echo -e "${YELLOW}Creating auto-updater script...${NC}"

cat << 'EOF' > /usr/local/bin/kuttans-auto-update.sh
#!/usr/bin/env bash
APP_DIR="APP_DIR_PLACEHOLDER"
ACTUAL_USER="USER_PLACEHOLDER"

cd ${APP_DIR}
sudo -u ${ACTUAL_USER} git fetch origin main

LOCAL=$(sudo -u ${ACTUAL_USER} git rev-parse HEAD)
REMOTE=$(sudo -u ${ACTUAL_USER} git rev-parse origin/main)

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "Changes detected on GitHub! Updating server..."
    sudo -u ${ACTUAL_USER} git pull origin main
    chmod +x update.sh
    systemctl restart kuttans-builder
fi
EOF

# Replace placeholders
sed -i "s|APP_DIR_PLACEHOLDER|${APP_DIR}|g" /usr/local/bin/kuttans-auto-update.sh
sed -i "s|USER_PLACEHOLDER|${ACTUAL_USER}|g" /usr/local/bin/kuttans-auto-update.sh
chmod +x /usr/local/bin/kuttans-auto-update.sh

echo -e "${YELLOW}Adding to system crontab...${NC}"

# Remove existing cron job if it exists to avoid duplicates
crontab -l | grep -v '/usr/local/bin/kuttans-auto-update.sh' | crontab - || true

# Add new cron job to run every minute
(crontab -l 2>/dev/null; echo "* * * * * /usr/local/bin/kuttans-auto-update.sh >> /var/log/kuttans-autoupdate.log 2>&1") | crontab -

echo -e "${GREEN}====================================================${NC}"
echo -e "${GREEN}  Auto-Updater is LIVE! 🚀${NC}"
echo -e "${GREEN}  Your EC2 server will now automatically pull and   ${NC}"
echo -e "${GREEN}  apply any new changes pushed to GitHub within     ${NC}"
echo -e "${GREEN}  60 seconds.                                       ${NC}"
echo -e "${GREEN}====================================================${NC}"
