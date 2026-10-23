@echo off
setlocal
set "DST=%LOCALAPPDATA%\TeleMonitor"

echo [1/3] Tat tu khoi dong...
if exist "%DST%\telemonitor.exe" (
  start /wait "" "%DST%\telemonitor.exe" --uninstall
) else (
  reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v TeleMonitor /f >nul 2>&1
)

echo [2/3] Dung tien trinh...
taskkill /f /im telemonitor.exe >nul 2>&1
timeout /t 2 >nul

echo [3/3] Xoa thu muc...
if exist "%DST%" rmdir /s /q "%DST%"

echo.
echo Da go cai dat.
pause
