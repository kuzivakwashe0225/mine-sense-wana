@echo off
cd /d %~dp0
call .venv\Scripts\activate.bat
set WANA_ROOT=%~dp0
REM laptop mode: no sign-in server, every request is a local geologist (never on a server)
set WANA_DEV_AUTH=geologist
set WANA_LOG_JSON=0
cd backend
python -m wana all-sample || exit /b 1
echo Open http://127.0.0.1:8000  (laptop mode: no sign-in; use docker compose for accounts)
python -m wana serve --port 8000
