# DECISIONS.md

> Code shows *what* changed. This shows *why*. Field Guide habit #2.
> Append only. Never edit a past entry — supersede it with a new one and link back.

**Format:** `D-NNN` · date · decider · model version · decision · why · what it rules out.

---

## D-001 · 2026-08-26 · Pranav + Claude Opus 5
### Reposition from "sentiment classifier" to "recommender with review-grounded explanations"

**Decision.** The project's product is a movie recommender whose distinguishing feature is that every
recommendation carries aspect-level evidence drawn from real review text. The IMDB sentiment work is
demoted from *the product* to *one component* (the ABSA model's training corpus).

**Why.** Two honest observations:
1. Standalone IMDB sentiment classification is a commodity. A fine-tuned transformer reaches the low
   90s on this dataset and a frontier LLM does comparably zero-shot. A 1,000-feature Naive Bayes at
   0.82 has no defensible position, and no consumer wants a sentiment API.
2. Standalone collaborative filtering is also a commodity (`implicit`, `LightFM`, `surprise`).
   Building another one is not a differentiator either.

The defensible thing is the **join**: per-aspect sentiment attached to recommendable items, surfaced
as evidence. That is a trust/workflow property, which is durable, rather than an algorithmic edge,
which is not. It is also the thing large incumbents do visibly badly ("Because you watched X").

**What this rules out.** Competing on raw recommendation accuracy against MovieLens leaderboards.
Competing on raw sentiment accuracy. Any framing where the notebook's 0.835 is the headline number.

**Supersedes.** The "SentimentStream" framing in `Movie Sentiment Analysis Summary` (E: drive).

---

## D-002 · 2026-08-26 · Claude Opus 5
### The existing dataset cannot power a recommender — acquire item-keyed review data

**Decision.** `Data/IMDB Dataset.csv` stays, scoped strictly to training the sentiment/ABSA model.
Recommendation requires new sources: MovieLens 32M (collaborative signal), TMDB (metadata), and an
item-keyed review corpus (Amazon Reviews 2023, Movies & TV) for aspect scoring.

**Why.** Measured, not assumed: the CSV has exactly two columns, `review` and `sentiment`. No movie
ID, no title, no user ID. There is literally nothing to recommend and no one to recommend it to. Any
plan that skips this step is building on a dataset that cannot support the feature.

**What this rules out.** Every "just add a recommender to the notebook" shortcut.

**Open risk.** Amazon item IDs are ASINs — a *product* (often one DVD edition), not a film. The
ASIN→film mapping is fuzzy. Flagged **reproduce first** in `HANDOVER.md`; do not assume it is clean.

---

## D-003 · 2026-08-26 · Claude Opus 5
### Preprocessing must not delete negation

**Decision.** The current stopword-removal step is rejected for any sentiment-bearing pipeline. The
replacement must either (a) remove `not`/`no`/`nor`/`never`/`n't` from the stoplist and use bigrams,
or (b) drop hand-rolled preprocessing entirely in favour of a subword tokenizer.

**Why.** Measured on 2026-08-26: `"This movie was not good at all."` and `"This movie was good."`
both reduce to the string `'movi good'`, produce byte-identical TF-IDF vectors, and receive the same
prediction. The pipeline is provably incapable of representing negation. This is not a tuning
problem; it is an information-destruction problem, and no amount of model swapping fixes it
downstream of the deletion.

**What this rules out.** Any claim that the classifier "handles context" — and specifically the
report §18 claim that the model weighs `not` as a unigram. It never receives that token.

---

## D-004 · 2026-08-26 · Claude Opus 5
### Model selection moves to cross-validation on train; the test set is touched once

**Decision.** Model/threshold selection uses k-fold CV on the training split only. The test set is
evaluated exactly once, at the end, and its number is reported as-is.

**Why.** The notebook picks its winner by comparing test accuracies (0.8350 vs 0.8330 — a 0.0020
gap). Measured 5-fold CV on train only, same features:

| Model | CV mean ± std |
|---|---|
| MultinomialNB (TF-IDF) | **0.8383 ± 0.0091** |
| MultinomialNB (BoW) | 0.8293 ± 0.0126 |
| BernoulliNB (BoW) | 0.8285 ± 0.0117 |

The 0.0020 winning margin is **an order of magnitude smaller than the ±0.011 fold-to-fold spread**,
and under CV the ranking *reverses*: the notebook's declared winner (BernoulliNB) comes last of the
three. The report's interpretive paragraph — "BernoulliNB dominating reflects a key NLP reality" —
is an explanation of noise.

**What this rules out.** Reporting any model comparison without its spread.

---

## D-005 · 2026-08-26 · Claude Opus 5
### Free tier is a hard architectural constraint, not a preference

**Decision.** Target: FastAPI in Docker on Hugging Face Spaces (free CPU), Next.js static on Vercel
free, artifacts on HF Hub. Everything expensive is precomputed offline. No GPU at serve time, ever.

**Why.** Pranav specified free-tier-only. That constraint propagates into architecture: it forbids
request-time embedding, request-time training, and any model too large for 2 vCPU / 16 GB. Deciding
this now prevents building something that must be re-architected to deploy.

**What this rules out.** Pure-serverless hosts (Vercel/Netlify functions) — no persistent disk and a
~250 MB unzipped bundle cap cannot hold transformer weights plus an ANN index. Render's free tier
(512 MB RAM) is too small for the same reason.

> **Pricing provenance:** the tier limits above are from general knowledge and were **NOT** looked up
> during the audit run. Verify current limits before committing to a host.

---

## D-006 · 2026-08-26 · Claude Opus 5
### The 64 MB dataset is gitignored, not committed

**Decision.** `Data/*.csv` is excluded from git. The repo ships a documented fetch step instead.

**Why.** 64 MB in git history is permanent and bloats every clone. The dataset is also
redistributable only under its source's terms, which a public repo would not satisfy cleanly.

**What this rules out.** `git clone` alone producing a runnable project — hence the explicit data
step in `README.md` and `TEST_CHECKLIST.md`.
