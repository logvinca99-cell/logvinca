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

python -c "import flask, openpyxl, requests, bcrypt" > nul 2>&1
if errorlevel 1 (
  echo 필요한 프로그램을 설치합니다...
  python -m pip install flask openpyxl requests bcrypt
)

python -m uploader %*
if errorlevel 1 pause
