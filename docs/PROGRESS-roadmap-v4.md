# PROGRESS: roadmap v4 (live note; read this first when told "continue")

Branch `feature/roadmap-v4`, worktree `D:\NLPPROJECT-dev`, local only, never pushed. The demo folder
`D:\NLPPROJECT` stays on `main` and is not edited. Plan: `docs/ROADMAP-2026-10-27.md` (section 15 wins).

## Done
* Phase 0: worktree created from `c41d41b`; venv imports `cinewhy` and `api` from the dev folder when run
  from it (checked); roadmap file moved here (untracked, uncommitted).

* Phase A committed `7bd336f`: runtime-only Dockerfile, CI docker job boots it on `tests/smoke_artifacts.py`
  artifacts. Verified locally: workflow parses, app boots on the synthetic set and passes CI's three probes,
  suite 427 passed, 1 skipped (baseline 426 passed, 1 skipped; first count of 427 passed was wrong). **Docker build
  itself is unverified until the branch is pushed and CI runs (needs Pranav's OK to push).**
* Phase B code committed `7b44c10`: icon tools below 960 px, bottom bar (Home, Search, Profile sheet) at 640 px
  and below. Browser-measured at 320/375/641/800/1440. Rate films and Library items arrive with Phase C.

* Phase B finished `f120ff7`: Playwright layout tests (run with the demo venv Python plus
  `PYTHONPATH=D:/NLPPROJECT-dev/.e2e-deps`; the new dev venv `.venv` cannot import scikit-learn because
  Windows Application Control blocked a DLL, so do NOT use it to run the suite).
* Phase C committed: `6ef51e9` profile model (20 Node tests, 11 mutants killed) + server limits raised
  (exclude ids 500 to 3000, body 64 to 160 KB; two guard tests re-pinned on purpose); `ef05770` seen and want
  buttons; `ad51b49` Library, Rate films, Profile sheet, hide-watched chip (17 browser tests, mutant killed);
  `116c858` favourite genres + "Save, then rate a few films".
* Phase D committed: `3a774d2` `POST /shelves` (score once, select per shelf; 19 tests, 14 planted bugs
  caught) and `096edaa` the page uses it (one 76 ms request, 13 shelves, 256 films, no repeats). No language
  mixer: the ratio is a catalogue ratio (Pranav's clarification), so the mix comes from the catalogue.
* Phase E committed: `b14b10b` year-range bar and Old school (before 1990) / New (2021 onward) presets,
  old era choices migrate; `f87ceb7` plain-language receipts (Loved/Liked/Mixed/Disliked/Panned).
* Docs: DECISIONS D-021..D-024 and the HANDOVER ritual are written.
* Whole suite on the branch (with the Playwright path): 466 passed, 1 skipped; ruff, format, mypy clean.

## Now
* Dev server on port 8010 against `CINEWHY_ARTIFACTS=D:/NLPPROJECT/artifacts/v3` (demo stays on 8000, untouched).

## Next (in order)
1. "Because you liked X" reasons (server field on each item) for the spotlight and tiles.
2. Phone visual QA of Library, Rate films, Profile sheet and the year bar; fix what shows.
3. Free official data without keys: IMDb non-commercial datasets (series lists, fresh votes) to size the series
   and 2024-2026 films; then F0 source verification (TMDB reviews pilot needs Pranav's OK to use the TMDB key).
4. Measure hit-at-20 by number of rated films (decides the Rate films deck size).
5. **Decision for Pranav: OK to push this branch** so CI can run the Docker image build and the browser job?

## Rules while working
* Commit only on this branch, explicit paths, never `git add -A`; never touch `D:\NLPPROJECT`.
* One logical change per commit; whole suite green before each commit (`cd D:\NLPPROJECT-dev` first, venv python by absolute path).
* A usage limit cannot be auto-resumed outside /loop: the user says "continue" and work restarts from this note.
