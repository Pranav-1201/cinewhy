# CineWhy

**A movie recommender that shows you *why* — with evidence from what real reviewers actually said.**

> Netflix says *"Because you watched Inception."*
> CineWhy says *"Because you consistently praise **pacing** and **endings** — and across 1,240
> reviews, this film's pacing scores +0.71. Here are the three sentences that say so."*

---

## Status: prototype — early, and honest about it

This repository currently contains **one Jupyter notebook** that trains a Naive Bayes sentiment
classifier on IMDB reviews. There is no API, no frontend, and no deployed service yet.

A full staff-level audit was completed on 2026-08-26 and graded the project **3.4/10 (prototype)**.
The audit, the roadmap, and every measured number live in **[`docs/AUDIT-2026-08-26.md`](docs/AUDIT-2026-08-26.md)**.

**Known defects in the current notebook — all measured, none yet fixed:**

| | Defect | Effect |
|---|---|---|
| C-1 | Vectorizer is fit before the train/test split | test rows shape the vocabulary; measured accuracy cost is **not distinguishable from zero** (D-009) |
| C-2 | "Best model" chosen on a 0.0020 gap on the test set | under CV the models differ by less than **one fold-to-fold std** (D-009) |
| C-3 | `not`/`no`/`nor` removed as stopwords | `"not good"` and `"good"` produce **identical vectors** |

The measured leak-free accuracy is **~0.83** (`docs/DECISIONS.md` D-009): the older report's 0.835 was not inflated by leakage on this sample, but it cannot separate the models. Fixing these
is Phase C of the roadmap.

> ⚠️ `Movie_Sentiment_Analysis_Report.md` predates the audit and contains claims the code
> contradicts (it asserts leakage was prevented; it was not). It is kept for history. Where the
> report and the audit disagree, **the audit is correct** — it was measured.

---

## Quick start

**Requirements:** Python 3.13, ~1 GB free disk.

```bash
# 1. Clone
git clone https://github.com/Pranav-1201/cinewhy.git
cd cinewhy

# 2. Set up the environment
setup.bat                      # Windows
#   creates venv/, installs requirements.txt, downloads the NLTK stopword corpus

# 3. Get the dataset  ← required; it is NOT in this repo
#    "IMDB Dataset of 50K Movie Reviews" (Lakshmipathi N, Kaggle)
#    Download and place it at exactly:
#        Data/IMDB Dataset.csv
#    Expected: 50,000 rows, columns [review, sentiment], ~64 MB

# 4. Verify
venv\Scripts\activate
python check_env.py

# 5. Run
jupyter notebook Movie_Sentiment_Analysis.ipynb
```

Then **Kernel → Restart & Run All**. Do not run cells piecemeal — cells 13–18 mutate the dataframe
in place, so re-running one alone silently corrupts the data (e.g. double-stemming).

> `check_env.py` only checks that packages *import*. It declares minimum versions but never compares
> them, so it prints ✓ for an out-of-date package. Treat its green as "importable", not "correct".

---

## Repository layout

```
.
├── Movie_Sentiment_Analysis.ipynb   the current prototype (38 cells)
├── Movie_Sentiment_Analysis_Report.md   original report — see warning above
├── check_env.py                     import-presence check
├── requirements.txt                 fully pinned closure (105 packages)
├── setup.bat                        Windows environment setup
├── CLAUDE.md                        session rules for AI-assisted work
├── Data/                            dataset goes here (gitignored)
└── docs/
    ├── AUDIT-2026-08-26.md          ★ the audit + full roadmap
    ├── ARCHITECTURE.md              system map (target + today)
    ├── FLOW.md                      execution trace, and where it breaks
    ├── DECISIONS.md                 why, not just what
    ├── MODEL_CARD.md                what the sentiment model does, fails at, and was measured on
    ├── CONSTRAINTS.md               what an AI session may not do
    ├── TEST_CHECKLIST.md            commands + expected observables
    ├── ROLLBACK.md                  the way back out
    ├── HANDOVER.md                  ★ where things stand right now
    └── templates/                   bug + feature trace templates
```

New here? Read `docs/HANDOVER.md` first, then the audit.

---

## Where this is going

| Phase | Work | Sessions |
|---|---|---|
| A | Correct false claims, pin dependencies | 1 |
| B | CI foundation — *before* any code change | 1 |
| C | Methodology repair (C-1, C-2, C-3) | 2 |
| D | Data acquisition + recommender core | 3 |
| E | FastAPI service | 2 |
| F | Next.js frontend + the "Why this?" panel | 3 |
| G | Deploy, monitor, drill the rollback | 1 |

Target stack, all free tier: **FastAPI on Hugging Face Spaces** · artifacts on **HF Hub** ·
**Next.js on Vercel**. Rationale and rejected alternatives are in the audit.

> The current dataset has two columns — `review` and `sentiment`. No movie IDs, no user IDs. It
> **cannot** power a recommender, which is why Phase D starts with data acquisition
> (MovieLens 32M + TMDB + an item-keyed review corpus). See `docs/DECISIONS.md` D-002.

---

## Documentation approach

This project follows the *AI Collaboration Field Guide* — nine documents that keep AI-assisted work
traceable: handover, decisions, flow, architecture, constraints, test checklist, rollback, and
bug/feature traces. The point is that no session, human or AI, has to re-derive context that was
already established, and no claim survives without evidence attached.

## Data & attribution

IMDB 50K Movie Reviews dataset — Lakshmipathi N, via Kaggle. Not redistributed here.
Planned: MovieLens 32M (GroupLens, non-commercial), TMDB API (attribution required).

## License

MIT — see [`LICENSE`](LICENSE).
