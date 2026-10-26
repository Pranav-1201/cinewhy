// Tests for web/js/deck.js (which films "Rate films" asks about), run by Node's built-in test runner.
// tests/test_web_logic.py runs this file as part of the normal pytest run.
import assert from "node:assert/strict";
import { test } from "node:test";

import { DECK_SIZE, deckSpecs, mergeDeck } from "../../web/js/deck.js";

const item = (n) => ({ movie: { movie_id: `cw-${n}`, title: `Film ${n}` } });
const ids = (deck) => deck.map((i) => i.movie.movie_id);
const profile = (extra = {}) => ({ languages: [], favouriteGenres: [], ...extra });

test("with nothing chosen the deck spans English and Hindi, eras and genres", () => {
  const specs = deckSpecs(profile());
  const languages = new Set(specs.flatMap((s) => s.languages));
  assert.deepEqual([...languages].sort(), ["en", "hi"]);
  assert.ok(specs.some((s) => s.to_year), "an older-film spec");
  assert.ok(specs.some((s) => s.from_year), "a newer-film spec");
  assert.ok(new Set(specs.flatMap((s) => s.genres ?? [])).size >= 6, "at least six genres");
  assert.equal(new Set(specs.map((s) => s.id)).size, specs.length, "spec ids are unique");
});

test("a visitor who chose only English is never asked about Hindi films", () => {
  const specs = deckSpecs(profile({ languages: ["en"] }));
  assert.ok(specs.length >= 8);
  assert.ok(specs.every((s) => s.languages.every((l) => l === "en")));
});

test("a visitor who chose only Hindi gets Hindi specs, not an empty deck", () => {
  const specs = deckSpecs(profile({ languages: ["hi"] }));
  assert.ok(specs.length >= 1);
  assert.ok(specs.every((s) => s.languages.every((l) => l === "hi")));
});

test("a language choice that matches nothing falls back to the full list", () => {
  assert.ok(deckSpecs(profile({ languages: ["fr"] })).length >= 10);
});

test("favourite genres come first, in the visitor's language", () => {
  const specs = deckSpecs(profile({ languages: ["hi"], favouriteGenres: ["Romance", "Drama"] }));
  assert.deepEqual(specs.slice(0, 2).map((s) => s.genres[0]), ["Romance", "Drama"]);
  assert.ok(specs.slice(0, 2).every((s) => s.languages[0] === "hi"));
});

test("with no language chosen the deck ends with an any-film fallback, so it is never empty", () => {
  const specs = deckSpecs(profile());
  assert.equal(specs.at(-1).id, "any");
  assert.deepEqual(specs.at(-1).languages, []);
});

test("once a language is chosen the any-film fallback is not used", () => {
  for (const languages of [["en"], ["hi"], ["en", "hi"]]) {
    assert.equal(deckSpecs(profile({ languages })).some((s) => s.id === "any"), false, languages.join());
  }
});

test("a favourite genre is not asked for twice", () => {
  const specs = deckSpecs(profile({ favouriteGenres: ["Comedy", "Comedy"] }));
  assert.equal(specs.filter((s) => s.id === "fav-Comedy").length, 1);
});

test("mergeDeck takes one film from each answer in turn", () => {
  const answers = [[item(1), item(2), item(3)], [item(4), item(5)], [item(6)]];
  assert.deepEqual(ids(mergeDeck(answers, [], 6)), ["cw-1", "cw-4", "cw-6", "cw-2", "cw-5", "cw-3"]);
});

test("mergeDeck drops repeats and films already answered", () => {
  const answers = [[item(1), item(2)], [item(1), item(3)], [item(2), item(4)]];
  assert.deepEqual(ids(mergeDeck(answers, ["cw-3"], 10)), ["cw-1", "cw-2", "cw-4"]);
});

test("mergeDeck stops at the requested size, and defaults to the deck size", () => {
  const long = Array.from({ length: 40 }, (_, n) => item(n));
  assert.equal(mergeDeck([long], [], 5).length, 5);
  assert.equal(mergeDeck([long]).length, DECK_SIZE);
});

test("mergeDeck copes with empty answers", () => {
  assert.deepEqual(mergeDeck([]), []);
  assert.deepEqual(ids(mergeDeck([[], [item(1)], []])), ["cw-1"]);
});
