// Tests for web/js/more.js (what "Show more" on a row asks for), run by Node's built-in test runner.
// tests/test_web_logic.py runs this file as part of the normal pytest run.
import assert from "node:assert/strict";
import { test } from "node:test";

import { EXCLUDE_CAP, MORE_LIMIT, freshItems, moreRequest } from "../../web/js/more.js";

const item = (id) => ({ movie: { movie_id: id, title: id } });
const base = {
  recency: 0.5,
  profile: { liked_movie_ids: ["cw-9"] },
  languages: ["hi"],
  exclude_movie_ids: ["cw-w1", "cw-w2"],
};

test("the request asks for one row, a page's worth, with the visitor's filters and taste unchanged", () => {
  const request = moreRequest(base, "lang-hi", new Set(["cw-1"]));
  assert.equal(request.only, "lang-hi");
  assert.equal(request.limit, MORE_LIMIT);
  assert.deepEqual(request.profile, base.profile);
  assert.deepEqual(request.languages, ["hi"]);
  assert.equal(request.recency, 0.5);
});

test("everything on screen and everything watched is left out, each id once", () => {
  const request = moreRequest(base, "new", new Set(["cw-1", "cw-w1", "cw-2"]));
  assert.deepEqual([...request.exclude_movie_ids].sort(), ["cw-1", "cw-2", "cw-w1", "cw-w2"]);
});

test("a visitor with nothing watched still gets a valid request", () => {
  const { exclude_movie_ids: _gone, ...bare } = base;
  assert.deepEqual(moreRequest(bare, "new", new Set(["cw-1"])).exclude_movie_ids, ["cw-1"]);
});

test("past the server's cap it is the watched list that is cut, never a title on screen", () => {
  const shown = new Set(Array.from({ length: 40 }, (_, i) => `on-${i}`));
  const watched = Array.from({ length: EXCLUDE_CAP + 50 }, (_, i) => `w-${i}`);
  const ids = moreRequest({ ...base, exclude_movie_ids: watched }, "new", shown).exclude_movie_ids;
  assert.equal(ids.length, EXCLUDE_CAP);
  for (const id of shown) assert.ok(ids.includes(id), id);
});

test("the request does not change what it was given", () => {
  const shown = new Set(["cw-1"]);
  const copy = structuredClone(base);
  moreRequest(base, "new", shown);
  assert.deepEqual(base, copy);
  assert.deepEqual([...shown], ["cw-1"]);
});

test("only the row asked about is read, and a title already on the page is not added again", () => {
  const response = {
    shelves: [
      { id: "new", items: [item("cw-1"), item("cw-2")] },
      { id: "classics", items: [item("cw-3")] },
    ],
  };
  assert.deepEqual(freshItems(response, "new", new Set(["cw-1"])).map((i) => i.movie.movie_id), ["cw-2"]);
  assert.deepEqual(freshItems(response, "classics", new Set()).map((i) => i.movie.movie_id), ["cw-3"]);
});

test("a row with nothing left, a missing row or an empty answer all mean no more", () => {
  assert.deepEqual(freshItems({ shelves: [] }, "new", new Set()), []);
  assert.deepEqual(freshItems({ shelves: [{ id: "new", items: [] }] }, "new", new Set()), []);
  assert.deepEqual(freshItems({ shelves: [{ id: "other", items: [item("cw-1")] }] }, "new", new Set()), []);
  assert.deepEqual(freshItems(null, "new", new Set()), []);
});
