# ARCHITECTURE.md

> The shape of the system, so no session has to re-derive the terrain.
> Field Guide habit #6. Update this when a module or a data flow changes — not when a line changes.

**Status:** target architecture. Only the shaded "Today" block below exists on disk as of 2026-08-26.
**Version-pin:** last revised by Claude Opus 5, 2026-08-26.

---

## 1. What this system is

**CineWhy** — a movie recommender that justifies every recommendation with *what real reviewers
actually said*, decomposed by aspect (acting, plot, pacing, visuals, ending, soundtrack).

The one-line difference from every other recommender:

> Netflix says *"Because you watched Inception."*
> CineWhy says *"Because you consistently praise **pacing** and **ending**, and across 1,240 reviews
> this film's pacing scores +0.71 — here are the three sentences that say so."*

The recommender is not the differentiator. Collaborative filtering is a solved, commodity problem
(`implicit`, `LightFM`, `surprise` all do it well). The **aspect-level review evidence layer** on top
of it is the differentiator, and it is a *trust* property, not an algorithmic one.

---

## 2. Today (what actually exists)

```
D:\NLPPROJECT\
├── Data\IMDB Dataset.csv        50,000 rows, 2 columns: review, sentiment
├── Movie_Sentiment_Analysis.ipynb   38 cells, linear, no persistence
├── Movie_Sentiment_Analysis_Report.md
├── check_env.py                 import-presence check
├── requirements.txt             unpinned (>=)
└── setup.bat
```

That is the entire system: **one notebook that trains a Naive Bayes sentiment classifier and forgets
it when the kernel dies.** There is no API, no persisted model, no test, no CI, no container.

### The dataset constraint that shapes the whole plan

`Data/IMDB Dataset.csv` has exactly two columns — `review` and `sentiment`. **No movie ID, no title,
no user ID.** It therefore *cannot* power a recommender of any kind: there is nothing to recommend
and nobody to recommend it to.

Its honest role is narrow and real: it is a **training corpus for the sentiment/ABSA model**, and
nothing else. Recommendation needs separate data (§4).

---

## 3. Target architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  CLIENT — Next.js (static export) on Vercel free tier                   │
│  Search · Movie page · "Why this?" evidence panel · Taste profile        │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │  HTTPS / JSON
┌───────────────────────────────▼─────────────────────────────────────────┐
│  API — FastAPI in Docker on Hugging Face Spaces (free CPU tier)         │
│                                                                         │
│  /search      title search          /movie/{id}   metadata + aspects    │
│  /recommend   ranked list + reasons /explain/{a}/{b}  evidence sentences │
│  /health      liveness              /feedback     thumbs up/down         │
└───┬─────────────────────┬──────────────────────┬────────────────────────┘
    │                     │                      │
┌───▼──────────┐  ┌───────▼─────────┐  ┌─────────▼──────────┐
│ RETRIEVAL    │  │ RANKING         │  │ EVIDENCE           │
│ ANN index    │  │ hybrid scorer   │  │ aspect sentences   │
│ (hnswlib)    │  │ CF + aspect fit │  │ + per-aspect score │
│ item vectors │  │ + diversity     │  │ from ABSA store    │
└───┬──────────┘  └───────┬─────────┘  └─────────┬──────────┘
    └─────────────────────┴──────────────────────┘
                          │  all read-only at request time
┌─────────────────────────▼───────────────────────────────────────────────┐
│  ARTIFACT STORE — versioned, built offline, loaded at boot              │
│  item_vectors.npy · hnsw.index · aspect_scores.parquet                  │
│  evidence_sentences.parquet · absa_model/ · manifest.json               │
│  Hosted on Hugging Face Hub (free, public, versioned by git-lfs)        │
└─────────────────────────────────────────────────────────────────────────┘
                          ▲
                          │  produced by, never at request time
┌─────────────────────────┴───────────────────────────────────────────────┐
│  OFFLINE PIPELINE — runs in CI / locally, never in the request path     │
│  ingest → clean → train ABSA → score aspects → build ANN → manifest     │
└─────────────────────────────────────────────────────────────────────────┘
```

### The load-bearing rule

**Nothing is computed at request time that could have been computed offline.**
The API loads immutable artifacts at boot and serves reads. This is what makes a free CPU tier
viable: no training, no embedding, no model fitting inside a request.

---

## 4. Data sources

| Source | Gives us | Licence note | Status |
|---|---|---|---|
| **IMDB 50k** (on disk) | sentiment training text | research use | have it |
| **MovieLens 32M** | userId, movieId, ratings, `links.csv` → imdbId/tmdbId | non-commercial; **redistribution restricted** — ship the loader, not the data | to acquire |
| **TMDB API** | titles, posters, genres, year | free key; attribution required | to acquire |
| **Amazon Reviews 2023** (Movies & TV) | review text **with item IDs** — the ABSA corpus | free, McAuley Lab | to acquire |

The join that makes the product work:
`MovieLens movieId → links.csv → imdbId/tmdbId → TMDB metadata`, and review text keyed to the same
item so aspect scores attach to a recommendable item.

> **Open risk, not yet resolved:** Amazon Movies&TV item IDs are ASINs (a *product* — often a
> specific DVD edition), not film IDs. The ASIN→film mapping is fuzzy and will need a matching pass
> with manual spot-checks. This is flagged as **"reproduce first"** in `HANDOVER.md`; do not assume
> it is clean.

---

## 5. Module boundaries

| Module | Owns | Must not |
|---|---|---|
| `cinewhy/data/` | loading, joining, splitting | know about models |
| `cinewhy/text/` | preprocessing, tokenisation | know about recommenders |
| `cinewhy/absa/` | aspect extraction + polarity | touch the ANN index |
| `cinewhy/recsys/` | CF, ranking, diversity | do preprocessing inline |
| `cinewhy/artifacts/` | build + load + version artifacts | be imported by the API's request path |
| `api/` | HTTP, validation, errors | contain business logic |
| `web/` | rendering | contain scoring logic |

Any preprocessing function used at training time must be imported by the serving path from the
**same module**. A second copy of the cleaning code is how train/serve skew gets in — and this
project already demonstrates the failure (see `DECISIONS.md` D-002).

---

## 6. What is deliberately NOT here

- **No user accounts in v1.** Taste profile lives in `localStorage`. Removes auth, GDPR, and a
  database from the critical path. Revisit only when retention data justifies it.
- **No real-time model training.** Ever, in the request path.
- **No GPU.** Every model choice must run on 2 vCPU. This is a hard constraint, not a preference.
- **No streaming-catalogue scraping.** "Where to watch" is a licensing minefield; TMDB's
  watch-provider field is the sanctioned route if it is ever wanted.

---

Related: [`FLOW.md`](FLOW.md) · [`CONSTRAINTS.md`](CONSTRAINTS.md) · [`DECISIONS.md`](DECISIONS.md)
