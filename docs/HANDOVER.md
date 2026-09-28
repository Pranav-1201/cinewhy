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
4. Three methodology defects: the vectorizer is fit before the split (accuracy cost **not
   distinguishable from zero** when re-measured, D-009), negation is deleted before the model
   (reproduced), and a "best model" is chosen on a 0.0020 test-set gap that sits inside the CV spread.
5. Nothing was implemented. **Zero lines of notebook/model code were changed.** Only docs, `.gitignore`,
   `README.md`, and the git repo itself were created.

---

## What is done

| | |
|---|---|
| ✅ | Full audit — Phases 0–4 — in [`AUDIT-2026-08-26.md`](AUDIT-2026-08-26.md), also published as a [web page](https://claude.ai/code/artifact/fe9f3518-15c7-400f-9cfc-ecbc5da0786f) |
| ✅ | Repo live at **https://github.com/Pranav-1201/cinewhy** (public, 4 commits) |
| ✅ | Field Guide document set: `ARCHITECTURE` `FLOW` `DECISIONS` `CONSTRAINTS` `TEST_CHECKLIST` `ROLLBACK` `HANDOVER` + bug/feature templates |
| ✅ | `CLAUDE.md` at repo root — the review habits (#10–15) as session rules |
| ✅ | Git repo initialised, `.gitignore` written, `README.md` corrected, pushed to GitHub |
| ✅ | Defect claims **verified by measurement**, not by reading code (see below) |

## What is NOT done

| | |
|---|---|
| ❌ | Any code fix. Every defect below is still live in the notebook. |
| ✅ | **Phase B done (2026-09-03):** ruff + mypy + pytest + GitHub Actions CI, all green |
| ✅ | **Scaffold done (2026-09-03):** `cinewhy/` package, `api/`, `tests/` — 23 passed, 20 xfailed |
| ✅ | `cinewhy/schemas.py` — the shared contract, fully implemented and tested |
| ✅ | `CONTRIBUTING.md` + `AGENTS.md` — two-person split, module ownership, PR flow |
| ✅ | `check_env.py` now actually enforces its version floors (was a no-op) |
| ❌ | Data acquisition (MovieLens / TMDB / item-keyed reviews) |
| ❌ | API, frontend, deployment — nothing beyond the notebook |
| ❌ | Rollback drill (`ROLLBACK.md` §7 is blank) |

---

## Measurements — trust the dates shown, not the section title

All from `D:\NLPPROJECT\venv\Scripts\python.exe`, seed 42, 10k sample. Figures marked
*re-measured* are from 2026-09-29 on the pinned environment; the rest are from 2026-08-26 and
have not been re-run.

**Notebook reproduced exactly.** As-written numbers match the committed notebook outputs
(0.8350 / 0.8330 / 0.8255 / 0.7820), so the notebook's numbers are *real* — just compromised.

**Leakage cost: the 2026-08-26 figures did not reproduce (re-measured).** Moving the vectorizer
fit after the split and changing nothing else gives 0.7830 / 0.8255 / 0.8355 / 0.8310
(GaussianNB BoW / MultinomialNB BoW / BernoulliNB BoW / MultinomialNB TF-IDF) against
0.7820 / 0.8255 / 0.8350 / 0.8330 as written. Over ten split seeds the difference stays within
±0.0055 with a spread of 0.0013 to 0.0031: not distinguishable from zero. Tables in D-009.

**5-fold CV on train only (re-measured, vectorizer refit inside every fold):**

| Model | CV mean ± std |
|---|---|
| MultinomialNB (TF-IDF) | 0.8345 ± 0.0063 |
| MultinomialNB (BoW) | 0.8297 ± 0.0095 |
| BernoulliNB (BoW) | 0.8294 ± 0.0065 |

TF-IDF leads by about 0.005, inside each model's own spread; the other two are tied to 0.0003.
The notebook's declared winner cannot be distinguished from the rest.

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

**H-2 · RESOLVED 2026-09-29.** The 418 duplicates are real (824 rows belong to a duplicated text).
Inside the notebook's 10k sample there are 22 duplicate rows, and **5 of the 2,000 test rows have
a twin in train**, all with agreeing labels: an upper bound of 0.25 points on accuracy. Guarded
permanently by `unique_review_indices` and `test_no_review_text_appears_in_both_splits`.

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
Session date:      2026-09-03
Model:             Claude Opus 5
What we did:       Phase B tooling + CI; package scaffold; schemas as the shared
                   contract; 43-test suite (23 pass, 20 xfail); CONTRIBUTING +
                   AGENTS for the Pranav/Lakshay split; fixed check_env.py.
What's left:       Phase A (pin deps, correct report claims), then C and D in
                   parallel. Every xfail marker is one unit of work.
Watch out for:     H-1 still unverified — data/ and recsys/ are empty shells on
                   purpose. Do not design them until the ASIN join is tested.

Session date:      2026-08-26
Model:             Claude Opus 5
What we did:       Full audit; wrote Field Guide doc set; created + pushed GitHub repo.
What's left:       Everything in Phase A onward. No code fixed yet.
Watch out for:     Report + summary contain false methodology claims. Verify, don't inherit.
```
