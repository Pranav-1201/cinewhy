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
| **Data** | Joins 100,000 IMDb reviews (aclImdb) to MovieLens 25M on the exact IMDb title number, giving 4,164 films with at least 5 reviews each (60,604 reviews, 33,355 quotable sentences). |
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
| Is the review-to-film join right? | 38.6% of reviews name their own film, against 0.17% when each film's reviews are paired with a different film (n = 55,780). |
| Polarity of whole reviews (official aclImdb test split, evaluated once) | 89.27% +/- 0.38 (n = 25,000). 5-fold CV: 88.80 +/- 0.89 (C=1) vs 89.72 +/- 0.56 (C=10). |
| Aspect finder **recall**: real aspect mentions it finds (300 random clauses, clean) | 50.8% [38.8, 62.7], n = 63 real mentions. |
| Aspect finder **precision**: flagged mentions that really are about the aspect (same sample) | 60.4% [46.9, 72.4], n = 53 flags. |
| Clause polarity sign on the mentions it finds (two clean random samples pooled) | 82.5% [72.7, 89.3], n = 80. |
| Sliders steer results the way they are labelled | Pushing any slider to 100% raises that aspect's average score in the top 20 by +0.30 to +0.45. This checks direction only, not that stated preferences predict enjoyment. |
| Recommender hit-rate@20 (2,000 held-out users, 4,164 films) | Popularity 12.6% [11.3, 14.1]; **collaborative filtering 34.9% [32.7, 37.0]**; aspect fit alone 9.6% [8.3, 10.9]; hybrid shown in the UI 33.8% [31.7, 35.9]. |

**Read these honestly.**

* Collaborative filtering does the heavy lifting. Aspect fit alone is *worse* than the popularity
  baseline at predicting what someone liked, and blending it in costs 1.1 points of hit-rate@20
  against pure CF (paired interval [-2.0, -0.3]). What it buys is that every pick can be explained
  with real sentences. The blend weight was chosen on separate validation users.
* The aspect finder is weak: it finds about half of what reviewers say about an aspect, and about
  4 in 10 of its flags are wrong. An earlier figure of 86.7% precision came from a sample drawn
  *from the finder's own flags*, which cannot show misses and flatters precision; it was replaced
  by random clauses. Word-list additions tuned on a sample looked like a big gain on that sample
  (recall 55% to 93%) and gave nothing on fresh clauses, and a classifier trained on the word list's
  own output raised recall by about 3 points while dropping precision from 74% to 49%. Both are
  recorded in `docs/DECISIONS.md` D-015.

## Limits you should know about

* The gold labels for aspect/polarity were written by the assistant that built the system, not by
  independent annotators, and the samples are small (hence the wide intervals). A kit to fix this
  is ready: fill `tests/data/aspect_label_sheet.csv` (see `docs/LABELLING.md`) and run
  `python -m cinewhy.absa.agreement` to get agreement and independent accuracy.
* The polarity model is trained on whole reviews and applied to clauses. A cue layer handles
  explicit negation ("aren't terrible") but did not measurably improve accuracy on clean data.
* The aspect finder's recall and precision are about 51% and 60% (see above).
* Aspect scores rest on 5-30 reviews per film, mostly from before 2012.
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
archive/        the original notebook and report, kept for history (see archive/README.md)
```

New here? Read `docs/HANDOVER.md`, then `docs/DECISIONS.md` (D-012 to D-014 cover this build).

> `archive/legacy/Movie_Sentiment_Analysis_Report.md` and the notebook beside it predate the audit
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
