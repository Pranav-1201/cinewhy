/* The "Where to watch" block of the film drawer. The server sends every country the title is on one
   of our six platforms in, so the visitor picks one. The first guess is the country they chose last
   time, then their browser's region; only a country the title is actually offered in can be picked.
   The logic is in where.js (tested in Node); this file only draws it. */

import { h } from "./dom.js";
import { NOT_ON_SIX, countriesOf, offersIn, pickCountry, regionOf, watchFooter } from "./where.js";

const KEY = "cinewhy.country";

function remembered() {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null; // private windows and blocked storage: the choice just is not kept
  }
}

function remember(code) {
  try {
    localStorage.setItem(KEY, code);
  } catch {
    /* not kept; the page still works */
  }
}

/** A country's name in the visitor's language, falling back to its code. */
function countryName(code) {
  try {
    return new Intl.DisplayNames([navigator.language || "en"], { type: "region" }).of(code) || code;
  } catch {
    return code;
  }
}

/** The list for one country, as a definition list: platform, then how to watch it there. */
function offersList(where, country) {
  const offers = offersIn(where, country);
  return h("dl", { class: "watch-list" }, offers.flatMap((offer) => [
    h("dt", { text: offer.platform }),
    h("dd", { text: offer.ways.join(" · ") }),
  ]));
}

/** The block, or nothing when the build has no availability data at all (an older build). */
export function whereToWatch(where) {
  if (!where) return null;
  const countries = countriesOf(where);
  const footer = h("p", { class: "watch-note" },
    watchFooter(where.fetched), " ",
    where.tmdb_url ? h("a", { href: where.tmdb_url, target: "_blank", rel: "noopener noreferrer", text: "Full list on TMDB" }) : null);
  if (!countries.length) {
    return h("section", { class: "watch", "aria-label": "Where to watch" },
      h("h3", { text: "Where to watch" }), h("p", { class: "film-overview", text: NOT_ON_SIX }), footer);
  }
  const chosen = pickCountry(countries, remembered(), regionOf(navigator.language));
  // Sorted by the name the visitor reads, not by ISO code ("AD, AE, AR" reads as a jumble).
  const named = countries.map((code) => ({ code, name: countryName(code) }));
  named.sort((a, b) => a.name.localeCompare(b.name));
  const select = h("select", { "aria-label": "Country" },
    named.map(({ code, name }) => h("option", { value: code, text: name })));
  select.value = chosen;
  const slot = h("div", { class: "watch-slot" }, offersList(where, chosen));
  select.addEventListener("change", () => {
    remember(select.value);
    slot.replaceChildren(offersList(where, select.value));
  });
  return h("section", { class: "watch", "aria-label": "Where to watch" },
    h("div", { class: "watch-head" }, h("h3", { text: "Where to watch" }), select), slot, footer);
}
