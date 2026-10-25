# CineWhy

**A movie recommender that shows you *why*, with the real review sentences behind every pick.**

> Netflix says *"Because you watched Inception."*
> CineWhy says *"Because you care about **pacing**: reviewers score this film's pacing +0.77,
> and here are the sentences that say so."*

---

## Status: working demo

Everything below runs on a laptop with `start.bat`. Nothing is deployed to the internet.

| Part | What it does |
|---|---|
| **Data** | Joins 100,000 IMDb reviews (aclImdb) to MovieLens 25M on the exact IMDb title number, giving 2,355 films with enough reviews. |
| **Polarity model** | Logistic regression on 1-2 word TF-IDF, trained through a harness that makes the leakage / test-reuse / spread rules structural. |
| **Aspect analysis** | Splits reviews into clauses, finds which of 7 aspects (acting, plot, pacing, visuals, ending, soundtrack, rewatchability) each is about, scores it, and keeps the strongest sentences as verbatim evidence. |
| **Recommender** | Item-item collaborative filtering on 3.4 M ratings, blended with aspect fit, evaluated on held-out users against a popularity baseline. |
| **API** | FastAPI. Verifies SHA-256 hashes of every artifact at boot and refuses to start on a mismatch. |
| **Web UI** | Three tabs: *Discover*, *Try a review*, *How well does it work?* No build step. |

## Run it

**Requirements:** Windows, Python 3.13, ~2 GB free disk, internet for the first run.

```bat
setup.bat      rem once: creates venv\ and installs requirements.txt
start.bat      rem first run builds the data artifacts (~10 min); later runs start in seconds
```

`start.bat` opens <http://localhost:8000/>. To do the steps by hand:

```bat
venv\Scripts\python.exe -m cinewhy.data.fetch      rem downloads + hash-checks both datasets (~350 MB)
venv\Scripts\python.exe -m cinewhy.absa.polarity   rem trains the polarity model, prints its report
venv\Scripts\python.exe -m cinewhy.build           rem builds artifacts\ and artifacts\manifest.json
venv\Scripts\python.exe -m uvicorn api.main:app --port 8000
```

## Test it yourself

### 1. Automated checks (about 10 seconds)

```bat
venv\Scripts\python.exe -m pytest tests -p no:cacheprovider
venv\Scripts\python.exe -m ruff check cinewhy api tests
venv\Scripts\python.exe -m mypy
```

Expected: every test passes (no `xfail`s remain), ruff says `All checks passed!`, and mypy says
`Success: no issues found in N source files` with N greater than zero.

### 2. Click through the demo

Open <http://localhost:8000/>.

1. **Discover.** Move the *Pacing* slider to ~90%. Within a second the list changes to films with
   a "Because you care about Pacing" reason, a blue/red bar, and quoted review sentences.
   Each quote names its source review and links to that film's reviews on IMDb.
2. **Find films.** Type `matrix`, press *Like* on a result. Your list shows it, and the
   recommendations now lean on films similar viewers also liked. Press *Skip* on another to see
   it vanish from results. Click a film title to open its page with every aspect and quotes.
3. **Cold start.** Press *Reset everything*. You get the most-liked films, labelled as a popular
   pick with *no* invented reason. That honesty is deliberate.
4. **Try a review.** Press *Use an example* then *Analyze*. Clauses are underlined blue or red,
   each tagged with its aspect and score, and a per-aspect summary appears. Paste your own text
   and check whether you agree with each call: that is the real test of the aspect analysis.
5. **How well does it work?** Every number on this tab is read from `artifacts/eval.json`,
   including the limits.

### 3. Poke the API

```bat
curl http://localhost:8000/health
curl "http://localhost:8000/search?q=matrix"
curl http://localhost:8000/movie/cw-0234215
curl -X POST http://localhost:8000/recommend -H "content-type: application/json" -d "{\"profile\":{\"aspect_weights\":{\"pacing\":0.9}}}"
curl -X POST http://localhost:8000/analyze   -H "content-type: application/json" -d "{\"text\":\"Great acting but the pacing dragged.\"}"
curl http://localhost:8000/movie/nope          rem 404 with no detail
```

Interactive docs: <http://localhost:8000/docs>.

### 4. Try to break it

* **Tamper test.** Stop the server, open `artifacts\profiles.json`, change one character, start
  the server again. It must refuse to boot with `ManifestMismatchError`. Restore the file (or
  re-run `python -m cinewhy.build`) to recover.
* **Abuse test.** Send a body over 64 KB (413), more than 120 POSTs in a minute (429), or text
  over 5,000 characters to `/analyze` (422). A forced server error returns only an opaque
  `error_id`, never a stack trace.

### 5. Re-derive the numbers

`python -m cinewhy.build` recomputes everything in `eval.json` from the raw data; the same seed
gives the same numbers. `python -m cinewhy.absa.polarity` reproduces the polarity report exactly
(it did, run twice). Datasets are checked against pinned SHA-256 hashes before use.

## What was measured

All numbers come from `artifacts/eval.json`. Intervals are 95%.

| Question | Result |
|---|---|
| Is the review-to-film join right? | 39.8% of reviews name their own film, against 0.14% when each film's reviews are paired with a different film (n = 44,768). |
| Polarity of whole reviews (official aclImdb test split, evaluated once) | 89.27% +/- 0.38 (n = 25,000). 5-fold CV: 88.80 +/- 0.89 (C=1) vs 89.72 +/- 0.56 (C=10). |
| Aspect detector precision (hand-labelled held-out clauses) | 86.7% [78.6, 92.1], n = 98. |
| Clause polarity sign (same sample) | 82.6% [72.0, 89.8], n = 69; 86.4% [75.5, 93.0] on clauses strong enough to be quoted, n = 59. |
| Recommender hit-rate@20 (2,000 held-out users) | Popularity 15.0% [13.4, 16.6]; **collaborative filtering 39.8% [37.6, 41.9]**; aspect fit alone 11.9% [10.4, 13.4]; hybrid shown in the UI 38.5% [36.4, 40.5]. |

**Read the last row honestly.** Collaborative filtering does the heavy lifting. Aspect fit alone is
*worse* than the popularity baseline at predicting what someone liked, and blending it in costs
1.3 points of hit-rate@20 against pure CF (paired interval [-2.1, -0.4]). What it buys is that every
pick can be explained with real sentences. The blend weight was chosen on separate validation
users, not the test users.

## Limits you should know about

* The gold labels for aspect/polarity were written by the assistant that built the system, not by
  independent annotators, and the samples are small (hence the wide intervals).
* The polarity model is trained on whole reviews and applied to clauses. Negation inside very
  short clauses ("aren't terrible") can still fool it.
* The aspect lexicon is a word list; its recall has not been measured.
* Aspect scores rest on 10-30 reviews per film, mostly from before 2012.
* Weights you set with the sliders cannot be validated offline: there is no ground truth for stated
  preferences.
* The Dockerfile and the CI job that builds it have **not been run yet** (no Docker on the
  development machine). Treat deployment as unverified.

## Repository layout

```
api/            FastAPI app (main.py), HTTP-only response models (models.py)
cinewhy/
  schemas.py    the contract between modules (changing it is a two-person decision)
  text/         normalisation shared by training and serving; negation is preserved
  data/         sources.py (the aclImdb x MovieLens join), fetch.py (hash-checked download)
  absa/         extract.py (clauses, aspects, build_profile), polarity.py (the model),
                train.py (the leakage-proof harness), gold.py (hand-labelled evaluation)
  recsys/       cf.py, rank.py (the one blend), catalogue.py (artifact I/O), evaluate.py
  artifacts/    manifest.py (hash, build, verify)
  build.py      the whole offline pipeline
web/            index.html, styles.css, app.js (no build step)
tests/          pytest suite; tests/data holds the hand-labelled gold clauses
docs/           HANDOVER, DECISIONS, ARCHITECTURE, MODEL_CARD, CONSTRAINTS, ...
start.bat       run the demo locally
Movie_Sentiment_Analysis.ipynb   the original prototype, kept for history
```

New here? Read `docs/HANDOVER.md`, then `docs/DECISIONS.md` (D-012 to D-014 cover this build).

> `Movie_Sentiment_Analysis_Report.md` and the notebook predate the audit
> (`docs/AUDIT-2026-08-26.md`) and contain claims the code contradicts. They are kept for history;
> where they disagree with the audit, the audit is right.

## Data and attribution

* **aclImdb v1**: Maas, Daly, Pham, Huang, Ng and Potts, *Learning Word Vectors for Sentiment
  Analysis*, ACL 2011. Not redistributed here.
* **MovieLens 25M**: F. Maxwell Harper and Joseph A. Konstan, *The MovieLens Datasets: History and
  Context*, ACM TiiS 2015. GroupLens data is for non-commercial use and must not be redistributed,
  so the repository ships only the loader.
* Quoted sentences are verbatim excerpts of IMDb user reviews from the aclImdb research dataset.

## License

MIT, see [`LICENSE`](LICENSE).
