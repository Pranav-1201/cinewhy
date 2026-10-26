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
| **Catalogue** | 11,065 English and Hindi films from 1950 to 2025: the most-voted films per language and year on TMDB (fewer per year before 2000, more after), each with at least 5 usable reviews. 3,757 are from 2012 on. |
| **Reviews** | 1.72 million reviews from aclImdb, IMDb (to about 2020) and Rotten Tomatoes users (to mid-2024), joined to films by IMDb number or by title, year and runtime. 179,807 sentences were kept as quotable evidence. |
| **Ratings** | MovieLens 32M: 26.6 million ratings of 10,229 of the catalogue films. |
| **Polarity model** | Logistic regression on 1-2 word TF-IDF, trained on aclImdb plus Rotten Tomatoes and IMDb reviews (whole films held out by hash) through a harness that makes the leakage / test-reuse / spread rules structural. |
| **Aspect analysis** | Splits reviews into clauses, finds which of 7 aspects (acting, plot, pacing, visuals, ending, soundtrack, rewatchability) each is about, scores it, and keeps the strongest sentences as verbatim evidence. |
| **Recommender** | Item-item collaborative filtering blended with aspect fit, plus a bounded "how new" lift, evaluated on held-out users against a popularity baseline. |
| **API** | FastAPI. Verifies SHA-256 hashes of every artifact at boot and refuses to start on a mismatch. Serves posters from TMDB (nothing is stored here). |
| **Web UI** | A poster wall: a spotlight pick, shelves (tonight's picks, new and now, Hindi picks, classics), a film drawer with the full "receipt", taste dials, an optional first-visit sheet, and a *How it works* page whose every number comes from `eval.json`. Plain ES modules, no build step. |

## Set up on a new machine (start here if you are joining the project)

You can work on the website and the API **without downloading any dataset**: you only need the
ready-made build (`artifacts\v3`) from Pranav. Datasets are needed only to rebuild that build.
The commands below are for Windows; for macOS or Linux use `source venv/bin/activate` instead of
`venv\Scripts\activate` and `python3` for `python`.

### 1. Install the tools (once)

| Tool | Version | Get it | Check it |
|---|---|---|---|
| Git | any recent | <https://git-scm.com/downloads> | `git --version` |
| Python | **3.13** (the project needs 3.13 or newer) | <https://www.python.org/downloads/> (on Windows tick *Add python.exe to PATH*) | `python --version` |
| Node.js | 20 or newer (24 was used) | <https://nodejs.org> (LTS) | `node --version` |
| A code editor | any | VS Code, Cursor or Antigravity | |

Node is used for one thing only: the tests of the browser-side helpers (`node --test`, built into
Node). **There is no `npm install` and no `node_modules` folder**: the front end has no packages
and no build step.

You also need a GitHub account that Pranav has added as a collaborator on
`Pranav-1201/cinewhy` (repository *Settings, Collaborators*), and a Kaggle account only if you
plan to rebuild the data.

### 2. Get the code

```bat
git clone https://github.com/Pranav-1201/cinewhy.git
cd cinewhy
git config user.name "Your Name"
git config user.email "you@example.com"
```

Later, every time you sit down to work, **before anything else**:

```bat
git fetch
git status
git pull --ff-only
```

If `git pull --ff-only` refuses, stop and ask: it means your copy and the remote have diverged.

### 3. Create the Python environment (once, and again if `requirements.txt` changes)

```bat
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
pip install -e ".[dev]"
set PYTHONUTF8=1
```

`requirements.txt` pins every runtime package to the exact version the results were produced with;
`.[dev]` adds pytest, ruff and mypy. (`setup.bat` does steps 3 in one go.) `set PYTHONUTF8=1`
must be repeated in each new terminal (Windows prints with cp1252 otherwise and scripts that print
quotes crash with `UnicodeEncodeError`).

### 4. Check that everything works

```bat
python -m pytest -p no:cacheprovider
python -m ruff check cinewhy api tests
python -m mypy
```

Expected: `409 passed` (or more as tests are added), `All checks passed!`, and
`Success: no issues found`. The tests need no data and no internet. If the count is lower, or
anything fails on a fresh clone, stop and tell Pranav before changing anything.

### 5. Get the ready-made build and run the site

Ask Pranav for **`cinewhy-artifacts-v3.zip`** (365 MB, SHA-256
`071CC4241C2D8B4608EE0351EBD59452AF658620BE4DF63F1CA806FE16984D47`; check it with
`certutil -hashfile cinewhy-artifacts-v3.zip SHA256`). Unzip it **into** `artifacts\v3\` so that
this file exists: `artifacts\v3\manifest.json`. The folder `artifacts\` is git-ignored, so it never
gets committed. Then:

```bat
start.bat
```

It opens <http://localhost:8000/>. The server checks the SHA-256 of every artifact file at start
and refuses to boot if one is missing or changed (`ManifestMismatchError`): unzip again if that
happens. The film posters load from `image.tmdb.org`, so you need internet for them.

Without `start.bat`: `python -m uvicorn api.main:app --port 8000` (add `--reload` while editing
Python). The server loads `$CINEWHY_ARTIFACTS` if set, else the highest-numbered `artifacts\vN` that has a manifest,
else `artifacts\`. Editing `web\` files needs no restart: refresh the browser.

### 6. Rebuilding the data (only if you change the data pipeline)

Skip this unless you are changing `cinewhy\data`, `cinewhy\absa` or `cinewhy\build.py`. You need
**about 15 GB free disk, 5 GB free RAM, and about an hour**. The raw files are git-ignored. Put
them exactly here (create the folders). Kaggle needs you to be logged in; use the *Download*
button in the browser (the Kaggle command-line and `kagglehub` have been unreliable for the TMDB
file: they hang at "awaiting compression").

| Save it as | Size | Where to get it |
|---|---|---|
| `Data\raw\tmdb1m\TMDB_all_movies.csv` | 0.8 GB | <https://www.kaggle.com/datasets/alanvourch/tmdb-movies-daily-updates> (the file `TMDB_all_movies.csv` inside the download) |
| `Data\raw\rt_mother\rt_mother.zip` | 4.3 GB | <https://www.kaggle.com/datasets/bwandowando/rotten-tomatoes-9800-movie-critic-and-user-reviews> (the downloaded `archive.zip`, renamed; do **not** unzip it) |
| `Data\raw\imdb_ebd\imdb_ebd.zip` | 2.9 GB | <https://www.kaggle.com/datasets/ebiswas/imdb-review-dataset> (the downloaded `archive.zip`, renamed; do **not** unzip it) |
| `Data\raw\aclImdb_v1.tar.gz` | 84 MB | <https://ai.stanford.edu/~amaas/data/sentiment/aclImdb_v1.tar.gz> (do not unpack) |
| `Data\raw\ml32m\ml-32m.zip` | 239 MB | <https://files.grouplens.org/datasets/movielens/ml-32m.zip> (do not unzip) |

If a download is slow, blocked or Kaggle misbehaves, ask Pranav to send the file from his
`Data\raw\` folder instead. Licences and what each file supplies: [`docs/DATASET.md`](docs/DATASET.md).

```bat
python -m cinewhy.absa.polarity --out artifacts\polarity.joblib       rem the aclImdb-only baseline model
python -m cinewhy.absa.polarity_mixed --old-model artifacts\polarity.joblib --out-dir artifacts\v3   rem retrain on all sources (about 45 min the first time)
python -m cinewhy.absa.polarity_mixed --old-model artifacts\polarity.joblib --out-dir artifacts\v3 --domain-only   rem held-out-film report
python -m cinewhy.build --out artifacts\v3          rem about 40 minutes with the cache, 5 GB RAM
python -m cinewhy.recsys.recency_check --artifacts artifacts\v3   rem recency cost; needs 5 GB free RAM
```

The first build caches its slow gathering step in `Data\raw\_cache\`; later builds take about 35
minutes. A TMDB token is **not** needed for any of this (posters load straight from TMDB). Never
put a token or key in a file or in a commit; if one is ever needed use an environment variable.

### 7. Working together

* Work on a branch (`git switch -c your-topic`), not on `main`; open a pull request on GitHub.
* Before every push run the three checks in step 4. CI runs the same ones.
* Stage files by name (`git add path\to\file`), never `git add -A`: stray files and data would
  slip in. Never commit anything from `Data\` or `artifacts\`.
* Rules, the Pranav / Lakshay split and the contract in `cinewhy\schemas.py` (changing it is a
  two-person decision): [`CONTRIBUTING.md`](CONTRIBUTING.md). Where things stand and what is left:
  [`docs\HANDOVER.md`](docs/HANDOVER.md). Why things are the way they are:
  [`docs\DECISIONS.md`](docs/DECISIONS.md).

### 8. If something goes wrong

| Symptom | Cause and fix |
|---|---|
| `python` is not recognised, or is 3.11 | Install Python 3.13 and reopen the terminal; try `py -3.13 -m venv venv`. |
| `UnicodeEncodeError` | `set PYTHONUTF8=1` in that terminal. |
| `ManifestMismatchError` at start | `artifacts\v3` is incomplete or edited: unzip the build again. |
| `start.bat` says no artifacts found | The zip is not unpacked into `artifacts\v3\` (check `artifacts\v3\manifest.json` exists). |
| Port 8000 is busy | Another copy is running: close it, or use `--port 8001`. |
| Posters are grey boxes | No internet, or `image.tmdb.org` is blocked by a network filter. The site still works. |
| Build runs out of memory | Needs 5 GB free; close Chrome and other programs. |

## Run it (short version)

```bat
start.bat      rem serves the newest artifacts\vN (else artifacts\) at http://localhost:8000/
```

Everything else is in the setup guide above. Posters need no key: the front end loads
`image.tmdb.org` URLs directly.

## Test it yourself

### 1. Automated checks (about 15 seconds)

```bat
venv\Scripts\python.exe -m pytest tests -p no:cacheprovider
venv\Scripts\python.exe -m ruff check cinewhy api tests
venv\Scripts\python.exe -m mypy
```

Expected: every test passes (the browser-side helpers run under Node's built-in test runner from
inside pytest), ruff says `All checks passed!`, and mypy says `Success: no issues found`.

### 2. Click through the demo

Open <http://localhost:8000/>.

1. **First visit.** A sheet asks, optionally, for languages, age and region. Answer or press *Skip*.
   Age only sets how strongly newer films are favoured; region India puts the Hindi shelf first.
   Nothing leaves your browser.
2. **Shelves.** Posters load from TMDB. Move *How new* in *Your taste* to 0 and the first page gets
   older; to 100% and it fills with recent films.
3. **Receipts.** Click a poster. The drawer shows each aspect's score as a bar, with real review
   sentences and the source (Rotten Tomatoes or IMDb) for each.
4. **Taste.** Open *Your taste* and push *Pacing* to ~90%. The picks change to films whose reviews
   praise pacing, each with a "which you care about" line. Press the heart on a poster and the
   list leans on films similar viewers liked.
5. **Try a review.** Press *Use an example*, then *Analyze*. Clauses are underlined blue or red,
   each tagged with its aspect and score.
6. **How it works.** Every number on this page is read from `eval.json`, including the limits.

### 3. Poke the API

```bat
curl http://localhost:8000/health
curl http://localhost:8000/facets
curl "http://localhost:8000/search?q=matrix"
curl http://localhost:8000/movie/cw-0468569
curl -X POST http://localhost:8000/discover -H "content-type: application/json" -d "{\"limit\":5,\"languages\":[\"hi\"],\"recency\":0.8}"
curl -X POST http://localhost:8000/recommend -H "content-type: application/json" -d "{\"profile\":{\"aspect_weights\":{\"pacing\":0.9}}}"
curl -X POST http://localhost:8000/analyze   -H "content-type: application/json" -d "{\"text\":\"Great acting but the pacing dragged.\"}"
curl http://localhost:8000/movie/nope          rem 404 with no detail
```

Interactive docs: <http://localhost:8000/docs>.

### 4. Try to break it

* **Tamper test.** Stop the server, open `artifacts\v3\profiles.json`, change one character, start
  the server again. It must refuse to boot with `ManifestMismatchError`. Restore the file (or
  rebuild) to recover.
* **Abuse test.** Send a body over 64 KB (413), more than 120 POSTs in a minute (429), or text
  over 5,000 characters to `/analyze` (422). A forced server error returns only an opaque
  `error_id`, never a stack trace.

### 5. Re-derive the numbers

`python -m cinewhy.build` recomputes everything in `eval.json` from the raw data; the same seed
gives the same numbers. Datasets are checked against pinned SHA-256 hashes where a hash is pinned.

## What was measured

All numbers come from `artifacts/v3/eval.json`. Intervals are 95%.

| Question | Result |
|---|---|
| Is the review-to-film join right? | A review names its own film's title 43.7% of the time for aclImdb, 38.5% for IMDb and 11.0% for Rotten Tomatoes, against 0.25%, 0.15% and 0.06% when it names the neighbouring film's title (n = 25,883 / 762,700 / 770,860). |
| Polarity of whole reviews on aclImdb's official test split (evaluated once) | 90.50% +/- 0.36 (n = 25,000). |
| Polarity on newer text, films held out of training, against the earlier aclImdb-only model on the same reviews | IMDb 91.1% [90.3, 91.8] (was 89.3%); **Rotten Tomatoes 83.5% [82.6, 84.5] (was 78.2%)**; n = 6,000 each (`docs/DECISIONS.md` D-017). |
| Aspect finder **recall**: real aspect mentions it finds (300 random clauses, clean) | 50.8%, 32 of 63 real mentions. |
| Aspect finder **precision**: flagged mentions that really are about the aspect (same sample) | 60.4%, 32 of 53 flags. |
| Clause polarity sign on the mentions it finds (two clean random samples pooled) | 88.8%, 71 of 80 (was 82.5%, 66 of 80, before the retraining). |
| Sliders steer results the way they are labelled | Pushing any slider to 100% raises that aspect's average score in the top 20 by +0.12 to +0.33. This checks direction only, not that stated preferences predict enjoyment. |
| Recommender hit-rate@20 (2,000 held-out users, 11,065 films) | Popularity 8.3% [7.2, 9.6]; **collaborative filtering 20.1% [18.3, 21.9]**; aspect fit alone 6.6% [5.5, 7.6]; hybrid shown in the UI 19.0% [17.2, 20.9]. |
| Does "how new" do what it says? | With nothing known about the visitor, 6 of the first 20 films are from 2000 on at no preference, 18 at the default (50%) and 20 at 80%. Cost in held-out hit rate@20 against the hybrid without it: +1.15 points at 25%, no measurable change at 50% (+0.95 [-0.15, 2.1]), **-2.8 at 80%** and **-7.05 at 100%** (`docs/DECISIONS.md` D-020). |

**Read these honestly.**

* Collaborative filtering does the heavy lifting: 11.8 points better than popularity at 20 [10.1,
  13.5]. Aspect fit alone is *worse* than the popularity baseline at predicting what someone liked,
  and blending it in costs about 1.1 points of hit-rate@20 against pure CF (paired interval
  [-2.05, -0.2]): the blend is slightly worse, not better. What it buys is that every pick can be
  explained with real sentences. The blend weight was chosen on separate validation users.
* The polarity model was first trained only on 2011-era IMDb reviews and was weak on Rotten
  Tomatoes text (78% on held-out films). Retraining on all three sources lifted that to 83.5%
  without costing the others (D-017). Rotten Tomatoes is still its weakest source.
* The aspect finder is weak: it finds about half of what reviewers say about an aspect, and about
  4 in 10 of its flags are wrong. An earlier figure of 86.7% precision came from a sample drawn
  *from the finder's own flags*, which cannot show misses and flatters precision; it was replaced
  by random clauses (`docs/DECISIONS.md` D-015).
* Collaborative filtering cannot see most Hindi films: few have MovieLens ratings, and only 72
  link to Rotten Tomatoes (their reviews come from IMDb). Hindi films are ranked on reviews and
  IMDb scores, and no Hindi film appears in the first 20 of the default list at any "how new"
  setting; they have their own shelf.

## Limits you should know about

* The gold labels for aspect/polarity were written by the assistant that built the system, not by
  independent annotators, and the samples are small (hence the wide intervals). A kit to fix this
  is ready: fill `tests/data/aspect_label_sheet.csv` (see `docs/LABELLING.md`) and run
  `python -m cinewhy.absa.agreement` to get agreement and independent accuracy.
* The polarity model is trained on whole reviews and applied to clauses. A cue layer handles
  explicit negation ("aren't terrible") but did not measurably improve accuracy on clean data.
* The catalogue is the popular top of each year, not all films; an obscure film will not be found.
* Age, region and language answers only set defaults (how new, which shelf leads, which language).
  Nothing is inferred about taste from them: a held-out test on MovieLens-1M found age and sex add
  about a tenth of a point of hit rate on a 6.5% base, so that feature is off (`docs/DECISIONS.md`
  D-019; `python experiments\demographics_ml1m.py` reproduces it, needing `Data\raw\ml1m\ml-1m.zip`
  from <https://files.grouplens.org/datasets/movielens/ml-1m.zip>). Region could not be tested.
* Weights you set with the sliders cannot be validated offline: there is no ground truth for stated
  preferences.
* The Dockerfile and the CI job that builds it have **not been run yet** and still describe the
  older build. Treat deployment as unverified.

## Repository layout

```
api/            FastAPI app (main.py), HTTP-only request/response models (models.py)
cinewhy/
  schemas.py    the contract between modules (changing it is a two-person decision)
  text/         normalisation shared by training and serving; negation is preserved
  data/         spine.py (which films), linking.py (title and year joins), reviews.py (RT and
                IMDb readers), catalogue_sources.py (gather, merge, cache), sources.py (MovieLens)
  absa/         extract.py (clauses, aspects, build_profile), polarity.py (the model),
                train.py (the leakage-proof harness), gold.py, domain_check.py
  recsys/       cf.py, rank.py (the one blend), discover.py (recency, filters), catalogue.py
                (artifact I/O), evaluate.py, recency_check.py
  artifacts/    manifest.py (hash, build, verify)
  build.py      the whole offline pipeline
web/            index.html, cinewhy.css, js/ (ES modules, no build step), fonts/
tests/          pytest suite (plus tests/web for the browser helpers); tests/data holds the
                hand-labelled gold clauses
docs/           HANDOVER, DECISIONS, DATASET, FEATURE-004/005, ARCHITECTURE, MODEL_CARD, ...
start.bat       run the demo locally
archive/        the original notebook and report, kept for history (see archive/README.md)
```

New here? Read `docs/HANDOVER.md`, then `docs/DATASET.md` and `docs/DECISIONS.md` (D-016 to D-018
cover this build).

> `archive/legacy/Movie_Sentiment_Analysis_Report.md` and the notebook beside it predate the audit
> (`docs/AUDIT-2026-08-26.md`) and contain claims the code contradicts. They are kept for history;
> where they disagree with the audit, the audit is right.

## Data and attribution

* **TMDB:** film list, posters and descriptions. *This product uses the TMDB API but is not
  endorsed or certified by TMDB.* Posters are loaded from TMDB's servers, never stored here.
* **Rotten Tomatoes user reviews:** Kaggle dataset "Mother of all movie review datasets"
  (bwandowando), CC BY-NC-SA 4.0. Quoted sentences are verbatim excerpts and link to the film.
* **IMDb reviews:** Kaggle dataset "IMDb Review Dataset - ebD" (ebiswas) and **aclImdb v1**: Maas,
  Daly, Pham, Huang, Ng and Potts, *Learning Word Vectors for Sentiment Analysis*, ACL 2011.
* **MovieLens 32M:** F. Maxwell Harper and Joseph A. Konstan, *The MovieLens Datasets: History and
  Context*, ACM TiiS 2015. GroupLens data is for non-commercial use and must not be redistributed,
  so the repository ships only the loader.
* **Font:** Bricolage Grotesque, SIL Open Font License (see `web/fonts/README.txt`).
* None of the raw data is committed: `Data/raw/` is gitignored.

## License

MIT, see [`LICENSE`](LICENSE).
