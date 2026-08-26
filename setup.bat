@echo off
echo ====================================
echo   NLP Project Setup Script
echo ====================================

REM Create virtual environment
echo [1/4] Creating virtual environment...
python -m venv venv

REM Activate venv
echo [2/4] Activating virtual environment...
call venv\Scripts\activate.bat

REM Install packages
echo [3/4] Installing required packages...
pip install -r requirements.txt

REM Download NLTK data
echo [4/4] Downloading NLTK stopwords...
python -c "import nltk; nltk.download('stopwords')"

echo.
echo ====================================
echo   Setup Complete!
echo ====================================
echo.
echo To run the notebook:
echo   1. Activate venv:  venv\Scripts\activate
echo   2. Launch Jupyter: jupyter notebook
echo   3. Open:  Copy_of_Movie_sentimental_analysis.ipynb
echo   4. Make sure IMDB Dataset.csv is in the Data\ folder
echo.
pause
