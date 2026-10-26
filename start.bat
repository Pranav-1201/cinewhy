@echo off
rem Run the CineWhy demo locally. The server loads artifacts\v2 (the TMDB + MovieLens 32M +
rem Rotten Tomatoes + IMDb build) when it exists, else artifacts\.
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PY=venv\Scripts\python.exe

if not exist "%PY%" (
  echo The virtual environment is missing. Run setup.bat first.
  exit /b 1
)
if not exist artifacts\v2\manifest.json if not exist artifacts\manifest.json (
  echo No artifacts found. The data build needs the raw datasets in Data\raw ^(see README.md,
  echo "Build the data"^), then:  %PY% -m cinewhy.build --out artifacts\v2
  exit /b 1
)
echo Starting CineWhy at http://localhost:8000/  (Ctrl+C to stop)
start "" cmd /c "timeout /t 6 /nobreak >nul & start http://localhost:8000/"
"%PY%" -m uvicorn api.main:app --port 8000
