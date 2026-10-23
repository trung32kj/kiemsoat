@echo off
setlocal
set "SRC=%~dp0"
set "DST=%LOCALAPPDATA%\TeleMonitor"

if not exist "%SRC%dist\telemonitor.exe" (
  echo [LOI] Chua co dist\telemonitor.exe. Chay build.bat truoc.
  pause
  exit /b 1
)

echo [1/5] Dung ban dang chay (neu co)...
taskkill /f /im telemonitor.exe >nul 2>&1
timeout /t 1 >nul

echo [2/5] Tao thu muc %DST%
if not exist "%DST%" mkdir "%DST%"

echo [3/5] Copy file...
copy /y "%SRC%dist\telemonitor.exe" "%DST%\telemonitor.exe" >nul
if errorlevel 1 (
  echo [LOI] Copy exe that bai.
  pause
  exit /b 1
)

rem Copy config BEFORE the app ever starts, otherwise the app creates an empty
rem one and this copy is skipped by the "if not exist" guard.
if not exist "%DST%\config.json" (
  if exist "%SRC%config.json" (
    copy /y "%SRC%config.json" "%DST%\config.json" >nul
    echo   Da copy config.json tu thu muc build.
  ) else if exist "%SRC%config.example.json" (
    copy /y "%SRC%config.example.json" "%DST%\config.json" >nul
    echo   Da tao config.json tu file mau - HAY DIEN bot_token va chat_id.
  )
)

echo [4/5] Bat tu khoi dong...
start /wait "" "%DST%\telemonitor.exe" --install

rem Only start the agent once it actually has credentials, otherwise it just
rem logs an error and exits.
for /f "usebackq delims=" %%A in (`powershell -NoProfile -Command "try{(Get-Content -Raw '%DST%\config.json'|ConvertFrom-Json).bot_token}catch{''}"`) do set "TOKEN=%%A"

if "%TOKEN%"=="" (
  echo.
  echo [CANH BAO] config.json chua co bot_token.
  echo Mo file nay va dien bot_token + chat_id:
  echo   %DST%\config.json
  echo Sau do chay lai: "%DST%\telemonitor.exe"
) else (
  echo [5/5] Chay TeleMonitor...
  start "" "%DST%\telemonitor.exe"
)

echo.
echo XONG. Thu muc: %DST%
echo Log: %DST%\app.log
pause
