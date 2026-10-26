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

rem A copy already listening on port 8000 would make the new one fail to start, and the browser
rem would show whatever that old copy serves. Say so instead of opening a confusing page.
netstat -ano | findstr /R /C:":8000 .*LISTENING" >nul
if not errorlevel 1 (
  echo CineWhy, or another program, is already running on port 8000.
  echo Close that window ^(or press Ctrl+C in it^) and run start.bat again, so the newest build is served.
  echo Opening the copy that is running now...
  start "" "http://localhost:8000/"
  exit /b 0
)

echo Starting CineWhy. The first load checks about 560 MB of data files and takes up to a minute;
echo the browser opens by itself as soon as the site is ready. Press Ctrl+C here to stop it.
rem Open the browser only once the server answers: it needs about 30 seconds to start, and a
rem browser opened sooner shows a "can't connect" page that looks like a broken site.
start "" powershell -NoProfile -WindowStyle Hidden -Command "for ($i = 0; $i -lt 240; $i++) { try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 5 | Out-Null; Start-Process 'http://localhost:8000/'; break } catch { Start-Sleep -Seconds 1 } }"
"%PY%" -m uvicorn api.main:app --port 8000
