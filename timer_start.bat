@echo off
chcp 65001 > nul
cd /d "%~dp0timer"

where python > /dev/null 2>&1
if errorlevel 1 (
  echo [!] 파이썬이 설치되어 있지 않습니다.
  echo     python.org 에서 설치할 때 "Add python.exe to PATH" 를 꼭 체크하세요.
  pause
  exit /b
)

where pythonw > /dev/null 2>&1
if errorlevel 1 (
  python work_timer.py
) else (
  start "" pythonw work_timer.py
)
