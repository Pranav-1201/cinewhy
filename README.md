# CineWhy

**A movie recommender that shows you *why*, with the real review sentences behind every pick.**

> Netflix says *"Because you watched Inception."*
> CineWhy says *"Because you care about **pacing**: reviewers score this film's pacing +0.77,
> and here are the sentences that say so."*

---

## Status: working demo

Everything below runs on a laptop (Windows or Mac) with `start.bat` or `bash start.sh`. Nothing is
deployed to the internet; to let a friend in, you make a temporary public link
([Share it with a friend](#share-it-with-a-friend)).

The current data build is **v13** (manifest `16c1ba2b4576`, built from TMDB, IMDb, MovieLens 32M,
Rotten Tomatoes and IMDb user reviews).

| Part | What it does |
|---|---|
| **Catalogue** | 106,115 titles (86,181 films and 19,934 series) in English, French, Japanese, Hindi and Telugu: every title with 200 or more IMDb votes. 20,485 of them carry **receipts** (at least 20 usable reviews and quotable sentences); the rest are **ratings-only**: listed and recommendable, but with no review sentences to quote. |
| **Reviews** | Reviews from aclImdb, IMDb and Rotten Tomatoes users, joined to titles by IMDb number or by title, year and runtime. 282,397 sentences were kept as quotable evidence. |
| **Ratings** | MovieLens 32M: about 29 million ratings, used for the similarity between titles. |
| **Cast and where to watch** | Who is in each title (search by actor) and a dated snapshot of where it streams, by country (from TMDB, credited to JustWatch). |
| **Polarity model** | Logistic regression on 1-2 word TF-IDF, trained on aclImdb plus Rotten Tomatoes and IMDb reviews (whole films held out by hash) through a harness that makes the leakage / test-reuse / spread rules structural. |
| **Aspect analysis** | Splits reviews into clauses, finds which of 7 aspects (acting, plot, pacing, visuals, ending, soundtrack, rewatchability) each is about, scores it, and keeps the strongest sentences as verbatim evidence. |
| **Recommender** | Item-item collaborative filtering blended with aspect fit, plus a bounded "how new" lift, evaluated on held-out users against a popularity baseline. |
| **Watch together** | Two to five people join a temporary room by code or invite link, each agrees to share their library, and the room gets one combined list. Rooms live in the server's memory only. |
| **API** | FastAPI. Verifies SHA-256 hashes of every data file at boot and refuses to start on a mismatch. Serves posters from TMDB (nothing is stored here). |
| **Web UI** | A poster wall: a spotlight pick with *Show me another*, shelves, a film drawer with the full "receipt", a library, taste dials, an optional first-visit sheet, and a *How it works* page whose every number comes from `eval.json`. Plain ES modules, no build step. |

---

## Set up on a new machine (start here)

This is the whole path for a fresh Windows or Mac computer: install the tools, get the code, install
the packages, get the data, run it. Allow about 15 minutes plus the data download.

**You need:** about **6 GB of free disk** (the data is 913 MB zipped and 1.8 GB unzipped), **at least
4 GB of free RAM** (the running server holds about 3 GB), and internet (for installing, and for the
film posters, which load from `image.tmdb.org`). You do **not** need an account anywhere: the code is
public, so cloning needs no login.

### 1. Install the tools (once)

| Tool | Version | Why |
|---|---|---|
| Git | any recent | to download the code |
| Python | **3.13 or newer** | runs the server |
| Node.js | 20 or newer (optional) | only for the developer tests of the browser code; skip it if you just want to run the site |

**Windows** (open *Command Prompt* or *PowerShell*; `winget` comes with Windows 10 and 11):

```bat
winget install --id Git.Git -e
winget install --id Python.Python.3.13 -e
```

Then **close the terminal and open a new one** so the new programs are found, and check:

```bat
git --version
python --version
```

`python --version` must say 3.13 or newer. (If it says 3.11 or nothing, try `py -3.13 --version`; if
that works, use `py -3.13` wherever this guide says `python`. Installing Python from
<https://www.python.org/downloads/> also works: tick *Add python.exe to PATH*.)

**Mac** (open *Terminal*). If you do not have Homebrew, install it first from <https://brew.sh>
(it prints the exact line to run), then:

```bash
brew install git python@3.13
```

Open a new Terminal window and check:

```bash
git --version
python3.13 --version
```

### 2. Get the code

Windows or Mac, the same:

```bash
git clone https://github.com/Pranav-1201/cinewhy.git
cd cinewhy
```

(To change the code and push it back you also need to be added as a collaborator on
`Pranav-1201/cinewhy`; to run it you do not.)

### 3. Install the Python packages (once)

This makes a private Python environment in a folder called `venv` and installs the pinned packages
into it. It does not change anything else on your computer.

| | Just run the site (small, recommended) | Everything: also the tests and dev tools |
|---|---|---|
| **Windows** | `setup.bat serve` | `setup.bat` |
| **Mac / Linux** | `bash setup.sh serve` | `bash setup.sh` |

In PowerShell write `.\setup.bat serve`. The script finds Python 3.13 and says so if it cannot.
If you prefer the steps by hand, `setup.bat serve` is exactly:

```bat
python -m venv venv
venv\Scripts\activate
pip install -r requirements-serve.txt
```

(Mac: `python3.13 -m venv venv`, then `source venv/bin/activate`, then the same `pip install`.)
`requirements-serve.txt` is the 19 packages the running site imports; `requirements.txt` is the full
development set (Jupyter, plotting and so on) plus `pip install -e ".[dev]"` for pytest, ruff and mypy.

### 4. Get the data

The site needs one folder of ready-made data, `artifacts/v13` (the current build). It is **not in the
git repository**: it contains material derived from MovieLens and Rotten Tomatoes, whose licences
do not allow it to be republished. So the owner (Pranav) shares it privately.

1. Ask Pranav for **`cinewhy-artifacts-v13.zip`** (913 MB) and save it, for example in your Downloads
   folder.
2. Check it arrived intact. The SHA-256 must be
   `1288510D82C1280D075F7E54C5A0C5F4221145E8BF2D03AF869B56A553CC0CA9`:

   Windows (PowerShell): `Get-FileHash "$HOME\Downloads\cinewhy-artifacts-v13.zip" -Algorithm SHA256`
   Mac: `shasum -a 256 ~/Downloads/cinewhy-artifacts-v13.zip`

3. Unzip it **into** `artifacts/v13` inside the project folder, so that this file exists:
   `artifacts/v13/manifest.json`.

   Windows (PowerShell, about a minute):

   ```powershell
   New-Item -ItemType Directory -Force artifacts\v13
   Expand-Archive -Path "$HOME\Downloads\cinewhy-artifacts-v13.zip" -DestinationPath artifacts\v13
   ```

   Mac:

   ```bash
   mkdir -p artifacts/v13
   unzip -q ~/Downloads/cinewhy-artifacts-v13.zip -d artifacts/v13
   ```

The folder `artifacts/` is git-ignored, so it never gets committed. When the owner publishes a newer
build it arrives the same way as a `cinewhy-artifacts-vN.zip` unpacked into `artifacts/vN`; the
server always loads the highest-numbered one. The server checks the SHA-256 of every file inside
at start and refuses to boot if one is missing or changed (`ManifestMismatchError`): unzip again if
that happens.

### 5. Run it

| | |
|---|---|
| **Windows** | double-click `start.bat`, or run `start.bat` in a terminal inside the project folder |
| **Mac / Linux** | `bash start.sh` |

The first start checks about 1.8 GB of files and takes up to a minute; your browser then opens
<http://localhost:8000/> by itself. Press **Ctrl+C in that terminal window** to stop it. The terminal
also prints a short reminder of how to make the temporary public link (next section).

Without the scripts: `python -m uvicorn api.main:app --port 8000` (add `--reload` while editing
Python). The server loads `$CINEWHY_ARTIFACTS` if set, else the highest-numbered `artifacts/vN` that
has a manifest, else `artifacts/`. Editing `web/` files needs no restart: refresh the browser.

### Share it with a friend

**Why this is needed.** Watch together rooms live in the memory of the one server that created them,
so everybody has to use *the same* running server. A friend who clones the project and runs their
own copy gets a separate server, and your room code does not exist there. The simplest fix is a
**temporary public link** to the server on your computer, made with Cloudflare's free quick tunnel.
No account and no change to the project are needed, and your friend needs nothing installed: they
just open the link in a browser.

**Install the tunnel tool (once).**

Windows (in a terminal, then close it and open a new one):

```bat
winget install --id Cloudflare.cloudflared
```

Mac: `brew install cloudflared`. Other systems:
<https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/>.

**Make a link (every time).**

1. Start the site as above (`start.bat` or `bash start.sh`) and **leave that window open**: it is the
   server.
2. Open a **second** terminal (any folder) and run:

   ```bash
   cloudflared tunnel --url http://localhost:8000
   ```

3. After a few seconds it prints an address that ends in `trycloudflare.com`, for example
   `https://some-random-words.trycloudflare.com`. **Open that address in your own browser** (not
   `localhost`), then *Profile*, *Watch together*, *Start a room*. The invite link it shows is built
   from the address you opened, so it works for your friend.
4. Send your friend the invite link. They open it, tick the agreement box and join.
5. When you are done, press **Ctrl+C in the second terminal** to close the link, and Ctrl+C in the
   server window to stop the site.

**Good to know.**

* The address is **new every time**: send the new one each session.
* Both windows must stay open and your computer must stay on while your friend uses it.
* While the link is up, **anyone who has it can open the app**. Treat it as a temporary demo; do not
  post it publicly. Rooms are protected by their code and each member's secret, but there is no
  login.
* If you send your friend a `localhost` address it will not work for them: always open the
  `trycloudflare.com` address first.
* Rooms are lost when the server restarts, so keep the server window open for the whole session.

### 6. Check that everything works (developers)

Needs the full install (`setup.bat` / `bash setup.sh` without `serve`). Windows commands shown;
on a Mac use `venv/bin/python` and `export PYTHONUTF8=1`.

```bat
set PYTHONUTF8=1
venv\Scripts\python.exe -m pytest -p no:cacheprovider
venv\Scripts\python.exe -m ruff check .
venv\Scripts\python.exe -m mypy
```

Expected: every test passes (about 880, plus the browser tests if Playwright is installed), `All
checks passed!`, and `Success: no issues found`. The tests need no data and no internet. If anything
fails on a fresh clone, stop and tell Pranav before changing anything. `PYTHONUTF8=1` must be set
in each new Windows terminal (it prints with cp1252 otherwise and scripts that print quotes crash
with `UnicodeEncodeError`).

### 7. Rebuilding the data (only if you change the data pipeline)

Skip this unless you are changing `cinewhy/data`, `cinewhy/absa` or `cinewhy/build.py`. Almost
nobody needs it: use the ready-made zip above.

Be aware that **v13 is not one command.** It is a base build plus several later steps (more
languages and series, ratings-only titles, the cast file, and where-to-watch from TMDB). The
where-to-watch step alone takes about nine hours and needs a TMDB API token (kept in an environment
variable, never in a file or a commit). The recipe, flags and decisions are recorded in
[`docs/HANDOVER.md`](docs/HANDOVER.md) and [`docs/DECISIONS.md`](docs/DECISIONS.md) (D-027 to
D-038). Budget **about 15 GB of free disk and 5 GB of free RAM** for the base build.

The base build reads five raw files, saved exactly here (create the folders; they are git-ignored).
Kaggle needs you to be logged in; use the *Download* button in the browser (the Kaggle command line
and `kagglehub` have been unreliable for the TMDB file).

| Save it as | Size | Where to get it |
|---|---|---|
| `Data/raw/tmdb1m/TMDB_all_movies.csv` | 0.8 GB | <https://www.kaggle.com/datasets/alanvourch/tmdb-movies-daily-updates> (the file `TMDB_all_movies.csv` inside the download) |
| `Data/raw/rt_mother/rt_mother.zip` | 4.3 GB | <https://www.kaggle.com/datasets/bwandowando/rotten-tomatoes-9800-movie-critic-and-user-reviews> (the downloaded `archive.zip`, renamed; do **not** unzip it) |
| `Data/raw/imdb_ebd/imdb_ebd.zip` | 2.9 GB | <https://www.kaggle.com/datasets/ebiswas/imdb-review-dataset> (the downloaded `archive.zip`, renamed; do **not** unzip it) |
| `Data/raw/aclImdb_v1.tar.gz` | 84 MB | <https://ai.stanford.edu/~amaas/data/sentiment/aclImdb_v1.tar.gz> (do not unpack) |
| `Data/raw/ml32m/ml-32m.zip` | 239 MB | <https://files.grouplens.org/datasets/movielens/ml-32m.zip> (do not unzip) |

Licences and what each file supplies: [`docs/DATASET.md`](docs/DATASET.md). The base build, which
gives the smaller original catalogue unless you add the flags from the docs above:

```bat
python -m cinewhy.absa.polarity --out artifacts\polarity.joblib
python -m cinewhy.absa.polarity_mixed --old-model artifacts\polarity.joblib --out-dir artifacts\v14
python -m cinewhy.build --out artifacts\v14
```

### 8. Working together

* Work on a branch (`git switch -c your-topic`), not on `main`; open a pull request on GitHub.
* Every time you sit down to work, **before anything else**: `git fetch`, `git status`, then
  `git pull --ff-only`. If the pull refuses, stop and ask: your copy and the remote have diverged.
* Set your name once: `git config user.name "Your Name"` and `git config user.email "you@example.com"`.
* Before every push run the three checks in step 6. CI runs the same ones.
* Stage files by name (`git add path/to/file`), never `git add -A`: stray files and data would
  slip in. Never commit anything from `Data/` or `artifacts/`.
* Rules, the Pranav / Lakshay split and the contract in `cinewhy/schemas.py` (changing it is a
  two-person decision): [`CONTRIBUTING.md`](CONTRIBUTING.md). Where things stand and what is left:
  [`docs/HANDOVER.md`](docs/HANDOVER.md). Why things are the way they are:
  [`docs/DECISIONS.md`](docs/DECISIONS.md).

### 9. If something goes wrong

| Symptom | Cause and fix |
|---|---|
| `python` is not recognised, or is older than 3.13 | Install Python 3.13 (step 1), open a **new** terminal; on Windows try `py -3.13`, on a Mac use `python3.13`. |
| `setup` says Python 3.13 was not found | Same: install it, then open a new terminal and run setup again. |
| `UnicodeEncodeError` | `set PYTHONUTF8=1` (Windows) or `export PYTHONUTF8=1` (Mac) in that terminal. |
| `start` says "No data found" | The zip is not unpacked into `artifacts/v13` (check that `artifacts/v13/manifest.json` exists). |
| `ManifestMismatchError` at start | `artifacts/v13` is incomplete or edited: check the zip's SHA-256 (step 4) and unzip it again. |
| The server dies or the machine slows right after "Starting" | Not enough free RAM (it needs about 3 GB): close Chrome and other programs. |
| Port 8000 is busy | Another copy is running: close it (Ctrl+C in its window), or run the server on another port with `--port 8001`. To find the program: `netstat -ano \| findstr ":8000"` (Windows) or `lsof -iTCP:8000` (Mac). |
| `cloudflared` is not recognised | Close the terminal and open a new one after installing; check with `cloudflared --version`. |
| The tunnel address shows an error page | The site is not running: start `start.bat` / `bash start.sh` first and wait for it to open. |
| My friend sees "room closed or expired" | The server restarted or the room sat idle for three hours: start a new room and send the new link. |
| Posters are grey boxes | No internet, or `image.tmdb.org` is blocked by a network filter. The site still works. |

---

## Run it (short version)

```bat
setup.bat serve        rem once. Mac: bash setup.sh serve
rem put the data in artifacts\v13 (step 4), then:
start.bat              rem Mac: bash start.sh   (opens http://localhost:8000/)
```

Posters need no key: the front end loads `image.tmdb.org` URLs directly.

## Test it yourself

### 1. Automated checks (about 15 seconds)

```bat
venv\Scripts\python.exe -m pytest tests -p no:cacheprovider
venv\Scripts\python.exe -m ruff check cinewhy api tests
venv\Scripts\python.exe -m mypy
```

Expected: every test passes (the browser-side helpers run under Node's built-in test runner from
inside pytest), ruff says `All checks passed!`, and mypy says `Success: no issues found`.

The browser tests (`tests/e2e`: the page at eight widths from 320 to 1440 px, watched films, the
library, rating, download and load) need Playwright and are skipped without it:
`pip install -e ".[e2e]"` then `python -m playwright install chromium`, and run the same `pytest`
command. CI runs them in their own job.

### 2. Click through the demo

Open <http://localhost:8000/>.

1. **First visit.** A sheet asks, optionally, for languages, what you like to watch (genres), age and
   region. Answer, press *Save, then rate a few films*, or press *Skip*. Age only sets how strongly
   newer films are favoured; region India puts the Hindi shelf first. Nothing leaves your browser.
2. **Shelves.** One request fills the whole page: *Tonight's picks*, then (once you have liked a
   film) *Viewers like you also watch* and *Something different*, *New and now* (2021 on), *Old
   school* (before 1990), a shelf per language and per genre. No film appears twice.
3. **Quick answers.** Hover a poster (or look at its right edge on a phone): heart = like, eye = I
   have watched it, bookmark = want to watch. Watched films leave every shelf unless you switch off
   *Hide films I've watched*.
4. **Years.** *Old school* and *New* are presets; drag the two handles for any span. With both
   handles at the ends it says *Any year* and nothing is limited.
5. **Receipts.** Click a poster. Each aspect gets one word (Loved, Liked, Mixed, Disliked, Panned),
   what it rests on ("Based on 238 review sentences about acting") and real review sentences with
   their source. After a like, picks say "Because you liked ...".
6. **Rate films** (top bar, or the bottom bar on a phone). One card at a time: rate it, say you have
   not seen it, or that it is not for you. **Library** lists what you watched (with your stars), want
   to watch, liked and said no to, and lets you change any of it.
7. **Profile.** Counts, shortcuts, the older tools (*Your taste*, *Try a review*, *How it works*), and
   *Download my profile* / *Load a profile file* to move your answers to another browser.
8. **Phone.** Resize the window below 640 px: the top bar keeps the search box and the theme
   button and a bottom bar holds Home, Search, Rate, Library and Profile.
9. **How it works.** Every number on this page is read from `eval.json`, including the limits.
10. **Watch together** (Profile sheet, then *Watch together*). Start a room, tick the agreement box, and
    send the invite link (see *Share it with a friend* above). A second person joins in another
    browser; the host presses *Find something for us* and both see one list.

### 3. Poke the API

```bat
curl http://localhost:8000/health
curl http://localhost:8000/facets
curl "http://localhost:8000/search?q=matrix"
curl http://localhost:8000/movie/cw-0468569
curl -X POST http://localhost:8000/discover -H "content-type: application/json" -d "{\"limit\":5,\"languages\":[\"hi\"],\"recency\":0.8}"
curl -X POST http://localhost:8000/shelves  -H "content-type: application/json" -d "{\"profile\":{\"liked_movie_ids\":[\"cw-0816692\"]}}"
curl -X POST http://localhost:8000/recommend -H "content-type: application/json" -d "{\"profile\":{\"aspect_weights\":{\"pacing\":0.9}}}"
curl -X POST http://localhost:8000/analyze   -H "content-type: application/json" -d "{\"text\":\"Great acting but the pacing dragged.\"}"
curl http://localhost:8000/movie/nope          rem 404 with no detail
```

Interactive docs: <http://localhost:8000/docs>.

### 4. Try to break it

* **Tamper test.** Stop the server, open `artifacts\v13\profiles.json`, change one character, start
  the server again. It must refuse to boot with `ManifestMismatchError`. Restore the file (or
  rebuild) to recover.
* **Abuse test.** Send a body over 160 KB (413), more than 120 POSTs in a minute (429), or text
  over 5,000 characters to `/analyze` (422). A forced server error returns only an opaque
  `error_id`, never a stack trace.

### 5. Re-derive the numbers

`python -m cinewhy.build` recomputes everything in `eval.json` from the raw data; the same seed
gives the same numbers. Datasets are checked against pinned SHA-256 hashes where a hash is pinned.

## What was measured

These numbers come from the earlier **v3** evaluation (11,065 films); the current build's figures are on the *How it works* page and in `artifacts/v13/eval.json`. The method is the same. Intervals are 95%.

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
* The catalogue is every title with 200 or more IMDb votes in five languages, not all titles; an obscure one will not be found.
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
start.bat / start.sh      run the demo locally (Windows / Mac)
setup.bat / setup.sh      one-time Python setup (Windows / Mac); `serve` installs only what running needs
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
