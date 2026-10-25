# FEATURE-004 · Modern, multi-source catalogue (English + Hindi, to 2025)

> Field Guide habit #5 — one file, start to finish.

**Status:** scoping (measurements done, nothing built yet)
**Opened:** 2026-10-26 by Pranav + Claude Sonnet 5.5 · **Model:** Claude Sonnet 5.5
**Plan row:** user request 2026-10-25 "recent films, Hindi films, posters, demographics, new UI" — this is step 1 of 6

---

## What and for whom

The catalogue today holds 4,164 films and the newest is from 2010, because the only review source
(aclImdb) stops in 2011. People born after 2000 are the main audience, so this feature rebuilds
the catalogue from sources that reach 2024-2025 and adds Hindi films. It is the data layer for the
poster, recency, demographics and UI work that follows.

## Why now

Everything else in the request (recency ranking, posters, a "New & Now" shelf) is meaningless on a
2010-capped catalogue. See `DECISIONS.md` D-016 (written when this lands).

## Measured before designing (2026-10-26, scratch scripts, not committed)

| Fact | Number | Source |
|---|---|---|
| RT user reviews | 55,130,430 rows; 35,665,901 (64.7%) have >= 40 chars of text | scan of `user_reviews.csv` |
| RT films | 10,233; English 8,795 + 231 UK; Hindi 105 | `movies.csv` |
| ebD IMDb reviews | 5,570,798 rows, ends ~2020; 225,911 film keys after dropping series | scan of the 6 JSON parts |
| TMDB 1M | `imdb_id`, `poster_path`, `original_language`, `popularity`, cast, keywords | CSV header |
| MovieLens 32M | ratings to 12 Oct 2023; `links.csv` = `movieId,imdbId,tmdbId` | zip |
| Join precision (RT, runtime within 3 min) | English exact-year 91.5% of 5,629; Hindi exact-year 79.5% of 73 | `join_validate.py` |
| ebD series contamination | English films with >= 20 reviews 8,328 -> 7,866 once series are excluded | `join_validate.py` |
| Candidate pool | 14,620 (en 11,550, hi 3,070) from per-year vote_count quotas | `join_measure.py` |
| English with ratings (>= 50) and text (>= 20 reviews) | 2,755 pre-2000; 2,795 in 2000-2011; 2,583 in 2012-2025 | `join_measure.py` |
| Hindi with text | 54 pre-2000; 235 in 2000-2011; 402 in 2012-2025 | `join_measure.py` |
| Hindi with ratings (>= 50) | 11 / 47 / 50 across the same three eras | `join_measure.py` |
| TMDB review text | median 0-6 per film; Hindi 12 of 100 films in 2024 have any | `spike_reviews.py` |
| Amazon 2023 | title-only join; 32 Hindi films after 2020 | `amazon_hindi.py` |

Caveat on the join numbers: they were measured with the loose ebD pattern that includes series and
with the +-1 year fallback, so they are upper bounds; the build recomputes them under the rules below.

## Success criteria — verifiable, not vibes

| # | Criterion | How it is verified |
|---|---|---|
| 1 | Catalogue reaches 2025 and holds English and Hindi films | `eval.json` catalogue block: films per era and language |
| 2 | Every RT match used has runtime within 15 min of TMDB (or no runtime on either side) | unit test + the build prints the rejected count |
| 3 | No ebD series row is ever used as a film | unit test on the tight title pattern |
| 4 | No film is accepted through an ambiguous key | unit test; build prints ambiguous and unmatched counts |
| 5 | Every evidence sentence names its source (`acl/`, `rt/`, `ebd/` prefix) and a URL | test over `evidence.json` |
| 6 | Methodology guards (#1-#3 in CONSTRAINTS) still pass untouched | full pytest, count read |
| 7 | Recommender re-evaluated on the new catalogue, spread reported | `eval.json` recommender block |
| 8 | Every figure quoted in README/docs about the old catalogue is replaced | grep for the old values |

## Scope

**In:** film selection from the TMDB catalogue; ratings from MovieLens 32M; review text from
aclImdb + RT + ebD; per-source provenance; a `meta.json` artifact with TMDB metadata; re-running
the build, polarity check and evaluation; a written overview of the dataset.

**Out:** posters in the UI, recency ranking, demographics, the UI redesign (steps 2-5); Amazon
(measured, dropped); TMDB review text except as a possible later gap filler; any change to
`schemas.py` (a two-person contract file). Extra metadata goes in `meta.json`, merged by the API later.

## Approach

1. `cinewhy/data/spine.py`: read the TMDB CSV and pick candidates per (language, year) by
   `vote_count` with quotas (pre-2000: 75 English, 25 Hindi; 2000+: 300 English, 70 Hindi). Films
   with no `imdb_id` are dropped and counted. The IMDb number stays the key, so `cw-<imdb>` ids of
   existing films do not change.
2. `cinewhy/data/linking.py`: one normaliser and the join rules, pure functions. Exact year only;
   a +-1 year fallback for English only, and only if runtimes agree within 15 minutes; ambiguous
   keys are dropped; ebD uses the tight pattern `(YYYY)` so series never match.
3. `cinewhy/data/reviews.py`: streaming readers for RT and ebD, cleaning RT's leading
   `:fresh:` / `:rotten:` tokens and bracketed edit notes, a deterministic per-film cap (150 per
   source, chosen by hash of the review id) so profiling time is bounded.
4. `build.py` / `sources.py`: parametrise the hard-coded `ml-25m` member names so 32M loads;
   `build_profile` accepts a per-review URL function (backwards compatible); a new `meta.json`
   artifact is hashed in the manifest.
5. Selection rule after linking: a film enters if it has >= `min_reviews` text reviews across all
   sources; films without ratings stay (aspect and popularity ranking can still serve them), their
   similarity row is zero.

**Rejected:**
- Crawling the TMDB API per film: slow and rate-limited; the 1M CSV holds the same fields offline.
- Using Amazon 2023: title-only join, 32 Hindi films after 2020, would need an 8.4 GB scan.
- Treating TMDB review text as a main source: median 0-6 reviews per film, almost none for Hindi.
- Sparse top-k similarity now: dense n x n is fine under ~10k films (about 400 MB). Revisit above that.

## Blast radius

`cinewhy/build.py`, `cinewhy/data/sources.py` (parametrise archive member names),
`cinewhy/absa/extract.py` (`build_profile` URL argument), `cinewhy/artifacts/manifest.py` list in
`build.py`, tests for each. `schemas.py` untouched. `item_sim.npy` grows with the catalogue and is
loaded whole at boot by the API; its size is reported at build time.

## Build order

A. spine + linking with tests (pure, no data). B. readers with tests on tiny fixtures. C. wire into
`build.py`, run end to end on a small slice. D. full build, evaluation, record numbers. E. replace
stale figures, write D-016, dataset overview doc. F. commit with explicit paths.

## Risks

- Title-and-year joins can pair the wrong film (remakes). Mitigation: runtime check, ambiguity drop,
  and a printed unmatched/ambiguous report; residual error is not zero and is stated in the overview.
- RT and ebD voices differ from aclImdb, so the polarity model's old accuracy does not transfer; it
  is re-measured, and the gold-set numbers are quoted only for the text they were measured on.
- Hindi ratings are sparse (50 films with >= 50 ratings after 2011), so Hindi picks lean on aspects.
- Raw data are manual downloads (Kaggle needs a login); `docs/DATASET.md` records filenames, sizes,
  and SHA-256 so a rebuild is checkable.
