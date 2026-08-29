@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$script=Join-Path (Get-Location) 'scripts\firewall-sync.ps1'; $action=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -File "' + $script + '"'); $trigger=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1); Register-ScheduledTask -TaskName 'Swarm Agent Firewall Sync' -Action $action -Trigger $trigger -RunLevel Highest -Force"
if errorlevel 1 pause
