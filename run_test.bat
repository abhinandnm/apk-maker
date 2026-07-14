@echo off
title APK Builder Studio Test Launcher
echo =================================================================
echo   Starting APK Builder Studio Test Environment (Windows)
echo =================================================================

:: Check for Python or Py launcher
set PY_CMD=
python --version >nul 2>&1
if %errorlevel% equ 0 (
    set PY_CMD=python
    goto python_found
)

py --version >nul 2>&1
if %errorlevel% equ 0 (
    set PY_CMD=py
    goto python_found
)

echo [ERROR] Python was not found in your system PATH.
echo.
echo To fix this:
echo 1. Make sure Python is installed. If not, download it from:
echo    https://www.python.org/downloads/
echo.
echo 2. IMPORTANT: When installing Python, make sure to check the box
echo    that says "Add Python to PATH" at the bottom of the installer window.
echo.
echo 3. If you installed it from the Microsoft Store, make sure
echo    "python" is enabled in Windows Settings ^> Apps ^> Advanced app settings
echo    ^> App execution aliases.
echo.
pause
exit /b 1

:python_found
echo [SYSTEM] Found Python environment. (Using command: %PY_CMD%)

:: Create virtual environment if it does not exist
if not exist venv (
    echo [SYSTEM] Virtual environment not found. Creating 'venv'...
    %PY_CMD% -m venv venv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

:: Activate the virtual environment
echo [SYSTEM] Activating virtual environment...
call venv\Scripts\activate.bat

:: Install/Upgrade dependencies
echo [SYSTEM] Restoring packages from requirements.txt...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install python dependencies.
    pause
    exit /b 1
)

:: Open the browser in the background
echo [SYSTEM] Launching default web browser to http://127.0.0.1:5000...
start http://127.0.0.1:5000

:: Start the Flask app
echo [SYSTEM] Starting server...
echo -----------------------------------------------------------------
echo   * Server is running!
echo   * Press Ctrl+C in this terminal window to stop the application.
echo -----------------------------------------------------------------
python app.py

pause
