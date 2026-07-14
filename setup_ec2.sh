#!/usr/bin/env bash

# ==============================================================================
# Kuttans App Builder - 1-Click EC2 Ubuntu Deployment Script
# ==============================================================================
# Supported OS: Ubuntu 22.04 LTS / 24.04 LTS
# Run: curl -sL https://raw.githubusercontent.com/.../setup_ec2.sh | bash
# Or upload and run: chmod +x setup_ec2.sh && ./setup_ec2.sh
# ==============================================================================

set -e

# Styling
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}====================================================${NC}"
echo -e "${GREEN}      Starting Kuttans App Builder Setup on EC2     ${NC}"
echo -e "${BLUE}====================================================${NC}"

# Check if running as root or sudo
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}[ERROR] Please run this script with sudo or as root:${NC}"
  echo -e "sudo ./setup_ec2.sh"
  exit 1
fi

# Determine the actual non-root user who called sudo
ACTUAL_USER=${SUDO_USER:-$USER}
USER_HOME=$(eval echo ~$ACTUAL_USER)

echo -e "${BLUE}[1/8] Updating system package index...${NC}"
apt-get update && apt-get upgrade -y
apt-get install -y python3 python3-pip python3-venv unzip git openjdk-21-jdk wget curl

# Setup Swap Memory (3GB) to protect against Out-Of-Memory (OOM) errors during Gradle builds
echo -e "${BLUE}[2/8] Setting up 3GB Swap Memory for build safety...${NC}"
if [ ! -f /swapfile ]; then
    fallocate -l 3G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    echo -e "${GREEN}[SUCCESS] 3GB Swap memory configured.${NC}"
else
    echo -e "${YELLOW}[INFO] Swap file already exists. Skipping creation.${NC}"
fi

# Install Gradle 9.6.1
echo -e "${BLUE}[3/8] Installing Gradle 9.6.1...${NC}"
if [ ! -d /opt/gradle/gradle-9.6.1 ]; then
    mkdir -p /opt/gradle
    wget -q https://services.gradle.org/distributions/gradle-9.6.1-bin.zip -O /tmp/gradle-9.6.1-bin.zip
    unzip -q -d /opt/gradle /tmp/gradle-9.6.1-bin.zip
    rm -f /tmp/gradle-9.6.1-bin.zip
    ln -sf /opt/gradle/gradle-9.6.1/bin/gradle /usr/bin/gradle
    echo -e "${GREEN}[SUCCESS] Gradle 9.6.1 installed to /opt/gradle and symlinked.${NC}"
else
    echo -e "${YELLOW}[INFO] Gradle 9.6.1 already installed. Skipping.${NC}"
fi

# Install Android SDK
echo -e "${BLUE}[4/8] Installing Android SDK Command-line Tools...${NC}"
SDK_DIR="${USER_HOME}/android-sdk"
mkdir -p "${SDK_DIR}/cmdline-tools"

if [ ! -d "${SDK_DIR}/cmdline-tools/latest" ]; then
    wget -q https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip -O /tmp/cmdline-tools.zip
    unzip -q -d "${SDK_DIR}/cmdline-tools" /tmp/cmdline-tools.zip
    rm -f /tmp/cmdline-tools.zip
    mv "${SDK_DIR}/cmdline-tools/cmdline-tools" "${SDK_DIR}/cmdline-tools/latest"
    chown -R ${ACTUAL_USER}:${ACTUAL_USER} "${SDK_DIR}"
    echo -e "${GREEN}[SUCCESS] Command-line tools installed.${NC}"
else
    echo -e "${YELLOW}[INFO] Android Command-line tools already installed. Skipping.${NC}"
fi

# Setup Environment variables in .bashrc for the user
echo -e "${BLUE}[5/8] Configuring environment variables...${NC}"
BASHRC="${USER_HOME}/.bashrc"
if ! grep -q "ANDROID_HOME" "${BASHRC}"; then
    echo "export ANDROID_HOME=${SDK_DIR}" >> "${BASHRC}"
    echo "export PATH=\$PATH:${SDK_DIR}/cmdline-tools/latest/bin:${SDK_DIR}/platform-tools" >> "${BASHRC}"
    echo "export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64" >> "${BASHRC}"
    echo -e "${GREEN}[SUCCESS] Environment variables written to ${BASHRC}.${NC}"
else
    echo -e "${YELLOW}[INFO] Environment variables already set in ${BASHRC}. Skipping.${NC}"
fi

# Export variables locally for script usage
export ANDROID_HOME="${SDK_DIR}"
export PATH="$PATH:${SDK_DIR}/cmdline-tools/latest/bin:${SDK_DIR}/platform-tools"
export JAVA_HOME="/usr/lib/jvm/java-21-openjdk-amd64"

# Install SDK Components
echo -e "${BLUE}[6/8] Accepting licenses and installing Android Platform SDK 35...${NC}"
# Use sudo -u to run as the actual user so files don't become root-owned
sudo -u ${ACTUAL_USER} -E "${SDK_DIR}/cmdline-tools/latest/bin/sdkmanager" --licenses <<EOF
yes
yes
yes
yes
yes
yes
EOF

sudo -u ${ACTUAL_USER} -E "${SDK_DIR}/cmdline-tools/latest/bin/sdkmanager" "platform-tools" "platforms;android-35" "build-tools;35.0.0"
echo -e "${GREEN}[SUCCESS] Android SDK Platform 35 components installed.${NC}"

# Python requirements and Virtual Environment setup
echo -e "${BLUE}[7/8] Configuring Python virtual environment and dependencies...${NC}"
APP_DIR="$(pwd)"
if [ -f "${APP_DIR}/app.py" ]; then
    sudo -u ${ACTUAL_USER} python3 -m venv "${APP_DIR}/venv"
    sudo -u ${ACTUAL_USER} "${APP_DIR}/venv/bin/pip" install --upgrade pip
    sudo -u ${ACTUAL_USER} "${APP_DIR}/venv/bin/pip" install -r "${APP_DIR}/requirements.txt"
    sudo -u ${ACTUAL_USER} "${APP_DIR}/venv/bin/pip" install gunicorn
    echo -e "${GREEN}[SUCCESS] Virtual environment and dependencies installed successfully.${NC}"
else
    echo -e "${YELLOW}[WARNING] No app.py found in current directory. Python venv config skipped.${NC}"
fi

# Create Systemd Service to keep app running
echo -e "${BLUE}[8/8] Installing systemd service for automatic execution...${NC}"
SERVICE_FILE="/etc/systemd/system/kuttans-builder.service"
cat <<EOF > "${SERVICE_FILE}"
[Unit]
Description=Kuttans App Builder Production Daemon
After=network.target

[Service]
User=${ACTUAL_USER}
WorkingDirectory=${APP_DIR}
Environment="PATH=${APP_DIR}/venv/bin:/opt/gradle/gradle-9.6.1/bin:/usr/lib/jvm/java-21-openjdk-amd64/bin:/usr/bin:/usr/local/bin"
Environment="ANDROID_HOME=${SDK_DIR}"
Environment="JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64"
ExecStart=${APP_DIR}/venv/bin/gunicorn -w 2 --timeout 3600 -b 0.0.0.0:5000 app:app
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable kuttans-builder.service
systemctl restart kuttans-builder.service

echo -e "${GREEN}====================================================${NC}"
echo -e "${GREEN}      DEPLOYMENT COMPLETE SUCCESSFULLY!             ${NC}"
echo -e "${GREEN}====================================================${NC}"
echo -e "Your Kuttans App Builder is now running in production mode."
echo -e "Web App URL: http://$(curl -s ifconfig.me):5000"
echo -e "You can manage the application status using:"
echo -e "  - Start:   sudo systemctl start kuttans-builder"
echo -e "  - Stop:    sudo systemctl stop kuttans-builder"
echo -e "  - Restart: sudo systemctl restart kuttans-builder"
echo -e "  - Logs:    journalctl -u kuttans-builder -n 100 -f"
echo -e "${BLUE}====================================================${NC}"
