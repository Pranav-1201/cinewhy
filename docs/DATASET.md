# The CineWhy dataset: what is in it, where it came from, how it is joined

Numbers below are from the build in `artifacts/v2` (manifest `123a0a7f5da2…`, built 2026-10-26) and
are read from its `eval.json`. Design reasoning is in `docs/FEATURE-004.md`; this file is the
inventory. Raw dumps live in `Data/raw/` and are gitignored.

## 1. What the catalogue contains

| | Films |
|---|---|
| Selected from TMDB (the "spine") | 14,620 |
| Of those, with at least one review | 12,019 |
| **In the shipped catalogue** (at least 5 usable reviews) | **11,065** |
| English / Hindi | 9,858 / 1,207 |
| With any MovieLens rating | 10,229 |
| With evidence scored for at least one aspect | all but a handful (plot 10,940, acting 10,803) |

| Language and era | Films |
|---|---|
| English, before 2000 | 3,566 |
| English, 2000 to 2011 | 3,005 |
| English, 2012 onward | 3,287 |
| Hindi, before 2000 | 262 |
| Hindi, 2000 to 2011 | 475 |
| Hindi, 2012 onward | 470 |

Reviews kept: **1,717,504** (after the per-film, per-source cap of 150 and de-duplication), from which
**179,807** sentences were extracted as quotable evidence.

## 2. Sources

| Source | File on disk | Size | What it supplies | Licence / terms |
|---|---|---|---|---|
| TMDB 1M movies (Kaggle, alanvourch) | `Data/raw/tmdb1m/TMDB_all_movies.csv` | 799,341,936 B | The film list, IMDb ids, language, year, runtime, genres, overview, poster path, IMDb rating and vote count | TMDB terms: attribution required, non-commercial unless licensed |
| Rotten Tomatoes "Mother of all movie review datasets" (Kaggle, bwandowando) | `Data/raw/rt_mother/rt_mother.zip` | 4,253,772,949 B | 55.1M user reviews, joined by title and year | CC BY-NC-SA 4.0 |
| IMDb reviews (Kaggle, ebiswas, "ebD") | `Data/raw/imdb_ebd/imdb_ebd.zip` | 2,888,741,649 B | 5.57M IMDb user reviews to about 2020, joined by title and year | Kaggle dataset terms |
| aclImdb v1 (Maas et al. 2011) | `Data/raw/aclImdb_v1.tar.gz` | 84,125,825 B | 50k labelled reviews with exact IMDb ids; trains the polarity model | Research use |
| MovieLens 32M (GroupLens) | `Data/raw/ml32m/ml-32m.zip` | 238,950,008 B | 26.6M ratings (to Oct 2023) of the catalogue films, 200,938 users | GroupLens research licence: no redistribution |
| MovieLens 25M (older) | `Data/raw/ml-25m.zip` | 261,978,986 B | Superseded by 32M; not used by the current build | as above |
| Amazon Reviews 2023, Movies and TV | `Data/raw/amazon2023/*.jsonl` | 8.4 GB + 1.3 GB | **Measured and dropped:** reviews are of products (DVDs, boxed sets), not films, and rarely carry an IMDb id | McAuley lab terms |

SHA-256 of each archive: re-create it with `sha256sum` on the files above if you need to verify a
re-download.

## 3. How the spine was chosen

Per language (English, Hindi) and release year 1950 to 2025, the films with the most TMDB votes:

* before 2000: 75 English and 25 Hindi per year;
* from 2000: 300 English and 70 Hindi per year;
* a film needs an IMDb number (187,622 rows without one were dropped); three duplicate IMDb numbers
  were collapsed.

Popularity is vote count, so obscure films are underrepresented by design.

## 4. How reviews are joined to films

* **aclImdb and MovieLens:** exact IMDb number.
* **Rotten Tomatoes and ebD:** normalised title plus year. Exact year first; plus or minus one year only
  for English films and only when both runtimes are known and agree within 15 minutes; a runtime check
  on every match; ambiguous titles are refused; two films claiming one RT film are settled by exact
  year, otherwise both are dropped. ebD matches only the pattern `Title (YYYY)`, so TV series cannot
  match.
* **Excluded reviews:** spoiler-flagged, profane, under 40 characters. RT `:fresh:` and `:rotten:`
  prefixes and edit notes are stripped. Identical text in two sources is kept once.
* **Cap:** at most 150 reviews per film per source, chosen by a hash of the review id (reproducible).

Link results (spine films, by language):

| | English | Hindi |
|---|---|---|
| Rotten Tomatoes: exact year | 5,612 | 72 |
| Rotten Tomatoes: adjacent year, runtime-confirmed | 513 | 0 |
| Rotten Tomatoes: no match | 5,382 | 2,995 |
| ebD: exact year | 8,239 | 2,019 |
| ebD: no match | 3,305 | 1,050 |

Reviews kept per source after the cap: aclImdb 28,538; ebD 839,245; Rotten Tomatoes 862,524.

**Hindi films get their reviews almost entirely from ebD.** Only 72 Hindi films link to Rotten
Tomatoes.

### Is the join right? An independent check

How often does a review name its own film's title, against how often it names the neighbouring film's
title (a wrong match would push the first rate down to the second):

| Source | Reviews checked | Name their own film | Name another film |
|---|---|---|---|
| aclImdb | 25,883 | 43.7% | 0.25% |
| ebD | 762,700 | 38.5% | 0.15% |
| Rotten Tomatoes | 770,860 | 11.0% | 0.06% |

RT reviews are short, so they name their film less often, but the gap is about 190 to 1.

## 5. What the data cannot tell you

* **Polarity model:** trained only on aclImdb. Accuracy on newer text: ebD 88.4% (95% CI 87.3 to
  89.4, n=3,362); **Rotten Tomatoes 75.0% (73.9 to 76.1, n=6,000)**, against 89.3% on aclImdb's own
  test set. It is weakest on exactly the source that supplies most post-2011 reviews. Retraining on
  mixed sources is an open decision (DECISIONS D-017).
* **Aspect finder:** a word list. On 300 random clauses it found 32 of 63 real mentions (51%), and 32
  of 53 flagged mentions were really about that aspect (60%).
* **MovieLens** mostly covers English-language films; Hindi films have few ratings, so collaborative
  filtering cannot be measured, or help much, for them. They are ranked on reviews and IMDb scores.
* **Selection:** the catalogue is the popular top of each year, not all films.

## 6. Recommender measurement (2,000 held-out MovieLens users)

Hit rate at 20 (one hidden liked film lands in the top 20 of 11,065), mean and 95% interval:

| Method | Hit@20 |
|---|---|
| Most popular | 8.3% (7.2 to 9.6) |
| Viewers with similar taste | 20.1% (18.3 to 21.9) |
| Review aspects alone | 5.5% (4.6 to 6.6) |
| Both together (shipped) | 18.9% (17.1 to 20.7) |

Similar-taste beats popularity by 11.8 points (10.1 to 13.5). The hybrid is 1.3 points below
similar-taste alone (difference interval minus 2.2 to minus 0.4 at 20), so slightly worse, not better;
the review aspects are kept in the blend because they are what produces the quotes, not because they
raise the hit rate. Validation hit@20 was identical (0.184) for shrink 10, 50 and 200, so that
setting does not matter at this scale.
