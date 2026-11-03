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
ratings-only; there is no season or episode level. The first download took series with 200+ votes only; the
50 to 199 range was added later for the Japanese split (D-031), giving a 61,136-series cache.

## D-031: Japanese is split 5 : 3 : 2 once series exist (2026-11-01, Sonnet 5.5)

The Japanese 5,000 becomes anime series 2,500, movies 1,500 and live-action series 1,000. **Rules.** Anime is a
Japanese series with the Animation genre; a Japanese FILM is a "movie" whether or not it is animated (the owner:
movies include anime films); any other Japanese series is live action. Films and series compete on votes inside a
bucket; full receipts count first. A build without series keeps the single Japanese target of 5,000. **Result in v6**
(series with 200+ votes only): movies 1,500 of 1,500; anime series 2,354 of 2,500 (short 146); live-action series
575 of 1,000 (short 425). The shortfall was supply, not a rule. **Result in v7** (`artifacts/v7`, manifest
`13179d3c1cde`, after downloading the 30,501 series with 50 to 199 votes, 26 minutes): **every target is met**, 26,105
titles, nothing short. Anime series 2,500 (35 with receipts, 2,465 ratings-only, 146 of them on 50 to 199 votes);
live-action series 1,000 (2 with receipts, 998 ratings-only, 425 on 50 to 199 votes); movies 1,500. So the last 146
anime and 425 live-action series rest on ratings from 50 to 199 voters, and are the ones the page shows last (the
front page, a Japanese-only view and the series shelf were checked: they lead with the well-voted titles). **Page.** A Films / Series choice, a Series shelf after old school, and an Anime shelf
(Japanese animation, films and series) after the language shelves.

## D-032: list every title with 200+ votes in the five languages, with no per-language target (2026-11-03, Sonnet 5.5)

The owner dropped the 4:3:2:1 ratio ("I want as much data as possible") and set the floor at 200 IMDb votes; the
languages stay English, Hindi, Telugu, French and Japanese. **Rule.** `--uncapped` gives every bucket the target
`spine.UNCAPPED` (a billion), so the vote floor alone decides who is listed; the Japanese split buckets stay, and
`eval.json` reports `target: null`, `short_by: 0`. `BuildConfig` refuses `uncapped` with a fallback floor: with no
target to meet, the fallback would never stop lowering the bar and would list every thinly rated title. **Why it
was needed.** The ratings-only tier stopped at each target, and English was already over 10,000 from the receipts
tier, so v7 listed no English title that lacked reviews: nothing from 2025-26 and 1,171 films from 2020-24.
**Result in v8** (`artifacts/v8`, manifest `8d17da05a041`, 19 minutes on the cached gather): 106,069 titles, 11,930
with full receipts (the same core as v7) and 94,139 ratings-only. English 85,574, French 7,427, Japanese 7,161, Hindi
4,277, Telugu 1,630. The page now leads "New and now" with 2025-26 English titles. **Costs, stated.** Hindi, Telugu
and the two Japanese series parts are SMALLER than in v7 (Hindi 5,250 to 4,277, Telugu 2,250 to 1,630, anime series
2,500 to 2,354, live-action series 1,000 to 575) because the 50-vote fallback that filled them is gone: that is the
200-vote floor working, not a fault. `/shelves` takes 0.45 to 0.62 s against 0.16 to 0.23 s on v7 (same machine,
interleaved, six runs each): `all_movies` is rebuilt about 20 times a request and `catalogue_facets` is recomputed
each time (found by profile, not yet fixed). `/discover` 0.17 s, `/search` 0.27 to 0.34 s. The recommender core is
unchanged (validation hit@20 0.171, hybrid weight 0.45, as v7), because ratings-only titles sit outside it.

## D-033: a wider candidate list reaches the films the 50-review build still misses (2026-11-03, Sonnet 5.5)

**Measured** (`experiments/floor50_reach.py`): ebD has 13,684 films with 50 or more reviews. 8,256 are in v8; 2,029
are reachable (one TMDB film in the five languages: English 1,886, French 61, Hindi 40, Japanese 39, Telugu 3); 2,335
match no TMDB film by title and year; 780 are another language (Italian 112, Spanish 95, German 79); 284 share a key.
Of the 2,029, **1,192 were selected and then lost**, not missed: `scan_ebd_keys` counts every review "whatever
its length or spoiler flag", while the gather excludes spoiler-flagged and profane reviews (shown to users as
evidence). Counted the gather's way, **1,168 of the 1,192 have fewer than 50 usable reviews** (the other 24 are
not explained by this check). Only **837** sit outside `wide_quota`. **Decision.**
`spine.widest_quota`: English 1,500 a year from 2000 and 600 before, 600 a year for every other language (a quota of
600 takes 638 of the 837, 1,500 takes 713; the curve flattens after that while memory climbs). It is an option
(`--widest`), so v4 to v8 stay reproducible, and it needs a new gather (the cache key records the quota). **Why now:**
the gather cache keeps the reviews of every selected film whatever the floor, so this one wider gather also serves
the later floor-20 build. **Expected gain** about 650 films with receipts (837 at the 87% that survive the filter),
not the 3,300 first quoted: that figure was the raw ebD count, which the filter does not honour. **Not yet run:**
free memory was 4.4 GB, below what a gather needs.

## D-034: the wider candidate list added 88 titles, not 650; D-033's expected gain is withdrawn (2026-11-03, Sonnet 5.5)

**Result** (`artifacts/v9`, manifest `d6cbf7291838`, 57 minutes; `--widest --uncapped`): 134,073 candidate films
(v8: 91,019), 12,018 titles with receipts (v8: 11,930, **+88**: English 11,187 against 11,105, Japanese movies 147
against 140, Hindi 426 against 427), 94,057 ratings-only, 106,075 in all. Hit-rate at 20 is 18.1% for both
collaborative filtering and the hybrid (validation 0.183; the tuned fit weight moved from 0.45 to 0.3, and 10,077 films
now have MovieLens ratings, so this is not like-for-like with v7). **Why so little** (`cache_diag`, the v8 and v9
gather caches): the 43,054 added candidates are obscure (median 4 TMDB votes, maximum 73); 33.1% have any review, 15.0%
five or more, 2.1% (909) twenty or more and **0.3% (114) fifty or more** (107 English, 7 Japanese), against 42.2%,
30.4%, 18.9% and 11.4% for the 91,019 candidates the old list already had. **Widening also costs links:** title
collisions rose from 471 to 847, and a popular film that shares its title and year with an obscure candidate is refused
as ambiguous, so 25 films the old list had fell below 50 reviews (Taras Bulba 1962, The Hunchback of Notre Dame 1996,
Anastasia 1997 among them; no film rose). 114 gained less 25 lost is 89 against the observed +88; the one-film
difference is not explained. **What D-033 got wrong.** It predicted about 650 from 837 films outside the old quota at
an 87% survival rate. That rate came from films the old list already held; at most 114 of the 837 (about 14%) reached
50 usable reviews. Why obscure films lose more of their reviews to the filters is untested. **Consequences.** (1)
`--widest` is not worth running and stays an option with that warning. (2) v9 is not recommended: it swaps 25 well-known films
that lost their reviews for 114 obscure ones, for a net +88, and costs a 57-minute build; v8 stays the build to
evaluate unless the owner prefers the extra titles (the owner has not decided). (3) D-033's claim that the wider gather also serves floor 20 is withdrawn, and is
not needed: **the v8 cache already holds 17,201 films with 20 or more merged reviews against 10,386 at 50 or more**
(+6,815, about +66%), so floor 20 can be built from it once the similarity matrix is made sparse.

## D-035: where to watch covers six platforms in every country TMDB lists, as a dated snapshot (2026-11-03, Sonnet 5.5)

**Owner's brief.** On opening a title, show where it can be watched, only on Netflix, Apple TV, Amazon Prime Video,
Disney+ Hotstar, Crunchyroll and HBO Max; region "every country TMDB lists". **Source.** TMDB's watch-providers
endpoint, one request per title, which returns every country at once and is powered by JustWatch (the page credits it,
as TMDB's terms require). **Platform mapping** (`fetch_providers.PLATFORMS`, TMDB provider ids): Netflix 8 and 1796
(with-ads variant); Apple TV 350 and 2; Amazon Prime Video 119, 9, 2100, 613, 10; Disney+ Hotstar 122 and 2336;
Crunchyroll 283; HBO Max 1899. **Left out on purpose:** Amazon Channel add-ons (1968, 1825: a third party sold through
Amazon), HBO Max sold through U-Next (2284), plain Disney+ (337, a different product from Hotstar) and Netflix Kids
(175). Ways shown: stream (flatrate), free (including ads), rent and buy. **Result** (v11, manifest `9ea566ea1455`,
`availability.json` 17 MB, fetch 105,843 answers in about 9 hours at 25 requests a second): 74,561 of 106,069 titles
(70%) are on at least one of the six in some country; by platform Prime 65,663, Apple TV 49,961, Netflix 10,921, HBO
Max 5,454, Hotstar 4,829, Crunchyroll 1,694; 139 countries appear. A title missing from the file is "none of the six",
shown as such with no link, never as "unknown". **Limits.** (1) It is a snapshot: availability changes daily, so the file
and the page carry the fetch date and tell the visitor to check the service. (2) Prime counts include titles that are
only rent or buy there, and the page says Rent or Buy, never "included". (3) The first guess of country is the visitor's
last choice, then their browser region; it is a guess, and the picker lists only countries where the title is offered.
(4) The data is TMDB's and is not independently checked; no spot-check against the services themselves was done.
(5) `availability.json` is read only when the verified manifest lists it, and only a plain `movie/N` or `tv/N` path can
become a link. **Next.** Refreshing is a re-run of `fetch_providers` and `availability` into a new folder (about 9 hours
at the same rate); nothing re-fetches while a visitor waits.

## D-036: "Try a review" and the receipts read two statements joined by "and" separately, and know nine more phrases (2026-11-03, Sonnet 5.5)

**Problem.** The owner's example ("the performances were fantastic, the storyline was captivating, and the ending was
absolutely brilliant") was already read correctly for acting and plot, but a clause joined by "and" or a comma shared
one polarity: "The acting was great and the plot was dull" scored -0.57 for both aspects. **Change 1 (splitting).**
`split_clauses` also cuts at "and" or a comma when BOTH pieces are statements: at least three words, an aspect, and a
verb after the aspect, and the next piece starts with a determiner or pronoun. Measured on 34,094 real sentences: 259
changed (0.76%), 31 flipped sign, 84 opinions were lost and 36 gained; about 60 changed examples were read. Reading them
found one bug (a list, "the plot, the acting and the scenery were bad", flipped plot to +0.14), fixed by requiring the
verb AFTER the aspect. The determiner/pronoun guard stays: without it 419 against 259 sentences change and sign flips are
50 against 31, and the extra cuts could not be shown to be better. **Change 2 (phrases).** From 60,000 real sentences
(45,873 with no aspect) candidate phrases were counted and read; only those whose examples were on-topic were added:
"chemistry" and "comic timing" (acting), "plodding", "breakneck", "fast-paced", "slow burn" (pacing), "beautifully
shot/filmed" (visuals), "storytelling" (plot), "resolution" (ending). Left out because they fire on other things: "shot"
(gunshots), "director" and "character" (not aspects), "gorgeous" and "stunning" (usually people), "color", "sound",
"singing", "final(ly)". **Not measured.** There is no aspect-labelled test set, so precision and recall of the new phrases
are NOT known; the evidence is the examples read, and the gold files hold pre-split clauses so they cannot score either
change. **Consequence.** Receipts change at the next rebuild, which must re-profile every title (hours); nothing on the
demo changes until then. Typo tolerance ("supeerb") and a semantic matcher (embeddings, parked) are not done.

## D-046: Watch together becomes a mood quiz, swipe cards and a results screen that refreshes only on request (2026-11-04, Sonnet 5.5)

**Owner's brief.** Instead of five identical titles, each person gets a long deck of cards from the pool the group shares, with
all the title's facts, and answers by swiping: right = want to watch, left = not for me, up = already watched, down = my ONE top
pick (naming a different one asks for confirmation; the replaced pick keeps a bonus above a plain right swipe but far below the
new one). The more people swipe, the narrower the offer. A results screen, open to anyone at any time, shows the top titles then
the next-closest, who wanted or passed on each, and changes only when Refresh is pressed. Before swiping, each person answers a
mood quiz (films or series, language, genre; not prefilled from the profile, because the profile already carries age, region and
the like), and a choice made by few people lowers a title without removing it. Everything answered stays in the room and never
touches a personal library; people are told all of this, and the four swipes, before they begin. **Engine** (`group.py`):
`Quiz` per member; `quiz_penalties` takes, per category, the share of the people who answered it who chose what the title is
(for genres its best-liked genre) and subtracts `quiz_penalty` (0.20) x (1 - share): comedy picked by one of three costs two
thirds of 0.20, a title nobody chose costs all of it, a category nobody answered costs nothing. Right swipes enter the member's
similarity seeds and want list but NOT "seen" (a real like would be, and the majority rule would then drop the title); left swipes
count as dislikes; up swipes as watched. The top pick adds `top_bonus` 0.60 (four times `want_bonus` 0.15) and a replaced one
`former_top_bonus` 0.25, each divided by the group size like the other bonuses. **Store and API** (`rooms.py`, `main.py`): per
member quiz, swipes, top pick and former top picks, bounded at 5,000 answers; `POST /rooms/{code}/quiz`, `/swipe`, `/deck`,
`/results`. A second top pick is refused with 409 `top_exists` unless `replace` is true. `/deck` returns the group's best titles
the member has not answered and is not holding, each card carrying overview, runtime, ratings, cast and where to watch; `/results`
returns 5 top and 15 close with each member's stand. A member alone in a room is paired with a copy of themself (the engine needs
two), so their deck is their own taste until a friend joins. `RoomView` shows each member's progress (quiz done, answers, whether
a top pick is set) and an `activity` counter, never the swipes themselves; those appear on the results screen. **Rate limit.**
Behind the tunnel every friend arrives from one address, so a shared per-address POST limit would stop a few people swiping;
swipes skip it and have their own limit per member (240 a minute). **Page.** `swipecore.js` (pure, Node-tested: directions,
thresholds, the card queue, the rules text, result wording), `cards.js` (one card: mouse and touch drags, flings, a guard that keeps
a card in place while a top-pick replacement is confirmed), `together.js` (rules once per room, quiz, cards, results). The deck
refills 20 at a time when six remain; arrow keys and four buttons do the same as the drags. The old `/rooms/{code}/recommend` route,
its tests and the `canAsk`, `isStale` and `standing` helpers are removed, and joining no longer sends the visitor's own language and
kind filters; these removals are deliberate. The card shows where to watch as one line for the visitor's own country (the full
panel was too tall and pushed the overview off the card). **Found and fixed on the way.** Replacing a top pick left the
"answered" count unchanged (the replaced title was in neither the swipes nor the top slot), now counted by one property; and the
front-end guard against flying a card before confirming was not pinned until a planted bug showed the server's refusal hid it.
**Checks.** 12 engine tests, 17 store tests, 12 new or rewritten route tests, 13 swipe Node tests, 14 two-browser tests (rules
before cards, quiz, buttons, keys, mouse drags, confirmation, results that stay until Refresh, and the personal profile unchanged
after every answer); planted bugs caught: quiz not applied, a top pick counted as a plain want, a replaced top pick ignored,
right swipes unused, left swipes not dislikes, kind weighting ignored, replace without asking, former pick forgotten, top slot
not freed, passes ignored, swipes sharing the address limit, no swipe limit, held cards dealt again, a ghost name for a lone
member, rules skipped, results refreshing by themselves, a tiny drag counting, and the card guard removed. On the real v13
catalogue a deck or results call took about 0.25 s and a swipe 5 ms; the screens fit a 390 px phone. **Limits.** The bonus and
penalty sizes are design choices, not measured; nothing shows that swipes predict what a group enjoys, and the group evaluation
(D-043) still does not exercise these rules. The cap stays at five and D-043's caution about larger groups stands. Rooms are still
in memory: a server restart ends them (the next to-do).

## D-045: rows stay put until the visitor asks; "Show more" adds titles to one row; the film page says what the rating is (2026-11-04, Sonnet 5.5)

**Owner's brief.** Liking or marking a title redrew the whole page 1.2 seconds later, so a visitor browsing a row lost the
other titles they might still have clicked. New suggestions should arrive only when the visitor reloads, changes a filter, or
reaches the end of a row and presses a **Show more** button. Answers given: Show more ADDS titles after the last one; a title
the visitor likes or marks watched STAYS in its row with its button showing the new state; the top pick stays put too. Second
observation: a row scrolled to its end stayed scrolled after a filter change although it held new titles. Third: the film page's
"adjusted mean 3.85" is jargon. **Changes.** (1) `main.js` no longer listens for the opinion event that redrew the page; the
tiles still announce it, nothing listens, on purpose. (2) `/shelves` takes two optional fields, `only` (a row id) and `limit`
(1 to 40, default 20); `build_shelves` then builds just that row, returns it even when fewer than the usual minimum remain, and
an unknown id gives nothing. The page sends every title already on screen (all rows and the top pick) and every watched title as
`exclude_movie_ids`, so nothing repeats, and the visitor's current likes and dislikes ride in the profile, so the next titles
reflect what they have just said (`web/js/more.js`, pure, tested in Node). The picks row is not given a button: "Show me another"
(D-042) walks it. (3) The scroll position memory in `rails.js` is deleted: it existed only to hide the automatic redraw (it kept
rows from jumping after a like), so with no automatic redraw a redraw always starts every row at its first title. (4) The film
page says "MovieLens viewers rate it 3.9 out of 5 (12,345 ratings)." The number is the same one as before: the average star
rating pulled toward the overall average when few people rated it, so three five-star votes do not look perfect. **A finding
worth keeping.** Two older browser tests (`test_library.py`: a watched film leaves the shelves; watched films come back when asked
for) passed after this change only by a race: the first-visit "Skip" schedules its own delayed redraw, which landed after the
test's click and excluded the film. They were not testing the click. They are **deliberately re-pinned** (one added step, a page
reload, each with a comment pointing here), because the owner changed the behaviour they described; the new
`test_rows_stay_put.py` pins the other half (the row is unchanged for 2.5 seconds after acting, and the watched title is gone
after a reload). **Checks.** Seven new server and route tests, seven Node tests for the request logic, one Node test for the
wording, four browser tests; planted bugs caught: every row built for `only`, the limit ignored, a short tail dropped, the
automatic redraw put back, and a row scroll position restored after a redraw. **Checked on the real v13 catalogue in a browser.**
After liking one title and marking another watched, the row was unchanged for 3 seconds; Show more grew it from 20 to 40 titles
with the first 20 intact and both answered titles still in place; no film appeared twice (two repeated names were different
films: One Piece 1999 and 2023, The Gentlemen 2020 and 2024); a row scrolled to 3,146 px, and every one of 15 rows, was back at
the start after a filter change. **Limit.** A row can run out (its leftovers may already sit on another row, as the anime row
holds what the Japanese row left), in which case the slot says "That is everything for now." and the button is gone until the
next redraw. The rows are not re-ranked as the visitor acts: only Show more and a reload use the new answers.
**Also, on request:** the Profile sheet's second dark/light button is removed (the one in the top bar is enough, and it stays
visible on phones). `test_layout.py`'s count of tools in that sheet is deliberately re-pinned from four to three.

## D-044: Watch together is a temporary in-memory room, joined by code or link, with no accounts (2026-11-03, Sonnet 5.5)

**Owner's brief.** Two or more people connect, both must agree before their libraries are combined, the combining is for
one sitting only, everything in the library counts (watched with stars, want, liked, disliked, taste), friends may see each
other's likes, five people now and twenty eventually, link and live joining both supported, accounts later. **Design.** A
room lives in the server's memory (`cinewhy/recsys/rooms.py`): a six-character code from an alphabet without 0, O, 1, I, L;
members in join order; a version number that changes with the membership. A room ends when the host closes it, when its last
member leaves (a leaving host hands over to the longest-standing member), or after three idle hours; at most 200 rooms are
held, then the server says it is busy. Nothing is written to disk. **Consent** is enforced twice: the dialog's join button
stays disabled until the box is ticked and nothing is sent before that (tested in a real browser), and the server refuses a
join that does not say `consent: true` (HTTP 400), so a client that skips the dialog cannot put a library in a room. **Entry point.**
A header button was built first and removed: `test_header_fits_at_every_width` pins exactly three top-bar tools, and a failing
guard is a finding, not something to edit. Watch together is reached from the Profile sheet and from invite links; a fourth
header button is a decision for the owner (it needs that guard re-pinned on purpose). **Secrets.**
Joining returns a secret that travels in an `X-Room-Token` header, never in an address, is kept in the tab's sessionStorage so a
reload does not drop the person, and is compared in constant time; a wrong secret and an unknown room give the same 404 so a
guess learns nothing. **Joining.** An invite link carries the code after `#` (so no server log sees it); the code is read and
removed from the address. "Live" is polling every four seconds while the dialog is open, not websockets: for five people it is
simpler and needs no new dependency. **Stars** are not sent as such; four and five stars are already likes and one and two are
dislikes in the profile, which is how the ranking reads them. **Size.** The server clamps a requested size to `MAX_GROUP` (5);
the store can be built for 20, and nothing else in the code assumes five, but see D-043 before raising it. **Concurrency.**
Routes run on a thread pool and the store is not thread-safe, so every touch of it holds one lock; scoring runs outside it on a
copy. **Checks.** 23 store tests, 15 route tests, 12 Node tests, 7 two-profile browser tests, and planted bugs (off-by-one
size, no expiry, anyone may close, any secret accepted, no host handover, consent not enforced, a lone person may ask,
likes hidden, join enabled before agreeing, polling off, close shown to everyone) were each caught. **Limits.** Server memory
is lost on a restart, which ends every room; with several workers each would hold its own rooms (the app runs one). A person who
closes the tab stays in the room until it expires, because a leave request cannot carry the secret header on page close. Cold
libraries give every title the same "100% fit", which is true but uninformative. The room is not rate-limited beyond the
existing per-client POST budget. Accounts (Supabase magic links, guest import) are not built.

## D-043: a group's members are combined by their mean percentile; this is a tie-break, not a win (2026-11-03, Sonnet 5.5)

**Owner's brief.** A group of two to five (twenty eventually) watches together; each member's library is combined for
one sitting. Pranav's rule for titles somebody has seen or disliked: with two people either one's seen or disliked
excludes it; with three or more a title is kept, with a small penalty per person, until a majority (n // 2 + 1) is in that
position. That rule and the want-to-watch bonus are decided by rule (`cinewhy/recsys/group.py`), not measured. How the
members' scores are COMBINED was measured, because the plausible answers disagree: mean, least misery (the unhappiest
member decides), geometric mean, blends of mean and least-misery, a lower quartile, and a naive baseline that keeps titles
in every member's own top 50. **Protocol, fixed in `group_eval.py` before any result was read.** There is no data on real
friends, so groups are built from MovieLens users. 300 validation and 300 test users are held out; item similarity and
popularity are rebuilt from every other user. A user's profile is 10 liked films and up to 10 they rated 1 or 2; the other
films they rated are "watched"; the liked films hidden from the profile are the targets. A member is hit when one of their
targets is in the group's top 20. Groups of 2, 3, 5, 10 and 20, drawn at random and as friends (an anchor and the users
most like them), 400 groups per cell, seed 2026. **Selection.** On VALIDATION groups only: the best average member hit
rate over sizes 2, 3 and 5; of the strategies within one standard error of it, the simplest. Best was `intersection`
(0.9325), `mean` 0.9301, `geometric` 0.9300, `blend` 0.925, `least_misery` 0.921: `mean` is within one standard error and
simplest, so it is the default (`GroupConfig.strategy`, pinned by a test). **Test result (opened once; mean hit rate per
member, 95% bootstrap interval).** Size 2 random: mean 0.951 [0.935, 0.966], blend 0.943, least-misery 0.939. Size 3
random: mean 0.909 [0.889, 0.927], least-misery 0.884 [0.863, 0.907]. Size 5 random: mean 0.858 [0.838, 0.877], geometric
0.857, blend 0.828 [0.804, 0.850], least-misery 0.821 [0.797, 0.844]. **What this does and does not show.** At sizes 2 and
3 every strategy is within noise of the others: a member's own top 20 already holds a target for 98% (validation) to 100%
(test) of members, so the metric is at its ceiling and cannot separate strategies there. `mean` is the default because the
rule says the simplest of the tied, not because it is shown better. At size 5, `mean` and `geometric` are ahead of the
blend, least-misery and lower-quartile rules, whose intervals sit below. **The inconvenient result.** The naive
intersection baseline is level with `mean` at 5 (random 0.867 [0.846, 0.887]; friends 0.981 against 0.974) and far ahead at
10 and 20 for friend-like groups (size 20 friends, share of groups where every member is hit: 0.393 [0.345, 0.440] against
0.048 for `mean`; size 10 friends 0.757 against 0.480). The default was chosen on 2, 3 and 5 as the rule required, so it is
`mean`; but the cap should not be raised past five on the strength of this default. Before it is, re-run with the selection
sizes extended and compare `intersection`, `mean` and a blend of the two. **Limits.** The targets are films a member liked
and had not told us about, so the seen, disliked and want rules and their penalties are NOT exercised (a target is never
ruled out for being seen); MovieLens users sharing a similarity are not friends choosing a film together; hit at 20 is a
proxy for "would enjoy it". Intervals come from resampling groups, which are drawn from only 300 users, so groups of 10 and 20
reuse the same people heavily. Raw numbers: `group_eval_results.json` from `python -m cinewhy.recsys.group_eval` (seed 2026).

## D-040: a blind-labelled sentence set, and a rule for "Great cast, terrible script" that changes almost nothing (2026-11-03, Sonnet 5.5)

**Why a new set.** Every earlier gold set is clause-level, taken AFTER splitting, so none can score a splitting change.
`aspect_gold_sentences.jsonl` is 200 whole sentences: 150 drawn uniformly at random (stratum U) and 50 at random among
sentences where the detector finds 2+ aspects (stratum M, the only place a split can show). Drawn with seed 20261103 from
IMDb and Rotten Tomatoes film reviews (not the aclImdb text of the older sets), sentences of 4+ words and at most 400
characters, skipping anything overlapping an older gold file (a test pins that). **Protocol.** The labels were written
BEFORE any code was run on the rows, from the text alone, to rules fixed beforehand: an aspect is labelled only if the
sentence evaluates it for the film (+1, -1, or 0 for no clear direction); plot summary, other films, and topics outside
the seven aspects (direction, editing, humour) are not labelled. **The labeller is the assistant, not an independent human**
(each row says so): the known weakness, so read these as an audit by one labeller. Of 151 labelled mentions in 91
sentences. **Baseline** (current code, v13 polarity model; Wilson 95%): on U, mention recall 53.2% [39.2, 66.7] (n=47) and
end-to-end 38.6% [25.7, 53.4] (n=44); over all 200, sign accuracy 85.4% [77.4, 91.0] (n=103) and end-to-end 62.4% [54.2,
70.0] (n=141), where "end-to-end" is the share of all labelled positive or negative aspects that were found, given an
opinion and given the right sign. **Stratum M's recall and precision (93%) are inflated by how M was chosen and must not be
quoted**; only its sign and end-to-end rates are fair. **The rule.** `_split_verdicts` cuts at a comma or "and" between two
short pieces (2 to 7 words) that each name an aspect, lean OPPOSITE ways (existing cue lists plus good, bad, nice, solid...,
negation honoured) and are not both full verbal statements. First version cut any two verdicts and was REJECTED on 120,000
real sentences: 124 changed, 10 sign flips (5 right, 3 wrong), 18 correct opinions lost to silence for 4 gained (two-word
clauses score too weakly to count). Final version: **6 of 120,000 sentences change (0.005%)**: 4 sign flips of which 3 are
right ("Despite the great cast, weak writing did this film in", "great cast, ridiculous premise but fun", "Good-looking and
well-cast, but utterly tedious") and 1 wrong (a run-on missing the space after a full stop), 0 opinions lost. **The 200-row
set is unchanged by it (0 of 200 sentences affected), so the set can neither confirm nor refute it**; the evidence is the
corpus reading above. The rule is kept because it is safe and right where it fires, not because it is valuable: the
pattern is rare. A guard test (a bare-noun second subject stays whole, D-036) was NOT edited: the rule steps aside when
both sides are full statements. Tests count work, pin literals, and eight planted bugs were caught after one survivor (the
aspect requirement) got its own test. **Where the pipeline fails** (read AFTER the rule was final; the 200 rows are a
DEVELOPMENT set from here on, and the next change must be judged on a new fresh sample): of 141 labelled positive or
negative aspects, 88 (62.4%) are right end to end; 28 (19.9%) were never flagged, 15 (10.6%) have the wrong sign and 10
(7.1%) were flagged but too weak to count. Most misses look like wording outside the lexicon ("talks in monologues", "hams
it up", "off the charts", "every frame is magic", "the look of", "theme tune", "wastes none of its three hour run time");
the wrong signs are polarity errors ("slow-paced, drawn-out thriller" scored +0.68; "depressing, frightening, shocking...
original" scored negative as praise). **What this means for embeddings (not decided).** Finding aspects by meaning could
address the largest single loss, but fixing every miss with the right sign could add at most 19.9 points (to about 82%): a
ceiling, not an estimate. The 25 wrong or weak polarities would remain, because they are a polarity-model problem
embeddings do not solve. Costs unchanged: a new dependency (needs the owner's approval), a model of about 100 MB, and
hours to re-read about 1.8M reviews. **Not measured:** agreement with an independent human; any effect on the shipped
receipts (nothing was rebuilt).

## D-039: the "and" splitter does bounded work (2026-11-03, Sonnet 5.5)

**Finding.** An automated security review of the pushed branch flagged `_split_statements` (D-036): for every "and" or
comma candidate it re-reads both sides, and when no cut is made the left side keeps growing, so the cost is quadratic in
the span. `/analyze` runs it on up to 5,000 characters of visitor text. **Reproduced:** a crafted 5,000-character text
of ", the" repeated took about 1.4 s against 0.1 s for a normal review; at the API's limit of 120 POSTs a minute from
one client on one worker that can keep the server busy. **Fix.** A span longer than 1,000 characters is not statement-split
(it behaves as before D-036) and at most 60 candidates are examined per span. After the fix the same inputs take under a
millisecond and the worst case under the character limit takes 13 ms. **Cost, measured.** On 120,000 real sentences the
output changed for 25 (0.02%), all unpunctuated run-ons of 1,000 to 3,287 characters (182 sentences exceed 1,000).
Tests count the work done rather than time it (so they cannot flake) and pin the numbers as literals; four planted bugs
(limit removed, cap removed, cap raised, limit moved) were caught after one surviving mutant, which compared the cap with
itself, was fixed. **Not changed.** The leading `\s*` in `_JOIN`, which the review also named: a 4,990-space run costs
0.0 ms, so it is not exploitable here. The build runs the same code, so a review that is one huge unpunctuated sentence
now keeps its old, single-clause behaviour. v12 and v13 were built BEFORE this change; a rebuild would differ in about
0.02% of sentences, which is immaterial to the receipts.

## D-042: "Show me another" walks down the picks without touching the visitor's lists (2026-11-03, Sonnet 5.5)

**Owner's brief.** A visitor who has been recommended a title, even marked it Want to watch, and still wants to look at
the choices gets a button that recommends the next best. **Design.** The picks shelf already ranks 16 titles, so the button
walks down that ranking (`web/js/picks.js`, pure, tested in Node): a queue of ids, the position, and every id shown, so
nothing comes back. A "Previous pick" button steps back. When the 16 run out the page asks `/discover` for 16 more with
`receipts_only: true` (a new optional request field, default false, so every existing call is unchanged; the top pick
promises the sentences behind it, so ratings-only titles are refused up front, as the picks shelf does) and with every
queue, shown and watched id excluded; when the server has none the button is disabled with a note saying so. The row under
the pick lists only what comes AFTER the title on show, so no title is on screen twice. **Behaviour pinned by tests.**
Marking the pick Want to watch keeps it on the list, the page does not jerk to another title when the visitor answers (a
redraw keeps the title on show if it is still ranked), and pressing the button never changes a list. Liking the pick moves
on to the next best, because a liked film leaves the picks (as it did before this change). **Limit.** If a visitor's
watched list plus the titles shown ever exceeded the server's cap of 3,000 excluded ids, the tail of the watched list would
be dropped from the request; the queue's own ids go first so a title just passed is never what is lost. Eight planted bugs
were caught, after two that needed a test of the request itself.

## D-041: the top pick carries the film page's essentials, and where-to-watch defaults to India (2026-11-03, Sonnet 5.5)

**Owner's brief (2026-11-03).** (1) On the top recommended title show what the film page shows: the Starring line, the
Like / Not for me / I've watched it / Want to watch buttons with IMDb and Rotten Tomatoes, and Where to watch; drop the
"why we picked this" receipts excerpt; rename the yellow button "Why we chose this", which opens the receipts. (2) Where to
watch defaults to India, and a profile's country defaults to India too. **Change 1.** `spotlight()` in `rails.js` reuses
`actions`, `starring` and `whereToWatch` from the film page (the pick already fetched `/movie/{id}`, so no new request);
the yellow button calls `openFilm(id, { toReceipt: true })`, which scrolls the drawer to the receipt. With no details
the pick still shows the yellow button. No existing test pinned the old wording. **Change 2.** The profile gains
`country`, an ISO two-letter capital code, default `IN` (`DEFAULT_COUNTRY`); an older save without it, or any invalid value,
reads as India; `setCountry` ignores anything but a valid code; the profile version is not bumped (the field is optional
on read); a taste reset keeps it (a setting, not a taste). `watch.js` opens on `state.country`, keeps that country in the
picker even when the title is not offered there, and in that case SAYS SO ("Not on Netflix... in India. Choose another
country...") instead of silently showing another country. A pick in the picker is saved to the profile. **Supersedes
D-035's limit (3)**: the first guess is no longer the browser's region and the separate browser-storage key
`cinewhy.country` is gone (a visitor who had chosen a country there starts on India once). **Tests.** `regionOf` and
`pickCountry` were removed with their tests, and two browser tests that encoded the browser-language default were
replaced, deliberately and on the owner's instruction; new Node tests pin the default, the validation, export and import
and the reset, and the browser tests pin India with an `en-US` browser, saving the pick, and the not-offered message.
Fourteen planted bugs across both changes were caught after two survivors (the scroll to the receipts) got a test with a
window short enough to need it. **Limits.** The first-visit sheet asks only a coarse region ("India", "North America"...)
and still has no country question, so every new visitor is India until they pick; a real profile with accounts (not
built) will adopt this field. "India only" was read as a default, not a removal of the picker: say if it should go.

## D-038: the review floor drops from 50 to 20 (build v12), which adds 8,555 thinner receipts (2026-11-03, Sonnet 5.5)

**Owner's plan** (2026-11-02): floor 50 first, then floor 20 once the floor-50 build was checked. **Blocker removed.**
Floor 20 was expected to need a sparse similarity; instead `build_item_similarity` now forms the matrix in row blocks
(`block_rows`, default 1,024), because the real cost was three dense float64 matrices at once (about 5 GB at 15,000 rated
films), not the float32 result. The result is unchanged up to rounding (tests compare it with the old whole-matrix
formula at three block sizes; four planted block-edge bugs were caught). **Result** (`artifacts/v12`, manifest
`aec535f651e1`, 27 minutes on the cached gather; `--min-reviews 20`, otherwise the v8 flags): **20,485 titles with
receipts** (17,191 films and 3,294 series) against 11,930, no title lost; 85,630 ratings-only; 282,397 quotable sentences
(v8: 191,874). English receipts 18,703 (11,105), Hindi 791 (427), French 495 (188), Japanese movies 323 (140), anime
series 95 (35), Telugu 74 (33). `item_sim.npy` is 1.68 GB (v8: 569 MB), so the server needs about 1.7 GB for it.
**What the new titles are like.** The 8,555 added titles have a median of 30 reviews, report 3.9 aspects on average
(the 11,930 older titles: 5.7) and 37.7% report three or fewer, because an aspect needs three supporting clauses. A
receipt from 20 to 49 reviews is thinner evidence; the page shows each score's support, so it says so. **Recommender.**
On the same 2,000 test users the hybrid minus collaborative filtering at 20 is -0.3 points [-1.2, +0.7] (v8: -1.55
[-2.5, -0.55]); the interval now includes zero. This is NOT like-for-like (the catalogue and so the candidate pool
differ; popularity's hit rate moved from 7.1% to 6.0%), so it does not show that the hybrid improved. Validation hit@20
is 0.212 (v8: 0.171); shrink 50 was chosen (v8: 200). **Effect of D-036 on the older receipts.** Over 68,224 aspect
scores of the 11,930 shared titles the mean absolute change is 0.014; 2.2% moved by more than 0.1; one crossed from
liked to disliked (both beyond 0.2); 61 aspects were dropped and 194 gained. The splitter and the nine phrases are
therefore not a visible change to existing receipts. **Not measured.** Whether the 20-to-49-review receipts are as
accurate as the older ones: the aspect and polarity gold sets are clause-level and cannot score a title. **Consequence.**
v12 holds no cast or availability; v13 is v12 plus both (add-on steps, new folders).

## D-037: spelling repair for the polarity model was measured and is NOT shipped (2026-11-03, Sonnet 5.5)

**Idea.** "Try a review" scored "supeerb" at +0.48 against +0.99 for "superb", because a misspelt word is not in the
polarity model's vocabulary. A repair step would replace an unknown word (5+ letters, letters only) with the most
frequent vocabulary word one edit away (delete, swap, replace or insert one letter). **Measured** on 30,000 real review
sentences (377,336 tokens; 6.1% of tokens are unknown to the model; probe in the session scratchpad, not committed).
(1) Repairing toward any vocabulary word fired 3,857 times on 2,455 distinct words, and of 70 sampled repairs I judged
about a fifth right (pleasent, beleiving, mediochre, adolesence, millionare, whirpool) and the rest wrong: real rare
words turned into other words (stocky to stock, parlance to palance, seance to stance, nooks to looks) and names (konrad
to conrad, mcmann to mcgann). (2) Limited to targets among the 1,500 most polar words it fired 363 times (0.1% of
tokens) and about 45% of the 70 sampled were still wrong (dented to rented, coker to cover, saeed to saved, pater to
later). **Decision.** Not built: a wrong repair is as likely as a right one, and the right ones touch about one token in a
thousand. **What could work instead (untested).** A character n-gram polarity model reads misspellings natively, but it
needs a retrain and a full re-profile; it belongs with the parked embeddings option, to be compared on a fresh random
clause sample. No dictionary was available to separate a real rare word from a typo; adding one is a new dependency.

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
