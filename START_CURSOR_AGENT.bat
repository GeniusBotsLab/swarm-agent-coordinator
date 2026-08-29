@echo off
setlocal
cd /d "%~dp0"
if not defined SWARM_URL if not defined SWARM_BASE_URL (
  echo Set SWARM_URL or SWARM_BASE_URL and SWARM_AGENT_KEY
  pause
  exit /b 1
)
if not defined CURSOR_WORKSPACE set "CURSOR_WORKSPACE=%CD%"
python adapters\cursor_worker.py
if errorlevel 1 pause
