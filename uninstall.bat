@echo off
setlocal
set "DST=%LOCALAPPDATA%\TeleMonitor"

if exist "%DST%\telemonitor.exe" start /wait "" "%DST%\telemonitor.exe" --uninstall
taskkill /f /im telemonitor.exe >nul 2>&1
timeout /t 1 >nul
if exist "%DST%" rmdir /s /q "%DST%"
echo Da go cai dat.
pause
