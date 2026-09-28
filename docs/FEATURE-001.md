# FEATURE-001 · Remove exact-duplicate reviews before splitting

> Field Guide habit #5 — one file, start to finish.

**Status:** shipped (helper and guard); not yet wired into a training pipeline, which does not exist
**Opened:** 2026-09-29 by Claude Sonnet 5.5 · **Model:** Claude Sonnet 5.5
**Plan row:** M4 (Phase A)

---

## What and for whom

`cinewhy.text.unique_review_indices` returns the row positions to keep so no review text can be
on both sides of a train/test split. It is for whoever writes the Phase C training job.

## Why now

The raw file holds 418 exact duplicate review texts. HANDOVER H-2 asked whether they straddle the
notebook's split. Measured: 22 duplicate rows in the 10,000 sample and 5 of 2,000 test rows with
a twin in train, all labels agreeing, so at most 0.25 points of accuracy. Small here, but a
permanent hazard for any other split or corpus, and a double-counted review distorts aspect
statistics later.

## Success criteria — verifiable, not vibes

| # | Criterion | How it is verified |
|---|---|---|
| 1 | Keeps the first copy of each text, in order | `tests/test_dedupe.py` |
| 2 | Refuses contradictory labels instead of choosing | `ConflictingLabelsError` test |
| 3 | No text on both sides after dedupe, across 25 seeds | guard `test_no_review_text_appears_in_both_splits` |
| 4 | The guard has teeth: without the helper the same splits do straddle | control assertion inside the guard |
| 5 | No new dependency | module imports only the standard library |

## Scope

**In:** the helper, its exceptions, and tests.
**Out:** wiring into a training job (Phase C), fuzzy or near-duplicate matching, editing the legacy notebook.

## Approach

Return positions rather than a filtered frame, so it needs no pandas and one index list subsets
any number of parallel arrays. Matching is exact, because the audit's number is a count of exact
duplicates.

**Rejected:** a pandas `drop_duplicates` wrapper, because CI installs neither pandas nor sklearn
and adding them needs approval. **Rejected:** normalising text before matching, because it
silently widens what "duplicate" means.

## Blast radius

New `cinewhy/text/dedupe.py`; two names added to `cinewhy/text/__init__.py`; new
`tests/test_dedupe.py`; one placeholder guard in `tests/test_methodology.py` made real. Nothing
loads a serialized artifact.

## Build order

- [x] 1. Unit tests first, watched failing (`ModuleNotFoundError`).
- [x] 2. Implementation; unit tests green.
- [x] 3. Guard made real; control added.
- [x] 4. Six planted bugs, each killed; the guard alone fails against a no-dedupe helper.

## Verification log

```
$ pytest tests/test_dedupe.py
7 passed in 0.02s
$ pytest            (after the guard was made real)
31 passed, 19 xfailed in 0.22s
mutation run: no dedupe / conflict never raised / length check removed /
              message leaks text / case-insensitive matching / keeps later copies
KILLED x6   restored identical: True
```

## What changed vs the plan

The plan expected to use pandas; CI's environment ruled that out and the position-list design
turned out simpler. The guard needed a control to avoid passing vacuously, which the placeholder
did not anticipate.
