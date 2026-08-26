# FEATURE-<id> · <name>

> Field Guide habit #5 — one file, start to finish. Copy to `docs/FEATURE-<id>.md`.

**Status:** scoping / building / in-review / shipped
**Opened:** <date> by <who> · **Model:** <e.g. Claude Opus 5>
**Plan row:** <idea ID from the audit, e.g. S2 / B4 / F1>

---

## What and for whom
One paragraph. The user-visible change, and who benefits. If you cannot name the user, stop.

## Why now
What this unblocks, or what breaks without it. Ties to `DECISIONS.md` D-___ where relevant.

## Success criteria — verifiable, not vibes
Turn the vague ask into checkable statements. Each needs a command or an observation that settles it.

| # | Criterion | How it is verified |
|---|---|---|
| 1 | | |
| 2 | | |

## Scope

**In:**
**Out:** (say this explicitly — undeclared scope is how a one-PR change becomes four)

## Approach
The plan, before the code (Field Guide habit #11 — why before what). Note the alternative you
rejected and why; that is the part worth reading later.

**Rejected:** … because …

## Blast radius
Files and modules touched. Anything that loads a serialized artifact, pins an import path, or is
imported by both training and serving code gets named here explicitly.

## Build order
Additive checkpoints — new code green *before* old code is removed, so the tree never goes red.

- [ ] 1.
- [ ] 2.
- [ ] 3.

## Verification log
Paste real output. Each checkpoint gets its own entry with the count visible.

```
$ <command>
<output>
```

## What changed vs the plan
Fill in at the end. Where the plan was wrong is the most useful thing here for the next feature.
