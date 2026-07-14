# APK Builder Studio - Deployment Guide
> **Live Demo**
> https://apk-maker.duckdns.org/

This guide describes how to install, configure, and run the Personal APK Builder Web Application on an **Ubuntu AWS EC2 server**.

---

## 1. Prerequisites & System Packages

Update your system package list and install basic utility tools:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y curl unzip git python3-pip python3-venv python3-dev build-essential
```

---

## 2. Install Java JDK 17

Android build tools and Gradle require the Java Development Kit (JDK). Install OpenJDK 17:
```bash
sudo apt install -y openjdk-17-jdk openjdk-17-jre
```
Verify the installation:
```bash
java -version
```

---

## 3. Install Android SDK

To build Android projects, we need to install the Android Command Line Tools, SDK platforms, and Build Tools.

### Step 3.1: Create Directory Structure
Create a folder for the Android SDK:
```bash
sudo mkdir -p /usr/lib/android-sdk
sudo chown -R $USER:$USER /usr/lib/android-sdk
```

### Step 3.2: Download Android Command Line Tools
Find the latest package URL for Linux command-line tools on the [Android Developers download page](https://developer.android.com/studio#command-tools) (scroll down to "Command line tools only").

Download and extract it:
```bash
cd ~
wget https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip
unzip commandlinetools-linux-11076708_latest.zip -d cmdline-tools
```

### Step 3.3: Reorganize Directory (Required for SDK Manager)
The SDK manager expects command-line tools to be under a subfolder named `latest`:
```bash
mkdir -p /usr/lib/android-sdk/cmdline-tools/latest
mv cmdline-tools/cmdline-tools/* /usr/lib/android-sdk/cmdline-tools/latest/
rm -rf cmdline-tools commandlinetools-linux-*
```

### Step 3.4: Configure Environment Variables
Open your shell configuration file (e.g., `~/.bashrc`):
```bash
nano ~/.bashrc
```
Add the following lines at the bottom of the file:
```bash
export ANDROID_HOME=/usr/lib/android-sdk
export ANDROID_SDK_ROOT=$ANDROID_HOME
export PATH=$PATH:$ANDROID_HOME/cmdline-tools/latest/bin
export PATH=$PATH:$ANDROID_HOME/platform-tools
export PATH=$PATH:$ANDROID_HOME/emulator
```
Save and close, then reload your shell environment:
```bash
source ~/.bashrc
```

### Step 3.5: Install Android SDK Packages & Licenses
Install the platform tools, specific SDK versions (e.g., API 34), and compilation build tools:
```bash
sdkmanager --update
sdkmanager "platform-tools" "platforms;android-34" "build-tools;34.0.0"
```
Accept all licenses:
```bash
sdkmanager --licenses
```
*(Press `y` and `Enter` for each license agreement prompt).*

---

## 4. Application Setup

Clone or place the Flask project repository on the server (e.g., in `/home/ubuntu/apk-maker`):
```bash
cd /home/ubuntu
git clone <your-repository-url> apk-maker
cd apk-maker
```

### Step 4.1: Create Virtual Environment & Install Dependencies
Create a Python 3 virtual environment and install the required libraries:
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 4.2: Verify Setup Locally
Run the Flask server temporarily to ensure it starts without errors:
```bash
python app.py
```
Press `Ctrl+C` to terminate it once validated.

---

## 5. Production Service Deployment (Gunicorn + Systemd)

For production, we run the Flask application inside Gunicorn using the `gevent` worker class to support non-blocking streaming connections (Server-Sent Events).

### Step 5.1: Create Systemd Service File
Create a new service configuration:
```bash
sudo nano /etc/systemd/system/apkbuilder.service
```
Paste the following configurations into the file:
```ini
[Unit]
Description=APK Builder Flask Application (Gunicorn)
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/apk-maker
Environment="PATH=/home/ubuntu/apk-maker/venv/bin"
Environment="ANDROID_HOME=/usr/lib/android-sdk"
Environment="ANDROID_SDK_ROOT=/usr/lib/android-sdk"
ExecStart=/home/ubuntu/apk-maker/venv/bin/gunicorn --worker-class gevent --workers 1 --threads 4 --bind 127.0.0.1:5000 app:app

[Install]
WantedBy=multi-user.target
```
*Note: Make sure to adjust `User` and directory paths if your configuration differs.*

### Step 5.2: Start and Enable Service
Reload Systemd, start the service, and enable it to run at system startup:
```bash
sudo systemctl daemon-reload
sudo systemctl start apkbuilder
sudo systemctl enable apkbuilder
```
Verify the service status:
```bash
sudo systemctl status apkbuilder
```

---

## 6. Nginx Web Server Configuration

Configure Nginx as a reverse proxy. Crucially, we must disable proxy buffering so that SSE live logs stream in real-time.

### Step 6.1: Install Nginx
```bash
sudo apt install -y nginx
```

### Step 6.2: Create Site Configuration
Create a site configuration file:
```bash
sudo nano /etc/nginx/sites-available/apkbuilder
```
Add the following Nginx server block:
```nginx
server {
    listen 80;
    server_name your-domain.com; # Replace with your EC2 Public IP or Domain Name

    # Max upload limit (matches app.config['MAX_CONTENT_LENGTH'])
    client_max_body_size 150M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Custom rules for SSE streaming logs
    location /stream/ {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        
        # Turn off buffering for live streaming
        proxy_buffering off;
        proxy_cache off;
        
        # Prevent connection timeouts during builds
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        
        # SSE Headers
        proxy_set_header Connection '';
        proxy_http_version 1.1;
        chunked_transfer_encoding off;
    }
}
```

### Step 6.3: Enable Configuration & Restart Nginx
Enable the site, disable default settings (if unused), and restart Nginx:
```bash
sudo ln -s /etc/nginx/sites-available/apkbuilder /etc/nginx/sites-enabled/
sudo rm /etc/nginx/sites-enabled/default
sudo nginx -t # Test configuration syntax
sudo systemctl restart nginx
```

---

## 7. Troubleshooting

- **Check Application Logs**:
  ```bash
  sudo journalctl -u apkbuilder.service -n 50 -f
  ```
- **Check Nginx Access/Error Logs**:
  ```bash
  sudo tail -f /var/log/nginx/error.log
  sudo tail -f /var/log/nginx/access.log
  ```
- **Verify Android SDK Installation**:
  Ensure `/usr/lib/android-sdk` has correct read/write permissions for the application user (`ubuntu`).
