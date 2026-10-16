@echo off
REM Downloads real open data. Put your digitised geology.geojson, structures.geojson and
REM occurrences.csv in data\inputs\ first (see README), otherwise those layers are skipped.
cd /d %~dp0
call .venv\Scripts\activate.bat
set WANA_ROOT=%~dp0
cd backend
python -m wana ingest --dry-run || exit /b 1
python -m wana ingest || exit /b 1
python -m wana stack || exit /b 1
python -m wana train || exit /b 1
python -m wana serve --port 8000
