"""Ingestion and joins across MovieLens, TMDB and the review corpus.

**Deliberately empty until H-1 is resolved.**

The open question is whether Amazon Movies&TV item IDs (ASINs — a specific product
edition) map cleanly onto MovieLens/TMDB film ids. Nobody has tested this. The audit
marked it "reproduce first": pull 200 random ASINs, attempt a title match, hand-check
30, and only then design this module's interface.

Scaffolding it now would mean committing to a join shape that may not survive contact
with the data, and every module downstream would inherit that guess. See
docs/HANDOVER.md H-1.
"""
