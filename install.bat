@echo off
python -m venv .venv
call .venv\Scripts\activate
pip install --upgrade pip
pip install -e .
echo Installation complete. Copy .env.example to .env and fill in your keys.
