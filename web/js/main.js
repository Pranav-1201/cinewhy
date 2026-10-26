/* Boot and wiring. The page asks the server what exists (aspects, filter counts), draws the
   filters, then asks for shelves. Everything the visitor chooses lives in state.js. */

import { api } from "./api.js";
import { $, clear, debounce, h, reducedMotion } from "./dom.js";
import { renderAbout } from "./about.js";
import { initDialogs, openOnboarding, openTaste } from "./dialogs.js";
import { openFilm } from "./film.js";
import { renderAll } from "./rails.js";
import { aspectLabels, initTheme, load, save, state, toggleTheme } from "./state.js";
import { poster } from "./tile.js";

const ERAS = [["any", "Any year"], ["new", "New and now"], ["2012", "Since 2012"], ["2000", "Since 2000"]];
const LANGS = [["en", "English"], ["hi", "Hindi"]];
const ctx = { facets: null, aspects: [], open: openFilm, refresh: null, syncFilters: null };

function chip(text, pressed, onclick) {
  return h("button", { class: "chip", type: "button", "aria-pressed": String(pressed), onclick, text });
}

function renderFilters() {
  const era = $("#era-chips"), lang = $("#lang-chips"), genre = $("#genre-chips");
  era.replaceChildren(h("span", { class: "chip-label", text: "When" }), ...ERAS.map(([v, t]) => chip(t, state.era === v, () => { state.era = v; save(); renderFilters(); ctx.refresh(); })));
  lang.replaceChildren(h("span", { class: "chip-label", text: "Language" }), ...LANGS.map(([v, t]) => chip(t, state.languages.includes(v), () => {
    state.languages = state.languages.includes(v) ? state.languages.filter((x) => x !== v) : [...state.languages, v];
    save(); renderFilters(); ctx.refresh();
  })));
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
  renderFilters();
  initDialogs(ctx);
  wireSearch();
  // The same three tools are reachable from the top bar (wide screens) and the Profile sheet
  // (phones), so each is defined once here.
  const tools = {
    taste: () => openTaste(ctx),
    review: () => $("#review-dialog").showModal(),
    about: () => { renderAbout(); $("#about-dialog").showModal(); },
    theme: toggleTheme,
  };
  $("#taste-btn").addEventListener("click", tools.taste);
  $("#review-btn").addEventListener("click", tools.review);
  $("#about-btn").addEventListener("click", tools.about);
  $("#nav-home").addEventListener("click", () => window.scrollTo({ top: 0, behavior: reducedMotion() ? "auto" : "smooth" }));
  $("#nav-search").addEventListener("click", () => { window.scrollTo({ top: 0 }); $("#q").focus(); });
  $("#nav-profile").addEventListener("click", () => $("#profile-dialog").showModal());
  for (const button of document.querySelectorAll("#profile-dialog [data-tool]")) {
    button.addEventListener("click", () => {
      $("#profile-dialog").close();
      tools[button.dataset.tool]();
    });
  }
  // A like or skip changes the ranking, but not while the visitor is still browsing the rails.
  document.addEventListener("cinewhy:opinion", debounce(() => renderAll(ctx), 1200));
  await renderAll(ctx);
  if (!state.onboarded) openOnboarding(ctx);
}

boot();
