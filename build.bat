@echo off
setlocal
cd /d "%~dp0"

python -m pip install --upgrade pyinstaller Pillow || goto :err

python -m PyInstaller ^
  --onefile ^
  --noconsole ^
  --name telemonitor ^
  --paths src ^
  --clean ^
  src\main.py || goto :err

echo.
echo Xong. File: dist\telemonitor.exe
goto :eof

:err
echo.
echo BUILD THAT BAI.
exit /b 1
