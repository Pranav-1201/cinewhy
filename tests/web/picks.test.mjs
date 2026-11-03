// Tests for web/js/picks.js, run by Node's built-in test runner (no dependency).
// tests/test_web_logic.py runs this file as part of the normal pytest run.
import assert from "node:assert/strict";
import { test } from "node:test";

import { append, canGoBack, currentId, hasNext, load, makeQueue, next, previous, upcoming } from "../../web/js/picks.js";

const queueOf = (...ids) => load(makeQueue(), ids);

test("a new list opens on its top title, and that title counts as shown", () => {
  const q = queueOf("a", "b", "c");
  assert.equal(currentId(q), "a");
  assert.deepEqual(q.seen, ["a"]);
  assert.deepEqual(upcoming(q), ["b", "c"]);
  assert.equal(canGoBack(q), false);
});

test("an empty list has no current title and nothing to step to", () => {
  const q = queueOf();
  assert.equal(currentId(q), null);
  assert.equal(hasNext(q), false);
  assert.equal(next(q), "more");
});

test("next walks down the ranking, and previous walks back", () => {
  const q = queueOf("a", "b", "c");
  assert.equal(next(q), "moved");
  assert.equal(currentId(q), "b");
  assert.equal(canGoBack(q), true);
  assert.deepEqual(upcoming(q), ["c"]);
  assert.equal(previous(q), true);
  assert.equal(currentId(q), "a");
  assert.equal(previous(q), false); // already at the top
});

test("when the ranking runs out it asks for more, and more titles continue the walk", () => {
  const q = queueOf("a", "b");
  next(q);
  assert.equal(next(q), "more");
  assert.equal(currentId(q), "b"); // it did not move
  assert.equal(append(q, ["c", "d"]), 2);
  assert.equal(next(q), "moved");
  assert.equal(currentId(q), "c");
});

test("more titles from the server never repeat one already in the queue or already shown", () => {
  const q = queueOf("a", "b", "c");
  next(q); // b shown
  assert.equal(append(q, ["a", "b", "c", "d", "d"]), 1); // only d is new
  assert.deepEqual(q.ids, ["a", "b", "c", "d"]);
  // A title that was shown and has since left the list is not brought back either.
  const r = queueOf("x", "y");
  next(r);
  load(r, ["y", "z"]); // x is gone from the new ranking
  assert.equal(append(r, ["x", "w"]), 1);
  assert.deepEqual(r.ids, ["y", "z", "w"]);
});

test("a redraw keeps the title on show when it is still ranked, so a click does not jerk the page", () => {
  const q = queueOf("a", "b", "c");
  next(q); // on b
  load(q, ["c", "b", "a"]); // the ranking changed order
  assert.equal(currentId(q), "b");
  assert.deepEqual(upcoming(q), ["a"]);
});

test("a redraw moves on to the first unseen title when the one on show has left the ranking", () => {
  const q = queueOf("a", "b", "c");
  // The visitor liked "a", which leaves the picks: the page should go to the next best, not repeat.
  load(q, ["b", "c", "d"]);
  assert.equal(currentId(q), "b");
  next(q); // c
  load(q, ["d", "e"]); // c left as well; b and c were shown, d was not
  assert.equal(currentId(q), "d");
});

test("when everything in a new ranking has already been shown it goes back to the top", () => {
  const q = queueOf("a", "b", "c");
  next(q);
  next(q); // on c; a, b and c have all been shown
  load(q, ["a", "b"]); // c has left, and nothing in the new ranking is unseen
  assert.equal(currentId(q), "a");
});

test("the list of shown titles is capped so a long session cannot grow it without end", () => {
  const q = queueOf(...Array.from({ length: 700 }, (_, i) => `t${i}`));
  while (hasNext(q)) next(q);
  assert.equal(q.seen.length, 500);
  assert.equal(q.seen.at(-1), "t699");
});

test("duplicate ids in a ranking are listed once", () => {
  const q = queueOf("a", "a", "b");
  assert.deepEqual(q.ids, ["a", "b"]);
});
