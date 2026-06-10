@echo off
REM ============================================================================
REM Windows Deploy Script - Copy backend to VPS and run setup
REM ============================================================================
REM Pre-configured for: algotradeai.net
REM VPS IP: 70.34.215.33
REM
REM Instructions:
REM 1. Make sure your VPS is running (Ubuntu 22.04, IP: 70.34.215.33)
REM 2. Double-click this file to run it
REM 3. Enter your VPS root password when prompted
REM ============================================================================

setlocal

REM --- CONFIGURATION: DO NOT EDIT ---
set VPS_IP=70.34.215.33
set VPS_USER=root

REM Path to your local backend folder
set LOCAL_BACKEND=C:\Users\adaga\OneDrive\Desktop\MT5\backend
set REMOTE_PATH=/opt/mt5-bot/

echo ==============================================
echo   Deploying Backend to VPS
echo   VPS IP: %VPS_IP%
echo ==============================================
echo.

REM Check if PSCP is available, if not use scp (Git Bash)
where pscp >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set SCP_CMD=pscp -r
) else (
    echo Trying scp command...
    set SCP_CMD=scp -r
)

echo [1/2] Copying backend files to VPS...
%SCP_CMD% "%LOCAL_BACKEND%" %VPS_USER%@%VPS_IP%:%REMOTE_PATH%

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Failed to copy files. Make sure:
    echo   - VPS_IP is correct in this file
    echo   - You can connect to the VPS
    echo   - If using pscp, download it from: https://www.chiark.greenend.org.uk/~sgtatham/putty/latest.html
    pause
    exit /b 1
)

echo.
echo [2/2] Files copied successfully!
echo.
echo ==============================================
echo   NEXT STEPS:
echo ==============================================
echo.
echo 1. Connect to your VPS using PuTTY
echo    Host: %VPS_IP%
echo    Login: root
echo    Password: (from your VPS provider email)
echo.
echo 2. Run the setup script:
echo    cd /opt/mt5-bot
echo    bash setup-vps.sh
echo.
echo 3. Wait for setup to complete (about 5-10 minutes)
echo.
echo 4. Visit https://api.algotradeai.net/api/health to test
echo.
pause
endlocal
