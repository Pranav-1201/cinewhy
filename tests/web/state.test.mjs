// Tests for the parts of web/js/state.js that need no browser, run by Node's built-in test runner.
// tests/test_web_logic.py runs this file as part of the normal pytest run. Storage is absent in
// Node, which state.js tolerates by design (a blocked localStorage must never break the page).
import assert from "node:assert/strict";
import { test } from "node:test";

import { replaceProfile, resetTaste, setCountry, state } from "../../web/js/state.js";
import { defaultProfile } from "../../web/js/profile.js";

test("the country is India until the visitor picks another, and the pick lands in the shared state", () => {
  replaceProfile(defaultProfile());
  assert.equal(state.country, "IN");
  setCountry("US");
  assert.equal(state.country, "US");
  setCountry("nonsense");
  assert.equal(state.country, "US"); // an invalid pick changes nothing
});

test("resetting what you like does not move where-to-watch: the country is a setting, not a taste", () => {
  replaceProfile({ ...defaultProfile(), liked: ["cw-1"], country: "CA", onboarded: true });
  resetTaste();
  assert.deepEqual(state.liked, []); // the taste is gone
  assert.equal(state.country, "CA"); // the country stays
  assert.equal(state.onboarded, true);
});

test("a reset of a profile that never chose a country leaves it in India", () => {
  replaceProfile(defaultProfile());
  resetTaste();
  assert.equal(state.country, "IN");
});
