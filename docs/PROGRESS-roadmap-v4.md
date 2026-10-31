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

* Also committed since: `cc82a5e` "Because you liked X" reasons; `3e4fa31` null-text fix + bigger stars (phone QA);
  `846f1de` D-025 (3 liked films double the cold-start hit rate: 6.7% to 12.9%; deck stays at 12) + README;
  `07d824a` artifact download at container start (16 tests); `0370bb2` proxy note; `38da0e0` TMDB pilot script
  (ready, needs the owner's token); `e8e5f5e` MovieLens belief 2024 measured: not useful (82 films with 20+ ratings).
* Official IMDb dumps downloaded and measured (roadmap section 17): recent films and series are plentiful; only
  25 titles with 1,000+ votes are flagged adult.

## Measured since (roadmap section 18, DECISIONS D-026)
* spine_reach: at 50 reviews Hindi+Telugu 355, Japanese 147, French 171 (targets 7,500 / 5,000 / 2,500): Tier B for those.
* title_join_lift: original-title matching helps French only (+2,778 ebD links); `film_key` guard added (`8c32296`).
* TMDB reviews pilot: 0 of 65 films reach 50 reviews; not a source for full receipts.
* confidence weighting: no gain (D-026); not shipped.
* Pranav accepted the language targets as unreachable for now, and asked for adult titles by both the explicit flag and mature ratings.

## Built since (all committed on this branch, suite 541 passed and 1 skipped with the Playwright path)
* Ratings-only tier (D-027): `a41e628` back end, `4ee02de` page. Languages ja and fr, Telugu inside the Hindi choice: `ee52fb2`.
* Accent folding and original-title links (D-028): `8740fc1`. Build options and the tier's selection: `eaeb1e2`.

## Update 2026-11-01: v5 is built and is the build to serve
* `artifacts/v5` (manifest `da475cc32788`, 24,967 films, 50-vote fallback for short languages, D-029) is verified and was
  looked at in a browser. Build command = the one below plus `--ratings-only-fallback-votes 50`, output `artifacts/v5`.
  `artifacts/v4` (200-vote floor, 21,730 films) is kept beside it; `start.bat` serves the highest `vN`, so v5.
* Branch pushed; draft PR #1; CI green. The notes below are from before the build finished.

## Now (older note)
* **The real v4 build is running** (started 07:58). Log:
  `C:/Users/Dell/AppData/Local/Temp/claude/D--NLPPROJECT/33717dde-bb2b-4de8-b656-cb441c7b62e6/scratchpad/build_v4.log`
  (last line says `build exit N`). Output: `D:\NLPPROJECT-dev\artifacts\v4` (git-ignored). Command, from `D:\NLPPROJECT-dev` with
  `PYTHONPATH=D:/NLPPROJECT-dev PYTHONUTF8=1`: `python -u -m cinewhy.build --tmdb/--rt/--ebd/--acl/--ml` pointing at
  `D:/NLPPROJECT/Data/raw/...`, `--out D:/NLPPROJECT-dev/artifacts/v4 --min-reviews 50 --wide --languages en,hi,te,ja,fr
  --max-year 2026 --cap 100 --ratings-only-min-votes 200 --cache D:/NLPPROJECT-dev/Data/raw/_cache/gathered_v4.jsonl`.
  `artifacts/v4` first needs `polarity.joblib`, `polarity_report.json`, `polarity_domain.json` copied from the demo's `artifacts/v3`.
  A cache from this run makes a rerun skip the 40-minute gather.
* Dev server on 8010 is stopped. Serve v4 with `CINEWHY_ARTIFACTS=D:/NLPPROJECT-dev/artifacts/v4`. The demo on 8000 is untouched.

## Next (in order)
1. When the build ends: read the log's last lines and `eval.json` (`catalogue.ratings_only.by_language` has each language's shortfall),
   verify the manifest, boot v4 on port 8010 and look at it in a browser at phone and desktop widths.
2. Series (IMDb dumps list them) and the Japanese anime split are not built; movies only for now.
3. **Decisions for Pranav:** push this branch so CI can run the Docker build and the browser job; "adult" was read as both the
   explicit flag and mature ratings (his reply was typed "noth").

## Rules while working
* Commit only on this branch, explicit paths, never `git add -A`; never touch `D:\NLPPROJECT`.
* One logical change per commit; whole suite green before each commit (`cd D:\NLPPROJECT-dev` first, venv python by absolute path).
* A usage limit cannot be auto-resumed outside /loop: the user says "continue" and work restarts from this note.
