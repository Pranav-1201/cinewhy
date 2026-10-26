// Tests for web/js/format.js, run by Node's built-in test runner (no dependency).
// tests/test_web_logic.py runs this file as part of the normal pytest run.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  clamp,
  eraRange,
  hueOf,
  languageName,
  pct,
  recencyForAge,
  reviewsLine,
  runtimeLabel,
  signed,
  sourceOf,
  wilson,
} from "../../web/js/format.js";

test("wilson matches the textbook interval and stays inside 0..1", () => {
  const [lo, hi] = wilson(50, 100);
  assert.ok(Math.abs(lo - 0.4038) < 0.0005, String(lo));
  assert.ok(Math.abs(hi - 0.5962) < 0.0005, String(hi));
  const [l0, h0] = wilson(0, 20);
  assert.equal(l0, 0);
  assert.ok(h0 > 0.1 && h0 < 0.2, String(h0));
  const [l1, h1] = wilson(20, 20);
  assert.equal(h1, 1);
  assert.ok(l1 > 0.8 && l1 < 0.9, String(l1));
  assert.deepEqual(wilson(0, 0), [0, 1]);
});

test("signed always shows a sign and uses a true minus", () => {
  assert.equal(signed(0.734), "+0.73");
  assert.equal(signed(0), "+0.00");
  assert.equal(signed(-0.5), "−0.50");
});

test("pct formats a fraction", () => {
  assert.equal(pct(0.1234, 1), "12.3%");
  assert.equal(pct(0.5, 0), "50%");
});

test("a review is credited to the site its id says, never to a hard-coded one", () => {
  assert.deepEqual(sourceOf("rt/a1/u1-2020-01-01"), { key: "rt", label: "Rotten Tomatoes" });
  assert.deepEqual(sourceOf("ebd/rw1133942"), { key: "ebd", label: "IMDb" });
  assert.deepEqual(sourceOf("acl/train/pos/12"), { key: "acl", label: "IMDb" });
  assert.equal(sourceOf("something/else").label, "A review");
  assert.equal(sourceOf("").label, "A review");
});

test("hueOf is stable, in range, and spreads different ids apart", () => {
  assert.equal(hueOf("cw-0000100"), hueOf("cw-0000100"));
  const hues = new Set();
  for (let i = 0; i < 200; i++) {
    const h = hueOf(`cw-${i}`);
    assert.ok(Number.isInteger(h) && h >= 0 && h < 360);
    hues.add(h);
  }
  assert.ok(hues.size > 60, `only ${hues.size} distinct hues in 200 ids`);
});

test("age sets a default for how much to favour new films, and unknown is neutral", () => {
  assert.equal(recencyForAge("18-24"), 0.8);
  assert.equal(recencyForAge("under-18"), 0.8);
  assert.equal(recencyForAge("25-34"), 0.6);
  assert.equal(recencyForAge("35-44"), 0.4);
  assert.equal(recencyForAge("45+"), 0.25);
  assert.equal(recencyForAge(null), 0.5);
  assert.equal(recencyForAge(undefined), 0.5);
  assert.equal(recencyForAge("prefer-not"), 0.5);
});

test("era chips map to year windows", () => {
  assert.deepEqual(eraRange("new", 2025), { from_year: 2018 });
  assert.deepEqual(eraRange("2012", 2025), { from_year: 2012 });
  assert.deepEqual(eraRange("2000", 2025), { from_year: 2000 });
  assert.deepEqual(eraRange("any", 2025), {});
  assert.deepEqual(eraRange(undefined, 2025), {});
});

test("runtimeLabel", () => {
  assert.equal(runtimeLabel(161), "2h 41m");
  assert.equal(runtimeLabel(120), "2h");
  assert.equal(runtimeLabel(45), "45m");
  assert.equal(runtimeLabel(0), "");
  assert.equal(runtimeLabel(null), "");
  assert.equal(runtimeLabel(-5), "");
});

test("clamp cuts at a word boundary and only adds an ellipsis when it cut", () => {
  assert.equal(clamp("short text", 40), "short text");
  assert.equal(clamp("exactly ten", 11), "exactly ten");
  const cut = clamp("the quick brown fox jumps over the lazy dog", 20);
  assert.equal(cut, "the quick brown fox…");
  assert.equal(clamp("  padded  ", 20), "padded");
});

test("languageName", () => {
  assert.equal(languageName("en"), "English");
  assert.equal(languageName("hi"), "Hindi");
  assert.equal(languageName("fr"), "");
  assert.equal(languageName(null), "");
});

test("reviewsLine words the per-source counts plainly", () => {
  assert.equal(reviewsLine({ rt: 4, ebd: 6 }), "Read 4 from Rotten Tomatoes and 6 from IMDb");
  assert.equal(reviewsLine({ acl: 3, ebd: 2 }), "Read 5 from IMDb");
  assert.equal(reviewsLine({ rt: 1200 }), "Read 1,200 from Rotten Tomatoes");
  assert.equal(reviewsLine({}), "");
  assert.equal(reviewsLine(undefined), "");
});
