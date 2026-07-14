# APK Builder Studio - Deployment Guide

**Live:** https://apk-maker.duckdns.org/

This guide explains how to install, configure, and deploy **APK Builder Studio** on an **Ubuntu AWS EC2 instance**. After completing these steps, your server will be ready to build Android applications into APK files through the web interface.

---

## 1. Update the System

Update the package index and upgrade existing packages:

```bash
sudo apt update && sudo apt upgrade -y
```

Install the required dependencies:

```bash
sudo apt install -y \
curl \
unzip \
git \
python3-pip \
python3-venv \
python3-dev \
build-essential
```
 2q
---

## 2. Install Java Development Kit (JDK 17)

Android Gradle builds require Java. Install **OpenJDK 17**:

```bash
sudo apt install -y openjdk-17-jdk openjdk-17-jre
```

Verify the installation:

```bash
java -version
```

Expected output:

```text
openjdk version "17.x.x"
```

---

## 3. Install the Android SDK

The Android SDK provides the tools required to build Android applications.

In the next steps, you will:

- Download the Android Command Line Tools
- Configure the Android SDK location
- Install the required SDK platforms and Build Tools
- Accept the Android SDK licenses

Once completed, the server will be fully configured to compile Android projects into APK files.
