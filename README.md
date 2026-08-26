# Movie Sentiment Analysis - NLP Project

## Project Structure

```
NLPPROJECT/
├── Data/
│   └── IMDB Dataset.csv        ← Place your dataset here
├── venv/                        ← Auto-created by setup script
├── Copy_of_Movie_sentimental_analysis.ipynb
├── requirements.txt
├── setup.bat                    ← Run this on Windows
├── setup.sh                     ← Run this on Mac/Linux
└── README.md
```

## Setup Instructions

### Step 1 — Add the Dataset
Place `IMDB Dataset.csv` inside the `Data/` folder.

### Step 2 — Run Setup Script

**Windows:**
```
setup.bat
```

**Mac / Linux:**
```bash
chmod +x setup.sh
./setup.sh
```

This will:
- Create a Python virtual environment (`venv/`)
- Install all required packages
- Download NLTK stopwords data

### Step 3 — Launch Jupyter

**Windows:**
```
venv\Scripts\activate
jupyter notebook
```

**Mac / Linux:**
```bash
source venv/bin/activate
jupyter notebook
```

Then open `Copy_of_Movie_sentimental_analysis.ipynb` in the browser.

---

## Required Packages
- numpy
- pandas
- nltk
- scikit-learn
- seaborn
- matplotlib
- jupyter

## Notes
- The notebook reads the dataset with `pd.read_csv('IMDB Dataset.csv')`.
  Make sure the CSV is in `Data/` and update that path in the notebook's
  second cell to `pd.read_csv('Data/IMDB Dataset.csv')`.
- The notebook was originally written for Google Colab — all Colab-specific
  rendering will be ignored when running locally in Jupyter; this is normal.
