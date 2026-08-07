@echo off
echo ========================================
echo   Leech - Open Source AI Gateway
echo ========================================
echo.

cd /d "%~dp0"

REM ===== Kill old instances first =====
echo Stopping old instances...
taskkill /FI "WINDOWTITLE eq Tor Daemon*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Leech Backend*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Leech Frontend*" /F >nul 2>&1
taskkill /IM cloudflared.exe /F >nul 2>&1
taskkill /IM tor.exe /F >nul 2>&1
timeout /t 2 /nobreak >nul
echo Old instances stopped.
echo.

REM ===== CONFIGURATION =====
REM Change this to YOUR Tor Browser path:
set "TOR_EXE=C:\Users\YOUR_USERNAME\Desktop\Tor Browser\Browser\TorBrowser\Tor\tor.exe"
set "TOR_DATA=%~dp0tor_data"
REM ==========================

REM ===== Start Tor =====
if exist "%TOR_EXE%" (
    echo [1/3] Starting Tor...
    if not exist "%TOR_DATA%" mkdir "%TOR_DATA%"
    start "Tor Daemon" /MIN "%TOR_EXE%" --SocksPort 9050 --ControlPort 9051 --CookieAuthentication 1 --DataDirectory "%TOR_DATA%"
    
    echo Waiting for Tor to bootstrap...
    :wait_tor
    timeout /t 2 /nobreak >nul
    netstat -an | findstr ":9050" | findstr "LISTENING" >nul 2>&1
    if errorlevel 1 goto wait_tor
    echo Tor ready!
) else (
    echo [!] Tor not found at: %TOR_EXE%
    echo     Skipping Tor...
)
echo.

REM ===== Start Backend =====
echo [2/3] Starting backend on http://localhost:8000...
start "Leech Backend" /MIN python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
timeout /t 3 /nobreak >nul
echo Backend ready!
echo.

REM ===== Start Cloudflare Tunnel =====
echo [3/3] Starting Cloudflare Tunnel...
echo.
echo ========================================
echo   SHARE THIS URL WITH OTHERS:
echo ========================================
echo.

cloudflared tunnel --url http://localhost:8000
