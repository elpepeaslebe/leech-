@echo off
echo ========================================
echo   Leech - Open Source AI Gateway
echo ========================================
echo.

cd /d "%~dp0"

REM ===== CONFIGURATION =====
REM Change this to YOUR Tor Browser path:
set "TOR_EXE=C:\Users\YOUR_USERNAME\Desktop\Tor Browser\Browser\TorBrowser\Tor\tor.exe"
REM ==========================

REM Start Tor if tor.exe exists
if exist "%TOR_EXE%" (
    echo Starting Tor...
    set "DATA=%~dp0tor_data"
    if not exist "%DATA%" mkdir "%DATA%"
    start "Tor Daemon" /MIN "%TOR_EXE%" --SocksPort 9050 --ControlPort 9051 --CookieAuthentication 1 --DataDirectory "%DATA%"
    echo Waiting for Tor to bootstrap...
    timeout /t 10 /nobreak >nul
) else (
    echo [!] Tor not found at: %TOR_EXE%
    echo     Skipping Tor. Set TOR_EXE in start.bat to enable.
    echo.
)

REM Start backend in background
echo Starting backend on http://localhost:8000...
start "Leech Backend" /MIN python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

REM Wait for backend to be ready
echo Waiting for backend to start...
timeout /t 3 /nobreak >nul

REM Start cloudflare tunnel
echo Starting Cloudflare Tunnel...
echo.
echo ========================================
echo   SHARE THIS URL WITH OTHERS:
echo ========================================
echo.

cloudflared tunnel --url http://localhost:8000
