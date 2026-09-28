# AGENTS.md — rules for any AI assistant working in this repo

> Cross-tool mirror of [`CLAUDE.md`](CLAUDE.md). Cursor, Codex and several other tools read
> `AGENTS.md`; Claude Code reads `CLAUDE.md`. **Keep the two in sync** — if you change one,
> change the other in the same commit.
>
> If your tool reads neither (verify what Antigravity looks for), copy these rules into
> whatever config file it does use. Both halves of this project must work under one set of
> constraints, or the halves stop fitting together.

---

## Read first, every session

1. [`docs/HANDOVER.md`](docs/HANDOVER.md) — where things stand right now.
2. [`docs/CONSTRAINTS.md`](docs/CONSTRAINTS.md) — what you may not do.
3. [`CONTRIBUTING.md`](CONTRIBUTING.md) — module ownership, PR flow, the xfail convention.
4. `git status --short` and `git log --oneline -5`. **Trust the working tree over any document,
   including this one.**

If the tree is dirty with the other person's work, say so and stop.

---

## Correctness rules — these are why the project exists in this shape

An audit on 2026-08-26 graded this project 3.4/10 and measured three methodology defects. Each
rule below traces to one of them. Breaking one is not a style disagreement; it reproduces a
known, measured bug.

1. **Split before you fit.** Never fit a vectoriser, scaler, encoder or selector on data that
   includes the test split. Split first, fit on train, `transform` everything else.
   *The original bug's measured accuracy cost is not distinguishable from zero (DECISIONS.md D-009); the rule stands on correctness, not on the size of the inflation.*
2. **Never select a model, threshold or hyperparameter on the test set.** Cross-validate on
   train. Touch test exactly once, at the end.
3. **Never report a difference without its spread.** A mean with no ± beside it is not a
   result. If the margin is smaller than the standard deviation, say so in the same sentence.
   *The original "best model" won by 0.0020 on the test set; under 5-fold CV the models differ
   by less than one fold-to-fold std (DECISIONS.md D-009).*
4. **Never remove `not`, `no`, `nor`, `never` or `n't` from sentiment-bearing text.**
   *In the original pipeline, "This movie was not good at all." and "This movie was good."
   produced byte-identical feature vectors.*
5. **Never train, embed or fit inside a request handler.** Artifacts are built offline and
   loaded at boot. This is what makes free-tier hosting viable.
6. **Never return `str(e)` or a traceback to an HTTP client.** Log server-side against an
   opaque error id; return the id.
7. **Never present a synthetic, hand-typed or illustrative number as a measurement.** A
   placeholder says `[PLACEHOLDER]` in the rendered output.

---

## Evidence rules

- **No success claim without fresh evidence in the same message** — the command you ran just
  now, plus its output. If you did not run it, say *"not verified — here is what would verify
  it."*
- **Read the count, not just the exit code.** A `mypy` run over zero files exits 0. A suite
  that collects zero tests exits 0. Both are false greens.
- **A number in a document is testimony, not evidence.** Re-measure before building on it. The
  audit found this project's own report asserting a safeguard the code did not implement.
- **Never invent a filename, symbol, package or capability.** Grep before you import.

---

## Scope rules

- **One logical change per PR.** "Fix the pipeline" is not a task; "move the vectoriser fit to
  after the split" is.
- **Stay inside your assigned modules** (see `CONTRIBUTING.md`). Cross-boundary edits are how
  two working halves stop fitting together.
- **`cinewhy/schemas.py` changes require the other person's approval.** It is the contract both
  halves import.
- **No new dependency without asking.** Use a throwaway venv for one-off tooling; never install
  into the project's `venv/`.
- **Additive checkpoints for any restructure.** New code lands and goes green *before* old code
  is removed. The tree never goes red between commits.
- **Never edit a test to make a change pass.** A failing guard test *is* the finding — revert
  the change. The sole exception is a test whose own name states a precondition now genuinely
  met; then invert it and rename it.
- **Do not delete an `xfail` marker without first watching the test fail** against the pre-fix
  code.

---

## Git rules

- **Stage explicit paths. Never `git add -A` or `git add .`** — zero-byte files appear in this
  repo's root from shell redirects. Run `git status --short` after every commit and delete what
  shows up.
- **Never commit `Data/*.csv`, model weights, or any file over ~5 MB.** CI enforces this.
- **Never commit a secret**, including in notebook outputs. Run `nbstripout` before committing
  the notebook.
- **Never force-push `main`** or rewrite published history.
- **Commits carry the author's name alone.** Do not add `Co-Authored-By` trailers naming an
  assistant or model, and do not add "Generated with …" lines to commits, PRs, tags or
  releases. Assistant-written code is the author's code.
  *(Engineering rationale in code comments and in `docs/` is not attribution — write plenty.)*

---

## Verification

Run all four before pushing. All must be green, with non-zero counts:

```bash
ruff format --check .    # N files already formatted
ruff check .             # All checks passed!
mypy                     # Success: no issues found in N source files   (N > 0)
pytest                   # N passed                                     (N > 0)
```

Current expected baseline: **23 passed, 20 xfailed**, mypy clean on **17 source files**.

---

## Environment

```
python:   use the project venv explicitly — a same-version global is NOT the same environment
encoding: PYTHONIOENCODING=utf-8   ← stdout is cp1252 on Windows; printing an emoji crashes
data:     Data/IMDB Dataset.csv    ← gitignored, 64 MB, fetch per README
```

Write files with your editor, not shell heredocs — quoted payloads carrying code mangle escapes
and leak junk files into the repo root on this machine.

---

## Comment style

Explain **intent**, not syntax. What is this block for, what calls into it, what does it assume
exists. Never restate the code.

```python
# bad
i += 1  # increment i

# good
# Fit on train only — test rows must never reach the vocabulary (DECISIONS.md D-004).
vectorizer.fit(X_train)
```
