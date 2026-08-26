# ROLLBACK.md

> The way back out. Field Guide habit #9.
> Confidence to let AI make big changes comes from knowing exactly how to reverse them.

**Version-pin:** last revised by Claude Opus 5, 2026-08-26.
**Drilled:** never. ← *this must say a date before anything is deployed publicly.*

---

## 0. Current safety net (be honest about it)

As of 2026-08-26 the repository was initialised for the first time. Before that commit there was
**no version history at all** — four months of work existed as loose files with no recovery point.

The single most valuable rollback asset right now is the initial commit, which captures the project
exactly as it stood before any audit-driven change.

Off-repo copies that exist, and what they are good for:

| Copy | Location | Good for |
|---|---|---|
| Rendered notebook | `E:\Projects and Research papers\NLP Project - Movie Sentiment Analysis\Movie_Sentiment_Analysis.html` | reading the original outputs if the notebook is ever corrupted |
| Report (docx) | same folder | the original written report |
| Raw dataset | `D:\NLPPROJECT\Data\IMDB Dataset.csv` | **not in git** — if deleted, re-download (see `README.md`) |

---

## 1. Undo an uncommitted mess

```bash
git status --short                 # look first. always.
git diff                           # read it. do not skip.
git restore <specific/file>        # one file
git restore .                      # everything tracked — destroys uncommitted work
```

`Data/` and `venv/` are gitignored, so neither is touched by any git restore.

---

## 2. Undo the last commit

```bash
git log --oneline -5
git revert <sha>                   # preferred: adds a new commit, history stays honest
git reset --soft HEAD~1            # only if UNPUSHED and you want to re-do the commit
```

Never `reset --hard` on anything already pushed. Never force-push a shared branch.

---

## 3. Roll back a phase

Each phase ends on a tagged commit (`phase-a`, `phase-b`, …).

```bash
git tag -l
git diff phase-b..HEAD --stat      # see what a rollback would discard
git revert --no-commit phase-b..HEAD && git commit -m "revert to phase-b"
```

Then re-run the Level 1 gates from `TEST_CHECKLIST.md` and confirm the counts are non-zero.

---

## 4. Roll back a deployment

**Hugging Face Space (API).** Spaces are git repos; a deploy is a push.

```bash
git -C <space-clone> log --oneline -5
git -C <space-clone> revert <sha> && git -C <space-clone> push
# then: curl -s https://<space>.hf.space/health  → expect {"status":"ok", "manifest":"<old sha>"}
```

**Vercel (frontend).** Use the dashboard's *Instant Rollback* on the previous production
deployment, or `vercel rollback <url>`. Verify by loading the site and checking the build id in the
footer changed back.

**Artifacts (HF Hub).** Artifacts are content-hashed and immutable; rolling back means pointing
`manifest.json` at the previous hashes and redeploying the API. Never mutate an artifact in place —
that breaks the integrity check that is supposed to protect you.

---

## 5. The order matters

Roll back **frontend first, API second, artifacts last**. The frontend tolerates an older API; an
older API cannot read newer artifacts. Going the other way leaves a window where the UI asks for
fields the API no longer returns.

---

## 6. What to re-check after any rollback

1. `curl /health` returns 200 and the **expected** manifest hash — not just 200.
2. One real recommendation request returns items *and* evidence.
3. The frontend loads and renders a movie page end to end.
4. Level 1 gates green at the rolled-back commit.
5. Write what happened into `docs/BUG-<id>.md` — including what you tried that did *not* work.

---

## 7. The drill (do this before public launch, then date it)

Deploy a deliberately broken change to the Space (e.g. a 500 on `/recommend`), confirm it is broken,
roll it back using §4, and confirm §6 passes. Record here:

```
Drill 1 — date: __________  performed by: __________
  broke:            ______________________________
  detected via:     ______________________________
  time to detect:   ______
  time to restore:  ______
  what surprised us:______________________________
```

An undrilled rollback plan is a hypothesis, not a safety net.
