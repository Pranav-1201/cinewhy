# FEATURE-005 · Recency, optional demographics, and a poster-led front end

> Field Guide habit #5 — one file, start to finish.

**Status:** scoping (the data layer, FEATURE-004, is built; posters reach the API)
**Opened:** 2026-10-26 by Pranav + Claude Sonnet 5.5 · **Model:** Claude Sonnet 5.5
**Plan row:** user request 2026-10-25, steps 3, 4 and 5 of six

---

## What and for whom

People born after 2000 are the main audience. Today the first film the app shows an anonymous
visitor is a 1949 black-and-white thriller, the page has no images, and the grey-blue theme looks
unfinished. This feature makes the product lead with films a younger viewer has heard of, lets
them say a little about themselves (optionally) to get a better first page, and presents it as a
poster-led, colourful, fast-feeling product.

## Constraints found by reading the code (not assumptions)

| Constraint | Where | Consequence |
|---|---|---|
| `schemas.py` is a two-person contract; `RecommendRequest` has no year, language or demographic field | `cinewhy/schemas.py` | Filters and demographics go through a new HTTP-layer endpoint (`api/models.py`), not a contract change |
| The server sets `Content-Security-Policy: default-src 'self'` and the UI never uses `innerHTML` on server data | `api/main.py`, `web/app.js` | Fonts must be self-hosted; images only from `image.tmdb.org` (already allowed); keep the `h()` element builder |
| The evaluation tab reads `join_check.own_title_rate`, now a per-source object | `web/app.js` | It would print `NaN%`; must be rewritten against the new `eval.json` |
| Evidence citations hard-code "aclImdb review" | `web/app.js` `quote()` | Evidence now comes from IMDb (aclImdb, ebD) and Rotten Tomatoes; the label must follow `source_review_id`'s prefix |
| "Limits" text says the catalogue is "mostly released before 2012, and has no posters" | `web/app.js` | Stale; generate it from `eval.json` numbers |
| MovieLens 25M and 32M carry no age, sex or location; ML-1M does, but its films end in 2003 | datasets | Demographics can only be a weak genre prior, and must be measured before it is trusted |
| The polarity model scores 75.0% (95% interval 73.9-76.1) on Rotten Tomatoes text against 88.4% (87.3-89.4) on ebD | `artifacts/v2/polarity_domain.json` | Newer films' evidence is judged by a weaker model; a retrain on mixed sources is a candidate follow-up (D-017) |

## Success criteria — verifiable, not vibes

| # | Criterion | How it is verified |
|---|---|---|
| 1 | A cold-start visitor's top 20 is mostly films from 2000 onward | a test over the built artifacts counts the share; the number is printed in `eval.json` |
| 2 | The visitor can narrow by era and by language (English, Hindi) and sees a "New & Now" shelf | API tests on the new endpoint; a browser run on all three viewport widths |
| 3 | Older films are demoted, never deleted: searching for a 1950s title still finds it | API test |
| 4 | The demographic prior ships ON only if it beats the no-demographic baseline on held-out MovieLens-1M users by more than the spread; otherwise it ships OFF and says so | the evaluation, recorded in `eval.json` and D-018 |
| 5 | Demographic answers are optional, kept in the browser, sent as coarse buckets only, never logged or stored | code review plus a test that the access log line holds none of them |
| 6 | Every film card shows its poster or a deliberate placeholder; no layout shift while images load | browser run; the placeholder is a generated gradient |
| 7 | Zero console errors and no horizontal scroll at 375, 768 and 1440 px; keyboard reachable; focus visible; reduced-motion respected | driven in Chrome with the console read, plus an accessibility audit run |
| 8 | The evaluation tab shows the new numbers with no `NaN`, and the citation names the true source | browser run against the real build |

## Scope

**In:** a `/discover` endpoint (filters: from-year, languages, genres, "new and now"; optional
demographic buckets); a recency prior in ranking; the full redesign of `web/` (layout, colour,
type, motion, posters, film drawer, onboarding sheet, evaluation tab); TMDB attribution in the
footer; one self-hosted variable font.

**Out:** accounts or login (there are none; onboarding is a skippable sheet kept in the browser);
streaming availability; trailers; any change to `schemas.py`; retraining the polarity model
(measured and logged here, decided separately).

## Approach

1. **Recency (step 3).** A `/discover` request carries the existing taste profile plus
   `from_year`, `languages`, `genres` and `recency` (0-1). Ranking takes the existing blended
   score and adds a small, documented recency term from the film's age; filters narrow the
   candidate set before ranking. Search results sort recent films ahead on ties, never hide old
   ones. The weight is chosen so the cold-start list meets criterion 1, and its cost in
   held-out hit-rate is measured and reported next to the gain, not hidden.
2. **Demographics (step 4).** Age band, sex and region are all optional. They map to a genre
   affinity vector learned from MovieLens-1M (the only open dataset with demographics), applied as
   a small prior on the TMDB genres of the catalogue. Region also maps to original-language
   preference (Hindi, English). Evaluated on held-out ML-1M users against a popularity baseline;
   ships off if it does not clear the spread. Sex is offered as "prefer not to say" by default.
3. **Front end (step 5).** Dark, cinematic default with a light option; one vivid gradient
   (violet to coral) for emphasis and each film's own poster colour on its detail view; poster
   rails with skeleton loaders; a spotlight hero; a detail drawer whose aspect bars use a
   colour-blind-safe diverging pair; sliders become labelled "dials". No framework and no build
   step (the CSP and the `h()` helper depend on that). Design systems skills are used for the
   visual pass; `dataviz` is read before any bar or chart code.

**Rejected:**
- Adding fields to `RecommendRequest`: a contract change needing a second person.
- Deleting pre-2000 films: the user asked for emphasis, not removal, and classics still matter.
- A UI framework: it would force a build step and break the strict CSP model.
- Hotlinking a web font from a CDN: blocked by the CSP and a privacy leak.

## Blast radius

`api/main.py`, `api/models.py`, `cinewhy/recsys/rank.py` (a new scoring term), `web/*` (rewritten),
tests for each, `docs/`. `cinewhy/schemas.py` untouched.

## Build order

A. Verify the real build and read its numbers. B. `/discover` with filters and the recency term,
tests first. C. Download ML-1M (small, needs your approval), measure the demographic prior,
decide ship-on or ship-off. D. Redesign `web/` against the real artifacts. E. Drive it in Chrome
at three widths; fix what the console and the audit say. F. Replace stale figures in README and
docs, write D-016 to D-018. G. Commit with explicit paths.

## Risks

- Recency is a product preference, not a quality signal: it will cost some held-out hit-rate. The
  cost is measured and shown.
- Hindi has few ratings (about 50 films with 50 or more MovieLens ratings after 2011), so Hindi
  picks lean on aspects and popularity; the UI says when a pick has no "viewers like you" signal.
- Posters depend on TMDB's CDN being reachable; the placeholder must look intentional.
- A demographic prior can encode stereotypes. It is opt-in, small, measured, and described
  plainly; it never narrows what a visitor can see, only the order.
