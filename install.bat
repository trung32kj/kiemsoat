@echo off
setlocal
set "SRC=%~dp0"
set "DST=%LOCALAPPDATA%\TeleMonitor"

if not exist "%SRC%dist\telemonitor.exe" (
  echo Chua co dist\telemonitor.exe. Chay build.bat truoc.
  pause
  exit /b 1
)

if not exist "%DST%" mkdir "%DST%"
copy /y "%SRC%dist\telemonitor.exe" "%DST%\telemonitor.exe" >nul

if not exist "%DST%\config.json" (
  if exist "%SRC%config.json" (
    copy /y "%SRC%config.json" "%DST%\config.json" >nul
  ) else (
    copy /y "%SRC%config.example.json" "%DST%\config.json" >nul
    echo Da tao %DST%\config.json - hay dien bot_token, chat_id, device_name.
  )
)

taskkill /f /im telemonitor.exe >nul 2>&1
start /wait "" "%DST%\telemonitor.exe" --install
timeout /t 1 >nul
start "" "%DST%\telemonitor.exe"
echo.
echo Da cai vao %DST% va bat tu khoi dong.
pause
