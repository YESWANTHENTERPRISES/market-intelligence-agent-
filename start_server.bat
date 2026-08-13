@echo off
title AI Market Intelligence Backend Server
echo Starting AI Market Intelligence Backend Server...
cd /d "%~dp0"

:: Check if server is already running on port 8000
netstat -ano | findstr :8000 >nul 2>&1
if %errorlevel%==0 (
    echo [INFO] Backend server is ALREADY running live on http://127.0.0.1:8000!
    echo You do not need to start it again. Your extension is already connected!
    echo.
    pause
    exit /b 0
)

set PYTHONPATH=backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
