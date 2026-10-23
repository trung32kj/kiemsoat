@echo off
setlocal
cd /d "%~dp0"

rem --- find a Python interpreter -------------------------------------------------
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo [LOI] Khong tim thay Python.
  echo Cai Python 3.11+ tu https://www.python.org/downloads/windows/
  echo Nho tick "Add python.exe to PATH" khi cai.
  pause
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
  pause
  exit /b 1
)

rem --- build --------------------------------------------------------------------
echo [3/3] Dong goi...
%PY% -m PyInstaller --onefile --noconsole --name telemonitor --paths src --clean src\main.py
if errorlevel 1 (
  echo.
  echo [LOI] Dong goi that bai. Xem loi phia tren.
  pause
  exit /b 1
)

if not exist "dist\telemonitor.exe" (
  echo.
  echo [LOI] Khong thay dist\telemonitor.exe sau khi build.
  pause
  exit /b 1
)

rem --- hash for GitHub Release ---------------------------------------------------
%PY% -c "import hashlib,pathlib;h=hashlib.sha256(pathlib.Path('dist/telemonitor.exe').read_bytes()).hexdigest();pathlib.Path('dist/telemonitor.exe.sha256').write_bytes((h+'\n').encode());print('SHA256:',h)"

echo.
echo XONG.
echo   dist\telemonitor.exe
echo   dist\telemonitor.exe.sha256
echo.
echo Bam dup file exe de cai dat (tu copy vao %%LOCALAPPDATA%%\TeleMonitor).
pause
