@echo off
rem One-time Python setup. Full guide, including the ready-made build and the datasets:
rem README.md, "Set up on a new machine".
echo ====================================
echo   CineWhy setup
echo ====================================

echo [1/3] Creating virtual environment...
python -m venv venv || goto :fail

echo [2/3] Installing pinned packages...
call venv\Scripts\activate.bat
rem "setup.bat serve" installs only what is needed to RUN the site (a much smaller install).
if /i "%~1"=="serve" (
  pip install -r requirements-serve.txt || goto :fail
  echo [3/3] Skipped the test tools ^(serve only^).
  goto :done
)
pip install -r requirements.txt || goto :fail

echo [3/3] Installing the project and its test tools...
pip install -e ".[dev]" || goto :fail

:done
echo.
echo ====================================
echo   Setup complete
echo ====================================
echo.
echo Next:
echo   1. Put the ready-made data in artifacts\v13  (README.md, "Get the data")
echo   2. start.bat
echo   Checks:  venv\Scripts\python.exe -m pytest -p no:cacheprovider
echo.
pause
exit /b 0

:fail
echo.
echo Setup failed: read the message above. Python 3.13 or newer is required.
pause
exit /b 1
