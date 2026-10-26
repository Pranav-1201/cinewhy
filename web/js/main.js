/* Boot and wiring. The page asks the server what exists (aspects, filter counts), draws the
   filters, then asks for shelves. Everything the visitor chooses lives in state.js. */

import { api } from "./api.js";
import { $, clear, debounce, h, reducedMotion } from "./dom.js";
import { renderAbout } from "./about.js";
import { initDialogs, openOnboarding, openTaste } from "./dialogs.js";
import { openFilm } from "./film.js";
import { openLibrary } from "./library.js";
import { openProfile, initProfile } from "./profilesheet.js";
import { renderAll } from "./rails.js";
import { openRate } from "./rate.js";
import { aspectLabels, initTheme, load, save, state, toggleTheme } from "./state.js";
import { poster } from "./tile.js";
import { activePreset, describeYears, normaliseYears, presetYears } from "./years.js";

const LANGS = [["en", "English"], ["hi", "Hindi"]];
const ctx = { facets: null, aspects: [], open: openFilm, refresh: null, syncFilters: null };

function chip(text, pressed, onclick) {
  return h("button", { class: "chip", type: "button", "aria-pressed": String(pressed), onclick, text });
}

/** The year-range bar: two presets and two sliders. "Any year" is simply the bar left at both ends,
    so it is not a highlighted choice. Dragging updates the label and chips in place (the sliders keep
    focus) and the shelves refresh a moment after the last move. */
function renderYears() {
  const { oldest_year: oldest, newest_year: newest } = ctx.facets;
  const box = $("#era-chips");
  if (!oldest || !newest) { box.replaceChildren(); return; }
  const first = normaliseYears(state.yearFrom, state.yearTo, oldest, newest);
  const low = h("input", { type: "range", min: String(oldest), max: String(newest), step: "1", value: String(first.from ?? oldest), "aria-label": "Earliest release year" });
  const high = h("input", { type: "range", min: String(oldest), max: String(newest), step: "1", value: String(first.to ?? newest), "aria-label": "Latest release year" });
  const readout = h("output", { class: "range-out" });
  const oldChip = chip("Old school", false, () => pick("old"));
  const newChip = chip("New", false, () => pick("new"));
  const bar = h("div", { class: "range", role: "group", "aria-label": "Release years" }, low, high);

  const paint = () => {
    const { from, to } = normaliseYears(Number(low.value), Number(high.value), oldest, newest);
    const preset = activePreset(from, to, oldest, newest);
    oldChip.setAttribute("aria-pressed", String(preset === "old"));
    newChip.setAttribute("aria-pressed", String(preset === "new"));
    readout.textContent = describeYears(from, to, oldest, newest);
    readout.classList.toggle("quiet", from === null && to === null);
    bar.style.setProperty("--from", String(((Number(low.value) - oldest) / (newest - oldest)) * 100));
    bar.style.setProperty("--to", String(((Number(high.value) - oldest) / (newest - oldest)) * 100));
  };
  const store = () => {
    const { from, to } = normaliseYears(Number(low.value), Number(high.value), oldest, newest);
    state.yearFrom = from;
    state.yearTo = to;
    save();
    paint();
    ctx.refresh();
  };
  function pick(name) {
    const same = activePreset(state.yearFrom, state.yearTo, oldest, newest) === name;
    const { from, to } = same ? { from: null, to: null } : presetYears(name);
    low.value = String(from ?? oldest);
    high.value = String(to ?? newest);
    store();
  }
  low.addEventListener("input", () => { if (Number(low.value) > Number(high.value)) low.value = high.value; store(); });
  high.addEventListener("input", () => { if (Number(high.value) < Number(low.value)) high.value = low.value; store(); });
  box.replaceChildren(h("span", { class: "chip-label", text: "When" }), oldChip, newChip, bar, readout);
  paint();
}

function renderFilters() {
  const lang = $("#lang-chips"), genre = $("#genre-chips");
  renderYears();
  lang.replaceChildren(h("span", { class: "chip-label", text: "Language" }), ...LANGS.map(([v, t]) => chip(t, state.languages.includes(v), () => {
    state.languages = state.languages.includes(v) ? state.languages.filter((x) => x !== v) : [...state.languages, v];
    save(); renderFilters(); ctx.refresh();
  })));
  $("#seen-chips").replaceChildren(h("span", { class: "chip-label", text: "Seen" }), chip("Hide films I've watched", state.hideWatched, () => {
    state.hideWatched = !state.hideWatched;
    save(); renderFilters(); ctx.refresh();
  }));
  const top = Object.keys(ctx.facets.genres || {}).slice(0, 8);
  genre.replaceChildren(h("span", { class: "chip-label", text: "Genre" }), ...top.map((g) => chip(g, state.genres.includes(g), () => {
    state.genres = state.genres.includes(g) ? state.genres.filter((x) => x !== g) : [...state.genres, g];
    save(); renderFilters(); ctx.refresh();
  })));
}

function wireSearch() {
  const input = $("#q"), list = $("#results"), form = $("#search-form");
  const hide = () => { list.hidden = true; input.setAttribute("aria-expanded", "false"); };
  const run = debounce(async () => {
    const q = input.value.trim();
    clear(list);
    if (!q) { hide(); return; }
    try {
      const films = await api(`/search?limit=8&q=${encodeURIComponent(q)}`);
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
      if (!films.length) list.append(h("li", {}, h("p", { class: "note", text: "No film by that name in this catalogue." })));
      for (const m of films) {
        list.append(h("li", {}, h("button", { type: "button", onclick: () => { hide(); input.value = ""; openFilm(m.movie_id); } },
          h("span", { class: "thumb" }, m.poster_url ? h("img", { src: m.poster_url, alt: "", loading: "lazy" }) : null),
          h("span", {}, m.title, h("br"), h("small", { text: m.year ? String(m.year) : "" })))));
      }
    } catch (err) {
      list.hidden = false;
      list.append(h("li", {}, h("p", { class: "note", text: err.message })));
    }
  }, 200);
  input.addEventListener("input", run);
  input.addEventListener("keydown", (e) => { if (e.key === "Escape") { input.value = ""; hide(); } });
  form.addEventListener("submit", (e) => e.preventDefault());
  document.addEventListener("click", (e) => { if (!form.contains(e.target)) hide(); });
}

async function boot() {
  initTheme();
  load();
  $("#theme-btn").addEventListener("click", toggleTheme);
  try {
    const [health, aspects, facets] = await Promise.all([api("/health"), api("/aspects"), api("/facets")]);
    ctx.aspects = aspects;
    ctx.facets = facets;
    for (const a of aspects) aspectLabels.set(a.aspect, a.label);
    $("#build").textContent = `Build ${health.manifest.slice(0, 12)}`;
  } catch (err) {
    const status = $("#status");
    status.hidden = false;
    status.textContent = `The server is not reachable. ${err.message}`;
    return;
  }
  const refresh = debounce(() => renderAll(ctx), 350);
  ctx.refresh = refresh;
  ctx.syncFilters = renderFilters;
  ctx.openRate = openRate;
  renderFilters();
  initDialogs(ctx);
  wireSearch();
  initProfile(ctx);
  // The tools that used to sit in the top bar now live in the Profile sheet; the sheet's buttons
  // and the places that open things are all defined once here.
  const tools = {
    taste: () => openTaste(ctx),
    review: () => $("#review-dialog").showModal(),
    about: () => { renderAbout(); $("#about-dialog").showModal(); },
    theme: toggleTheme,
  };
  const opens = { library: () => openLibrary(ctx), rate: () => openRate(), profile: () => openProfile() };
  for (const [name, open] of Object.entries(opens)) {
    for (const id of [`#${name}-btn`, `#nav-${name}`]) $(id)?.addEventListener("click", open);
  }
  $("#nav-home").addEventListener("click", () => window.scrollTo({ top: 0, behavior: reducedMotion() ? "auto" : "smooth" }));
  $("#nav-search").addEventListener("click", () => { window.scrollTo({ top: 0 }); $("#q").focus(); });
  for (const button of document.querySelectorAll("#profile-dialog [data-tool], #profile-dialog [data-open]")) {
    button.addEventListener("click", () => {
      $("#profile-dialog").close();
      (button.dataset.tool ? tools[button.dataset.tool] : opens[button.dataset.open])();
    });
  }
  // A like or skip changes the ranking, but not while the visitor is still browsing the rails.
  document.addEventListener("cinewhy:opinion", debounce(() => renderAll(ctx), 1200));
  await renderAll(ctx);
  if (!state.onboarded) openOnboarding(ctx);
}

boot();
