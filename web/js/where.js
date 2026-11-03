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

/** The region of a language tag: "en-IN" is "IN", "en" is null. */
export function regionOf(languageTag) {
  const match = /^[A-Za-z]{2,3}[-_]([A-Za-z]{2})\b/.exec(String(languageTag ?? ""));
  return match ? match[1].toUpperCase() : null;
}

/** The country to show first: the first preferred one the title is offered in (the visitor's own
    choice, then their browser's region), else the first country it is offered in. Only a country
    the title is offered in can be picked, so the answer is never an empty page for a title that
    is available somewhere. */
export function pickCountry(countries, ...preferred) {
  for (const code of preferred) {
    if (code && countries.includes(code)) return code;
  }
  return countries[0] ?? null;
}

/** The line shown when the title is on none of the six anywhere. */
export const NOT_ON_SIX =
  "Not on Netflix, Apple TV, Amazon Prime Video, Disney+ Hotstar, Crunchyroll or HBO Max in any country we checked.";

/** The caveat under the list. Availability changes daily, so the date is always stated. */
export function watchFooter(fetched) {
  const when = fetched ? `As of ${fetched}. ` : "";
  return `${when}Availability changes, so check the service before you plan an evening. Data from TMDB, powered by JustWatch.`;
}
