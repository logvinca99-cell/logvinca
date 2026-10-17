@echo off
chcp 65001 > nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

where python > nul 2>&1
if errorlevel 1 (
  echo [!] 파이썬이 설치되어 있지 않습니다.
  echo     python.org 에서 설치할 때 "Add python.exe to PATH" 를 꼭 체크하세요.
  pause
  exit /b
)

python -c "import flask, openpyxl, requests, bcrypt, anthropic, PIL" > nul 2>&1
if errorlevel 1 (
  echo 필요한 프로그램을 설치합니다...
  python -m pip install flask openpyxl requests bcrypt anthropic pillow
)

python -m uploader %*
echo.
echo 등록기가 꺼졌습니다. 위의 메시지(또는 data\uploader.log)를 복사해 보내 주세요.
pause
