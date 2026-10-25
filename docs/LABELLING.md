# LABELLING.md — get an independent check on the accuracy numbers

Every accuracy figure for aspect detection and clause polarity currently rests on labels written
by the assistant that built the system. That is the weakest link in the evidence. A second person
labelling the same clauses fixes it, and takes about 30-45 minutes (you can stop early: only rows
you mark done count).

## What you are labelling

`tests/data/aspect_label_sheet.csv` has 300 short pieces of IMDb reviews (clauses), chosen at
random. Open it in Excel or any editor. For each clause, decide which of seven aspects of **the
film** it comments on, and whether the comment is positive, negative or neither.

| Letter | Aspect | It counts when the clause comments on... |
|---|---|---|
| `a` | acting | performances, casting, how an actor did |
| `p` | plot | story, script, dialogue, premise, how well it is written |
| `c` | pacing | speed, drag, rushing, being too long, momentum |
| `v` | visuals | cinematography, effects, costumes, sets, how it looks |
| `e` | ending | how the story ends or lands |
| `s` | soundtrack | music and songs |
| `r` | rewatchability | whether they would watch it again |

Add a sign: `+` praise, `-` criticism, `0` it discusses the aspect but is neutral or mixed.

## The one rule that matters

A clause counts for an aspect only if it **comments on that aspect of this film**. These do not
count:

* a plot summary ("Alice goes to the island and meets a man")
* a bare cast list or a mention of an actor with no opinion ("starring Jane Roe")
* remarks about a different film, or about the reviewer's life ("I watched it in 1998")
* words used in another sense ("he was cast out", "a score of 4 out of 10")

## How to fill the sheet

* `labels` column: letters and signs separated by spaces, e.g. `a+ p-` (acting praised, plot
  criticised). Leave it **empty** if the clause discusses none of the seven aspects.
* `done` column: type `y` on every row you have looked at, **including rows you left empty**.
  A row without `y` is treated as "not looked at" and ignored.
* Do not look at `tests/data/aspect_gold_random_c.jsonl`: it holds the assistant's answers.

Examples (invented, not from the sheet):

| Clause | `labels` |
|---|---|
| The acting was superb, but the plot made no sense. | `a+ p-` |
| It runs far too long. | `c-` |
| I'd happily watch it a second time. | `r+` |
| Set in Paris in 1923, it follows a young painter. | *(empty, `done` = y)* |
| The soundtrack is fine, I guess. | `s0` |

## Then run the comparison

```bat
venv\Scripts\python.exe -m cinewhy.absa.agreement tests\data\aspect_label_sheet.csv
```

It prints:

* **presence kappa**: how often you and the assistant agree on which aspects a clause discusses,
  corrected for chance (0.6 or more is substantial; below 0.4 means the task itself is ambiguous
  and the numbers should be trusted less),
* **polarity agreement** on mentions you both found, and
* the system's **recall, precision and polarity accuracy scored against your labels**, which are
  the first independent numbers in the project.

A typo in the `labels` column stops the run with a message naming the bad token rather than
silently dropping a mention.
