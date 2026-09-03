"""Collaborative filtering, candidate retrieval and ranking.

**Deliberately empty until H-1 is resolved** — the ranker consumes whatever `data`
produces, so its interface is downstream of the same unverified join. See
`cinewhy.data` and docs/HANDOVER.md H-1.

What is already settled and will not change: ranking consumes `MovieAspectProfile` and
emits `Recommendation` objects carrying `Reason`s, per cinewhy/schemas.py. Build against
those types; the uncertainty is in how candidates are retrieved, not in what comes out.
"""
