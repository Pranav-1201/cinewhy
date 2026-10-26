@echo off
rem Run the CineWhy demo locally. The server loads the newest artifacts\vN (the TMDB + MovieLens
rem 32M + Rotten Tomatoes + IMDb builds), else artifacts\.
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PY=venv\Scripts\python.exe

if not exist "%PY%" (
  echo The virtual environment is missing. Run setup.bat first.
  exit /b 1
)
set FOUND=
for /d %%D in (artifacts\v*) do if exist "%%D\manifest.json" set FOUND=1
if exist artifacts\manifest.json set FOUND=1
if not defined FOUND (
  echo No artifacts found. Unzip the ready-made build into artifacts\v3 ^(README.md, step 5^), or
  echo build one from the raw datasets ^(README.md, step 6^):  %PY% -m cinewhy.build --out artifacts\v3
  exit /b 1
)
echo Starting CineWhy at http://localhost:8000/  (Ctrl+C to stop)
start "" cmd /c "timeout /t 6 /nobreak >nul & start http://localhost:8000/"
"%PY%" -m uvicorn api.main:app --port 8000
