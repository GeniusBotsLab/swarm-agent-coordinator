@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Unregister-ScheduledTask -TaskName 'Swarm Agent Firewall Sync' -Confirm:$false -ErrorAction SilentlyContinue; Remove-NetFirewallRule -DisplayName 'Swarm Agent API 8443' -ErrorAction SilentlyContinue"
