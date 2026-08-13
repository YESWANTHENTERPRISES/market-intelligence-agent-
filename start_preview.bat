@echo off
title AI Market Intelligence Web Preview
echo Starting Frontend Web Preview Server...
cd /d "%~dp0extension"
npx vite --host 0.0.0.0 --port 5173
pause
