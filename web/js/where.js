/* Where to watch, the logic only: no DOM, no network, so Node's test runner can exercise it
   (tests/web/where.test.mjs). watch.js draws it. The server sends, per platform and per way of
   watching, the countries where that way is offered; this file turns that into "what can I do in
   my country". */

/** The six platforms we cover, with the names people use for them. */
export const PLATFORM_NAMES = {
  netflix: "Netflix",
  apple: "Apple TV",
  prime: "Amazon Prime Video",
  hotstar: "Disney+ Hotstar",
  crunchyroll: "Crunchyroll",
  hbo: "HBO Max",
};

const WAY_NAMES = { stream: "Stream", free: "Free", rent: "Rent", buy: "Buy" };

/** Every country code the title is offered in on any of the six, sorted. */
export function countriesOf(where) {
  const found = new Set();
  for (const option of where?.platforms ?? []) {
    for (const codes of Object.values(option.ways)) for (const code of codes) found.add(code);
  }
  return [...found].sort();
}

/** What is offered in one country: [{ platform: "Netflix", ways: ["Stream", "Rent"] }, ...],
    platforms in the server's order. A platform with nothing in that country is left out. */
export function offersIn(where, country) {
  const offers = [];
  for (const option of where?.platforms ?? []) {
    const ways = Object.entries(option.ways)
      .filter(([, codes]) => codes.includes(country))
      .map(([way]) => WAY_NAMES[way] ?? way);
    if (ways.length) offers.push({ platform: PLATFORM_NAMES[option.platform] ?? option.platform, ways });
  }
  return offers;
}

/** One sentence for a small space (a swipe card): where it can be watched in one country. Empty when
    the build has no availability data, and a plain "not on our six" when nothing offers it there. */
export function watchSummary(where, country, countryLabel = country) {
  if (!where) return "";
  const offers = offersIn(where, country);
  if (!offers.length) return `Not on our six streaming services in ${countryLabel}.`;
  const named = offers.map((o) => `${o.platform} (${o.ways.join(", ")})`).join("; ");
  return `Where to watch in ${countryLabel}: ${named}.`;
}

/** The countries the picker lists: every country the title is offered in, plus the visitor's own
    country even when it is not among them. The page always opens on the visitor's country (India
    unless they chose another), so it must be in the list; for a title not offered there the list
    says so rather than quietly showing some other country. */
export function withCountry(countries, chosen) {
  return countries.includes(chosen) ? countries : [...countries, chosen].sort();
}

/** The line shown when none of the six services offers the title in the visitor's country. */
export const notInCountry = (name) =>
  `Not on Netflix, Apple TV, Amazon Prime Video, Disney+ Hotstar, Crunchyroll or HBO Max in ${name}. Choose another country to see where else it is.`;

/** The line shown when the title is on none of the six anywhere. */
export const NOT_ON_SIX =
  "Not on Netflix, Apple TV, Amazon Prime Video, Disney+ Hotstar, Crunchyroll or HBO Max in any country we checked.";

/** The caveat under the list. Availability changes daily, so the date is always stated. */
export function watchFooter(fetched) {
  const when = fetched ? `As of ${fetched}. ` : "";
  return `${when}Availability changes, so check the service before you plan an evening. Data from TMDB, powered by JustWatch.`;
}
