@echo off
REM One-time setup on Windows. Needs Python 3.10+ and Node.js 20+ on PATH.
cd /d %~dp0
python -m venv .venv || goto :err
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r backend\requirements.txt || goto :err
cd frontend
call npm install || goto :err
call npm run build || goto :err
cd ..
echo.
echo Setup finished. Next:
echo   run_sample.bat   - build the SAMPLE dataset and start the app (for testing)
echo   run_real.bat     - download the real Shurugwi data, train, and start the app
exit /b 0
:err
echo Setup failed. Read the message above.
exit /b 1
