@echo off
chcp 65001 > nul
cd /d "%~dp0"

where python > nul 2>&1
if errorlevel 1 (
  echo [!] 파이썬이 설치되어 있지 않습니다.
  echo     python.org 에서 설치할 때 "Add python.exe to PATH" 를 꼭 체크하세요.
  pause
  exit /b
)

python -c "import pyautogui, pyperclip, pywinauto, win32clipboard" > nul 2>&1
if errorlevel 1 (
  echo 필요한 도구를 설치합니다. 1~2분 걸립니다...
  python -m pip install -r requirements.txt
)

python sellup.py %*
pause
