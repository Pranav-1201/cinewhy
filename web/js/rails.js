/* The shelves: a spotlight pick and horizontal rails of posters. Each rail is one /discover
   request. The server ranks; this file only asks and draws. A response that arrives after a newer
   request was made is dropped, so a slow answer can never overwrite a fresh one. */

import { api, post } from "./api.js";
import { $, clear, h, icon, reducedMotion } from "./dom.js";
import { clamp, languageName, runtimeLabel } from "./format.js";
import { requestYears } from "./years.js";
import { linesFromAspects, receipt } from "./receipt.js";
import { excludedIds, profileForApi, state } from "./state.js";
import { poster, tile } from "./tile.js";
import { hueOf } from "./format.js";

let sequence = 0;
const scrollMemory = new Map();

/** The filters every shelf shares, from what the visitor has chosen. */
function shared(facets) {
  const req = { recency: state.recency, profile: profileForApi() };
  if (state.languages.length) req.languages = state.languages;
  if (state.genres.length) req.genres = state.genres;
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
  const root = $("#spotlight");
  if (!item) { clear(root); return; }
  const m = item.movie;
  let d = null;
  try { d = await api(`/movie/${encodeURIComponent(m.movie_id)}`); } catch (_) { /* the pick still shows without details */ }
  const chips = [m.year ? String(m.year) : "", languageName(item.language), runtimeLabel(d?.runtime_minutes), ...(m.genres || []).slice(0, 2)].filter(Boolean);
  const lines = d?.aspects?.length ? linesFromAspects(d.aspects.slice(0, 2)) : [];
  const section = h("div", { class: "spotlight", vars: { "--tint": hueOf(m.movie_id) } },
    poster(m, { language: item.language, isNew: item.is_new }),
    h("div", { class: "body" },
      h("h1", { text: m.title }),
      item.because ? h("p", { class: "because", text: `Because you liked ${item.because}` }) : null,
      h("div", { class: "meta" }, chips.map((c) => h("span", { class: "chip static", text: c }))),
      d?.overview ? h("p", { class: "overview", text: clamp(d.overview, 300) }) : null,
      h("div", { class: "actions" }, h("button", { class: "btn primary", type: "button", onclick: () => open(m.movie_id), text: "See all the receipts" })),
      lines.length ? h("div", { class: "receipts" }, receipt({ title: m.title, lines, bySource: d.reviews_by_source, maxQuotes: 1, heading: "Why we picked this" })) : null));
  root.replaceChildren(section);
}

/** Fetch every shelf and draw it. Safe to call again at any time. */
export async function renderAll(ctx) {
  const mine = ++sequence;
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
      spotlight(shelf.items[0], open);
      if (shelf.items.length > 1) rails.push(filledRail(spec, shelf.items.slice(1), open));
    } else {
      rails.push(filledRail(spec, shelf.items, open));
    }
  }
  root.replaceChildren(...rails);
  if (!any) {
    clear($("#spotlight"));
    status.hidden = false;
    status.textContent = failure
      ? `Could not load films. ${failure.message}`
      : "No films match these filters. Try a wider era, both languages, or fewer genres.";
  }
}
