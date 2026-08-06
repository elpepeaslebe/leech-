@echo off
echo ========================================
echo   WMan Leech - Public Server
echo ========================================
echo.
echo Starting backend on http://localhost:8000
echo.

cd /d "%~dp0"

REM Start backend in background
start "Leech Backend" /MIN python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

REM Wait for backend to be ready
echo Waiting for backend to start...
timeout /t 3 /nobreak >nul

REM Start cloudflare tunnel (show URL for sharing)
echo Starting Cloudflare Tunnel...
echo.
echo ========================================
echo   SHARE THIS URL WITH OTHERS:
echo ========================================
echo.

"C:\Users\bebey\cloudflared.exe" tunnel --url http://localhost:8000

