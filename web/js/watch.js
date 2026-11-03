/* The "Where to watch" block of the film drawer and the top pick. It opens on the visitor's own
   country: the one saved in their profile, which is India until they choose another. The server
   sends every country a title is on one of our six platforms in, so the picker can show any of
   them, and a pick is saved to the profile. If the title is not offered in the visitor's country
   the block says so instead of quietly showing another country.
   The logic is in where.js (tested in Node); this file only draws it. */

import { h } from "./dom.js";
import { state, setCountry } from "./state.js";
import { NOT_ON_SIX, countriesOf, notInCountry, offersIn, watchFooter, withCountry } from "./where.js";

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
  if (!offers.length) return h("p", { class: "watch-none", text: notInCountry(countryName(country)) });
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
  const chosen = state.country;
  // Sorted by the name the visitor reads, not by ISO code ("AD, AE, AR" reads as a jumble).
  const named = withCountry(countries, chosen).map((code) => ({ code, name: countryName(code) }));
  named.sort((a, b) => a.name.localeCompare(b.name));
  const select = h("select", { "aria-label": "Country" },
    named.map(({ code, name }) => h("option", { value: code, text: name })));
  select.value = chosen;
  const slot = h("div", { class: "watch-slot" }, offersList(where, chosen));
  select.addEventListener("change", () => {
    setCountry(select.value);
    slot.replaceChildren(offersList(where, select.value));
  });
  return h("section", { class: "watch", "aria-label": "Where to watch" },
    h("div", { class: "watch-head" }, h("h3", { text: "Where to watch" }), select), slot, footer);
}
