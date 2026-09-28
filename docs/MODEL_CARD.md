# MODEL_CARD.md — the sentiment classifier in `Movie_Sentiment_Analysis.ipynb`

> Audit item S5. What the model does, what it cannot do, and what has and has not been
> measured. Every figure here was produced on 2026-09-29 on the pinned environment
> (`requirements.txt`: scikit-learn 1.8.0, numpy 2.4.4, pandas 3.0.2) and is transcribed from
> that run's output. Where something was not measured, this file says so instead of guessing.

**Version-pin:** written by Claude Sonnet 5.5, 2026-09-29. Supersedes the claims in
`Movie_Sentiment_Analysis_Report.md` §12–§21 wherever they differ (see that file's corrections block).

---

## What it is

A bag-of-words Naive Bayes classifier that labels an English movie review *positive* or
*negative*. It is the prototype this repository started from. It is **not** the CineWhy
recommender and is not used by it: CineWhy's planned pipeline replaces it in Phase C
(`docs/AUDIT-2026-08-26.md` §Phase 4).

| | |
|---|---|
| Data | `Data/IMDB Dataset.csv`: 50,000 reviews, two columns (`review`, `sentiment`), 25,000 per class |
| Sample used | 10,000 rows, `df.sample(10_000, random_state=42)`; 8,000 train / 2,000 test, `random_state=42` |
| Cleaning | strip HTML, lowercase, keep alphanumerics, drop NLTK English stopwords, Porter stem |
| Features | `max_features=1000` unigram counts (BoW) or TF-IDF weights |
| Models compared | GaussianNB, MultinomialNB, BernoulliNB (BoW); MultinomialNB (TF-IDF) |
| Persisted? | **No.** The fitted model exists only in the notebook's memory. There is no saved artifact and nothing to deploy. |

## Measured performance

### Test set, one split, leak-free (vectorizer fit on the 8,000 training rows only)

| Model | Accuracy | Precision |
|---|---|---|
| GaussianNB (BoW) | 0.7830 | 0.8154 |
| MultinomialNB (BoW) | 0.8255 | 0.8300 |
| BernoulliNB (BoW) | 0.8355 | 0.8268 |
| MultinomialNB (TF-IDF) | 0.8310 | 0.8234 |

A single split has **no spread**, so these four numbers cannot be ranked against each other.
The notebook as written (vectorizer fit before the split) reports 0.7820 / 0.8255 / 0.8350 /
0.8330; the difference is not distinguishable from zero (`DECISIONS.md` D-009).

### 5-fold cross-validation on the training split (vectorizer refit in every fold)

| Model | Accuracy, mean ± sample std over folds |
|---|---|
| MultinomialNB (TF-IDF) | 0.8345 ± 0.0063 |
| MultinomialNB (BoW) | 0.8297 ± 0.0095 |
| BernoulliNB (BoW) | 0.8294 ± 0.0065 |

TF-IDF leads by 0.0048 to 0.0051, which is inside each model's own fold std. The honest
summary is **about 0.83 accuracy, with the three multinomial and Bernoulli variants not
distinguishable from one another.** GaussianNB was not cross-validated.

### Duplicates

418 exact duplicate review texts in the raw file (824 rows belong to a duplicated text). In
this sample, 22 duplicate rows fall inside the 10,000, and 5 of the 2,000 test rows have a twin
in train, all with matching labels (an upper bound of 0.25 points on accuracy). New code
removes them before splitting (`cinewhy.text.unique_review_indices`).

## Known failures

- **It cannot read negation.** `not`, `no` and `nor` are in NLTK's stoplist and are deleted
  before vectorising. "This movie was not good at all." and "This movie was good." both clean
  to `movi good`, produce identical vectors, and are both predicted negative (reproduced
  2026-09-29). Any two sentences that differ only by one of these negation words receive the same prediction, because the vectors are identical.
- **Neutral or mixed text is forced into one of two classes.** The notebook's own output
  labels "It was okay, nothing special but not bad either." negative (notebook cell 37).
- **Vocabulary is capped at 1,000 stemmed words**, so rare or domain-specific terms are ignored.
- **Order is discarded**: there is no phrase, sarcasm or context handling.

## Not measured

Calibration of the predicted probabilities. Performance on reviews from any source other than
this IMDB file, on non-English text, on very short or very long reviews, or across genres.
Per-class recall on the leak-free split. Anything about how a person reading the output would
use it. Do not assume any of these; each needs its own measurement before it is claimed.

## Intended use

A teaching prototype and a baseline for Phase C. **Do not** present it as a production
inference engine, ship it behind an API, or quote its accuracy without the spread above.
