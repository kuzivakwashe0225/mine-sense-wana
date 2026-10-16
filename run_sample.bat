@echo off
cd /d %~dp0
call .venv\Scripts\activate.bat
set WANA_ROOT=%~dp0
cd backend
python -m wana all-sample || exit /b 1
echo Open http://127.0.0.1:8000  (geologist key: dev-geologist-key unless WANA_GEOLOGIST_KEY is set)
python -m wana serve --port 8000
