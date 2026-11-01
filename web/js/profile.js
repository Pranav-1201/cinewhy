/* The profile: everything the visitor told us, as one plain object. No DOM, no network, no storage:
   state.js keeps it in localStorage and the pages read it, so Node can test every rule here
   (tests/web/profile.test.mjs). The object is exportable as one JSON file, so a person can move it
   between browsers now and an account can adopt the same shape later.

   Rules that other code relies on:
   * a film is in at most one of liked / disliked, and in at most one of watched / want;
   * a star rating is only ever kept for a film marked watched (you rate what you have seen);
   * every list holds only well-formed film ids and is capped, so a corrupted or hostile value can
     neither break rendering nor make a request the server would refuse. */

export const PROFILE_VERSION = 3;
export const LIST_CAP = 3000; // must stay at or below the server's exclude_movie_ids limit
const TITLE_CAP = 200;
const IMPORT_CAP_BYTES = 1_000_000;
const ID = /^[A-Za-z0-9_-]{1,32}$/;
const AGES = ["under-18", "18-24", "25-34", "35-44", "45+"];
const REGIONS = ["india", "north-america", "europe", "elsewhere"];
const SEXES = ["female", "male", "other"];
const LANGUAGES = ["en", "hi", "ja", "fr"];
const KINDS = ["film", "series"];
// Profiles saved before the year-range bar stored one of four fixed choices; each becomes a start year.
const LEGACY_ERA_FROM = { new: 2021, 2012: 2012, 2000: 2000 };

export const defaultProfile = () => ({
  version: PROFILE_VERSION,
  weights: {}, liked: [], disliked: [], watched: [], want: [], ratings: {}, titles: {},
  languages: [], kinds: [], favouriteGenres: [], genres: [], yearFrom: null, yearTo: null,
  recency: 0.5, recencyTouched: false,
  age: null, region: null, sex: null, hindiFirst: false, onboarded: false,
  hideWatched: true,
});

const idList = (value) => {
  if (!Array.isArray(value)) return [];
  return [...new Set(value.filter((v) => typeof v === "string" && ID.test(v)))].slice(0, LIST_CAP);
};
const stringList = (value, allowed, cap = 20) => {
  if (!Array.isArray(value)) return [];
  const ok = value.filter((v) => typeof v === "string" && v.length <= 40 && (!allowed || allowed.includes(v)));
  return [...new Set(ok)].slice(0, cap);
};
const oneOf = (value, allowed) => (allowed.includes(value) ? value : null);

/**
 * Turn anything that was once stored (version 2 had no `version` field) into a valid profile.
 * Unknown keys are dropped; invalid values fall back to their defaults.
 */
export function migrate(raw) {
  const p = defaultProfile();
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return p;
  p.liked = idList(raw.liked);
  p.disliked = idList(raw.disliked).filter((id) => !p.liked.includes(id));
  p.watched = idList(raw.watched);
  p.want = idList(raw.want).filter((id) => !p.watched.includes(id));
  if (raw.weights && typeof raw.weights === "object" && !Array.isArray(raw.weights)) {
    for (const [aspect, weight] of Object.entries(raw.weights)) {
      if (typeof weight === "number" && weight > 0 && weight <= 1 && aspect.length <= 40) p.weights[aspect] = weight;
    }
  }
  if (raw.ratings && typeof raw.ratings === "object" && !Array.isArray(raw.ratings)) {
    for (const [id, stars] of Object.entries(raw.ratings)) {
      if (ID.test(id) && Number.isInteger(stars) && stars >= 1 && stars <= 5 && p.watched.includes(id)) p.ratings[id] = stars;
    }
  }
  if (raw.titles && typeof raw.titles === "object" && !Array.isArray(raw.titles)) {
    const known = new Set([...p.liked, ...p.disliked, ...p.watched, ...p.want]);
    for (const [id, title] of Object.entries(raw.titles)) {
      if (known.has(id) && typeof title === "string") p.titles[id] = title.slice(0, TITLE_CAP);
    }
  }
  p.languages = stringList(raw.languages, LANGUAGES);
  p.kinds = stringList(raw.kinds, KINDS, KINDS.length);
  p.favouriteGenres = stringList(raw.favouriteGenres, null, 12);
  p.genres = stringList(raw.genres, null, 10);
  const year = (v) => (Number.isInteger(v) && v >= 1880 && v <= 2100 ? v : null);
  p.yearFrom = year(raw.yearFrom);
  p.yearTo = year(raw.yearTo);
  if (p.yearFrom === null && p.yearTo === null && typeof raw.era === "string" && Object.hasOwn(LEGACY_ERA_FROM, raw.era)) {
    p.yearFrom = LEGACY_ERA_FROM[raw.era];
  }
  if (p.yearFrom !== null && p.yearTo !== null && p.yearFrom > p.yearTo) [p.yearFrom, p.yearTo] = [p.yearTo, p.yearFrom];
  if (typeof raw.recency === "number" && raw.recency >= 0 && raw.recency <= 1) p.recency = raw.recency;
  p.recencyTouched = raw.recencyTouched === true;
  p.age = oneOf(raw.age, AGES);
  p.region = oneOf(raw.region, REGIONS);
  p.sex = oneOf(raw.sex, SEXES);
  p.hindiFirst = raw.hindiFirst === true;
  p.onboarded = raw.onboarded === true;
  p.hideWatched = raw.hideWatched !== false; // hidden unless the visitor switched it off
  return p;
}

const without = (list, id) => list.filter((x) => x !== id);
const remember = (p, movie) => {
  p.titles[movie.movie_id] = String(movie.title + (movie.year ? ` (${movie.year})` : "")).slice(0, TITLE_CAP);
};
const valid = (movie) => movie && typeof movie.movie_id === "string" && ID.test(movie.movie_id);

export const opinionOf = (p, id) => (p.liked.includes(id) ? "like" : p.disliked.includes(id) ? "dislike" : null);
export const isWatched = (p, id) => p.watched.includes(id);
export const isWanted = (p, id) => p.want.includes(id);

/** Like, dislike, or neither (null) for a film. Liking and disliking exclude each other. */
export function setOpinion(p, movie, opinion) {
  if (!valid(movie)) return p;
  const id = movie.movie_id;
  p.liked = without(p.liked, id);
  p.disliked = without(p.disliked, id);
  if (opinion === "like" && p.liked.length < LIST_CAP) p.liked.push(id);
  if (opinion === "dislike" && p.disliked.length < LIST_CAP) p.disliked.push(id);
  remember(p, movie);
  return p;
}

/** Mark a film watched (on) or not (off). Watching removes it from want-to-watch; unwatching drops its rating. */
export function setWatched(p, movie, on) {
  if (!valid(movie)) return p;
  const id = movie.movie_id;
  p.watched = without(p.watched, id);
  if (on) {
    if (p.watched.length < LIST_CAP) p.watched.push(id);
    p.want = without(p.want, id);
  } else {
    delete p.ratings[id];
  }
  remember(p, movie);
  return p;
}

/** Put a film on the want-to-watch list (on) or take it off. Wanting a film means it is not watched. */
export function setWant(p, movie, on) {
  if (!valid(movie)) return p;
  const id = movie.movie_id;
  p.want = without(p.want, id);
  if (on) {
    if (p.want.length < LIST_CAP) p.want.push(id);
    p.watched = without(p.watched, id);
    delete p.ratings[id];
  }
  remember(p, movie);
  return p;
}

/** The opinion a star rating stands for: 4 or 5 like, 1 or 2 dislike, 3 neither. */
export const opinionForStars = (stars) => (stars >= 4 ? "like" : stars <= 2 ? "dislike" : null);

/** Rate a film 1 to 5 (null clears it). Rating means it was watched, and sets like or dislike to match. */
export function rate(p, movie, stars) {
  if (!valid(movie)) return p;
  if (stars === null) {
    delete p.ratings[movie.movie_id];
    return p;
  }
  if (!Number.isInteger(stars) || stars < 1 || stars > 5) return p;
  setWatched(p, movie, true);
  p.ratings[movie.movie_id] = stars;
  return setOpinion(p, movie, opinionForStars(stars));
}

/** Film ids the server must leave out: the watched ones, unless the visitor chose to see them. */
export const excludedIds = (p) => (p.hideWatched ? [...p.watched] : []);

/** The part of the profile a ranking request carries. */
export const profileForApi = (p) => ({
  aspect_weights: p.weights, liked_movie_ids: p.liked, disliked_movie_ids: p.disliked,
});

/** True when the visitor has told us nothing yet (so the first-visit questions should be offered). */
export const isEmpty = (p) =>
  !p.liked.length && !p.disliked.length && !p.watched.length && !p.want.length &&
  !Object.keys(p.weights).length && !p.languages.length && !p.favouriteGenres.length &&
  !p.age && !p.region;

export const counts = (p) => ({
  liked: p.liked.length, disliked: p.disliked.length, watched: p.watched.length, want: p.want.length,
});

/** The profile as the text of a downloadable file. */
export function exportText(p, now = new Date()) {
  return JSON.stringify({ app: "cinewhy", version: PROFILE_VERSION, exportedAt: now.toISOString(), profile: p }, null, 2);
}

/** Read an exported file. Returns {ok: true, profile} or {ok: false, error}; never throws. */
export function importText(text) {
  if (typeof text !== "string" || text.length > IMPORT_CAP_BYTES) return { ok: false, error: "That file is too large to be a CineWhy profile." };
  let data;
  try { data = JSON.parse(text); } catch (_) { return { ok: false, error: "That file is not valid JSON." }; }
  if (!data || data.app !== "cinewhy" || typeof data.profile !== "object") return { ok: false, error: "That file is not a CineWhy profile export." };
  if (!Number.isInteger(data.version) || data.version > PROFILE_VERSION) return { ok: false, error: "That profile was made by a newer version of CineWhy." };
  return { ok: true, profile: migrate(data.profile) };
}
