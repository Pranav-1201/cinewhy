# CONSTRAINTS.md

> What an AI session must never do here. Field Guide habit #7.
> "Allow" should mean *scoped* permission. This is the scope.

**Version-pin:** last revised by Claude Opus 5, 2026-08-26.

---

## Hard rules — no exceptions without Pranav saying so in the session

1. **Never fit a vectorizer, scaler, encoder, or selector on data that includes the test split.**
   Split first. Fit on train. `transform` everything else. This project's headline number was
   inflated 1.65 points by exactly this bug (`DECISIONS.md` D-004, `FLOW.md` F-1).

2. **Never select a model, threshold, or hyperparameter using the test set.** Cross-validate on
   train. The test set is evaluated once, at the end.

3. **Never report a model comparison without its spread.** A mean with no ± beside it is not a
   result. If the gap is smaller than the standard deviation, say so in the same sentence.

4. **Never remove `not`, `no`, `nor`, `never`, or `n't` from sentiment-bearing text.** See D-003.

5. **Never train, embed, or fit anything inside an HTTP request handler.** Artifacts are built
   offline and loaded at boot. This is what keeps the free tier viable.

6. **Never commit `Data/*.csv`, model weights, or any file over ~5 MB.** Artifacts go to HF Hub.

7. **Never commit a secret.** No API keys in code, notebooks, `.env`, or notebook *outputs*. TMDB
   keys come from the environment. If one is ever committed, it is burned — rotate, don't just
   `git rm`.

8. **Never return `str(e)` or a traceback to an HTTP client.** Log it server-side with an error id;
   return the id.

9. **Never present a synthetic, hand-typed, or illustrative number as a measurement.** If a figure
   is a placeholder, it says `[PLACEHOLDER]` in the rendered output. The current report violates
   this (§15, `[INSERT FIGURE 3 ...]` with a narrative "~170" beside it).

10. **Never use `git add -A` or `git add .`** Stage explicit paths. Stray shell-redirect artifacts
    are a known hazard on this machine.

11. **Never edit a test to make a change pass.** A failing guard test is the finding. Revert the
    change instead. The one exception: a test whose *own name* states a precondition now genuinely
    met — invert it and rename it.

12. **Never modify `Movie_Sentiment_Analysis.ipynb` in place without a `.bak` first.** It is the
    project's only historical artifact and it is not yet under git for its full history.

---

## Scope rules

13. **One logical change per PR** (Field Guide habit #12). "Fix the pipeline" is not a task; "move
    the vectorizer fit after the split" is.

14. **No new dependency without asking.** Adding one changes resolution for every other package and
    invalidates prior test results. If you need a tool for a one-off check, build a throwaway venv —
    never install into the project's `venv/`.

15. **Additive checkpoints for any restructure.** New code lands and goes green *before* old code is
    removed. The tree never goes red between commits.

16. **Leave uncommitted work alone.** If the working tree is dirty when a session starts, say so and
    stop. Do not stash, reset, or commit someone else's work.

---

## Claims discipline

17. **No success claim without fresh evidence in the same message.** "Tests pass" requires the
    command and its output from *this* session. Read the count, not just the exit code — a suite
    that collected 0 tests and exited 0 proved nothing.

18. **Numbers are transcribed, never remembered or recomputed from memory.** If a value is not
    visible in output in front of you, re-run to get it.

19. **A prior document's number is testimony, not evidence.** Re-measure before building on it. The
    audit that produced these docs found the project's own report asserting leakage *prevention*
    while the code did the opposite.

---

## Known environment gotchas (this machine)

- Python stdout is **cp1252** by default → any script printing emoji or `—` dies with
  `UnicodeEncodeError`. Set `PYTHONIOENCODING=utf-8`.
- Use `D:\NLPPROJECT\venv\Scripts\python.exe` by absolute path. The global 3.13.1 looks identical
  and is not the same environment.
- Bash tool cwd is unreliable between calls — always absolute paths.
- Don't put `"` inside a PowerShell here-string passed to a native exe; it word-splits.
- Write files with the editor, not shell heredocs. Quoted payloads containing `{...}` format specs
  leak shell artifacts into the repo root.
