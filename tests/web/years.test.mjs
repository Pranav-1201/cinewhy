// Tests for web/js/years.js (the year range a visitor chooses), run by Node's built-in test runner.
// tests/test_web_logic.py runs this file as part of the normal pytest run.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  NEW_FROM,
  OLD_SCHOOL_TO,
  activePreset,
  describeYears,
  normaliseYears,
  presetYears,
  requestYears,
} from "../../web/js/years.js";

const OLDEST = 1950;
const NEWEST = 2025;
const norm = (a, b) => normaliseYears(a, b, OLDEST, NEWEST);
const req = (a, b) => requestYears(a, b, OLDEST, NEWEST);
const label = (a, b) => describeYears(a, b, OLDEST, NEWEST);
const preset = (a, b) => activePreset(a, b, OLDEST, NEWEST);

test("the presets are the ones that were asked for", () => {
  assert.equal(OLD_SCHOOL_TO, 1989);
  assert.equal(NEW_FROM, 2021);
});

test("no choice, or a choice that covers the whole catalogue, is no limit at all", () => {
  assert.deepEqual(norm(null, null), { from: null, to: null });
  assert.deepEqual(norm(OLDEST, NEWEST), { from: null, to: null });
  assert.deepEqual(req(null, null), {});
  assert.deepEqual(req(OLDEST, NEWEST), {});
  assert.equal(label(null, null), "Any year");
  assert.equal(label(OLDEST, NEWEST), "Any year");
});

test("a request carries only the ends that narrow the range", () => {
  assert.deepEqual(req(1990, null), { from_year: 1990 });
  assert.deepEqual(req(null, 2010), { to_year: 2010 });
  assert.deepEqual(req(1990, 2010), { from_year: 1990, to_year: 2010 });
  assert.deepEqual(req(1990, NEWEST), { from_year: 1990 });
  assert.deepEqual(req(OLDEST, 2010), { to_year: 2010 });
});

test("years outside the catalogue are pulled inside it, and from never passes to", () => {
  assert.deepEqual(norm(1700, 2010), { from: null, to: 2010 });
  assert.deepEqual(norm(1990, 2500), { from: 1990, to: null });
  assert.deepEqual(norm(2010, 1990), { from: 1990, to: 2010 });
});

test("anything that is not a whole year is ignored", () => {
  for (const bad of ["1990", 1990.5, NaN, undefined, {}, []]) {
    assert.deepEqual(norm(bad, bad), { from: null, to: null }, String(bad));
  }
});

test("the presets are recognised, and only exactly", () => {
  assert.equal(preset(null, 1989), "old");
  assert.equal(preset(OLDEST, 1989), "old");
  assert.equal(preset(2021, null), "new");
  assert.equal(preset(2021, NEWEST), "new");
  assert.equal(preset(null, 1990), null);
  assert.equal(preset(2020, null), null);
  assert.equal(preset(2021, 2023), null);
  assert.equal(preset(null, null), null);
});

test("choosing a preset stores its years, and they are recognised again", () => {
  const old = presetYears("old");
  const fresh = presetYears("new");
  assert.deepEqual(req(old.from, old.to), { to_year: 1989 });
  assert.deepEqual(req(fresh.from, fresh.to), { from_year: 2021 });
  assert.equal(preset(old.from, old.to), "old");
  assert.equal(preset(fresh.from, fresh.to), "new");
});

test("the range is described in words", () => {
  assert.equal(label(null, 1989), "Before 1990");
  assert.equal(label(null, 1999), "Up to 1999");
  assert.equal(label(2021, null), "2021 onward");
  assert.equal(label(1990, 2010), "1990 to 2010");
  assert.equal(label(2001, 2001), "2001");
});
