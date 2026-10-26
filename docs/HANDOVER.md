# HANDOVER.md

> Where things stand *right now*. Field Guide habits #1 and #13.
> Read this first, every session. Update it last, every session.

**Last updated:** 2026-09-29 · Claude Sonnet 5.5 · Phase A + start of Phase C
**Next session should start with:** the "Phase C so far" rows below, then the decisions listed in the ritual at the bottom

---

## State in five lines

0. **UPDATE 2026-10-22: the five lines below describe the 2026-08-26 audit and are historical.**
   A working local demo now exists (data join, polarity model, aspect analysis, recommender, API,
   web UI, hash-verified artifacts). Read the "Session 2026-10-22" ritual entry at the bottom first.
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
| ✅ | **Phase A done in-repo (2026-09-29):** B11 `requirements.txt` pinned to the 105-package closure; M4 `unique_review_indices` + a real guard test; S4 report corrected in place with an errata block; S5 `MODEL_CARD.md`; S1 already true in-repo (README, D-001) |
| ⚠️ | **Phase A leftovers:** `pip-audit` in CI (B11) needs a new tool, so it is waiting on Pranav; the **E: drive summary** (SVC claim, "SentimentStream") is outside the repo and this machine has no E: drive, so it is untouched |
| ✅ | **D-009 (2026-09-29):** re-measuring showed the "1.65 points of leakage" claim does not reproduce; every document that quoted it was corrected |
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

**H-1 · RESOLVED 2026-10-22 by a different route (D-012): aclImdb's `urls_*.txt` give an exact
IMDb title number per review, joined to MovieLens `links.csv`. No ASIN matching was needed.**
The original text below is kept for history.

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
Session date:      2026-10-26 (session "nlp 2", final state)
Model:             Claude Sonnet 5.5
What we did:       Data layer (FEATURE-004), posters/meta API, /discover + /facets with recency
                   (FEATURE-005), an ES-module front end (web/js; poster wall with receipts,
                   optional onboarding, How it works from eval.json), checked at 375/768/1440
                   px, dark mode, keyboard, reduced motion. Demographics tested on MovieLens-1M
                   and shipped OFF (D-019). Recency cost measured (D-020): free up to 50%, so the
                   age default is capped at 50%. Polarity model retrained on aclImdb + RT + ebD
                   with whole films held out (D-017): Rotten Tomatoes 78.2% to 83.6%, all
                   sources up. REAL BUILD artifacts/v3 (11,065 films, 1.72M reviews, manifest
                   6ef2235588a8). docs/DATASET.md is the inventory; D-016..D-020 the decisions.
What's left:       1) Deployment: the Dockerfile and the CI docker job still describe the old
                   build (CI quality and secrets jobs pass; docker fails). Public hosting also
                   meets dataset terms: RT is CC BY-NC-SA, MovieLens forbids redistribution, TMDB
                   needs attribution. 2) Aspect finder recall is 51% on random clauses and the
                   gold labels are the assistant's: needs an independent second labeller
                   (docs/LABELLING.md). 3) Constitution section 6 self-revision passes.
                   4) Hindi has almost no collaborative signal (few MovieLens ratings, 72 films
                   link to RT).
Watch out for:     The hybrid is slightly WORSE than similar-taste alone (D-018); do not claim
                   the aspects raise hit rate. artifacts/ is git-ignored: the served build travels
                   as cinewhy-artifacts-v3.zip (365 MB, SHA-256 071CC424...4D47, README step 5);
                   older builds are in artifacts/v2 and artifacts/ and are skipped by the server
                   (it picks the highest vN). Old test servers on ports 8000-8003 may still be
                   running. Junk 0-byte files appear at the repo root: sweep with git status.
                   A hook shows a harmless Windows 'cannot find http://localhost...' pop-up when
                   command output contains that URL. The TMDB token was regenerated by Pranav
                   (not stored anywhere). Teammate onboarding: README "Set up on a new machine".

Session date:      2026-10-25 (session "nlp 1", continued)
Model:             Claude Sonnet 5.5
What we did:       Pushed the demo (3 commits). Then fixed quality gaps: measured aspect-finder
                   recall/precision on random clauses (51% / 60%; D-015 corrects D-013's 86.7%),
                   tried and recorded two failed recall fixes, added a negation cue layer,
                   a slider direction check, catalogue 2,355 to 4,164 films (min_reviews 5),
                   independent-labelling kit (docs/LABELLING.md, cinewhy.absa.agreement),
                   archive/ for the old notebook and report, fully pinned requirements-serve.txt.
What's left:       A human must fill tests/data/aspect_label_sheet.csv (only an independent
                   labeller can remove "the assistant labelled everything"). Deployment is
                   still unverified (Dockerfile never built; CI docker job never run). The aspect
                   finder is the weakest component; improving it needs far more labelled data.
                   Constitution section 6 and audit-prompt Phase 5 passes are owed.
Watch out for:     Never quote D-013's 86.7%. Samples A and B informed the lexicon, so only C
                   (and B+C polarity) are clean. GateGuard denies first writes per path; stub first.

Session date:      2026-10-22 (session "nlp 1")
Model:             Claude Sonnet 5.5
What we did:       Built the whole demo. aclImdb x MovieLens join (D-012, H-1 resolved);
                   polarity model via run_experiment; clause-level aspect analysis with
                   hand-labelled dev + held-out gold sets (D-013); item-item CF + aspect
                   blend evaluated on held-out users (D-014); hash-verified artifacts;
                   FastAPI (+rate limit, size cap, opaque errors); web UI (3 tabs);
                   start.bat; fetch.py with pinned SHA-256. All xfails are gone.
Verified (RAN):    pytest all green, ruff clean, mypy strict clean (37+ files); UI driven in
                   Chrome: sliders, analyze tab, eval tab. See README "What was measured".
What's left:       Deployment, deliberately postponed at the user's request: the Dockerfile
                   and its CI job have NEVER been run (no Docker here). Independent human
                   labels for the gold sets. Measure aspect-lexicon recall. Fix negation in
                   short clauses. Poster images (needs a TMDB key). Commit: NOTHING from
                   this session is committed yet; stage explicit paths.
Watch out for:     GateGuard denies the first write to every new path: state facts, write a
                   one-line stub, then the real content. Junk 0-byte files appear at the repo
                   root named after the token after `->`; sweep with git status. artifacts/
                   and Data/raw/ are gitignored and must be rebuilt on a fresh machine
                   (start.bat does it). ai.stanford.edu was unreachable; the HF mirror is
                   hash-pinned. Do not quote 0.89 as clause accuracy: it is whole-review.

Session date:      2026-09-29
Model:             Claude Sonnet 5.5
What we did:       Phase A (pinned requirements, dedupe helper, report errata, model
                   card); found the 1.65-pt leakage claim does not reproduce (D-009,
                   BUG-001); Phase C text pipeline: strip_html/build_stoplist/normalise,
                   stdlib only, no stemming (D-010, FEATURE-002). 62 pass, 13 xfail.
What's left:       score_polarity (train a polarity model with the harness; the
                   classifier must go through run_experiment), a hand-labelled sample so aspect
                   detection can be measured, bumping the 14 vulnerable pins (169
                   advisories; the requirements.txt audit is informational until then),
                   E: drive summary corrections, H-1, Phase D onward.
Also done later:   split_sentences + detect_aspects (lexicon baseline, accuracy NOT
                   measured); pip-audit and ML deps added to CI; main pushed to GitHub.
                   Then cinewhy/absa/train.py: split/CV/pick_winner/final_evaluation,
                   all three methodology guards real, first real-data run = no winner
                   (D-011, different sample from D-009 so not like-for-like).
                   123 passed, 7 xfailed. Remaining xfails are Phase D/E work.
Watch out for:     Do not quote the old leakage numbers. venv/pyvenv.cfg was repointed to
                   this machine's Python 3.13.15 (venv is gitignored). NLTK stopwords
                   corpus was downloaded to ~/nltk_data for scratch measurement only.
                   Measurement scripts were not committed, so re-derive from D-009/D-010.

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
