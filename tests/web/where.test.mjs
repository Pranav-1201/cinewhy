// Tests for web/js/where.js, run by Node's built-in test runner (no dependency).
// tests/test_web_logic.py runs this file as part of the normal pytest run.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  NOT_ON_SIX,
  PLATFORM_NAMES,
  countriesOf,
  offersIn,
  pickCountry,
  regionOf,
  watchFooter,
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

test("regionOf reads the country out of a language tag", () => {
  assert.equal(regionOf("en-IN"), "IN");
  assert.equal(regionOf("hi_in"), "IN");
  assert.equal(regionOf("fr-CA"), "CA");
  assert.equal(regionOf("en"), null);
  assert.equal(regionOf(""), null);
  assert.equal(regionOf(undefined), null);
});

test("pickCountry prefers the visitor's choice, then their region, and only a country on offer", () => {
  const countries = ["GB", "IN", "US"];
  assert.equal(pickCountry(countries, "US", "IN"), "US");
  assert.equal(pickCountry(countries, "FR", "IN"), "IN"); // the chosen country is not on offer here
  assert.equal(pickCountry(countries, null, "ZZ"), "GB"); // nothing preferred is on offer
  assert.equal(pickCountry(countries), "GB");
  assert.equal(pickCountry([], "US"), null);
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
