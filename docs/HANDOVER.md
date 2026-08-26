# HANDOVER.md

> Where things stand *right now*. Field Guide habits #1 and #13.
> Read this first, every session. Update it last, every session.

**Last updated:** 2026-08-26 · Claude Opus 5 · audit + documentation session
**Next session should start with:** Phase A, task A1 (see `AUDIT-2026-08-26.md` §Phase 4)

---

## State in five lines

1. Project is a **prototype**, graded **3.4/10** overall — one notebook, no tests, no CI, no API.
2. It was repositioned this session from *sentiment classifier* → **recommender with review-grounded
   explanations** (`DECISIONS.md` D-001). The Netflix-recommender assignment is the real target.
3. **The existing dataset cannot power a recommender** — 2 columns, no movie/user IDs (D-002).
   Acquiring item-keyed data is the first real blocker.
4. Three measured methodology defects: vocabulary leakage (−1.65 pts), negation deleted before the
   model, and a "best model" chosen on noise whose ranking *reverses* under CV.
5. Nothing was implemented. **Zero lines of notebook/model code were changed.** Only docs, `.gitignore`,
   `README.md`, and the git repo itself were created.

---

## What is done

| | |
|---|---|
| ✅ | Full audit — Phases 0–4 — in [`AUDIT-2026-08-26.md`](AUDIT-2026-08-26.md) |
| ✅ | Field Guide document set: `ARCHITECTURE` `FLOW` `DECISIONS` `CONSTRAINTS` `TEST_CHECKLIST` `ROLLBACK` `HANDOVER` + bug/feature templates |
| ✅ | `CLAUDE.md` at repo root — the review habits (#10–15) as session rules |
| ✅ | Git repo initialised, `.gitignore` written, `README.md` corrected, pushed to GitHub |
| ✅ | Defect claims **verified by measurement**, not by reading code (see below) |

## What is NOT done

| | |
|---|---|
| ❌ | Any code fix. Every defect below is still live in the notebook. |
| ❌ | Test suite, linter, typechecker, CI — none exist |
| ❌ | Data acquisition (MovieLens / TMDB / item-keyed reviews) |
| ❌ | API, frontend, deployment — nothing beyond the notebook |
| ❌ | Rollback drill (`ROLLBACK.md` §7 is blank) |

---

## Measurements taken this session — trust these, they are fresh

All from `D:\NLPPROJECT\venv\Scripts\python.exe`, 2026-08-26, seed 42, 10k sample.

**Notebook reproduced exactly.** As-written numbers match the committed notebook outputs
(0.8350 / 0.8330 / 0.8255 / 0.7820), so the notebook's numbers are *real* — just compromised.

**Leakage cost** (move vectorizer fit after the split, change nothing else):

| Model | as written | leak-free | delta |
|---|---|---|---|
| BernoulliNB (BoW) | 0.8350 | 0.8185 | **−0.0165** |
| MultinomialNB (TF-IDF) | 0.8330 | 0.8220 | −0.0110 |
| MultinomialNB (BoW) | 0.8255 | 0.8200 | −0.0055 |
| GaussianNB (BoW) | 0.7820 | 0.7805 | −0.0015 |

**5-fold CV on train only — the winner reverses:**

| Model | CV mean ± std |
|---|---|
| MultinomialNB (TF-IDF) | **0.8383 ± 0.0091** |
| MultinomialNB (BoW) | 0.8293 ± 0.0126 |
| BernoulliNB (BoW) | 0.8285 ± 0.0117 |

The notebook's declared winner comes **last**. Its 0.0020 margin sits inside a ±0.011 spread.

**Negation witness (end to end):** `"This movie was not good at all."` and `"This movie was good."`
→ both preprocess to `'movi good'` → `np.array_equal` on their TF-IDF vectors is `True` → both
predicted **0 (negative)**.

**Dataset:** 50,000 rows · **418 exact duplicate review texts** · 0 conflicting labels ·
29,200 rows contain `<br` · mean 1,309 chars · max 13,704 chars.

---

## Open items marked "reproduce first"

**H-1 · ASIN → film mapping (not attempted this session).**
Amazon Movies&TV review item IDs are ASINs — a specific product/edition, not a film. Whether they
map cleanly to MovieLens/TMDB IDs is **unknown and unverified**. Do not assume. Reproduce by pulling
200 random ASINs, attempting a title match, and hand-checking 30 of them before designing around it.
*Hypotheses not yet falsified — this is unexplored, not dead-ended.*

**H-2 · Whether the 418 duplicate reviews actually straddle the train/test split.**
Known: the duplicates exist. Not measured: how many land on both sides under `random_state=42`.
Cheap to check; do it before quoting any accuracy as clean.

---

## Environment gotchas — do not rediscover these

- **cp1252 stdout.** Any script printing emoji/em-dashes raises `UnicodeEncodeError`. Always
  `export PYTHONIOENCODING=utf-8` first. Cost one wasted run this session.
- **Two identical-looking Pythons.** `venv\Scripts\python.exe` and the global are both 3.13.1. Use
  the venv path absolutely; never bare `python`.
- **`pypdf` is not in the project venv** — a throwaway venv was built in the scratchpad to read the
  field guide. Do not install it into `venv/`.
- **Poppler/`pdftoppm` is not installed**, so the Read tool cannot render PDFs on this machine.
- **Bash cwd resets between calls.** Absolute paths only.
- **No git repo existed before this session** — hence no `git diff` baseline for anything older.

---

## What to watch out for

- The **project report is not trustworthy as a source**. It asserts leakage was *prevented*
  (§12), claims a stratified split that the code does not perform, labels test numbers as
  "Validation", and explains an error mechanism (`not` as a unigram) that cannot occur. Re-verify
  anything taken from it. Its confusion-matrix figures are `[INSERT FIGURE]` placeholders.
- The **E: drive summary** claims SVC is used. Grep says `SVC` appears **0 times** in the notebook.
  Do not let that claim reach a résumé.
- The notebook is **not idempotent** — cells 13–18 mutate `df["review"]` in place. Re-running cell
  17 alone double-stems the corpus silently. Restart-and-run-all or nothing.

---

## Five-line handoff ritual (fill in each session)

```
Session date:      2026-08-26
Model:             Claude Opus 5
What we did:       Full audit; wrote Field Guide doc set; created + pushed GitHub repo.
What's left:       Everything in Phase A onward. No code fixed yet.
Watch out for:     Report + summary contain false methodology claims. Verify, don't inherit.
```
