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
| **Polarity model** | Logistic regression on 1-2 word TF-IDF, trained on aclImdb through a harness that makes the leakage / test-reuse / spread rules structural. |
| **Aspect analysis** | Splits reviews into clauses, finds which of 7 aspects (acting, plot, pacing, visuals, ending, soundtrack, rewatchability) each is about, scores it, and keeps the strongest sentences as verbatim evidence. |
| **Recommender** | Item-item collaborative filtering blended with aspect fit, plus a bounded "how new" lift, evaluated on held-out users against a popularity baseline. |
| **API** | FastAPI. Verifies SHA-256 hashes of every artifact at boot and refuses to start on a mismatch. Serves posters from TMDB (nothing is stored here). |
| **Web UI** | A poster wall: a spotlight pick, shelves (tonight's picks, new and now, Hindi picks, classics), a film drawer with the full "receipt", taste dials, an optional first-visit sheet, and a *How it works* page whose every number comes from `eval.json`. Plain ES modules, no build step. |

## Run it

**Requirements:** Windows, Python 3.13, about 1 GB free disk for the served build (the raw datasets
are about 8 GB more, only needed to rebuild), internet for posters.

```bat
setup.bat      rem once: creates venv\ and installs requirements.txt
start.bat      rem serves artifacts\v2 (else artifacts\) at http://localhost:8000/
```

The server loads `$CINEWHY_ARTIFACTS` if set, else `artifacts\v2` when it has a manifest, else
`artifacts\`.

### Build the data

The data build is **not** automatic: Kaggle and GroupLens downloads need your accounts. Put these
under `Data\raw\` (full inventory, sizes and licences in [`docs/DATASET.md`](docs/DATASET.md)):

| File | From |
|---|---|
| `tmdb1m\TMDB_all_movies.csv` | Kaggle, alanvourch, "The Ultimate 1Million Movies Dataset (TMDB + IMDb)" |
| `rt_mother\rt_mother.zip` | Kaggle, bwandowando, "Mother of all movie review datasets" |
| `imdb_ebd\imdb_ebd.zip` | Kaggle, ebiswas, "IMDb Review Dataset - ebD" |
| `aclImdb_v1.tar.gz` | Stanford, Maas et al. (`python -m cinewhy.data.fetch` also downloads it, hash-checked) |
| `ml32m\ml-32m.zip` | GroupLens, MovieLens 32M |

```bat
venv\Scripts\python.exe -m cinewhy.absa.polarity --out artifacts\v2\polarity.joblib
venv\Scripts\python.exe -m cinewhy.build --out artifacts\v2          rem about an hour the first time, 5 GB RAM
venv\Scripts\python.exe -m cinewhy.absa.domain_check                 rem polarity on RT and IMDb text
venv\Scripts\python.exe -m cinewhy.recsys.recency_check              rem recency cost; needs 5 GB free RAM
```

Posters need no key: the front end loads `image.tmdb.org` URLs directly. A TMDB token is needed
only to refresh the film list; keep it in the `TMDB_TOKEN` environment variable, never in a file.

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

* **Tamper test.** Stop the server, open `artifacts\v2\profiles.json`, change one character, start
  the server again. It must refuse to boot with `ManifestMismatchError`. Restore the file (or
  rebuild) to recover.
* **Abuse test.** Send a body over 64 KB (413), more than 120 POSTs in a minute (429), or text
  over 5,000 characters to `/analyze` (422). A forced server error returns only an opaque
  `error_id`, never a stack trace.

### 5. Re-derive the numbers

`python -m cinewhy.build` recomputes everything in `eval.json` from the raw data; the same seed
gives the same numbers. Datasets are checked against pinned SHA-256 hashes where a hash is pinned.

## What was measured

All numbers come from `artifacts/v2/eval.json`. Intervals are 95%.

| Question | Result |
|---|---|
| Is the review-to-film join right? | A review names its own film's title 43.7% of the time for aclImdb, 38.5% for IMDb and 11.0% for Rotten Tomatoes, against 0.25%, 0.15% and 0.06% when it names the neighbouring film's title (n = 25,883 / 762,700 / 770,860). |
| Polarity of whole reviews, on the data it was trained on (official aclImdb test split, evaluated once) | 89.27% +/- 0.38 (n = 25,000). |
| Polarity on newer text it never saw | IMDb 88.4% [87.3, 89.4] (n = 3,362); **Rotten Tomatoes 75.0% [73.9, 76.1] (n = 6,000)**. |
| Aspect finder **recall**: real aspect mentions it finds (300 random clauses, clean) | 50.8%, 32 of 63 real mentions. |
| Aspect finder **precision**: flagged mentions that really are about the aspect (same sample) | 60.4%, 32 of 53 flags. |
| Clause polarity sign on the mentions it finds (two clean random samples pooled) | 82.5%, 66 of 80. |
| Sliders steer results the way they are labelled | Pushing any slider to 100% raises that aspect's average score in the top 20 by +0.17 to +0.37. This checks direction only, not that stated preferences predict enjoyment. |
| Recommender hit-rate@20 (2,000 held-out users, 11,065 films) | Popularity 8.3% [7.2, 9.6]; **collaborative filtering 20.1% [18.3, 21.9]**; aspect fit alone 5.5% [4.5, 6.6]; hybrid shown in the UI 18.9% [17.1, 20.6]. |
| Does "how new" do what it says? | With nothing known about the visitor, 6 of the first 20 films are from 2000 on at no preference, 18 at the default (50%) and 20 at 80%. See `eval.json` `recency` for the cost in hit rate. |

**Read these honestly.**

* Collaborative filtering does the heavy lifting: 11.8 points better than popularity at 20 [10.1,
  13.5]. Aspect fit alone is *worse* than the popularity baseline at predicting what someone liked,
  and blending it in costs about 1.25 points of hit-rate@20 against pure CF (paired interval
  [-2.15, -0.35]): the blend is slightly worse, not better. What it buys is that every pick can be
  explained with real sentences. The blend weight was chosen on separate validation users.
* The polarity model was trained on 2011-era IMDb reviews and is clearly weaker on Rotten Tomatoes
  text (75%), which supplies most post-2011 reviews. Retraining on mixed sources is an open decision
  (`docs/DECISIONS.md` D-017).
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
  Nothing is inferred about taste from them: a test of that needs MovieLens-1M demographics and has
  not been run.
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
web/            index.html, styles.css, js/ (ES modules, no build step), fonts/
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
