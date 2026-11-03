/* The shelves: a spotlight pick and horizontal rails of posters. Each rail is one /discover
   request. The server ranks; this file only asks and draws. A response that arrives after a newer
   request was made is dropped, so a slow answer can never overwrite a fresh one. */

import { api, post } from "./api.js";
import { $, clear, h, icon, reducedMotion } from "./dom.js";
import { clamp, kindLabel, languageName, runtimeLabel } from "./format.js";
import { requestYears } from "./years.js";
import { actions } from "./film.js";
import * as picks from "./picks.js";
import { starring } from "./people.js";
import { excludedIds, profileForApi, state } from "./state.js";
import { poster, tile } from "./tile.js";
import { whereToWatch } from "./watch.js";
import { hueOf } from "./format.js";

let sequence = 0;
const scrollMemory = new Map();

// The top pick and "Show me another" (the walk itself is picks.js, tested in Node).
const MORE_PICKS = 16;
const queue = picks.makeQueue();
const byId = new Map(); // id -> the item the server sent, for every title in the queue
let picksSpec = null; // the picks shelf's heading, to redraw its row as the pick changes
let lastCtx = null;
let spotlightSeq = 0;
let exhausted = false; // the server has no more picks for the current filters
let busy = false;

/** The filters every shelf shares, from what the visitor has chosen. */
function shared(facets) {
  const req = { recency: state.recency, profile: profileForApi() };
  if (state.languages.length) req.languages = state.languages;
  if (state.genres.length) req.genres = state.genres;
  if (state.kinds.length) req.kinds = state.kinds;
  const watched = excludedIds(); // films the visitor has seen are left out unless they chose to see them
  if (watched.length) req.exclude_movie_ids = watched;
  return { ...req, ...requestYears(state.yearFrom, state.yearTo, facets.oldest_year, facets.newest_year) };
}

/** What the page shows while the shelves load: three empty rails, so the layout does not jump. */
const LOADING = ["a", "b", "c"].map((id) => ({ id, title: "Finding films", sub: "Reading what people said about them" }));

/** The server's shelves in display order. A visitor from India sees the Hindi shelf before English. */
function ordered(shelves) {
  if (!state.hindiFirst) return shelves;
  const hindi = shelves.findIndex((s) => s.id === "lang-hi");
  const english = shelves.findIndex((s) => s.id === "lang-en");
  if (hindi < 0 || english < 0 || hindi < english) return shelves;
  const copy = [...shelves];
  [copy[english], copy[hindi]] = [copy[hindi], copy[english]];
  return copy;
}

function skeletonRail(spec) {
  const items = Array.from({ length: 8 }, () => h("li", { class: "tile" }, h("span", { class: "poster skeleton" })));
  return h("section", { class: "rail", "data-rail": spec.id, "aria-busy": "true" },
    h("div", { class: "rail-head" }, h("div", {}, h("h2", { text: spec.title }), h("p", { text: spec.sub }))),
    h("ul", { class: "rail-scroll", "aria-label": spec.title }, items));
}

function filledRail(spec, items, open) {
  const scroller = h("ul", { class: "rail-scroll", "aria-label": spec.title }, items.map((item) => tile(item, open)));
  const step = (dir) => scroller.scrollBy({ left: dir * scroller.clientWidth * 0.8, behavior: reducedMotion() ? "auto" : "smooth" });
  const nav = h("div", { class: "rail-nav" },
    h("button", { class: "btn", type: "button", "aria-label": `Scroll ${spec.title} left`, onclick: () => step(-1) }, icon("left")),
    h("button", { class: "btn", type: "button", "aria-label": `Scroll ${spec.title} right`, onclick: () => step(1) }, icon("right")));
  const section = h("section", { class: "rail", "data-rail": spec.id },
    h("div", { class: "rail-head" }, h("div", {}, h("h2", { text: spec.title }), h("p", { text: spec.sub })), nav), scroller);
  scroller.addEventListener("scroll", () => scrollMemory.set(spec.id, scroller.scrollLeft), { passive: true });
  requestAnimationFrame(() => { scroller.scrollLeft = scrollMemory.get(spec.id) || 0; });
  return section;
}

async function spotlight(item, open) {
  const mine = ++spotlightSeq;
  const root = $("#spotlight");
  if (!item) { clear(root); return; }
  const m = item.movie;
  let d = null;
  try { d = await api(`/movie/${encodeURIComponent(m.movie_id)}`); } catch (_) { /* the pick still shows without details */ }
  if (mine !== spotlightSeq) return; // another pick was asked for while this one loaded
  const chips = [m.year ? String(m.year) : "", kindLabel(m.kind), languageName(item.language), runtimeLabel(d?.runtime_minutes), ...(m.genres || []).slice(0, 2)].filter(Boolean);
  // The top pick carries what the film page carries: who is in it, the answers (like, watched, ...),
  // the links, and where to watch. The reasons live behind the yellow button, not on the pick, so
  // the pick shows the facts a visitor decides on and the receipts stay one press away.
  const why = h("button", { class: "btn primary", type: "button", onclick: () => open(m.movie_id, { toReceipt: true }), text: "Why we chose this" });
  const row = d ? actions(m, d) : h("div", { class: "film-actions" }); // no details: the pick still offers its reasons
  row.classList.add("actions");
  // "Show me another" is for the visitor who has seen this pick, even marked it Want to watch, and
  // still wants to look at the choices: it steps to the next best and never touches their lists.
  const finished = exhausted && !picks.hasNext(queue);
  const another = h("button", { class: "btn", type: "button", text: "Show me another", disabled: finished, onclick: () => showAnother(open) });
  const back = picks.canGoBack(queue) ? h("button", { class: "btn", type: "button", text: "Previous pick", onclick: () => showPrevious(open) }) : null;
  row.prepend(...[why, another, back].filter(Boolean));
  const section = h("div", { class: "spotlight", vars: { "--tint": hueOf(m.movie_id) } },
    poster(m, { language: item.language, isNew: item.is_new }),
    h("div", { class: "body" },
      h("h1", { text: m.title }),
      item.because ? h("p", { class: "because", text: `Because you liked ${item.because}` }) : null,
      h("div", { class: "meta" }, chips.map((c) => h("span", { class: "chip static", text: c }))),
      d?.overview ? h("p", { class: "overview", text: clamp(d.overview, 300) }) : null,
      starring(d?.cast),
      row,
      finished ? h("p", { class: "pick-note", text: "That is every pick for these filters. Widen the era, language or genre to see more." }) : null,
      whereToWatch(d?.where_to_watch)));
  root.replaceChildren(section);
}

/** Draw the title the queue is on, and the row of what comes after it (so no title is on screen twice). */
function showPick(open) {
  spotlight(byId.get(picks.currentId(queue)), open);
  const root = $("#rails");
  const old = root.querySelector('[data-rail="picks"]');
  const items = picks.upcoming(queue).map((id) => byId.get(id)).filter(Boolean);
  if (!items.length || !picksSpec) { old?.remove(); return; }
  const fresh = filledRail(picksSpec, items, open);
  if (old) old.replaceWith(fresh); else root.prepend(fresh);
}

/** Move to the next best pick, asking the server for more when the ranking we hold runs out. */
async function showAnother(open) {
  if (busy) return;
  if (picks.next(queue) === "more") {
    busy = true;
    const stamp = sequence;
    try {
      // What the server must leave out: what the visitor has watched, plus every title already in the
      // queue or shown. The queue comes first, so if a huge watched list ever hit the server's cap it
      // is the tail of that list that is dropped, never a title the visitor has just passed.
      const ids = [...new Set([...queue.ids, ...queue.seen, ...excludedIds()])].slice(0, 3000);
      const body = { ...shared(lastCtx.facets), limit: MORE_PICKS, receipts_only: true, exclude_movie_ids: ids };
      const more = (await post("/discover", body)).items;
      if (stamp !== sequence) return; // the page was redrawn meanwhile; its own list is the truth
      for (const item of more) byId.set(item.movie.movie_id, item);
      if (picks.append(queue, more.map((item) => item.movie.movie_id))) picks.next(queue);
      else exhausted = true;
    } catch (err) {
      const status = $("#status");
      status.hidden = false;
      status.textContent = `Could not load more picks. ${err.message}`;
    } finally {
      busy = false;
    }
  }
  showPick(open);
}

function showPrevious(open) {
  if (picks.previous(queue)) showPick(open);
}

/** Fetch every shelf and draw it. Safe to call again at any time. */
export async function renderAll(ctx) {
  const mine = ++sequence;
  lastCtx = ctx;
  const { facets, open } = ctx;
  const root = $("#rails");
  const status = $("#status");
  status.hidden = true;
  root.replaceChildren(...LOADING.map(skeletonRail));
  let shelves = [];
  let failure = null;
  try {
    shelves = ordered((await post("/shelves", shared(facets))).shelves);
  } catch (err) {
    failure = err;
  }
  if (mine !== sequence) return; // a newer request has taken over
  const rails = [];
  let any = false;
  for (const shelf of shelves) {
    const spec = { id: shelf.id, title: shelf.title, sub: shelf.subtitle };
    if (shelf.id === "picks") {
      any = shelf.items.length > 0;
      // The queue keeps the title on show if it is still ranked (so liking it does not jerk the page),
      // and otherwise moves on to the first one the visitor has not been shown.
      picksSpec = spec;
      byId.clear();
      for (const item of shelf.items) byId.set(item.movie.movie_id, item);
      picks.load(queue, shelf.items.map((item) => item.movie.movie_id));
      exhausted = false;
    } else {
      rails.push(filledRail(spec, shelf.items, open));
    }
  }
  root.replaceChildren(...rails);
  if (any) showPick(open);
  if (!any) {
    picks.load(queue, []);
    clear($("#spotlight"));
    status.hidden = false;
    status.textContent = failure
      ? `Could not load films. ${failure.message}`
      : "No films match these filters. Try a wider era, both languages, or fewer genres.";
  }
}
