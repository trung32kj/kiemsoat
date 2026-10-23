@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem --- find a WORKING Python -----------------------------------------------------
rem The Microsoft Store ships a fake "python.exe" alias that only opens the Store
rem and exits non-zero. Each candidate is actually executed, so that alias can
rem never be selected. Common install paths are tried last, for machines where
rem PATH was never updated.
set "PY="
set "TRY=py -3"
call :try_py
if not defined PY (
  set "TRY=python"
  call :try_py
)
if not defined PY (
  set "TRY=python3"
  call :try_py
)
if not defined PY (
  for %%D in (
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "C:\Python313\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
  ) do (
    if not defined PY (
      set "TRY=%%~D"
      call :try_py
    )
  )
)

if not defined PY (
  echo.
  echo [LOI] Khong tim thay Python that tren may.
  echo.
  echo  1. Tai Python 3.11+ : https://www.python.org/downloads/windows/
  echo  2. Khi cai, TICK vao "Add python.exe to PATH"
  echo  3. Tat alias gia cua Microsoft Store:
  echo     Settings ^> Apps ^> Advanced app settings ^> App execution aliases
  echo     tat "python.exe" va "python3.exe"
  echo  4. Mo lai CMD roi chay lai build.bat
  echo.
  if not defined TELEMONITOR_NOPAUSE pause
  exit /b 1
)

echo [1/3] Dung Python: %PY%
%PY% --version

rem --- install build dependencies -----------------------------------------------
echo [2/3] Cai PyInstaller va Pillow...
%PY% -m pip install --upgrade --disable-pip-version-check pyinstaller Pillow
if errorlevel 1 (
  echo.
  echo [LOI] Cai thu vien that bai. Kiem tra ket noi mang.
  if not defined TELEMONITOR_NOPAUSE pause
  exit /b 1
)

rem --- build --------------------------------------------------------------------
echo [3/3] Dong goi...
%PY% -m PyInstaller --onefile --noconsole --name telemonitor --paths src --clean src\main.py
if errorlevel 1 (
  echo.
  echo [LOI] Dong goi that bai. Xem loi phia tren.
  if not defined TELEMONITOR_NOPAUSE pause
  exit /b 1
)

if not exist "dist\telemonitor.exe" (
  echo.
  echo [LOI] Khong thay dist\telemonitor.exe sau khi build.
  if not defined TELEMONITOR_NOPAUSE pause
  exit /b 1
)

%PY% -c "import hashlib,pathlib;h=hashlib.sha256(pathlib.Path('dist/telemonitor.exe').read_bytes()).hexdigest();pathlib.Path('dist/telemonitor.exe.sha256').write_bytes((h+'\n').encode());print('SHA256:',h)"

echo.
echo XONG.
echo   dist\telemonitor.exe
echo   dist\telemonitor.exe.sha256
echo.
echo Bam dup file exe de cai dat (tu copy vao %%LOCALAPPDATA%%\TeleMonitor).
if not defined TELEMONITOR_NOPAUSE pause
exit /b 0

rem ------------------------------------------------------------------------------
:try_py
rem Uses %TRY% because passing quoted paths as call arguments breaks cmd parsing.
rem Sets PY only when the interpreter really runs and is Python 3.9+.
%TRY% -c "import sys; sys.exit(0 if sys.version_info>=(3,9) else 1)" >nul 2>&1
if not errorlevel 1 set "PY=%TRY%"
exit /b 0
