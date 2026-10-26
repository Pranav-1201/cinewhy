/* Rate films: one card at a time, so a visitor can teach the recommender quickly. Which films to ask
   about is decided by deck.js (a fixed rule that spans languages, eras and genres). Each answer goes
   through state.js and tells the page, so the shelves behind the dialog refresh as taste builds up. */

import { api, post } from "./api.js";
import { $, h } from "./dom.js";
import { DECK_SIZE, PER_SPEC, deckSpecs, mergeDeck } from "./deck.js";
import { clamp, languageName } from "./format.js";
import { rate, setOpinion, setWant, setWatched, state } from "./state.js";
import { starRow } from "./stars.js";
import { poster } from "./tile.js";

let deck = [];
let index = 0;
const skipped = new Set(); // "haven't seen it" this visit: not asked again until the page is reloaded
const overviews = new Map();

const changed = () => document.dispatchEvent(new CustomEvent("cinewhy:opinion"));

/** Ask the server for each spec in the deck rule and merge the answers into one list of cards. */
async function loadDeck() {
  const exclude = [...new Set([...state.watched, ...state.liked, ...state.disliked, ...state.want, ...skipped])].slice(0, 3000);
  const answers = await Promise.all(deckSpecs(state).map(({ id: _id, ...filters }) => (
    post("/discover", {
      limit: PER_SPEC, exclude_movie_ids: exclude, ...(filters.languages.length ? filters : { ...filters, languages: undefined }),
    }).then((r) => r.items).catch(() => [])
  )));
  deck = mergeDeck(answers, exclude, DECK_SIZE);
  if (!deck.length) {
    // The filters matched nothing (for example a chosen language the catalogue has no films for):
    // ask for the best-known films instead, so the dialog is never empty while films remain.
    const fallback = await post("/discover", { limit: DECK_SIZE, exclude_movie_ids: exclude }).then((r) => r.items).catch(() => []);
    deck = mergeDeck([fallback], exclude, DECK_SIZE);
  }
  index = 0;
}

function next() {
  index += 1;
  changed();
  draw();
}

function finished() {
  const box = $("#rate-card");
  box.replaceChildren(
    h("p", { class: "rate-progress", text: deck.length ? "That is all for now." : "No more films to ask about right now." }),
    h("p", { class: "lede", text: "Your answers are saved in this browser and already shape your picks." }),
    h("div", { class: "rate-actions" },
      deck.length ? h("button", { class: "btn primary", type: "button", text: "Show me more films", onclick: start }) : null,
      h("button", { class: "btn", type: "button", text: "Done", onclick: () => $("#rate-dialog").close() })));
}

function draw() {
  if (index >= deck.length) { finished(); return; }
  const item = deck[index];
  const movie = item.movie;
  const overview = h("p", { class: "overview", text: overviews.get(movie.movie_id) ?? "" });
  if (!overviews.has(movie.movie_id)) {
    api(`/movie/${encodeURIComponent(movie.movie_id)}`).then((d) => {
      const text = d.overview ? clamp(d.overview, 240) : "";
      overviews.set(movie.movie_id, text);
      overview.textContent = text;
    }).catch(() => overviews.set(movie.movie_id, ""));
  }
  const chips = [movie.year ? String(movie.year) : "", languageName(item.language), ...(movie.genres || []).slice(0, 2)].filter(Boolean);
  const button = (text, onclick, cls = "btn") => h("button", { class: cls, type: "button", text, onclick });
  $("#rate-card").replaceChildren(
    h("p", { class: "rate-progress", text: `Film ${index + 1} of ${deck.length}` }),
    h("div", { class: "rate-card" },
      poster(movie, { language: item.language, isNew: item.is_new }),
      h("div", {},
        h("h3", { text: movie.title }),
        h("div", { class: "meta" }, chips.map((c) => h("span", { class: "chip static", text: c }))),
        overview,
        h("p", { class: "rate-ask", text: "Seen it? Rate it." }),
        starRow(0, (stars) => { if (stars) { rate(movie, stars); next(); } }, `Rate ${movie.title}`))),
    h("div", { class: "rate-actions" },
      button("Haven't seen it", () => { skipped.add(movie.movie_id); next(); }),
      button("Not for me", () => { setOpinion(movie, "dislike"); next(); }),
      button("Want to watch", () => { setWant(movie, true); next(); }),
      button("Seen it, no rating", () => { setWatched(movie, true); next(); })));
}

async function start() {
  $("#rate-card").replaceChildren(h("p", { class: "note", text: "Finding films to ask about." }));
  await loadDeck();
  draw();
}

export function openRate() {
  const dialog = $("#rate-dialog");
  if (!dialog.open) dialog.showModal();
  start();
}
