/* What the visitor chose. It lives in this browser only (localStorage); the server stores nothing
   and sees only what a request carries. Reads and writes are wrapped because private windows and
   blocked storage make localStorage throw. The rules for the profile itself (what a valid one looks
   like, how likes, watched and want-to-watch relate) are in profile.js, which Node tests directly. */

import * as profile from "./profile.js";

const KEY = "cinewhy.profile.v3";
const OLD_KEY = "cinewhy.profile.v2"; // read once and migrated; never written again
const THEME_KEY = "cinewhy.theme";

export const state = profile.defaultProfile();
export const aspectLabels = new Map();
export const labelOf = (id) => aspectLabels.get(id) || id;

/** Replace what `state` holds with `next`, keeping the same object so other modules' imports stay valid. */
function adopt(next) {
  for (const key of Object.keys(state)) delete state[key];
  Object.assign(state, next);
}

export function load() {
  let raw = null;
  try {
    raw = localStorage.getItem(KEY) ?? localStorage.getItem(OLD_KEY);
    adopt(profile.migrate(raw ? JSON.parse(raw) : null));
  } catch (_) { adopt(profile.defaultProfile()); /* corrupted or blocked storage: start fresh */ }
}

export function save() {
  try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (_) { /* ignore */ }
}

export function resetTaste() {
  const keep = { onboarded: state.onboarded };
  adopt({ ...profile.defaultProfile(), ...keep });
  save();
}

/** Replace the whole profile (used by Import) and keep it. */
export function replaceProfile(next) {
  adopt(next);
  save();
}

export const profileForApi = () => profile.profileForApi(state);
export const excludedIds = () => profile.excludedIds(state);
export const opinionOf = (id) => profile.opinionOf(state, id);
export const isWatched = (id) => profile.isWatched(state, id);
export const isWanted = (id) => profile.isWanted(state, id);
export const isEmpty = () => profile.isEmpty(state);
export const counts = () => profile.counts(state);
export const exportText = () => profile.exportText(state);

/** Record like, dislike, or neither for a film; the film's title is kept to word the list later. */
export function setOpinion(movie, opinion) { profile.setOpinion(state, movie, opinion); save(); }
export function setWatched(movie, on) { profile.setWatched(state, movie, on); save(); }
export function setWant(movie, on) { profile.setWant(state, movie, on); save(); }
export function rate(movie, stars) { profile.rate(state, movie, stars); save(); }

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
