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

---

## D-011 · 2026-09-30 · Claude Sonnet 5.5
### Model comparisons come from `cinewhy.absa.train.run_experiment`, and it names no winner inside the noise

**Decision.** Any model comparison reported from this project is produced by `run_experiment`.
It deduplicates, splits, cross-validates on the training rows only (vectorizer refit in every
fold), and names a winner only when the lead over second place is at least the larger of the two
fold standard deviations. Test accuracy is computed once, after selection, for every candidate,
and is reported but never used to choose.

**Why.** The three methodology rules were promises in prose until now (CONSTRAINTS #1-#3). The
harness makes them structural, and each is guarded by a test that was watched to fail: a control
proving a test-only token does reach a vocabulary fitted on train plus test, a sequence that
records every row selection reads, a spy vectorizer that logs every document it is fitted on, and
ten planted bugs, all killed.

**First real-data result** (`python -m cinewhy.absa.train --sample 10000`, seed 42, negation kept,
no stemming, 5-fold CV):

| Model | CV mean ± sample std | Test (one evaluation) |
|---|---|---|
| MultinomialNB TF-IDF | 0.8375 ± 0.0129 | 0.8362 |
| MultinomialNB BoW | 0.8306 ± 0.0115 | 0.8267 |
| BernoulliNB BoW | 0.8323 ± 0.0116 | 0.8367 |

9,982 unique of 10,000 rows (18 duplicates removed); 7,986 train, 1,996 test. Winner by CV:
**none**, since the 0.005 lead is well inside a fold std of about 0.012. The test column spans
0.010, which is the same size as the spread, so it cannot rank them either.

**Caveat, read before comparing with D-009.** This CLI draws its sample with Python's `random`,
not pandas' `sample(random_state=42)`, so it is a different set of 10,000 rows, a different
split, and a different duplicate count (18 here, 22 there). It is not a like-for-like rerun. The
fold std is also larger (about 0.012 against 0.006 to 0.010). What carries over is the
conclusion, not the digits: about 0.83 to 0.84, and the three candidates are not separable.

**What this rules out.** Naming a best model from test accuracy, quoting any accuracy without its
spread, and treating this table and D-009's as one series.

---

## D-012 · 2026-10-22 · Claude Sonnet 5.5
### Join reviews to films on the IMDb title number from aclImdb's `urls_*.txt`, not on Amazon ASINs

**Decision.** The review corpus is the original aclImdb v1 archive, whose `urls_pos/neg/unsup.txt`
give the IMDb title page of every review (line N of each file belongs to review file `N_<stars>.txt`).
That number joins exactly to MovieLens `links.csv`. This resolves HANDOVER item H-1 without any
fuzzy ASIN-to-film matching. The Kaggle CSV that `Data/` holds had dropped these files, which is
why D-002 found it keyless.

**Evidence (RAN 2026-10-22).** 100,000 URL lines, 14,127 films; 7,897 exist in MovieLens; 2,355 have
at least 10 reviews and form the catalogue. A misaligned join would show as reviews that do not
mention their film: 39.8% of 44,768 reviews name their own film's title against 0.14% when each film's
reviews are paired with the next film's title (`title_match_rate`, tested with a deliberately shifted
join).

**Caveats.** Up to 30 reviews per film, mostly from before 2012, so the catalogue is old films only.
ai.stanford.edu was unreachable from the development machine, so the tarball came from a Hugging Face
mirror (`NolanChai/aclImdb_v1`); `cinewhy.data.fetch` accepts any mirror only if the bytes match the
pinned SHA-256 (size 84,125,825 as published).

---

## D-013 · 2026-10-22 · Claude Sonnet 5.5
### Score clauses, not reviews; measure clause accuracy on hand-labelled samples and disclose who labelled

**Decision.** Sentences are split at contrast markers (`but`, `however`, `although`, `though`, `yet`,
`whereas`, `;`) into clauses that are verbatim substrings, so "great acting but dull plot" gives each
aspect its own polarity. Only clauses with |polarity| >= 0.2 count as opinions; neutral mentions would
dilute means and inflate support. Rewatchability is read by rule ("watch it again", negated only by a
negator within six words before the phrase) because normalisation strips "again".

**Why.** The polarity model is trained on whole reviews (official test 89.27% +/- 0.38, evaluated once;
CV 88.80 +/- 0.89 vs 89.72 +/- 0.56, so C=10 wins by 0.0092 against a fold std of 0.0089: barely).
On clauses it is out of distribution, so it was measured on its own.

**Gold sets.** `tests/data/aspect_gold_dev.jsonl` (154 clauses) was used to tune the lexicon;
`aspect_gold_heldout.jsonl` (98 clauses, fresh sample, new lexicon, no shared reviews) is reported.
Held-out: detector precision 86.7% [78.6, 92.1]; clause polarity 82.6% [72.0, 89.8] (n=69), 86.4% at
the evidence threshold (n=59). Before the lexicon fixes the dev sample gave 76.0% precision and 77.9%
polarity, so the fixes were worth about 6 and 2 points, on the data they were tuned on.

**Disclosure.** **The labels were written by the assistant, not an independent human**, and each row
says `labelled_by: assistant`. Recall of the aspect lexicon is not measurable from a sample drawn from
what it flagged. Known remaining failure: negation inside short clauses ("aren't terrible" scores
strongly negative).

**Found by reading output, not by metrics.** "win High Points on the Score Board" was quoted as
soundtrack evidence; fixed and pinned by a test.

> **Correction (D-015, 2026-10-25):** the 86.7% detector precision above came from a sample drawn
> from the detector's own flags and must not be quoted. On random clauses recall is 50.8% and
> precision 60.4%. The 82.6% clause-polarity figure was close: pooled clean samples give 82.5%.

---

## D-014 · 2026-10-22 · Claude Sonnet 5.5
### The recommender is collaborative filtering plus an explanation layer; the aspect blend costs accuracy and says so

**Protocol.** Users are split by user: train, 1,000 validation, 2,000 test. Similarity and popularity
are fitted on train users only; the similarity shrinkage and the aspect-fit share are chosen on
validation users only; test users are read once. Each test user hides one liked film (rating >= 4) and
gives the ranker up to ten others. Hit-rate@k with bootstrap 95% intervals; differences are paired over
users; ties count against the method.

**Result (RAN, seed 42).** hit@20: popularity 0.150 [0.134, 0.166]; CF 0.398 [0.376, 0.419]; aspect
fit alone 0.119 [0.104, 0.134]; hybrid 0.385 [0.364, 0.405]. CF beats popularity by 24.7 points
(interval [22.6, 26.9]). Aspect fit alone is significantly *worse* than popularity (-3.1 points). The
hybrid costs 1.3 points against pure CF (paired [-2.1, -0.4]).

**Decision.** Keep the aspect layer because it is the product (every pick is explained with real
sentences), but do not claim it improves accuracy. With inferred taste the aspect share is the largest
whose validation hit@20 stays within one standard error of CF (rule fixed before looking): 0.2, from
candidates 0 to 0.45 (0.45 cost 5 points on validation). When the viewer sets sliders themselves the
share is 0.45: they asked for aspect-driven results. **That explicit case cannot be validated offline**
(no ground truth for stated preferences) and is documented as such.

**Also found and fixed.** A first 45% blend cost 6.5 points of hit-rate@20; a single liked film with
no positive aspect silently dropped viewers onto the popularity list (now shows the film's own
best-supported praise with `user_weight = 0`); a manifest that hashed a log file still being written
would have failed verification on the next boot (now takes an explicit file list).

> **Update 2026-10-25.** Numbers here are for the first build (2,355 films). After D-015 the
> catalogue is 4,164 films and the figures are CF 0.349 [0.327, 0.370], popularity 0.126
> [0.113, 0.141], hybrid 0.338 [0.317, 0.359] at hit@20; the hybrid costs 1.1 points against CF
> (paired [-2.0, -0.3]). The conclusions are unchanged.

---

## D-015 · 2026-10-25 · Claude Sonnet 5.5
### Measure the aspect finder on random clauses; report what failed; widen the catalogue to 5 reviews

**Correction.** D-013 reported aspect-detector precision of 86.7% from a sample drawn from clauses
the detector had already flagged. That design cannot count misses and inflates precision. Replaced by
three uniform random samples of clauses from the aclImdb test split (A: 200, B: 300, C: 300),
labelled by the assistant before looking at what the detector flagged. **D-013's precision figure
should not be quoted.**

**Result on clean sample C** (nothing tuned on it): recall **50.8%** [38.8, 62.7] (n = 63 real
mentions); precision **60.4%** [46.9, 72.4] (n = 53 flags); polarity sign on found mentions **82.5%**
[72.7, 89.3] (n = 80, samples B and C pooled; the cue layer was not tuned on either).

**What did not work, kept so nobody repeats it.**
1. *Hand-added lexicon terms.* After tuning on A's misses, recall on A rose from 54.5% to 93.2%.
   On the fresh sample B it was 47.9% before mining and 71.2% after tuning on B. On clean C the
   expanded lexicon scored recall 54.0% / precision 53.1%, versus the old lexicon's 49.2% / 62.0%:
   about +5 points of recall for -9 of precision. A per-term ablation on A+B (keep a term only if it
   recovered at least one true mention and added no false flag) pruned the list; the pruned lexicon
   scores 50.8% / 60.4% on C, indistinguishable from the old one. Generic words were the worst:
   `characters?` added 3 true and 13 false matches.
2. *Weak supervision.* A classifier trained on 478,073 train-split clauses, labelled by the lexicon
   with every trigger word masked, combined with the lexicon by OR. On dev samples recall rose from
   79.5% to at most 82.1% while precision fell from 73.8% to 49.0%. Under a threshold rule fixed in
   advance (most recall within 3 points of the lexicon's dev precision) no threshold qualified.
3. *The polarity cue layer* (`apply_cues`: explicit positive and negative cue words, flipped by a
   nearby negator) lifted the dev and held-out gold sets from 0.800 to 0.863 and 0.826 to 0.913, but
   those were the sets it was tuned on. On clean data it is 80.8% without and 82.1% with the layer
   (n = 78): +1.3 points, not significant. It stays because it fixes explicit negation patterns that
   unit tests pin ("aren't terrible"), not because it is proven to help.

**Catalogue threshold.** `min_reviews` default 10 to 5: 2,355 to 4,164 films, same relative
recommender quality (CF is 2.8x popularity at hit@20 versus 2.65x). Films with few reviews simply
report fewer aspects, each with its support.

**Slider check.** For each aspect, the top 20 with that slider at 100% had average aspect score
+0.30 to +0.45 above the default list. This shows the controls point the right way. It does not
validate that stated preferences predict enjoyment, which has no ground truth.

**Still open.** All labels are the assistant's. The kit for an independent second labeller is
`tests/data/aspect_label_sheet.csv` + `docs/LABELLING.md` + `python -m cinewhy.absa.agreement`.

## D-016: the catalogue is the popular top of each year, joined by IMDb number (2026-10-26, Sonnet 5.5)

Per language (English, Hindi) and year, the films with most TMDB votes: 75 en / 25 hi before 2000,
300 en / 70 hi from 2000 (the user's stated ranges). Rotten Tomatoes and ebD reviews join by title and
year with a runtime check; the independent title-name check gives own-film rates of 43.7%, 38.5% and
11.0% against 0.25%, 0.15% and 0.06% for the neighbouring title. Result: 11,065 films with at least 5
reviews. Hindi reviews come almost entirely from ebD (72 Hindi films link to RT). Full inventory:
`docs/DATASET.md`.

## D-017: retrain the polarity model on a mix of sources; shipped (2026-10-26, Sonnet 5.5)

**Problem.** Trained only on aclImdb (2011 IMDb text), the model was right on 89.3% of aclImdb's own
test split but only 78.2% of Rotten Tomatoes reviews from films it never saw (75.0% on the first,
review-hash sample; 88.4% on ebD). Rotten Tomatoes supplies most post-2011 evidence.
**Experiment** (`cinewhy/absa/polarity_mixed.py`; rules written in its docstring before any result):
training pool = aclImdb train + 50,000 labelled Rotten Tomatoes and 50,000 ebD reviews (stars give
the label, the middle of the scale left out), taken only from films whose hash puts them on the
training side (one film in five is held out with ALL its reviews, so film names cannot leak). Old and
new model scored on identical held-out samples (aclImdb official test split; 6,000 balanced reviews
each from held-out RT and ebD films) with a paired bootstrap. Ship rule fixed in advance: RT must
improve with the whole interval above zero, and aclImdb and ebD may lose at most one point.
**Result** (new minus old, points of accuracy, 95% interval): Rotten Tomatoes 78.2% to 83.6%,
**+5.4 [+4.5, +6.3]**; ebD 89.3% to 91.1%, +1.8 [+1.1, +2.4]; aclImdb 89.3% to 90.5%, +1.2 [+0.9,
+1.5]. Every source improved, so the rule was met and the new model ships (`artifacts/v3`). Clause
polarity on the 80 hand-labelled clauses rose from 66 to 71 right (82.5% to 88.8%).
**Limits.** The regularisation strength was chosen by cross-validation by review, which is
optimistic about film names for the new sources (it only picked C; the cross-validation could not
separate the two candidates and the pre-declared default C=1 was used). Labels come from star
ratings, not annotators. Rotten Tomatoes is still the weakest source (83.5%). The held-out sets are
scored by `polarity_mixed --domain-only`; the older `domain_check` samples by review hash and would
include films this model trained on, so it is only valid for the aclImdb-only model.

## D-018: the hybrid does not beat similar-taste alone; aspects stay for the quotes (2026-10-26, Sonnet 5.5)

On 2,000 held-out MovieLens users, hit@20 (v3 build): popularity 8.3%, similar-taste 20.1%, aspects
alone 6.6%, hybrid 19.0%. Hybrid minus similar-taste is -1.1 points at 20 (interval -2.05 to -0.2):
slightly worse (-1.25 [-2.15, -0.35] on the earlier v2 build).
The aspect blend stays because every pick needs its sentences, not because it raises the hit rate;
the About page says so. Validation hit@20 was identical (0.184) for shrink 10, 50 and 200.

## D-019: demographic recommendations ship OFF; age and region only set defaults (2026-10-26, Sonnet 5.5)

**Question.** Does a visitor's age or sex, with nothing else known, predict what they will like?
**Protocol** (`experiments/demographics_ml1m.py`, MovieLens-1M: 6,040 users, 3,883 films): users split
50/50 with a fixed seed before any fitting; a per-group genre-taste prior fitted on training users;
variant (age x sex, age, sex) and strength chosen on a validation slice of the training users; test
users scored once. One liked film hidden per user, the ranker sees only age and sex, hit@20.
**Result.** Validation: every variant within about 0.5 points of popularity (5.4%), inside the
noise of 1,005 users. Test (n = 3,019): popularity 6.5% [5.6, 7.4]; the validation-chosen variant
(sex, strength 0.2) +0.03 points [+0.00, +0.10]. For context, not used for selection: age x sex
+0.13 [+0.03, +0.26], age +0.10 [+0.00, +0.23]. An effect of a tenth of a point on a 6.5% base is
not worth a feature that asks strangers for personal details.
**Decision.** Off. The sex question stays hidden (`Facets.demographics_enabled` is not sent), no
demographic term enters the ranking, and the first-visit sheet says nothing is inferred. Age keeps
one job (the default "how new" setting) and region India keeps one job (Hindi shelf first); both are
interface defaults the visitor can change, not predictions.
**Limits of the test.** ML-1M has no location (only a US zip code), so region could not be tested
at all; its users joined in 2000 and rated until 2003, so even a positive result would describe
people from that era; and it measures genre taste only.

## D-020: the "how new" lift is free up to 50% and costs hit rate above that (2026-10-26, Sonnet 5.5)

`python -m cinewhy.recsys.recency_check` re-ran the held-out protocol (2,000 test users, same split;
it reproduces the `recommender` block exactly) with the live `recency_lift` added to the hybrid.
Change in hit@20 against the hybrid without the lift, mean [95% paired interval]:

| How new | Change in hit@20 |
|---|---|
| 25% | +1.15 points [+0.35, +1.95] |
| 50% (default) | +0.95 points [-0.15, +2.10], no measurable difference |
| 80% (was the default for under 25s) | -2.80 points [-4.25, -1.40] |
| 100% | -7.05 points [-8.55, -5.55] |

(Measured on the v3 build; the v2 build gave +1.45, +0.90, -2.50 and -6.25 for the same settings.)
Baseline hybrid 19.0% [17.2, 20.85]. First-page mix for an unknown visitor (same file, `cold_start`):
6 of 20 films from 2000 on at no preference, 13 at 25%, 18 at 50%, 20 at 80% and 100%.
**Decision.** Keep the lift, and cap the age-based default at 50%, the highest setting measured as
free: under-18, 18 to 24 and 25 to 34 start at 50% (they used to start at 80%, 80% and 60%), 35 to 44
at 40%, 45 and over at 25%. The first page still has 18 of 20 films from 2000 on. A visitor can raise
the slider to 80% or 100% and the *How it works* page prints what that costs. (Changed after
Pranav asked for everything outside deployment to be finished; the one test that pinned the old
values was updated to the new ones on purpose.) **Caveat:** the evaluated hybrid ranks with MovieLens popularity, not the IMDb
scores the live list uses, and MovieLens users rated films of every year, so this is the cost for
people who rate old and new films alike.

## D-021: the profile lives in the browser as one exportable object; accounts come later (2026-10-27, Sonnet 5.5)

**Decision (Pranav, "browser now, accounts later").** Everything a visitor says (likes, not for me,
watched with optional 1 to 5 stars, want to watch, favourite genres, languages, year range, age and
region) is one versioned object in `localStorage` (`cinewhy.profile.v3`), with Download and Load as
a JSON file, so a person can move browsers now and an account can adopt the same shape later. The rules
(one list per opinion, ratings only for watched films, capped well-formed id lists, migration of the
v2 key and of the old four era chips) are in `web/js/profile.js` and pinned by 22 Node tests; 11
planted bugs were each caught. **Limits changed to carry it:** `exclude_movie_ids` 500 to 3,000 and the
request body 64 KB to 160 KB, because the watched list travels with every shelf request. Two guard
tests that pinned the old numbers were re-pinned to the new boundary on purpose, with a new test that
the largest library the browser can send is accepted. **Not decided:** what a star rating is worth to
the ranker. Today 4 and 5 stars count as a like and 1 and 2 as a dislike (`opinionForStars`); how
many answers it takes is measured in D-025, what a single star is worth is not.

## D-022: one request returns every shelf, and a short shelf is left out (2026-10-27, Sonnet 5.5)

`POST /shelves` (`cinewhy/recsys/shelves.py`) replaces one `/discover` call per row. `discover()` was
split into `score_films` (the costly pass) and `select_items` (cheap per shelf) with unchanged behaviour
(27 existing tests). Shelves in order: picks (spotlight plus 15), similar viewers, explore, new (2021
on), old school (before 1990), one per language with at least 25 films (English, Hindi, Japanese,
French), one per top genre. No film is on two shelves; watched, liked and disliked films never appear;
a shelf under 4 films is not shown. **The language ratio is a catalogue ratio, not an exposure ratio**
(Pranav's clarification), so there is no language mixer: the mix comes from how many films each
language has. *Explore* first offered famous but mediocre films under a "well reviewed" heading; it now
needs the top quarter by shrunk IMDb rating, and its subtitle says popular and well rated. Measured in
a browser: 13 shelves, 256 films, no repeats, one 76 ms request.

## D-023: receipts say a word, then what it rests on (2026-10-27, Sonnet 5.5)

The signed score is no longer printed. Five words from symmetric bands (Loved at 0.5 and up, Liked at
0.2, Mixed between, Disliked at minus 0.2, Panned at minus 0.5), the basis in plain words ("Based on 238
review sentences about acting"), and the raw score in a hover. This changes presentation only: no score
or ranking changed. **Open:** the bands are a judgement, not a measurement; the true share of positive
sentences per aspect needs a build change (roadmap B4).

## D-024: the Docker image is runtime-only and CI boots it on synthetic artifacts (2026-10-27, Sonnet 5.5)

The Dockerfile used to fetch `ml-25m.zip` and rebuild the old pipeline; its CI job failed on four
commits with a certificate error and never described build v3. The image now holds code and web files
only; artifacts are mounted or downloaded at start and still verified against the manifest.
`tests/smoke_artifacts.py` writes a six-film verified set, and the CI `docker` job boots the image on it
and probes `/health`, `/recommend` and the page. **Unverified until the branch is pushed:** Docker is not
installed here, so the image build has never run; everything else in that job was run locally.
**Follow-up.** A free host has no volume holding the 365 MB set, so the image's start command runs
`python -m cinewhy.artifacts.download` first: if no manifest is present it downloads
`$CINEWHY_ARTIFACTS_URL` (https only), requires the zip's SHA-256 to equal
`$CINEWHY_ARTIFACTS_SHA256`, and unpacks it, refusing paths that escape the folder, symlinks, an
oversize archive and an archive with no manifest. 16 tests; 12 planted bugs, each caught either alone
or (for the overlapping path checks, which back one another up) when all path checks are removed
together. Where the zip is hosted, and whether its licence allows that, is still Pranav's decision.
**Rate limit behind a proxy (SOURCE-ONLY, not exercised).** The limiter keys on the connecting
address, so behind a host's proxy every visitor would share one 120-a-minute budget. uvicorn's
documented `FORWARDED_ALLOW_IPS` setting makes it read the real address from `X-Forwarded-For`; the
Dockerfile says to set it to `*` only where the container is reachable through the proxy alone. A
check from a real proxied deployment is still owed.

## D-025: three liked films roughly double the first page; keep the 12-card Rate deck and let people go on (2026-10-27, Sonnet 5.5)

`experiments/seed_curve.py` replays the held-out protocol (D-018) giving the ranker 0, 1, 2, 3, 5, 10
or 20 of a user's liked films; same 2,000 test users and same hidden film at every count, similarity
and popularity fitted on training users only, shrink 200 and aspect-fit share 0.45 as `eval.json`
chose. Hit-at-20 for the shipped hybrid, mean and 95% interval: **0 films 6.7% [5.6, 7.7]; 1 8.7%
[7.5, 10.0]; 2 11.3% [10.0, 12.8]; 3 12.9% [11.5, 14.3]; 5 13.6% [12.0, 15.2]; 10 16.0% [14.4, 17.5];
20 17.8% [16.2, 19.5]**. Paired gains: 0 to 1 +2.1 points [+0.5, +3.5]; 1 to 2 +2.6 [+1.5, +4.0]; 2 to
3 +1.6 [+0.4, +2.6]; **3 to 5 +0.7 [-0.6, +1.9] (not distinguishable from zero)**; 5 to 10 +2.5 [+1.2,
+3.7]; 10 to 20 +1.8 [+0.7, +3.0]. Pure collaborative filtering scores 18.8% at 20 films against the
hybrid's 17.8%, the same direction as D-018. **Decision.** The first three answers are worth the most
(they double the cold-start rate), so the Rate dialog stays at 12 cards, since a person likes
perhaps a third to a half of the films they have seen, and offers "Show me more films" at the end.
**Limits.** Only users with at least 21 liked films qualify (so every count uses the same users); they
are heavier raters than a typical newcomer, so read the curve for its shape, not as the rate a new
visitor will see. The deck is chosen for variety, not for films a person has probably seen; choosing
films people are likely to know would raise the number of useful answers per card and is untested.

## D-026: do not weight films by review count (2026-10-27, Sonnet 5.5)

Pranav's idea: films with few reviews should count for less, so thin evidence cannot lift a film.
`experiments/confidence_weight.py` multiplies each film's hybrid score by n/(n+k), n being its review
count, under the D-018 protocol. The rule was fixed before looking: k chosen among 10, 50, 200 on
1,000 validation cases, adopted only if it beat no weighting by more than one standard error. Validation
hit-at-20: **none 0.192; k=10 0.197; k=50 0.189; k=200 0.180**; standard error 0.012, so the best
gain (+0.005) is inside it and **no weighting was chosen**. Test (2,000 cases, read once), paired
difference from unweighted with 95% interval: k=10 +0.001 [-0.003, +0.005]; k=50 +0.0005 [-0.0055,
+0.007]; k=200 -0.004 [-0.0125, +0.004]. Unweighted test hit-at-20 is 0.190. **Decision.** Do not ship
it. **Limit.** Test users can only be scored on films that have MovieLens ratings, so this shows the
weighting does not help (and at k=200 may hurt) among rated films. It cannot say whether it would
protect users from films that have reviews but no ratings, which is the Tier B case; there the
honest label and the 50-review / 200-vote floors do that job.

## D-027: films with ratings but no reviews are a second tier, outside the similarity matrix (2026-10-27, Sonnet 5.5)

Pranav's rules: a full receipt needs 50 reviews; below that, a film with at least 200 IMDb votes may be
listed with ratings only. **Why a separate tier, not more rows.** `item_sim.npy` is a dense n by n float32
matrix: 11,065 films is 490 MB, so tens of thousands more would be gigabytes, and these films have no
viewer overlap to fill the rows with anyway. They live in `ratings_only.json` (`ro-NNNNNNN` ids) beside the
catalogue, hashed into the manifest only when present, and `Catalogue.index` stays core-only so no code
that indexes the matrix can reach one. **Ranking.** Cold: IMDb rating and votes on the same 0 to 1 scale as
the other tier, plus the recency lift. Personal: 0.1 of that popularity plus 0.45 of genre match (liked
films' genres, dislikes counting half), plus the lift. **0.45 is a judgement, not a measurement**: there
are no ratings for these films to tune it on, so it is set below collaborative filtering's 0.9 on purpose.
**Where they appear.** The new, old school, language and genre shelves, search and the film page; never
the spotlight and picks, "viewers like you" or "something different", which promise quotes or viewer
overlap they cannot back. **How they are labelled.** A "Ratings only" line on the tile, and on the film
page the IMDb rating with its votes and a sentence saying no reviews were read. The card carries
`ratings_only: true`; no reason or quote is ever invented. **Targets.** English 10,000; Hindi 5,250 and
Telugu 2,250 (7,500 at 70/30); Japanese 5,000; French 2,500. They are minimums the owner wants. The build
fills each language from the best-voted films not already in the first tier and reports `short_by` in
`eval.json`, never padding. **Language choices.** English, Hindi, Japanese, French; the Hindi choice also
includes Telugu. **Limits.** Movies only: series need another source (IMDb dumps list them; not built).
Japanese is not split anime : movies : live action, because only films are in the data.

## D-030: TV series are built from IMDb's list, TMDB's details and ebD's reviews (2026-11-01, Sonnet 5.5)

Pranav asked for series in every language (Friends, Mirzapur, anime). **Sources.** IMDb's dumps list which titles
are series (with start year, votes, genres) but carry no language, poster or description; TMDB's `/find` gives
all three from an IMDb number, one request per series (the join is exact, no title matching). Reviews exist for
series only in ebD (aclImdb and Rotten Tomatoes are films): 611,000 reviews over 31,866 series, joined by title and
START year; a key two series share, or a title with no Latin letters, is refused. **Measured supply**
(`experiments/series_reach.py`): about 1,900 series reach 50 ebD reviews (1,704 non-animation, 193 animation),
mostly English; 30,635 series have 200+ IMDb votes. So series follow the film pattern: a modest tier with full
receipts, and a larger ratings-only tier (D-027). **v6** (`artifacts/v6`, manifest `a475a9f294c5`): 25,533 titles;
1,546 series with receipts (230,773 ebD reviews after the cap), 3,892 ratings-only series. English already exceeds
its target (11,104). **IMDb decides a title's type**: TMDB's film list can carry a number IMDb files as a series (the
first build chose one number twice and the catalogue refused it); the series wins and the film row is dropped
(4 in the real build). **Downloader.** `cinewhy.data.fetch_series` is resumable, rate-limited and keeps one connection
per worker: a new TLS connection per request cost 0.7 to 8 seconds here against 0.24 s on a reused one, which
would have been most of a day instead of 26 minutes (24 workers, 20 requests a second). The token is read from
the environment and never written. **Limits.** ebD ends about 2020, so recent series have no reviews and are
ratings-only; there is no season or episode level; series with 50 to 199 votes were never downloaded.

## D-031: Japanese is split 5 : 3 : 2 once series exist (2026-11-01, Sonnet 5.5)

The Japanese 5,000 becomes anime series 2,500, movies 1,500 and live-action series 1,000. **Rules.** Anime is a
Japanese series with the Animation genre; a Japanese FILM is a "movie" whether or not it is animated (the owner:
movies include anime films); any other Japanese series is live action. Films and series compete on votes inside a
bucket; full receipts count first. A build without series keeps the single Japanese target of 5,000. **Result in v6:**
movies 1,500 of 1,500; anime series 2,354 of 2,500 (short 146); live-action series 575 of 1,000 (short 425). The
shortfall is real supply, not a rule: only series with 200+ votes were downloaded, so the 50-vote fallback has no
Japanese series to draw on. Fetching 50 to 199 votes (about 22,000 more requests, 40 minutes) is the lever if
the targets must be met. **Page.** A Films / Series choice, a Series shelf after old school, and an Anime shelf
(Japanese animation, films and series) after the language shelves.

## D-029: a 50-vote fallback fills the short languages; the build is v5 (2026-11-01, Sonnet 5.5)

At the 200-vote floor Hindi, Telugu and Japanese were 3,270 films short of the owner's targets (roadmap
section 19). Pranav chose to lower the floor for them. **Rule.** A language still short once every film with
200 or more IMDb votes is used is filled, best-voted first, from films with 50 to 199 votes, only as far as
its target needs; a language already at target takes none. Because films are taken in vote order, the thin ones
can never displace a better-voted one. **Result** (`artifacts/v5`, manifest `da475cc32788`): 24,967 films, 10,386
with full receipts and 14,581 ratings-only; Hindi 5,250 and Japanese 5,000 reach their targets (1,871 and 715 of
their films are in the thin tier), Telugu 2,217 of 2,250 (651 thin; 33 short, as no more films have 50 votes).
`eval.json` counts the thin films per language (`of_which_below_the_main_floor`). **Check on the page.**
Across the home page, a Hindi-only and a Japanese-only view, no film with under 200 votes is on any shelf (the
fewest votes shown is 1,669): popularity shrinks a thin rating toward the average, so these films fill the count
and are found by search or deep browsing, not by the front page. Recommender quality is unchanged (hybrid 17.95%
against collaborative filtering 18.6% at 20, the D-018 finding). **Limit.** A rating from 50 voters is weak
evidence; the film page states the vote count next to the rating.

## D-028: accent-folded title keys and original-title links (2026-10-27, Sonnet 5.5)

`title_key` kept only ASCII letters, so an accented letter was dropped ("amlie") and a title with no Latin
letters became the bare year, which linked to any film of that year. It now folds accents (and sharp s,
ae, o with stroke), refuses an empty key, and a film may carry its original-language title, tried only
when the English one finds nothing. **Safeguards.** An English-title refusal (ambiguous, runtime) is final;
an original title any other candidate also uses is given up; two films reaching one ebD record both lose
it. Measured on 125,897 candidates: accent folding adds 54 French ebD links (3,799 to 3,853); original
titles add about 2,800 more French and almost none for Japanese, Hindi or Telugu (62, 35, 1). Gather
cache version 3, and the cache key now includes the selection. **Caution.** The venv's editable install
points at the demo folder: a script run from `experiments/` imports the OLD code unless `PYTHONPATH` is
the dev folder (a rerun first showed identical numbers because of it).
