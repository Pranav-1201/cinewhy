/* The library: the four lists a visitor builds (watched, want to watch, liked, not for me) behind one
   toggle. Every change goes through state.js and tells the page, so the shelves refresh and watched
   films drop out of the picks. Posters are fetched lazily from the film page endpoint; the list itself
   draws at once from the titles the profile remembers, so a slow network never leaves it empty. */

import { api } from "./api.js";
import { $, h } from "./dom.js";
import { starRow } from "./stars.js";
import { counts, rate, setOpinion, setWant, setWatched, state } from "./state.js";

const LISTS = [
  { key: "watched", label: "Watched", ids: () => state.watched, empty: "Films you mark as watched are listed here, and are left out of your picks." },
  { key: "want", label: "Want to watch", ids: () => state.want, empty: "Press the bookmark on any film to keep it here for later." },
  { key: "liked", label: "Liked", ids: () => state.liked, empty: "Films you like are listed here and steer your picks." },
  { key: "disliked", label: "Not for me", ids: () => state.disliked, empty: "Films you say are not for you are listed here and are never recommended." },
];
const PAGE = 30;
const details = new Map(); // film id to what the film page endpoint said (null if it failed)
let ctxRef = null;
let current = "watched";
let shown = PAGE;

const movieOf = (id) => ({ movie_id: id, title: state.titles[id] || id, year: null });
const changed = () => document.dispatchEvent(new CustomEvent("cinewhy:opinion"));

function actionsFor(key, id, redraw) {
  const movie = movieOf(id);
  const after = () => { changed(); redraw(); };
  const button = (text, onclick) => h("button", { class: "btn", type: "button", text, onclick });
  if (key === "watched") return [button("Not watched", () => { setWatched(movie, false); after(); })];
  if (key === "want") {
    return [
      button("I've watched it", () => { setWatched(movie, true); after(); }),
      button("Remove", () => { setWant(movie, false); after(); }),
    ];
  }
  return [button(key === "liked" ? "Remove like" : "Remove", () => { setOpinion(movie, null); after(); })];
}

function row(key, id, redraw) {
  const title = state.titles[id] || id;
  const thumb = h("span", { class: "thumb" });
  const fill = (d) => {
    if (d?.movie?.poster_url) thumb.replaceChildren(h("img", { src: d.movie.poster_url, alt: "", loading: "lazy" }));
  };
  if (details.has(id)) fill(details.get(id));
  else {
    api(`/movie/${encodeURIComponent(id)}`)
      .then((d) => { details.set(id, d); fill(d); })
      .catch(() => details.set(id, null));
  }
  const sub = key === "watched"
    ? starRow(state.ratings[id] || 0, (stars) => { rate(movieOf(id), stars); changed(); redraw(); }, `Your rating for ${title}`)
    : null;
  return h(
    "li", { class: "lib-row" },
    thumb,
    h("div", {}, h("button", { class: "name", type: "button", text: title, onclick: () => ctxRef.open(id) }), sub),
    h("div", { class: "row-actions" }, actionsFor(key, id, redraw)));
}

function draw() {
  const n = counts();
  $("#library-tabs").replaceChildren(...LISTS.map((list) => h(
    "button", {
      class: "btn", type: "button", "aria-pressed": String(list.key === current),
      onclick: () => { current = list.key; shown = PAGE; draw(); },
    },
    list.label, " ", h("span", { class: "count", text: `(${n[list.key]})` }))));
  const list = LISTS.find((l) => l.key === current);
  const ids = [...list.ids()].reverse(); // newest first
  const box = $("#library-list");
  if (!ids.length) { box.replaceChildren(h("p", { class: "note", text: list.empty })); return; }
  const more = ids.length > shown
    ? h("button", { class: "btn", type: "button", text: `Show ${Math.min(PAGE, ids.length - shown)} more`, onclick: () => { shown += PAGE; draw(); } })
    : null;
  box.replaceChildren(h("ul", { class: "lib-list" }, ids.slice(0, shown).map((id) => row(current, id, draw))), more);
}

/** Open the library, on `which` ("watched", "want", "liked" or "disliked") if given. */
export function openLibrary(ctx, which) {
  ctxRef = ctx;
  if (which && LISTS.some((l) => l.key === which)) current = which;
  shown = PAGE;
  draw();
  const dialog = $("#library-dialog");
  if (!dialog.open) dialog.showModal();
}
