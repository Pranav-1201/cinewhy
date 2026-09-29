# FEATURE-003 · Training and evaluation harness that enforces the methodology rules

> Field Guide habit #5 — one file, start to finish.

**Status:** shipped; no polarity model is trained or persisted yet
**Opened:** 2026-09-29 by Claude Sonnet 5.5 · **Model:** Claude Sonnet 5.5
**Plan row:** M1, M2, M5, M6 (Phase C)

---

## What and for whom

`cinewhy.absa.train` splits, cross-validates and evaluates classifier candidates so that the
three rules in CONSTRAINTS #1-#3 are properties of the code. It is for whoever trains the
polarity model that `score_polarity` will use.

## Why now

Three guard tests were `pytest.fail` placeholders waiting on "the training pipeline". Guarding
functions that did not exist proved nothing, and every comparison so far (D-009, D-010) had come
from throwaway scripts that were not committed.

## Success criteria — verifiable, not vibes

| # | Criterion | How it is verified |
|---|---|---|
| 1 | No vectorizer is ever fitted on a test row | spy vectorizer log; guard on vocabulary |
| 2 | Selection reads only training positions | recording sequence; guard on selection |
| 3 | Each fold fits on a strict subset of train | batch-size test |
| 4 | No winner inside the fold spread | guard on margin; D-009 numbers |
| 5 | Duplicates removed before the split | split tests |
| 6 | Every guard can fail | control assertion, and 10 planted bugs killed |

## Scope

**In:** split, folds, summary, winner rule, final evaluation, report formatting, a CLI.
**Out:** persisting a model, GaussianNB (dense), stratified splits, hyperparameter search, the
aspect-level classifier, `score_polarity` itself.

## Approach

Positions cross every boundary instead of frames, so a test can hand in a sequence that records
which rows were read. Test rows are read in exactly one function, after selection.

**Rejected:** sklearn's `cross_val_score`/`Pipeline`, because they hide where the vectorizer is
fitted, which is the very thing under guard. **Rejected:** a bare `>` for the winner rule,
because a lead exactly equal to the spread is no more noise than one just above it.

## Blast radius

New `cinewhy/absa/train.py`, `tests/test_train.py`; three guards in `tests/test_methodology.py`
made real. numpy and scikit-learn became CI dependencies (approved 2026-09-29). Suite time rose
from under one second to about seven because the tests fit real models.

## Build order

- [x] 1. Module written; ruff and mypy clean before any test.
- [x] 2. Tests written, then a gap found in them (per-fold subset) and closed.
- [x] 3. Three guards made real, markers removed.
- [x] 4. Ten planted bugs, each killed, file restored byte-identical.
- [x] 5. First real-data run recorded as D-011.

## Verification log

```
$ pytest -p no:cacheprovider
123 passed, 7 xfailed in 7.48s
$ ruff check .   All checks passed!      $ mypy   Success: no issues found in 23 source files
mutation run: 10 of 10 killed, restored identical: True
$ python -m cinewhy.absa.train --sample 10000
rows 10000, unique 9982, train 7986, test 1996
  MultinomialNB TF-IDF   CV 0.8375 +/- 0.0129   test 0.8362
  MultinomialNB BoW      CV 0.8306 +/- 0.0115   test 0.8267
  BernoulliNB BoW        CV 0.8323 +/- 0.0116   test 0.8367
winner by CV: none - the lead is inside the fold spread
```

## What changed vs the plan

I described the first real run as "the same sample as D-009". It was not: the CLI samples with
Python's `random`, pandas used its own generator, so the rows, split and duplicate count all
differ. Caught before it was written down; D-011 carries the caveat.
