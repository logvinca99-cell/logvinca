@echo off
cd /d "%~dp0"

set PY=python
where python > /dev/null 2>&1
if errorlevel 1 set PY=py
where %PY% > /dev/null 2>&1
if errorlevel 1 (
  echo [!] Python is not installed.
  echo     Install it from python.org and check "Add python.exe to PATH".
  pause
  exit /b
)

set PYTHONIOENCODING=utf-8
chcp 65001 > nul
%PY% renew.py --dry-run %*
pause
