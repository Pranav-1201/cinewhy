// Tests for web/js/where.js, run by Node's built-in test runner (no dependency).
// tests/test_web_logic.py runs this file as part of the normal pytest run.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  NOT_ON_SIX,
  PLATFORM_NAMES,
  countriesOf,
  notInCountry,
  offersIn,
  watchFooter,
  watchSummary,
  withCountry,
} from "../../web/js/where.js";

const WHERE = {
  fetched: "2026-11-03",
  tmdb_url: "https://www.themoviedb.org/movie/603/watch",
  platforms: [
    { platform: "netflix", ways: { stream: ["GB", "US"], rent: ["US"] } },
    { platform: "hbo", ways: { stream: ["IN"] } },
  ],
};

test("the six platforms carry the names people use", () => {
  assert.deepEqual(Object.values(PLATFORM_NAMES), [
    "Netflix", "Apple TV", "Amazon Prime Video", "Disney+ Hotstar", "Crunchyroll", "HBO Max",
  ]);
});

test("countriesOf lists every country on any platform once, sorted", () => {
  assert.deepEqual(countriesOf(WHERE), ["GB", "IN", "US"]);
  assert.deepEqual(countriesOf({ platforms: [] }), []);
  assert.deepEqual(countriesOf(null), []);
});

test("watchSummary says in one sentence where a title can be watched in the visitor's country", () => {
  assert.equal(watchSummary(WHERE, "US", "the United States"), "Where to watch in the United States: Netflix (Stream, Rent).");
  assert.equal(watchSummary(WHERE, "IN", "India"), "Where to watch in India: HBO Max (Stream).");
  assert.equal(watchSummary(WHERE, "FR", "France"), "Not on our six streaming services in France.");
  assert.equal(watchSummary(null, "IN", "India"), ""); // a build with no availability data says nothing
  assert.equal(watchSummary(WHERE, "GB"), "Where to watch in GB: Netflix (Stream)."); // label defaults to the code
});

test("offersIn gives one country's platforms in the server's order, with the ways in plain words", () => {
  assert.deepEqual(offersIn(WHERE, "US"), [{ platform: "Netflix", ways: ["Stream", "Rent"] }]);
  assert.deepEqual(offersIn(WHERE, "IN"), [{ platform: "HBO Max", ways: ["Stream"] }]);
  assert.deepEqual(offersIn(WHERE, "FR"), []);
  assert.deepEqual(offersIn(undefined, "US"), []);
});

test("an unknown platform or way is shown as sent, never dropped or renamed", () => {
  const odd = { platforms: [{ platform: "newco", ways: { barter: ["US"] } }] };
  assert.deepEqual(offersIn(odd, "US"), [{ platform: "newco", ways: ["barter"] }]);
});

test("withCountry keeps the visitor's own country in the picker even when the title is not offered there", () => {
  assert.deepEqual(withCountry(["GB", "US"], "US"), ["GB", "US"]); // already there: unchanged
  assert.deepEqual(withCountry(["GB", "US"], "IN"), ["GB", "IN", "US"]); // added, in order
  assert.deepEqual(withCountry([], "IN"), ["IN"]);
});

test("the not-offered line names the country and tells the visitor what to do", () => {
  const line = notInCountry("India");
  assert.match(line, /in India\./);
  assert.match(line, /Choose another country/);
  for (const name of Object.values(PLATFORM_NAMES)) assert.ok(line.includes(name), name);
});

test("the footer always states the date and credits the source", () => {
  assert.match(watchFooter("2026-11-03"), /^As of 2026-11-03\./);
  assert.match(watchFooter("2026-11-03"), /TMDB, powered by JustWatch/);
  assert.match(watchFooter(undefined), /powered by JustWatch/);
  assert.doesNotMatch(watchFooter(undefined), /As of/);
});

test("the none-of-the-six line names all six platforms", () => {
  for (const name of Object.values(PLATFORM_NAMES)) assert.ok(NOT_ON_SIX.includes(name), name);
});
