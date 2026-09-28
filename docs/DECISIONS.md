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

---

## D-007 · 2026-09-03 · Claude Opus 5
### The legacy notebook keeps its outputs; the strip gate applies to new notebooks only

**Decision.** `nbstripout --verify` runs in CI over every tracked notebook *except*
`Movie_Sentiment_Analysis.ipynb`.

**Why.** The gate exists for two reasons: committed outputs can leak secrets, and they make
diffs unreadable. Neither applies to this file, and one real cost does.

The committed outputs are the primary evidence for the figures the audit analysed — 0.8350,
0.8330, 0.8255, 0.7820. Those numbers were reproduced by re-running the pipeline, but the
notebook's own outputs are what a reader checks the audit against. Stripping them deletes the
record. The file is also write-once: Phase C replaces it with real modules rather than editing
it, so it will never produce a noisy diff. And the secret-leak risk is already covered by the
`gitleaks` job, which scans notebook outputs along with everything else and passes.

**What this rules out.** Silently exempting future notebooks. The CI step enumerates what it
checked and says so when there is nothing to check, so a carve-out cannot quietly widen into
"we don't check notebooks".

---

## D-008 · 2026-09-03 · Claude Opus 5
### Unimplemented functions raise `NotImplementedError`; their tests are `xfail(strict=True)`

**Decision.** The scaffold ships real signatures with `NotImplementedError` bodies, and every
test covering them is marked `xfail(strict=True)` rather than skipped or omitted.

**Why.** Pranav proposed scaffolding the project with pseudocode so both contributors would have
something to build against. The goal is right; prose is the wrong medium. A `# TODO: compute the
aspect scores` comment is an unverified claim that rots silently the moment the design shifts —
structurally the same failure that put this project at 3.4/10, where documents asserted things
the code did not do.

Failing tests carry the same information and cannot rot, because CI reports the moment they stop
being true. `strict=True` closes the loop: implementing the function makes the test XPASS, which
*fails* the suite and forces the marker's removal in the same PR. A stale marker cannot survive.

Stub bodies raise rather than returning plausible placeholder values, because a stub that returns
fake data becomes a mock-data landmine the instant real code is layered on top (CONSTRAINTS.md #9).

**What this rules out.** Pseudocode bodies, `pytest.mark.skip` (which hides work rather than
queueing it), and stubs returning synthetic data.

---

## D-009 · 2026-09-29 · Claude Sonnet 5.5
### The "1.65 points of leakage" figure did not reproduce; the rule stands, the magnitude does not

**Decision.** No document may quote the 2026-08-26 leak-free numbers (0.8185 / 0.8220 / 0.8200 /
0.7805) or "inflated by 1.65 points" as a measurement. Fit-on-train-only (CONSTRAINTS #1) stays a
hard rule. What changes is the claim about how much it cost on this data. This entry supersedes
the leakage figures and the CV table in D-004, `FLOW.md` F-1 and `AUDIT-2026-08-26.md` C-1/C-2.

**Why.** Phase A required re-measuring inherited numbers before building on them
(CONSTRAINTS #19). On the pinned environment (sklearn 1.8.0, numpy 2.4.4, pandas 3.0.2), same
pipeline, sample of 10,000 rows at seed 42, split at seed 42:

| Model | as written | leak-free, same split | leak-free minus as written |
|---|---|---|---|
| GaussianNB (BoW) | 0.7820 | 0.7830 | +0.0010 |
| MultinomialNB (BoW) | 0.8255 | 0.8255 | +0.0000 |
| BernoulliNB (BoW) | 0.8350 | 0.8355 | +0.0005 |
| MultinomialNB (TF-IDF) | 0.8330 | 0.8310 | -0.0020 |

The as-written column reproduces the notebook's committed outputs exactly, so the pipeline
under test is the right one. The leak-free column does not reproduce the earlier −0.0165.
Repeated over ten split seeds, as-written minus leak-free has mean and spread:

| Model | mean | std | range |
|---|---|---|---|
| GaussianNB (BoW) | -0.0010 | 0.0031 | -0.0045 to +0.0035 |
| MultinomialNB (BoW) | -0.0010 | 0.0013 | -0.0030 to +0.0015 |
| BernoulliNB (BoW) | +0.0000 | 0.0013 | -0.0025 to +0.0015 |
| MultinomialNB (TF-IDF) | -0.0009 | 0.0031 | -0.0050 to +0.0055 |

The effect is not distinguishable from zero on any model. The script that produced the earlier
figures is not in the repository, so the discrepancy cannot be traced and no cause is claimed.

Five-fold CV on the train split (vectorizer refit inside every fold, shuffled KFold, seed 42):
MultinomialNB TF-IDF 0.8345 ± 0.0063, MultinomialNB BoW 0.8297 ± 0.0095, BernoulliNB BoW
0.8294 ± 0.0065 (sample std over folds). TF-IDF leads by 0.0048 to 0.0051, which is **inside**
each model's own fold spread. The direction of D-004 survives; its "order of magnitude" wording
and its ±0.011 spread do not. Two of the three are tied to 0.0003.

**What still holds.** The leakage is real in structure (test rows shaped the vocabulary and IDF
weights) and is still forbidden. The negation defect (D-003) reproduced today: both witness
sentences clean to `movi good`, produce identical vectors and are both predicted 0. Duplicates
(H-2): 5 of 2,000 test rows have a twin in train, all with agreeing labels.

**Honest baseline.** About 0.83 leak-free on this sample, not the ~0.82 the audit projected. The
Phase C story is therefore not "the headline was inflated"; it is "the headline cannot
distinguish the models, and the model cannot read negation".

**What this rules out.** Quoting a leakage cost as a measurement, or telling a reader the
original 0.835 was inflated. Both were true only of the earlier, unreproducible run.

---

## D-010 · 2026-09-29 · Claude Sonnet 5.5
### `cinewhy.text.normalise` keeps negation, embeds its stoplist, and does not stem

**Decision.** `normalise` is standard library only. It strips HTML, lowercases, expands
`n't` contractions to `not`, replaces non-alphanumerics with spaces, and drops stopwords from
an embedded copy of NLTK's English list (198 words, nltk 3.9.4) minus the negation carriers.
It does not stem.

**Why.**
- *Embedded list, no stemming:* CI and the request path install neither nltk nor its downloadable
  corpus, and adding a dependency needs approval (CONSTRAINTS #14). Porter stemming lives in nltk.
- *Contraction expansion:* splitting `didn't` on punctuation gives `didn` + `t`, both stopwords,
  so the negation vanished even with `not` protected.
- *Not stemming costs nothing measurable.* Same 10,000-row sample, split and 5-fold CV as D-009,
  vectorizer refit per fold (CV mean ± sample std; A is the notebook's cleaning, B is `normalise`,
  C is `normalise` plus Porter):

| Model | A notebook | B normalise | C normalise + stem |
|---|---|---|---|
| MultinomialNB TF-IDF | 0.8345 ± 0.0063 | 0.8367 ± 0.0088 | 0.8347 ± 0.0076 |
| MultinomialNB BoW | 0.8297 ± 0.0095 | 0.8296 ± 0.0106 | 0.8285 ± 0.0096 |
| BernoulliNB BoW | 0.8294 ± 0.0065 | 0.8266 ± 0.0031 | 0.8291 ± 0.0051 |

Every difference between pipelines (largest 0.0028) is inside the fold spread. Column A
reproduces the D-009 figures exactly, so the harness is the same.

**What it does and does not buy.** "This movie was not good at all." and "This movie was good."
now clean to `movie not good` and `movie good` and produce different vectors. Both are still
predicted negative by a MultinomialNB TF-IDF model, and accuracy did not measurably move. A
unigram bag of words can carry the word `not`, but cannot combine it with `good`. Reading
negation properly is a modelling problem for later in Phase C, not something this step solves.

**What this rules out.** Claiming the negation fix improved accuracy, and importing nltk into
`cinewhy.text` without a new decision.
