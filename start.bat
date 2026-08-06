@echo off
echo ========================================
echo   Leech - Open Source AI Gateway
echo ========================================
echo.

cd /d "%~dp0"

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
