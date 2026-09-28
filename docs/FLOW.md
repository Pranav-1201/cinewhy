# FLOW.md

> How execution actually travels — what calls what, in what order.
> Field Guide habit #4. Bugs live in the gaps between files; this file is the map of those gaps.

**Version-pin:** last revised by Claude Opus 5, 2026-08-26.

---

## 1. The only flow that exists today

`Movie_Sentiment_Analysis.ipynb`, executed top to bottom. There is no other entry point.

```
cell 2    imports + nltk.download("stopwords")
cell 4    pd.read_csv("Data/IMDB Dataset.csv")        → df  (50000, 2)
cell 9    df.sample(10_000, random_state=42)          → df  (10000, 2)   ⚠ discards 80%
cell 10   sentiment: "positive"→1 / "negative"→0

          ── preprocessing: SIX SEQUENTIAL IN-PLACE MUTATIONS OF df["review"] ──
cell 13   df["review"] = df["review"].apply(clean_html)        ⚠ idempotent
cell 14   df["review"] = df["review"].apply(convert_lower)     ⚠ idempotent
cell 15   df["review"] = df["review"].apply(remove_special)    ⚠ idempotent
cell 16   df["review"] = df["review"].apply(remove_stopwords)  ⚠ str → list[str]
cell 17   df["review"] = df["review"].apply(stem_words)        ⚠ NOT idempotent
cell 18   df["review"] = df["review"].apply(join_back)         ⚠ list[str] → str

cell 20   cv.fit_transform(df["review"])              → X_bow   ⚠⚠ FIT ON ALL 10k
cell 21   train_test_split(X_bow, y, 0.2, rs=42)      → train/test
cell 23   fit GaussianNB / MultinomialNB / BernoulliNB
cell 24   predict on X_test_bow
cell 26   accuracy + precision table
cell 30   tfidf.fit_transform(df["review"])           → X_tfidf ⚠⚠ FIT ON ALL 10k
cell 32   fit + evaluate MultinomialNB (TF-IDF)
cell 35   "best model" selected by TEST accuracy      ⚠⚠ test set reused for selection
cell 37   predict_sentiment() — closes over `tfidf` and `model_tfidf` from globals
```

Nothing is written to disk. When the kernel dies, the model dies.

---

## 2. The three places this flow breaks

### F-1 · Vocabulary leakage (cells 20 and 30)

```
        ┌──────────────── df: all 10,000 rows ─────────────────┐
        │                                                      │
cell 20 │  cv.fit_transform(df)  ← vocabulary learned HERE     │
        │            │              from all 10,000            │
        └────────────┼─────────────────────────────────────────┘
                     ▼
cell 21   train_test_split  →  8,000 train  |  2,000 test
                                             └─ its words already
                                                shaped the vocabulary
```

The 2,000 test reviews contributed to `max_features=1000` selection and (for TF-IDF) to the IDF
statistics. The test set is therefore not held out.

**Measured cost.** The 2026-08-26 figures (−0.0165 on BernoulliNB) did not reproduce. Re-measured
on 2026-09-29 over ten split seeds, as-written minus leak-free is between −0.0010 and +0.0000 on
every model, with a spread (std) of 0.0013 to 0.0031: not distinguishable from zero. The rule
stands regardless. Full tables: `DECISIONS.md` D-009.

### F-2 · Negation is deleted before the model ever sees it (cell 16)

`not`, `no`, `nor` are all in NLTK's English stoplist. Stopword removal runs at cell 16, *before*
anything else looks at the text. The result:

```
"This movie was not good at all."  ──┐
                                     ├──►  "movi good"  ──►  identical TF-IDF vector
"This movie was good."            ───┘                        ──► identical prediction
```

Verified end to end on 2026-08-26: both strings preprocess to `'movi good'`, produce
`np.array_equal(va, vb) == True`, and both are predicted **0 (negative)** — so the pipeline gets the
positive review wrong, and the negated one right only by accident.

Note this also falsifies the mechanism given in the project report §18, which claims the model sees
`not`, `exact`, `terribl` as independent unigrams. It never sees `not` at all.

### F-3 · Order of operations: stopwords stripped before stemming (cells 16 → 17)

The stoplist is unstemmed, so it is applied to unstemmed text — correct so far. But 28 stoplist
entries stem to something *not* in the stoplist (`has`→`ha`, `his`→`hi`, `does`→`doe`,
`once`→`onc`, `because`→`becaus`…). Those survive only when they arrive via a non-stopword route,
leaving low-signal fragments in the 1,000-feature budget.

---

## 3. Target flow (offline build → serve)

```
OFFLINE  (CI or local; never in a request)
─────────────────────────────────────────────────────────────────────
  raw sources
     │
     ├─ IMDB 50k ──────────► cinewhy.text.preprocess ──┐
     │                                                  ├──► train ABSA
     ├─ Amazon Movies&TV ──► cinewhy.text.preprocess ──┘        │
     │        (has item IDs)                                     ▼
     │                                              aspect_scores.parquet
     ├─ MovieLens 32M ─────► cinewhy.recsys.cf ──► item_vectors.npy
     │                                                  │
     └─ TMDB API ──────────► metadata.parquet           ▼
                                              cinewhy.artifacts.build
                                                        │
                                                        ▼
                                          manifest.json + artifacts/
                                          (content-hashed, uploaded to HF Hub)

SERVE  (FastAPI, boot once, then read-only)
─────────────────────────────────────────────────────────────────────
  boot:    load manifest → verify hashes → mmap vectors → load hnsw index
  request: /recommend
             │
             ├─ resolve taste profile (from request body; no DB)
             ├─ hnsw.knn_query()              ~1ms
             ├─ rerank: CF score × aspect fit × diversity
             └─ attach evidence sentences     ← from parquet, by (movie, aspect)
                                                 NEVER generated at request time
```

**The invariant:** `cinewhy.text.preprocess` is imported by *both* the training job and the serving
path. One definition, one import. A second copy is how train/serve skew enters — and this project
already has the seed of that bug, since `predict_sentiment()` re-implements the pipeline by calling
six module-level functions that also happen to have mutated `df` in place.

---

## 4. Where a request can fail (target)

| Stage | Failure | Correct response |
|---|---|---|
| boot | manifest hash mismatch | refuse to start — do NOT serve stale artifacts |
| `/recommend` | unknown movie id | 404, no stack trace |
| `/recommend` | empty taste profile | 200 with popularity fallback, `"cold_start": true` |
| `/explain` | no evidence sentences | 200 with `"evidence": []` — never fabricate a sentence |
| any | unhandled | 500 with an opaque error id; the trace goes to logs, never the client |

---

Related: [`ARCHITECTURE.md`](ARCHITECTURE.md) · [`DECISIONS.md`](DECISIONS.md) · [`TEST_CHECKLIST.md`](TEST_CHECKLIST.md)
