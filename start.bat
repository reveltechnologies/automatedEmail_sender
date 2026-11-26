@echo off
rem Double-click this file to open the email sender page in your browser.
rem It runs straight from this folder, so nothing needs to be installed.
rem Keep the black window open while you use the page; close it to stop.

cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "PYTHONUNBUFFERED=1"

python -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul
if errorlevel 1 (
    echo Python 3.11 or newer is needed. Get it from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" during setup.
    pause
    exit /b 1
)

if not exist ".env" (
    echo Note: there is no .env file yet, so sending is switched off.
    echo You can still edit the list and preview emails. See docs\Usage.md to set it up.
    echo.
)

python -m email_sender ui %*
if errorlevel 1 pause
