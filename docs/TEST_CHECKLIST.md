# TEST_CHECKLIST.md

> Actual commands, actual expected outputs. Field Guide habit #8.
> "AI claiming success" and "code actually working" are two different facts.

**Version-pin:** last revised by Claude Opus 5, 2026-08-26.

Run everything with `PYTHONIOENCODING=utf-8` set (see `CONSTRAINTS.md` gotchas).
Python is **`D:\NLPPROJECT\venv\Scripts\python.exe`** — absolute path, always.

---

## Level 0 — what exists today (2026-08-26)

There is **no test suite, no linter config, no typechecker, no CI, and no build**.
Honest status of every gate:

| Gate | Command | Status today |
|---|---|---|
| Unit tests | — | **does not exist** |
| Lint | — | **does not exist** |
| Typecheck | — | **does not exist** |
| Build | — | **does not exist** |
| CI | — | **does not exist** (no `.github/` on disk) |
| Env check | `venv\Scripts\python.exe check_env.py` | exists, but see caveat ↓ |

> **`check_env.py` caveat — it cannot fail the way it implies.** It declares minimum versions in its
> `REQUIRED` dict, then never compares them: `min_ver` is bound and unused. It only checks that the
> import succeeds. A too-old package prints `✓` and the script reports "All packages present."
> Treat its green as "importable", not "correct version".

Until Phase B lands, the only real verification available is running the notebook top to bottom and
reading the outputs.

---

## Level 1 — the gates every phase must pass (target)

Each is a command plus the **observable** that makes it meaningful. A gate with no count is not a
gate.

```bash
# 1. Tests — must report a non-zero collected count
venv/Scripts/python.exe -m pytest -q
#    expect: "N passed" with N > 0.  N == 0 is a FAILURE, not a pass.

# 2. Coverage on first-party code only
venv/Scripts/python.exe -m pytest --cov=cinewhy --cov-report=term-missing
#    expect: total >= 70% (Phase C), >= 80% (Phase E)

# 3. Lint
venv/Scripts/python.exe -m ruff check .
#    expect: "All checks passed!"

# 4. Format check (does not write)
venv/Scripts/python.exe -m ruff format --check .
#    expect: "N files already formatted"

# 5. Types
venv/Scripts/python.exe -m mypy cinewhy api
#    expect: "Success: no issues found in N source files", N > 0
#    NOTE: an empty file list is a false green. Check N.

# 6. Notebook is output-stripped before commit
venv/Scripts/python.exe -m nbstripout --verify Movie_Sentiment_Analysis.ipynb
#    expect: exit 0, no diff
```

---

## Level 2 — methodology gates (this project's real risk)

These are the tests that would have caught what the audit found. They are **guard tests**: if one
fails, the change is wrong, not the test (`CONSTRAINTS.md` #11).

```bash
venv/Scripts/python.exe -m pytest tests/test_methodology.py -v
```

| Test | Asserts | Why it exists |
|---|---|---|
| `test_vectorizer_never_sees_test_split` | the fitted vocabulary is a subset of tokens present in the **train** split only | catches F-1 leakage regression |
| `test_negation_changes_the_vector` | `preprocess("not good") != preprocess("good")` | catches D-003 regression |
| `test_negation_changes_the_prediction` | the two strings above get different labels | end-to-end version of the above |
| `test_train_serve_preprocess_identical` | serving path imports the *same* `preprocess` symbol as training | catches train/serve skew |
| `test_model_selection_uses_no_test_data` | selection routine is never handed the test arrays | catches D-004 regression |
| `test_reported_gap_exceeds_spread` | any claimed winner's margin > 1 std of its CV folds | stops noise being reported as a result |
| `test_no_duplicate_reviews_across_splits` | train ∩ test review texts = ∅ | the raw file has **418** exact duplicate reviews; a random split can straddle them |

---

## Level 3 — API gates (Phase D onward)

```bash
# boot + liveness
docker build -t cinewhy-api . && docker run -d -p 7860:7860 cinewhy-api
curl -s localhost:7860/health         # expect: {"status":"ok","manifest":"<sha>"}

# artifact integrity — must REFUSE to boot on mismatch
#   corrupt one byte of an artifact, restart, expect non-zero exit + log line
#   "manifest hash mismatch", and NO server listening on 7860

# no stack traces leak
curl -s localhost:7860/movie/does-not-exist | grep -qi "traceback" && echo LEAK || echo OK
#    expect: OK

# recommendations are deterministic for a fixed profile
curl -s -X POST localhost:7860/recommend -d @tests/fixtures/profile.json > a.json
curl -s -X POST localhost:7860/recommend -d @tests/fixtures/profile.json > b.json
diff a.json b.json                     # expect: no output

# every recommendation carries evidence or explicitly declares it has none
venv/Scripts/python.exe -m pytest tests/test_evidence_contract.py
#    expect: passes — no item may return a reason string with an empty evidence array
```

---

## Level 4 — before any public deploy

- [ ] All Level 1 gates green **in CI**, not just locally. A green suite that exists only on this
      machine does not count.
- [ ] `pip-audit` clean, or every finding explicitly accepted in writing.
- [ ] No secret in the tree: `gitleaks detect --no-git` → 0 findings.
- [ ] Rate limiting verified by actually exceeding it and receiving 429.
- [ ] `ROLLBACK.md` drilled once end to end, with the timestamp written into that file.
- [ ] Every user-facing number traced to a command in this file. No exceptions.

---

## The rule this file exists to enforce

Before writing "done", paste the command **and** its output. If the output has no count in it,
derive one and say how. If you did not run it this session, write
**"not verified — here is what would verify it."**
