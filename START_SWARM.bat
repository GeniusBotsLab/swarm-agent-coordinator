@echo off
setlocal
cd /d "%~dp0"
set "PATH=%PATH%;C:\Program Files\Docker\Docker\resources\bin"
docker compose up -d
if errorlevel 1 pause
