@echo off
setlocal
cd /d "%~dp0"

python -m venv venv
if errorlevel 1 exit /b 1
call venv\Scripts\activate

pip install --upgrade pip
if errorlevel 1 exit /b 1
pip install -r backend\requirements.txt
if errorlevel 1 exit /b 1

REM Register the medrag package for imports (medrag.x.y) without reinstalling deps
pip install -e . --no-deps
if errorlevel 1 exit /b 1

echo Installation complete. Copy .env.example to .env and fill in your keys.
