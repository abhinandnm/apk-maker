#!/usr/bin/env bash

# ==============================================================================
# Kuttans App Builder - 1-Click Update Script
# ==============================================================================
# Run this script on your EC2 server whenever you push new changes to GitHub
# Command: sudo ./update.sh
# ==============================================================================

set -e

# Styling
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}====================================================${NC}"
echo -e "${GREEN}      Updating Kuttans App Builder from GitHub      ${NC}"
echo -e "${BLUE}====================================================${NC}"

# Check if running as root or sudo
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}[ERROR] Please run this script with sudo:${NC}"
  echo -e "sudo ./update.sh"
  exit 1
fi

# Determine actual non-root user
ACTUAL_USER=${SUDO_USER:-$USER}
APP_DIR="/home/${ACTUAL_USER}/apk-maker"

if [ -d "${APP_DIR}" ]; then
  cd "${APP_DIR}"
fi

echo -e "${YELLOW}[1/3] Pulling latest changes from GitHub...${NC}"
sudo -u ${ACTUAL_USER} git pull

echo -e "${YELLOW}[2/3] Updating file permissions...${NC}"
chmod +x update.sh

echo -e "${YELLOW}[3/3] Restarting Kuttans App Builder Service...${NC}"
systemctl restart kuttans-builder

echo -e "${GREEN}====================================================${NC}"
echo -e "${GREEN}      UPDATE COMPLETE! Server is now running        ${NC}"
echo -e "${GREEN}      the latest version of your application.       ${NC}"
echo -e "${GREEN}====================================================${NC}"
