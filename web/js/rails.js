/* The shelves: a spotlight pick and horizontal rails of posters. Each rail is one /discover
   request. The server ranks; this file only asks and draws. A response that arrives after a newer
   request was made is dropped, so a slow answer can never overwrite a fresh one. */

import { api, post } from "./api.js";
import { $, clear, h, icon, reducedMotion } from "./dom.js";
import { clamp, eraRange, languageName, runtimeLabel } from "./format.js";
import { linesFromAspects, receipt } from "./receipt.js";
import { profileForApi, state } from "./state.js";
import { poster, sampleHue, tile } from "./tile.js";
import { hueOf } from "./format.js";

let sequence = 0;
const scrollMemory = new Map();

function personalised() {
  return state.liked.length > 0 || Object.keys(state.weights).length > 0;
}

/** The filters every shelf shares, from what the visitor has chosen. */
function shared(facets) {
  const req = { recency: state.recency, profile: profileForApi() };
  if (state.languages.length) req.languages = state.languages;
  if (state.genres.length) req.genres = state.genres;
  return { ...req, ...eraRange(state.era, facets.newest_year) };
}

function shelves(facets) {
  const base = shared(facets);
  const newest = facets.newest_year;
  const hindiOk = state.languages.length === 0 || state.languages.includes("hi");
  const list = [
    { id: "main", title: personalised() ? "Picked for you" : "Tonight's picks", sub: personalised() ? "Ranked by your taste, with the sentences behind each pick" : "Well known and well liked, newest first", req: { ...base, limit: 14 } },
  ];
  const extra = [];
  if (state.era === "any") {
    extra.push({ id: "new", title: "New and now", sub: "Released in the last few years", req: { ...base, from_year: newest - 7, recency: 1, limit: 20 } });
  }
  if (hindiOk) {
    const { from_year, to_year } = base;
    extra.push({ id: "hindi", title: "Hindi picks", sub: "Bollywood and beyond", req: { ...base, languages: ["hi"], from_year, to_year, limit: 20 } });
  }
  if (state.era === "any") {
    extra.push({ id: "classics", title: "Classics worth the detour", sub: "Released in 1999 or earlier", req: { ...base, to_year: 1999, recency: 0, limit: 20 } });
  }
  if (state.hindiFirst) extra.sort((a) => (a.id === "hindi" ? -1 : 0));
  return [...list, ...extra];
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
      h("div", { class: "meta" }, chips.map((c) => h("span", { class: "chip static", text: c }))),
      d?.overview ? h("p", { class: "overview", text: clamp(d.overview, 300) }) : null,
      h("div", { class: "actions" }, h("button", { class: "btn primary", type: "button", onclick: () => open(m.movie_id), text: "See all the receipts" })),
      lines.length ? h("div", { class: "receipts" }, receipt({ title: m.title, lines, bySource: d.reviews_by_source, maxQuotes: 1, heading: "Why tonight's pick" })) : null));
  root.replaceChildren(section);
  if (m.poster_url) {
    const hue = await sampleHue(m.poster_url);
    if (hue !== null && section.isConnected) section.style.setProperty("--tint", String(hue));
  }
}

/** Fetch every shelf and draw it. Safe to call again at any time. */
export async function renderAll(ctx) {
  const mine = ++sequence;
  const { facets, open } = ctx;
  const specs = shelves(facets);
  const root = $("#rails");
  const status = $("#status");
  status.hidden = true;
  root.replaceChildren(...specs.map(skeletonRail));
  const results = await Promise.allSettled(specs.map((s) => post("/discover", s.req)));
  if (mine !== sequence) return; // a newer request has taken over
  const rails = [];
  let any = false;
  let failure = null;
  results.forEach((result, i) => {
    if (result.status === "rejected") { failure = result.reason; return; }
    const items = result.value.items;
    if (specs[i].id === "main") {
      any = items.length > 0;
      spotlight(items[0], open);
      if (items.length > 1) rails.push(filledRail(specs[i], items.slice(1), open));
    } else if (items.length) {
      rails.push(filledRail(specs[i], items, open));
    }
  });
  root.replaceChildren(...rails);
  if (!any) {
    clear($("#spotlight"));
    status.hidden = false;
    status.textContent = failure
      ? `Could not load films. ${failure.message}`
      : "No films match these filters. Try a wider era, both languages, or fewer genres.";
  }
}
