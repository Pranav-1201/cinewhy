/* One swipe card: what it shows, and how it moves. A card can be dragged (mouse or finger), flung
   by a button or an arrow key, and snapped back when the answer needs a confirmation first. The
   rules (which drag is which answer) are swipecore.js; this file only draws and animates.

   Position is set as custom properties through the CSSOM (--dx, --dy, --rot) and the stylesheet
   turns them into a transform: the page's security policy forbids inline style attributes. */

import { h, reducedMotion } from "./dom.js";
import { clamp, imdbLine, kindLabel, languageName, movieLensLine, runtimeLabel } from "./format.js";
import { starring } from "./people.js";
import { state } from "./state.js";
import { ACTIONS, LABELS, decide, hint } from "./swipecore.js";
import { poster } from "./tile.js";
import { watchSummary } from "./where.js";

const FLING_MS = 260;

/** A country's name, falling back to its code (the card says "in India", not "in IN"). */
function countryLabel(code) {
  try { return new Intl.DisplayNames(["en"], { type: "region" }).of(code) || code; } catch (_) { return code; }
}

/** The rating line a card shows: IMDb alone for a title we only have ratings for, else both. */
export function ratingLine(card) {
  const imdb = imdbLine(card.imdb_rating, card.imdb_votes);
  if (card.ratings_only) return imdb;
  return [movieLensLine(card.rating_count, card.mean_rating), imdb].filter(Boolean).join(" ");
}

/** What a card says about the title: everything the owner asked for and nothing more. */
function info(card) {
  const m = card.movie;
  const chips = [m.year ? String(m.year) : "", kindLabel(m.kind), languageName(card.language), runtimeLabel(card.runtime_minutes), ...(m.genres || []).slice(0, 3)].filter(Boolean);
  const rating = ratingLine(card);
  return h("div", { class: "sw-info" },
    h("h3", { text: m.title }),
    h("div", { class: "meta" }, chips.map((c) => h("span", { class: "chip static", text: c }))),
    rating ? h("p", { class: "sw-rating", text: rating }) : null,
    card.because ? h("p", { class: "sw-because", text: `Because you liked ${card.because}` }) : null,
    card.overview ? h("p", { class: "sw-overview", text: clamp(card.overview, 220) }) : null,
    starring(card.cast),
    // The full where-to-watch panel is too tall for a card; this is the same data in one line, for
    // the visitor's own country (the film page keeps the full panel and the country picker).
    card.where_to_watch ? h("p", { class: "sw-where", text: watchSummary(card.where_to_watch, state.country, countryLabel(state.country)) }) : null);
}

/**
 * Build the card for `card` (a DeckCard from the server). `onDecide(action, handle)` is called once
 * the card has left the screen; the handle's `snapBack()` returns it if the answer is not final yet.
 * `guard(direction, handle)` is asked before a card flies: false keeps it where it is.
 */
export function buildCard(card, { onDecide, guard = () => true }) {
  const stamps = Object.fromEntries(Object.entries(LABELS).map(([action, text]) =>
    [action, h("span", { class: `sw-stamp ${action}`, "aria-hidden": "true", text })]));
  const el = h("article", { class: "sw-card", "aria-label": card.movie.title },
    h("div", { class: "sw-poster" }, poster(card.movie, { language: card.language })),
    info(card),
    ...Object.values(stamps));
  let start = null;
  let decided = false;

  const place = (dx, dy) => {
    el.style.setProperty("--dx", `${dx}px`);
    el.style.setProperty("--dy", `${dy}px`);
    el.style.setProperty("--rot", `${dx / 18}deg`);
  };
  const lean = (dx, dy) => {
    const leaning = hint(dx, dy);
    for (const [action, stamp] of Object.entries(stamps)) {
      stamp.style.setProperty("--o", String(leaning?.action === action ? leaning.strength : 0));
    }
  };

  const handle = {
    el,
    /** Send the card off the screen in `direction` ("right", "left", "up" or "down"). */
    fling(direction) {
      if (decided) return;
      // The page can refuse a direction for now (a second top pick must be confirmed first): the
      // card stays, and the page asks its question.
      if (!guard(direction, handle)) { place(0, 0); lean(0, 0); return; }
      decided = true;
      const far = 1.3 * Math.max(window.innerWidth, window.innerHeight, 600);
      const [dx, dy] = { right: [far, 0], left: [-far, 0], up: [0, -far], down: [0, far] }[direction];
      el.classList.remove("dragging");
      el.classList.add("flying");
      lean(dx, dy);
      place(dx, dy);
      let finished = false;
      const finish = () => { if (finished) return; finished = true; onDecide(ACTIONS[direction], handle); };
      if (reducedMotion()) finish();
      else { el.addEventListener("transitionend", finish, { once: true }); setTimeout(finish, FLING_MS + 80); }
    },
    /** Bring the card back (the answer was not confirmed). */
    snapBack() {
      decided = false;
      el.classList.remove("flying");
      place(0, 0);
      lean(0, 0);
    },
  };

  el.addEventListener("pointerdown", (event) => {
    if (decided || event.button > 0 || event.target.closest("button, a")) return; // cast and links still click
    start = { x: event.clientX, y: event.clientY };
    el.setPointerCapture(event.pointerId);
    el.classList.add("dragging");
  });
  el.addEventListener("pointermove", (event) => {
    if (!start) return;
    const dx = event.clientX - start.x;
    const dy = event.clientY - start.y;
    place(dx, dy);
    lean(dx, dy);
  });
  const release = (event) => {
    if (!start) return;
    const dx = event.clientX - start.x;
    const dy = event.clientY - start.y;
    start = null;
    el.classList.remove("dragging");
    const direction = decide(dx, dy);
    if (direction) handle.fling(direction);
    else { place(0, 0); lean(0, 0); }
  };
  el.addEventListener("pointerup", release);
  el.addEventListener("pointercancel", () => {
    start = null;
    el.classList.remove("dragging");
    place(0, 0);
    lean(0, 0);
  });
  place(0, 0);
  return handle;
}
