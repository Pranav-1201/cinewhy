/* What the visitor chose. It lives in this browser only (localStorage); the server stores nothing
   and sees only what a request carries. Reads and writes are wrapped because private windows and
   blocked storage make localStorage throw. */

const KEY = "cinewhy.profile.v2";
const THEME_KEY = "cinewhy.theme";

const defaults = () => ({
  weights: {}, liked: [], disliked: [], titles: {},
  languages: [], era: "any", genres: [],
  recency: 0.5, recencyTouched: false,
  age: null, region: null, sex: null, hindiFirst: false, onboarded: false,
});

export const state = defaults();
export const aspectLabels = new Map();
export const labelOf = (id) => aspectLabels.get(id) || id;

/** Keep only what the page expects, so a corrupted value cannot break rendering. */
function sanitise() {
  const d = defaults();
  for (const key of ["liked", "disliked", "languages", "genres"]) if (!Array.isArray(state[key])) state[key] = d[key];
  for (const key of ["weights", "titles"]) if (typeof state[key] !== "object" || !state[key]) state[key] = d[key];
  if (typeof state.recency !== "number" || state.recency < 0 || state.recency > 1) state.recency = d.recency;
  if (!["any", "new", "2012", "2000"].includes(state.era)) state.era = "any";
}

export function load() {
  try { Object.assign(state, JSON.parse(localStorage.getItem(KEY) || "{}")); } catch (_) { /* start fresh */ }
  sanitise();
}

export function save() {
  try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (_) { /* ignore */ }
}

export function resetTaste() {
  const keep = { onboarded: state.onboarded };
  Object.assign(state, defaults(), keep);
  save();
}

export const profileForApi = () => ({
  aspect_weights: state.weights, liked_movie_ids: state.liked, disliked_movie_ids: state.disliked,
});

export const opinionOf = (id) => (state.liked.includes(id) ? "like" : state.disliked.includes(id) ? "dislike" : null);

/** Record like, dislike, or neither for a film; the film's title is kept to word the list later. */
export function setOpinion(movie, opinion) {
  state.titles[movie.movie_id] = movie.title + (movie.year ? ` (${movie.year})` : "");
  state.liked = state.liked.filter((id) => id !== movie.movie_id);
  state.disliked = state.disliked.filter((id) => id !== movie.movie_id);
  if (opinion === "like") state.liked.push(movie.movie_id);
  if (opinion === "dislike") state.disliked.push(movie.movie_id);
  save();
}

export function initTheme() {
  let stored = null;
  try { stored = localStorage.getItem(THEME_KEY); } catch (_) { /* default */ }
  if (stored === "light" || stored === "dark") document.documentElement.dataset.theme = stored;
}

export function toggleTheme() {
  const root = document.documentElement;
  const current = root.dataset.theme || (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
  const next = current === "light" ? "dark" : "light";
  root.dataset.theme = next;
  try { localStorage.setItem(THEME_KEY, next); } catch (_) { /* ignore */ }
}
