// Tests for web/js/swipecore.js (swipe directions, the card queue, the rules text, result wording),
// run by Node's built-in test runner. tests/test_web_logic.py runs this file with the others.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ACTIONS, DIRECTION_OF, LABELS, RULES, THRESHOLD, add, advance, current, decide, genreOptions, heldIds,
  hint, isStale, keyAction, makeDeck, needsConfirm, needsMore, quizBody, reaction, remaining, upcoming,
} from "../../web/js/swipecore.js";

const card = (id) => ({ movie: { movie_id: id, title: id } });

test("the four directions are the four answers the owner chose", () => {
  assert.deepEqual(ACTIONS, { right: "want", left: "pass", up: "seen", down: "top" });
  assert.equal(DIRECTION_OF.top, "down");
  assert.deepEqual(Object.keys(LABELS).sort(), ["pass", "seen", "top", "want"]);
});

test("a long enough drag is the direction it mostly points, and a short one is nothing", () => {
  assert.equal(decide(THRESHOLD + 1, 5), "right");
  assert.equal(decide(-(THRESHOLD + 1), 5), "left");
  assert.equal(decide(5, -(THRESHOLD + 1)), "up");
  assert.equal(decide(5, THRESHOLD + 1), "down");
  assert.equal(decide(THRESHOLD - 1, 0), null);
  assert.equal(decide(0, 0), null);
});

test("a diagonal drag goes to the axis it travelled furthest on", () => {
  assert.equal(decide(120, 100), "right");
  assert.equal(decide(100, 120), "down");
  assert.equal(decide(-100, -100), "left"); // a tie goes to the sideways answers
});

test("while dragging the lean and its strength grow towards the threshold and stop at 1", () => {
  assert.equal(hint(3, 3), null);
  assert.deepEqual(hint(THRESHOLD / 2, 0), { direction: "right", action: "want", strength: 0.5 });
  assert.equal(hint(0, -THRESHOLD * 3).strength, 1);
  assert.equal(hint(0, -40).action, "seen");
});

test("arrow keys mean the same answers as the swipes", () => {
  assert.equal(keyAction("ArrowRight"), "want");
  assert.equal(keyAction("ArrowLeft"), "pass");
  assert.equal(keyAction("ArrowUp"), "seen");
  assert.equal(keyAction("ArrowDown"), "top");
  assert.equal(keyAction("Enter"), null);
});

test("the deck deals each title once, in order, and says what is left", () => {
  const deck = makeDeck();
  assert.equal(add(deck, [card("a"), card("b"), card("c")]), 3);
  assert.equal(add(deck, [card("b"), card("d")]), 1); // b is already held
  assert.equal(current(deck).movie.movie_id, "a");
  assert.deepEqual(upcoming(deck).map((c) => c.movie.movie_id), ["b", "c"]);
  advance(deck);
  assert.equal(current(deck).movie.movie_id, "b");
  assert.equal(remaining(deck), 3);
  for (let i = 0; i < 10; i += 1) advance(deck);
  assert.equal(current(deck), null);
  assert.equal(remaining(deck), 0);
});

test("the deck asks for more when low, unless the server said it has no more", () => {
  const deck = makeDeck();
  add(deck, Array.from({ length: 8 }, (_, i) => card(`m${i}`)));
  assert.equal(needsMore(deck, 6), false);
  advance(deck); advance(deck);
  assert.equal(needsMore(deck, 6), true);
  deck.exhausted = true;
  assert.equal(needsMore(deck, 6), false);
});

test("the ids sent to the server are the newest ones, capped", () => {
  const deck = makeDeck();
  add(deck, Array.from({ length: 700 }, (_, i) => card(`m${i}`)));
  const ids = heldIds(deck, 600);
  assert.equal(ids.length, 600);
  assert.equal(ids.at(-1), "m699");
});

test("changing a top pick needs a confirmation, choosing the first or the same one does not", () => {
  assert.equal(needsConfirm(null, "a"), false);
  assert.equal(needsConfirm("a", "a"), false);
  assert.equal(needsConfirm("a", "b"), true);
});

test("the quiz offers the common genres without 'N/A', and sends only offered values once", () => {
  const options = genreOptions({ Drama: 9, Comedy: 5, "N/A": 5, Action: 4 }, 2);
  assert.deepEqual(options, [["Drama", "Drama"], ["Comedy", "Comedy"]]);
  const body = quizBody(["film", "film", "play"], ["hi", "xx", "hi"], ["Drama", "Drama", "Comedy"]);
  assert.deepEqual(body, { kinds: ["film"], languages: ["hi"], genres: ["Drama", "Comedy"] });
  assert.deepEqual(quizBody([], [], []), { kinds: [], languages: [], genres: [] });
});

test("the rules tell people everything before they begin", () => {
  const text = JSON.stringify(RULES).toLowerCase();
  for (const word of ["right", "left", "up", "down", "top pick", "refresh", "quiz", "group's picks"]) {
    assert.ok(text.includes(word), word);
  }
  assert.equal(RULES.swipes.length, 4);
  assert.match(RULES.topPick, /only one/);
  assert.match(RULES.topPick, /confirm/);
  assert.match(RULES.privacy.join(" "), /nothing changes in your own profile/i);
  assert.match(RULES.privacy.join(" "), /not a like/);
  assert.match(RULES.privacy.join(" "), /three hours/);
});

test("a results list is stale once the room has more answers than it was made with", () => {
  assert.equal(isStale(null, 5), false); // no list yet
  assert.equal(isStale(5, 5), false);
  assert.equal(isStale(5, 9), true);
});

test("what a member said comes first in a result chip, then how well it fits", () => {
  const fit = (extra) => ({ name: "Ann", percentile: 0.876, saw_it: false, disliked: false, wants: false, top: false, ...extra });
  assert.deepEqual(reaction(fit({ top: true, wants: true })), { tone: "top", text: "Ann: top pick" });
  assert.deepEqual(reaction(fit({ disliked: true, saw_it: true })), { tone: "warn", text: "Ann: said no" });
  assert.deepEqual(reaction(fit({ saw_it: true })), { tone: "warn", text: "Ann: has seen it" });
  assert.deepEqual(reaction(fit({ wants: true })), { tone: "good", text: "Ann: wants it" });
  assert.deepEqual(reaction(fit({})), { tone: "plain", text: "Ann: 88% fit" });
});
