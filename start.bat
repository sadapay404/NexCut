@echo off
title Sheikh Arsalan Automation - Clip Studio
cd /d "%~dp0"
echo.
echo   Sheikh Arsalan Automation - Clip Studio
echo   ---------------------------------------
echo   Starting the studio... keep this window open.
echo.
start "" http://localhost:8137
python -m nexcut.server
if errorlevel 1 (
  echo.
  echo   Python was not found. Install Python 3.10+ from python.org,
  echo   tick "Add python.exe to PATH", then run this file again.
  pause
)
