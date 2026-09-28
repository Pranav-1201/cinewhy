# Contributing to CineWhy

Two people build this: **Pranav** and **Lakshay**. They use different tools — Pranav is on
Claude Code, Lakshay on an AI IDE (Antigravity or Cursor). That is fine and expected.

**Which assistant writes the code does not matter. What matters is that everything below is
enforced by CI rather than by agreement.** The formatter normalises style, the linter and type
checker reject drift, and the test suite proves the contract still holds. A PR that conforms
merges; one that doesn't, doesn't.

---

## Setup (do this once)

```bash
git clone https://github.com/Pranav-1201/cinewhy.git
cd cinewhy

python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

pip install -e ".[dev]"
```

Get the dataset separately — it is not in the repo. See [`README.md`](README.md) §Quick start.

**Verify your environment before writing anything:**

```bash
python check_env.py            # exits 0 only if every package meets its floor
pytest                         # expect: "23 passed, 20 xfailed"
```

If `pytest` reports a different passed count, stop and ask before continuing — you are not
looking at the same tree as everyone else.

> **Windows note:** Python's stdout here is cp1252, so any script printing emoji or em dashes
> raises `UnicodeEncodeError`. Set `PYTHONIOENCODING=utf-8` first. This cost a full session
> once already.

---

## Who owns what

Split by **module**, not by phase. Phases that touch disjoint directories run in parallel.

| Directory | Phase | Owner |
|---|---|---|
| `cinewhy/text/`, `cinewhy/absa/` | C — methodology repair | **Pranav** |
| `cinewhy/data/`, `cinewhy/recsys/` | D — data + recommender | **Lakshay** |
| `api/` | E — service | **Pranav** |
| `web/` | F — frontend | **Lakshay** |
| `cinewhy/schemas.py` | — | **both, by agreement** |
| `cinewhy/artifacts/` | D | whoever reaches it first — announce in the PR |

Stay inside your directories. If your work needs a change in the other person's, open an issue
rather than reaching across — a cross-boundary edit is how two working halves stop fitting.

**Phases A and B are joint.** Do them together in one sitting before splitting up; they define
the rules everything else obeys.

---

## Changing the contract

`cinewhy/schemas.py` is the one file neither person edits alone.

Every object crossing a module boundary is defined there. Lakshay's ranker consumes what
Pranav's ABSA produces; the frontend renders what the API serialises. All of them import the
same types, which is the mechanism that keeps the halves compatible.

To change it:

1. Open a PR that changes **only** `schemas.py` and `tests/test_schemas.py`.
2. Say in the description what breaks and who has to adapt.
3. Get the other person's approval before merging.
4. Merge it **before** either of you writes code against the new shape.

Adding an `Aspect` member is a migration, not a tweak — it invalidates every stored aspect
score and forces an artifact rebuild. Treat it accordingly.

---

## The xfail convention

The scaffold ships with 20 `xfail(strict=True)` tests. They are your work queue, and they are
more precise than any to-do list: each one states exactly what its function must do.

```python
@pytest.mark.xfail(strict=True, reason="Phase C: normalise() not implemented")
def test_negation_survives_preprocessing(negation_pair): ...
```

Working a task means:

1. Find the xfail tests covering your function.
2. **Watch them fail for the right reason first** — run them before you write anything. A guard
   test you never saw fail proves nothing.
3. Implement until they pass.
4. `strict=True` means a passing xfail *fails the suite* (XPASS). That is the handshake:
   delete the marker in the same PR. A forgotten marker cannot go unnoticed.

Never delete a test to get to green. If your change breaks a test in
`tests/test_methodology.py`, the change is wrong — those guard the three defects the audit
measured, and re-introducing one is worse than not shipping the feature.

---

## Branch and PR flow

```bash
git switch -c phase-c/negation-preserving-preprocess    # phase/short-description
# ... work ...
git add cinewhy/text/preprocess.py tests/test_methodology.py   # explicit paths, never -A
git commit
git push -u origin phase-c/negation-preserving-preprocess
```

Then open a PR. Rules:

- **One plan row per PR.** Reference the audit idea ID (`M3`, `B7`, `F2`…) in the title.
- **CI green before review.** Not "green on my machine".
- **The other person reviews.** Pranav can run `/code-review` on any branch; use it on
  Lakshay's PRs before merging. That gives both of you the benefit of one subscription.
- **Never `git add -A`.** Stray zero-byte files appear in this repo's root from shell
  redirects — two showed up during the audit alone. Stage explicit paths and run
  `git status --short` after every commit.
- **Never force-push `main`.** Never rewrite published history.

Stop at phase boundaries for a joint review rather than rolling straight into the next one.

---

## What CI checks

Everything in [`.github/workflows/ci.yml`](.github/workflows/ci.yml), on every push and PR:

| Gate | Command | Passing looks like |
|---|---|---|
| Format | `ruff format --check .` | `N files already formatted` |
| Lint | `ruff check .` | `All checks passed!` |
| Types | `mypy` | `Success: no issues found in N source files`, **N > 0** |
| Tests | `pytest` | `N passed`, **N > 0** |
| Notebook | `nbstripout --verify` | exit 0 |
| Size | tracked files ≤ 5 MB | no output |
| Secrets | `gitleaks` | 0 findings |

The two count assertions are deliberate. A `mypy` run that checks zero files exits 0. A suite
that collects zero tests exits 0. Both are false greens that get recorded as evidence, so CI
fails if the count is absent.

Run all four locally before pushing:

```bash
ruff format . && ruff check . && mypy && pytest
```

---

## Code conventions

Most of this is enforced, so you do not need to remember it — but knowing *why* helps:

- **Type annotations everywhere** (`ANN` rules). The types are the contract; unannotated code
  can't participate in it.
- **Google-style docstrings** on every public function. Explain what the block is *for*, what
  calls into it, what it assumes — never restate the code. `# increment i` is noise;
  `# fit on train only — test rows must never reach the vocabulary (D-004)` is insurance.
- **Line length 100.** Set by the formatter; don't fight it.
- **No new dependency without asking.** Adding one changes resolution for every other package
  and invalidates prior test results. For one-off tooling, build a throwaway venv — never
  install into the project's `venv/`.

---

## The rules that are actually about correctness

Full list in [`docs/CONSTRAINTS.md`](docs/CONSTRAINTS.md). The ones that cost this project a
grade of 3.4/10:

1. **Split before you fit.** Never fit a vectoriser, scaler or encoder on data containing the
   test split. The audit claimed this cost 1.65 points; that did not reproduce (DECISIONS.md D-009), but the rule stands.
2. **Never select a model or threshold on the test set.** Cross-validate on train; touch test
   once, at the end.
3. **Never report a difference without its spread.** The original "best model" won by 0.0020
   on the test set; under CV the models differ by less than one fold-to-fold std (D-009).
4. **Never delete negation** from sentiment text.
5. **Never train or embed inside a request handler.** Artifacts are built offline, loaded at
   boot. This is what keeps the free tier viable.
6. **Never return `str(e)` or a traceback to a client.**
7. **Never present a synthetic number as a measurement.** If a figure is a placeholder, it says
   so in the rendered output.

---

## Where to read next

| | |
|---|---|
| Where things stand right now | [`docs/HANDOVER.md`](docs/HANDOVER.md) |
| The audit and full roadmap | [`docs/AUDIT-2026-08-26.md`](docs/AUDIT-2026-08-26.md) |
| System map | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| Execution trace and where it breaks | [`docs/FLOW.md`](docs/FLOW.md) |
| Why decisions were made | [`docs/DECISIONS.md`](docs/DECISIONS.md) |
| Verification commands | [`docs/TEST_CHECKLIST.md`](docs/TEST_CHECKLIST.md) |
| How to undo a bad change | [`docs/ROLLBACK.md`](docs/ROLLBACK.md) |

Start with `HANDOVER.md`. It is updated at the end of every session and says exactly where the
project stands.

---

## End of session

Whoever worked last updates the five-line ritual at the bottom of `docs/HANDOVER.md`: what we
did, what's left, what to watch out for. Thirty seconds, and it is the difference between the
next session starting cold and starting informed.
