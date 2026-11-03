/* Watch together, swipe cards: the rules that need no browser. Which way a drag counts as, how the
   queue of cards works, what the rules screen says, and how a result line is worded. No DOM, no
   network, so Node tests every rule here (tests/web/swipecore.test.mjs). cards.js draws and
   together.js talks to the server using these.

   The four swipes (owner, 2026-11-04): right = want to watch, left = not for me, up = already
   watched, down = my one top pick. Everything a person answers lives in the room only. */

export const ACTIONS = { right: "want", left: "pass", up: "seen", down: "top" };
export const DIRECTION_OF = Object.fromEntries(Object.entries(ACTIONS).map(([d, a]) => [a, d]));
export const LABELS = {
  want: "Want to watch",
  pass: "Not for me",
  seen: "Already watched",
  top: "My top pick",
};
export const THRESHOLD = 90; // pixels of drag that count as a swipe
const KEYS = { ArrowRight: "want", ArrowLeft: "pass", ArrowUp: "seen", ArrowDown: "top" };

/** Which direction a finished drag of (dx, dy) pixels is, or null when it was too short to count. */
export function decide(dx, dy, threshold = THRESHOLD) {
  const ax = Math.abs(dx);
  const ay = Math.abs(dy);
  if (Math.max(ax, ay) < threshold) return null;
  if (ax >= ay) return dx > 0 ? "right" : "left";
  return dy > 0 ? "down" : "up";
}

/** While dragging: the leaning direction and how far towards a swipe it is (0 to 1), for the labels. */
export function hint(dx, dy, threshold = THRESHOLD) {
  const ax = Math.abs(dx);
  const ay = Math.abs(dy);
  const reach = Math.max(ax, ay);
  if (reach < 8) return null; // a tap or a tremble is not a lean
  const direction = ax >= ay ? (dx > 0 ? "right" : "left") : dy > 0 ? "down" : "up";
  return { direction, action: ACTIONS[direction], strength: Math.min(1, reach / threshold) };
}

/** The answer an arrow key stands for, or null for any other key. */
export const keyAction = (key) => KEYS[key] ?? null;

// --- the queue of cards ------------------------------------------------------------------------

export const makeDeck = () => ({ cards: [], index: 0, held: new Set(), exhausted: false });
export const current = (deck) => deck.cards[deck.index] ?? null;
export const upcoming = (deck, n = 2) => deck.cards.slice(deck.index + 1, deck.index + 1 + n);
export const remaining = (deck) => deck.cards.length - deck.index;

/** Add cards the page does not hold yet (a title is never dealt twice); returns how many were new. */
export function add(deck, cards) {
  let added = 0;
  for (const card of cards) {
    const id = card.movie.movie_id;
    if (deck.held.has(id)) continue;
    deck.held.add(id);
    deck.cards.push(card);
    added += 1;
  }
  return added;
}

export function advance(deck) {
  if (deck.index < deck.cards.length) deck.index += 1;
}

/** True when the deck is running low and the server may still have more. */
export const needsMore = (deck, low = 6) => !deck.exhausted && remaining(deck) <= low;

/** The ids to tell the server this page already holds (it never deals them again), newest last. */
export const heldIds = (deck, cap = 600) => [...deck.held].slice(-cap);

/** Naming a different top pick while one is set must be confirmed first. */
export const needsConfirm = (currentTop, movieId) => Boolean(currentTop) && currentTop !== movieId;

// --- the quiz ------------------------------------------------------------------------------------

export const KIND_OPTIONS = [["film", "Films"], ["series", "Series"]];
export const LANGUAGE_OPTIONS = [["en", "English"], ["hi", "Hindi"], ["ja", "Japanese"], ["fr", "French"]];

/** The most common genres to offer, from the server's genre counts (most titles first). */
export function genreOptions(counts, n = 12) {
  return Object.keys(counts ?? {}).filter((g) => g !== "N/A").slice(0, n).map((g) => [g, g]);
}

/** The quiz request: each list holds only values the page offered, once each. */
export function quizBody(kinds, languages, genres) {
  const once = (list, allowed) => [...new Set(list)].filter((v) => allowed.includes(v));
  return {
    kinds: once(kinds, KIND_OPTIONS.map(([v]) => v)),
    languages: once(languages, LANGUAGE_OPTIONS.map(([v]) => v)),
    genres: [...new Set(genres)].slice(0, 10),
  };
}

// --- what people are told before they begin ----------------------------------------------------------

export const RULES = {
  title: "How Watch together works",
  steps: [
    "Answer a quick mood quiz: what you feel like watching tonight.",
    "Swipe through cards for titles the whole group could enjoy. Keep going as long as you like: every answer narrows what the group is offered.",
    "Open the group's picks at any time to see the best titles so far, then the next-closest ones.",
  ],
  swipes: [
    { direction: "right", action: "want", label: "Right: I want to watch this" },
    { direction: "left", action: "pass", label: "Left: not for me" },
    { direction: "up", action: "seen", label: "Up: I have already watched it" },
    { direction: "down", action: "top", label: "Down: my top pick" },
  ],
  topPick:
    "You can have only one top pick: the one title you most want to watch right now. It counts for much more than a normal right swipe. If you swipe down on a different title later, you are asked to confirm the change. The old top pick still counts a little more than a normal right swipe.",
  results:
    "The group's picks list does not change by itself while people swipe. Press Refresh to bring it up to date. Anyone can open it at any time and sees who wanted, passed on or has seen each title.",
  privacy: [
    "Everything you answer here stays in this room. Nothing changes in your own profile or library: a right swipe is not a like, and an up swipe does not mark the title as watched in your library.",
    "The people in the room see your answers on the group's picks list only. Your answers are deleted when you leave, when the host closes the room, or when it has been idle for three hours.",
  ],
  mouse: "On a computer you can drag a card, press the buttons under it, or use the arrow keys. On a phone, swipe.",
};

// --- the results screen --------------------------------------------------------------------------------

/** A list made at one activity count is out of date once the room has more answers. */
export const isStale = (listActivity, roomActivity) => listActivity !== null && roomActivity > listActivity;

/** How one member stands on a title, for a chip. What they said comes before how well it fits. */
export function reaction(fit) {
  if (fit.top) return { tone: "top", text: `${fit.name}: top pick` };
  if (fit.disliked) return { tone: "warn", text: `${fit.name}: said no` };
  if (fit.saw_it) return { tone: "warn", text: `${fit.name}: has seen it` };
  if (fit.wants) return { tone: "good", text: `${fit.name}: wants it` };
  return { tone: "plain", text: `${fit.name}: ${Math.round(fit.percentile * 100)}% fit` };
}
