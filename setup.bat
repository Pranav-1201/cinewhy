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
pip install -r requirements.txt || goto :fail

echo [3/3] Installing the project and its test tools...
pip install -e ".[dev]" || goto :fail

echo.
echo ====================================
echo   Setup complete
echo ====================================
echo.
echo Next:
echo   1. Put the ready-made build in artifacts\v2  (see README.md step 5)
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
