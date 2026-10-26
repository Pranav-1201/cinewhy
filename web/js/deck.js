/* Which films to ask a visitor about in "Rate films". A fixed rule, not chance: the deck spans
   languages, eras and genres, so a few answers reveal taste across the catalogue instead of ten
   near-identical blockbusters. No DOM and no network, so Node tests it (tests/web/deck.test.mjs).

   `deckSpecs` says WHAT to ask the server for (each spec is the filter part of a /discover request);
   `mergeDeck` turns the answers into one list, taking one film from each spec in turn. */

export const DECK_SIZE = 12;
export const PER_SPEC = 3;

const EN = ["en"];
const HI = ["hi"];
const BASE = [
  { id: "en-recent", languages: EN, from_year: 2015 },
  { id: "en-classic", languages: EN, to_year: 1999 },
  { id: "en-comedy", languages: EN, genres: ["Comedy"] },
  { id: "hi-any", languages: HI },
  { id: "en-action", languages: EN, genres: ["Action"] },
  { id: "en-drama", languages: EN, genres: ["Drama"] },
  { id: "hi-recent", languages: HI, from_year: 2012 },
  { id: "en-thriller", languages: EN, genres: ["Thriller"] },
  { id: "en-romance", languages: EN, genres: ["Romance"] },
  { id: "en-scifi", languages: EN, genres: ["Science Fiction"] },
  { id: "en-horror", languages: EN, genres: ["Horror"] },
  { id: "en-animation", languages: EN, genres: ["Animation"] },
  // Last resort, used only when no language was chosen: films whose language or year the catalogue
  // does not know match none of the filters above, and the deck must never come out empty.
  { id: "any", languages: [] },
];

/**
 * The requests to make for this profile, in the order their films should appear.
 * - A visitor who chose languages only gets specs in those languages (never an empty deck: if the
 *   choice leaves nothing, the whole base list is used).
 * - Favourite genres come first, each as its own spec in the visitor's languages.
 */
export function deckSpecs(p) {
  const chosen = p.languages?.length ? p.languages : null;
  const allowed = (spec) => (spec.languages.length === 0 ? !chosen : !chosen || spec.languages.every((l) => chosen.includes(l)));
  const languages = chosen ?? EN;
  const favourites = (p.favouriteGenres ?? []).map((genre) => ({ id: `fav-${genre}`, languages, genres: [genre] }));
  let rest = BASE.filter(allowed);
  if (!rest.length) rest = BASE;
  const seen = new Set();
  return [...favourites, ...rest].filter((spec) => (seen.has(spec.id) ? false : (seen.add(spec.id), true)));
}

/**
 * One film from each answer in turn, until `size` films or nothing is left. `answers` is an array
 * of /discover item arrays in spec order; films in `skip` (already answered) and repeats are dropped.
 */
export function mergeDeck(answers, skip = [], size = DECK_SIZE) {
  const taken = new Set(skip);
  const queues = answers.map((items) => [...items]);
  const deck = [];
  while (deck.length < size && queues.some((q) => q.length)) {
    for (const queue of queues) {
      while (queue.length) {
        const item = queue.shift();
        if (!taken.has(item.movie.movie_id)) {
          taken.add(item.movie.movie_id);
          deck.push(item);
          break;
        }
      }
      if (deck.length >= size) break;
    }
  }
  return deck;
}
