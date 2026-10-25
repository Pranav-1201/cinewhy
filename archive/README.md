# archive/

History only. Nothing here is part of the running system and nothing here should be quoted.

`legacy/Movie_Sentiment_Analysis.ipynb` is the original prototype: a Naive Bayes sentiment
classifier on the Kaggle IMDB CSV. Its committed outputs are the primary evidence for the numbers
the 2026-08-26 audit analysed, which is why CI exempts it from output-stripping and why it is
kept byte-for-byte unchanged (moved here on 2026-10-25 with `git mv`).

`legacy/Movie_Sentiment_Analysis_Report.md` is the original write-up. It **contradicts the code**:
it says leakage was prevented when it was not, claims a stratified split the code never did, and
explains an error mechanism that cannot occur. See `docs/AUDIT-2026-08-26.md` and
`docs/DECISIONS.md` D-009. Where the report and the audit disagree, the audit is right.

The system that replaced both lives in `cinewhy/`, `api/` and `web/`.
