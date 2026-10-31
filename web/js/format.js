/* Pure helpers: no DOM, no network. They live apart so Node's test runner can exercise them
   (tests/web/format.test.mjs). Everything the page needs to word, label or bucket is decided here. */

export const signed = (x) => (x >= 0 ? "+" : "−") + Math.abs(x).toFixed(2);
export const pct = (x, digits = 1) => (100 * x).toFixed(digits) + "%";

// aclImdb and ebD are both IMDb's reviews; Rotten Tomatoes is its own site. The server prefixes
// every review id with its source, so the label follows the id and never a hard-coded name.
const SOURCES = { acl: "IMDb", ebd: "IMDb", rt: "Rotten Tomatoes" };

/** Which site a quoted review came from, by the prefix of its id. */
export function sourceOf(reviewId) {
  const key = String(reviewId).split("/")[0];
  return { key, label: SOURCES[key] || "A review" };
}

/** "From an IMDb review", "From a Rotten Tomatoes review", or "From a review" when the site is unknown. */
export function sourceStamp(label) {
  if (!label || label === "A review") return "From a review";
  return `From ${/^[AEIOU]/.test(label) ? "an" : "a"} ${label} review`;
}

/** A stable hue (0-359) from an id, for the placeholder shown when a poster is missing. */
export function hueOf(id) {
  let h = 0;
  for (const ch of String(id)) h = (h * 31 + ch.codePointAt(0)) >>> 0;
  return h % 360;
}

/**
 * Default "how much to favour new films" from an optional age band; 0.5 when unknown.
 * Never above 0.5: on held-out users 50% cost nothing in hit rate while 80% cost 2.5 points
 * (DECISIONS D-020), so younger visitors start at the highest setting measured as free and can
 * raise it themselves, seeing its cost on the How it works page.
 */
export function recencyForAge(band) {
  const table = { "under-18": 0.5, "18-24": 0.5, "25-34": 0.5, "35-44": 0.4, "45+": 0.25 };
  return table[band] ?? 0.5;
}

/** "2h 41m" from minutes; empty when the runtime is unknown. */
export function runtimeLabel(minutes) {
  if (!minutes || minutes <= 0) return "";
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return h ? `${h}h${m ? ` ${m}m` : ""}` : `${m}m`;
}

/** Shorten text at a word boundary, adding an ellipsis only when something was cut. */
export function clamp(text, max) {
  const t = String(text).trim();
  if (t.length <= max) return t;
  const cut = t.slice(0, max);
  return cut.slice(0, Math.max(cut.lastIndexOf(" "), max * 0.6)).trimEnd() + "…";
}

/** Language chip text for an ISO code the catalogue uses. */
export function languageName(code) {
  return { en: "English", hi: "Hindi", te: "Telugu", ja: "Japanese", fr: "French" }[code] || "";
}

const count = (n) => n.toLocaleString("en");

/** Plain sentence for a film's reviews, from the per-source counts the server sends. */
export function reviewsLine(bySource) {
  const rt = bySource?.rt || 0;
  const imdb = (bySource?.acl || 0) + (bySource?.ebd || 0);
  const total = rt + imdb;
  if (!total) return "";
  const noun = total === 1 ? "review" : "reviews";
  if (!rt) return `We read ${count(total)} ${noun} from IMDb`;
  if (!imdb) return `We read ${count(total)} ${noun} from Rotten Tomatoes`;
  return `We read ${count(total)} reviews: ${count(rt)} from Rotten Tomatoes and ${count(imdb)} from IMDb`;
}

/** What stands in for a receipt on a film whose reviews we have not read. Says so, invents no quotes. */
export const RATINGS_ONLY_NOTE =
  "We have not read reviews of this film yet, so there are no quotes to show. It is placed by its IMDb rating and its genres.";

/** "IMDb rating 7.8 from 12,400 votes."; empty when the server sent no rating. */
export function imdbLine(rating, votes) {
  if (!(rating > 0)) return "";
  const from = votes > 0 ? ` from ${count(votes)} ${votes === 1 ? "vote" : "votes"}` : "";
  return `IMDb rating ${Number(rating).toFixed(1)}${from}.`;
}

/**
 * One word for how reviewers felt, from an aspect score between -1 and +1. The edges are symmetric
 * and inclusive on the strong side: 0.5 is Loved and -0.5 is Panned; 0.2 is Liked and -0.2 is Disliked.
 */
export function verdictFor(score) {
  if (score >= 0.5) return "Loved";
  if (score >= 0.2) return "Liked";
  if (score > -0.2) return "Mixed";
  if (score > -0.5) return "Disliked";
  return "Panned";
}

/** "Based on 238 review sentences about acting": what a verdict rests on; empty when unknown. */
export function basisLine(n, aspectName, [one, many] = ["review sentence", "review sentences"]) {
  return n ? `Based on ${count(n)} ${n === 1 ? one : many} about ${String(aspectName).toLowerCase()}` : "";
}

/** Wilson 95% interval for hits out of n: the spread shown beside every measured rate. */
export function wilson(hits, n) {
  if (!n) return [0, 1];
  const z = 1.96;
  const p = hits / n;
  const denom = 1 + (z * z) / n;
  const centre = (p + (z * z) / (2 * n)) / denom;
  const half = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / denom;
  return [Math.max(0, centre - half), Math.min(1, centre + half)];
}
