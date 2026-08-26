# CLAUDE.md — session rules for CineWhy

> Read this, then [`docs/HANDOVER.md`](docs/HANDOVER.md), before doing anything else.
> These rules come from the AI Collaboration Field Guide (habits #3, #10–#15) and from an audit of
> this project on 2026-08-26 that found three methodology defects the previous documentation
> actively denied.

---

## Start of every session

1. Read `docs/HANDOVER.md` — it says exactly where things stand.
2. Read `docs/CONSTRAINTS.md` — it says what you may not do.
3. `git status --short` and `git log --oneline -5`. Trust the working tree over any doc, including
   this one.
4. If the tree is dirty with someone else's work, say so and stop.

## End of every session

Update the five-line ritual at the bottom of `docs/HANDOVER.md`: what we did, what's left, what to
watch out for. Thirty seconds. It is the cheapest and highest-leverage habit here.

---

## The habits, as rules

**#3 · Comment intent, not syntax.** Explain what a block is *for*, what calls into it, what it
assumes exists. Never restate the code. `# increment i` is noise; `# fit on train only — test rows
must never reach the vocabulary (see DECISIONS D-004)` is insurance.

**#10 · Read the diff.** Never accept a change based on a summary of it — including your own
summary. Diffs cannot lie about what changed; summaries can.

**#11 · Why before what.** Explain the plan before implementing. Catching a flawed plan costs a
paragraph; catching a flawed implementation costs a day.

**#12 · One logical change per request.** "Fix the pipeline" is not a task. "Move the vectorizer fit
to after the split" is.

**#13 · Handoff summary, every session.** See above.

**#14 · Version-pin your context.** Note which model made which decision. Every entry in
`DECISIONS.md` carries a model name for exactly this reason — behaviour shifts between versions, and
that matters when you are debugging the decision six months later.

**#15 · Own the mental model.** If Pranav cannot explain what the code does in his own words, it does
not get accepted, no matter how good the docs are. These files support understanding; they do not
replace it.

---

## Non-negotiables (full list in `docs/CONSTRAINTS.md`)

- No success claim without fresh evidence **in the same message** — command plus output, run this
  session. Read the *count*, not just the exit code.
- Split before you fit. Never fit a vectorizer/scaler/encoder on data containing the test split.
- Never select a model or threshold on the test set.
- Never report a difference without its spread. This project's headline conclusion was noise.
- Never delete negation from sentiment text.
- Never train or embed inside a request handler.
- Stage explicit paths. Never `git add -A`.
- Never edit a test to make a change pass — a failing guard test *is* the finding.
- No new dependency without asking. Use a throwaway venv for one-off tooling.

---

## Attribution

Commits carry Pranav's name alone. Do **not** add `Co-Authored-By` trailers naming an assistant, or
"Generated with …" lines in commits, PRs, tags, or releases. Assistant-written code is Pranav's code.

*(Engineering rationale in code comments and in `docs/` is not attribution — write plenty of it.)*

---

## Environment

```
python:  D:\NLPPROJECT\venv\Scripts\python.exe     ← absolute, always
encoding: export PYTHONIOENCODING=utf-8            ← stdout is cp1252 without it
data:     D:\NLPPROJECT\Data\IMDB Dataset.csv      ← gitignored, 64 MB, fetch per README
```

The global Python is also 3.13.1 and is **not** the same environment. Bash cwd resets between calls.
Write files with the editor, not shell heredocs.
