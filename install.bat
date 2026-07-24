@echo off

python -m venv venv
call venv\Scripts\activate

pip install --upgrade pip
pip install -r backend\requirements.txt
pip install -r frontend\requirements.txt

REM Register the medrag package for imports (medrag.x.y) without reinstalling deps
pip install -e . --no-deps

echo Installation complete. Copy .env.example to .env and fill in your keys.