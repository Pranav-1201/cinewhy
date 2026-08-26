# BUG-<id> · <one-line symptom>

> Field Guide habit #5 — one file, start to finish. Copy this to `docs/BUG-<id>.md`.
> Anyone reading it cold should know exactly how to pick up where it left off.

**Status:** open / reproduce-first / root-caused / fixed / wont-fix
**Found:** <date> by <who> · **Model:** <e.g. Claude Opus 5> · **Severity:** P0 / P1 / P2

---

## Symptom
What was observed, in the terms it was observed in. Not a diagnosis.

## Reproduce
Exact commands and inputs. If it does not reproduce reliably, say so and give the conditions under
which it *did*.

```bash
PYTHONIOENCODING=utf-8 D:/NLPPROJECT/venv/Scripts/python.exe ...
```

**Expected:**
**Actual:**

> If it will not reproduce, ask whether the harness can even *express* the condition before
> concluding it does not exist. Integer-only viewports, mocked clocks and fixed-DPI screenshots all
> hide whole classes of bug.

## Hypotheses falsified
The most valuable section. Each entry stops the next session repeating the work.

| # | Hypothesis | Evidence that killed it |
|---|---|---|
| 1 | | |
| 2 | | |

> **Stop after two dead ends.** Hand over an unsolved bug rather than a plausible wrong cause — a
> wrong cause sends the next session down paths already eliminated.

## Root cause
The mechanism, named specifically, with the file and line. If unknown, write **UNKNOWN** and mark
the bug reproduce-first.

## Fix
What changed and why that addresses the root cause rather than the symptom.

## Verification
Command run **after** the fix, with its real output pasted in. Include the count.

```
$ <command>
<output>
```

- [ ] Fails against pre-fix code (the regression test was watched failing)
- [ ] Passes against post-fix code
- [ ] Level 1 gates still green (`TEST_CHECKLIST.md`)

## Follow-ups
Anything deliberately left undone, and why.
