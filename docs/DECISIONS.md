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

## D-017: polarity model is weak on Rotten Tomatoes text; left as is, undecided (2026-10-26, Sonnet 5.5)

Trained only on aclImdb (89.3% on its own test set). On newer text: ebD 88.4% (87.3 to 89.4), Rotten
Tomatoes 75.0% (73.9 to 76.1, n = 6,000). The How it works page prints this. Candidate fix, not
done: retrain on a mixture of sources with a held-out split per source. Not decided because it needs a
new CV round and the choice must not be made on the evaluation text.

## D-018: the hybrid does not beat similar-taste alone; aspects stay for the quotes (2026-10-26, Sonnet 5.5)

On 2,000 held-out MovieLens users, hit@20: popularity 8.3%, similar-taste 20.1%, aspects alone 5.5%,
hybrid 18.9%. Hybrid minus similar-taste is -1.3 points at 20 (interval -2.2 to -0.4): slightly worse.
The aspect blend stays because every pick needs its sentences, not because it raises the hit rate;
the About page says so. Validation hit@20 was identical (0.184) for shrink 10, 50 and 200.
