# FEATURE-002 · Negation-preserving text normalisation

> Field Guide habit #5 — one file, start to finish.

**Status:** shipped (module and tests); the training pipeline that will call it does not exist yet
**Opened:** 2026-09-29 by Claude Sonnet 5.5 · **Model:** Claude Sonnet 5.5
**Plan row:** M3 (Phase C), with C-3 from the audit

---

## What and for whom

`cinewhy.text.strip_html`, `build_stoplist` and `normalise` replace the stubs. The cleaning
step no longer deletes `not`, `no`, `nor` or the negative contractions. It is for the Phase C
training job and, later, the request path, which must import the same function.

## Why now

The audit's C-3 defect reproduced on 2026-09-29: "This movie was not good at all." and "This
movie was good." both cleaned to `movi good` and were both predicted negative. `DECISIONS.md`
D-003 forbids it and D-010 records the design.

## Success criteria — verifiable, not vibes

| # | Criterion | How it is verified |
|---|---|---|
| 1 | No negation carrier is in the stoplist | `test_negation_tokens_are_never_in_the_stoplist` |
| 2 | A negated and a plain sentence normalise differently | `test_negation_survives_preprocessing` |
| 3 | `not` reaches the output | `test_negation_token_is_present_in_output` |
| 4 | `n't` forms, including irregular ones, become `not` | `tests/test_preprocess.py`, 12 cases |
| 5 | Pure, returns `str`, idempotent | contract tests and `test_normalise_is_idempotent` |
| 6 | Standard library only | imports checked; CI environment has no nltk |
| 7 | No measurable accuracy loss from dropping stemming | D-010 comparison table |

## Scope

**In:** the three functions, the embedded stoplist, tests, the decision record.
**Out:** the training pipeline, stemming or lemmatising, modelling negation scope, editing the notebook.

## Approach

Expand contractions to `not` before punctuation is stripped, because `didn` and `t` are both
stopwords. Embed NLTK's list with its provenance instead of importing it.

**Rejected:** importing nltk, because it is a new dependency and the request path would need the
corpus. **Rejected:** keeping Porter stemming, because it lives in nltk and the measured effect
of dropping it is inside the noise.

## Blast radius

`cinewhy/text/preprocess.py` rewritten; `tests/test_methodology.py` and
`tests/test_pipeline_contracts.py` lose six `xfail` markers; new `tests/test_preprocess.py`.
The notebook is untouched.

## Build order

- [x] 1. Implementation; the six strict-xfail tests XPASSed as intended.
- [x] 2. Markers removed; behaviour tests added.
- [x] 3. Lint fixes (two intentional curly apostrophes carry `noqa` with a reason).
- [x] 4. Ten planted bugs, each killed; file restored byte-identical.
- [x] 5. Pipeline comparison recorded as D-010.

## Verification log

```
$ pytest -p no:cacheprovider
62 passed, 13 xfailed
$ ruff check .      All checks passed!
$ mypy              Success: no issues found in 20 source files
mutation run: 10 of 10 killed, restored identical: True
```

## What changed vs the plan

The plan assumed removing negation from the stoplist was enough. It was not: contractions
split into `didn` + `t` and lost the negation anyway, which the tests for `n't` now pin.
The hoped-for accuracy gain did not appear (D-010): the benefit is representational only.
