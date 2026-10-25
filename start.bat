@echo off
rem Run the CineWhy demo locally. First run builds the artifacts (about 10 minutes, needs
rem internet for the two datasets); later runs start in seconds.
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PY=venv\Scripts\python.exe

if not exist "%PY%" (
  echo The virtual environment is missing. Run setup.bat first.
  exit /b 1
)
if not exist artifacts\manifest.json (
  echo Building artifacts for the first time...
  "%PY%" -m cinewhy.data.fetch || exit /b 1
  "%PY%" -m cinewhy.absa.polarity || exit /b 1
  "%PY%" -m cinewhy.build || exit /b 1
)
echo Starting CineWhy at http://localhost:8000/  (Ctrl+C to stop)
start "" cmd /c "timeout /t 6 /nobreak >nul & start http://localhost:8000/"
"%PY%" -m uvicorn api.main:app --port 8000
