@echo off
title AI Market Intelligence Backend Server (GCP Production)
echo Starting AI Market Intelligence Backend Server for GCP (0.0.0.0)...
cd /d "%~dp0"

set PYTHONPATH=backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
pause
