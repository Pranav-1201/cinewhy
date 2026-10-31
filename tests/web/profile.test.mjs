// Tests for web/js/profile.js, run by Node's built-in test runner (no dependency).
// tests/test_web_logic.py runs this file as part of the normal pytest run.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  LIST_CAP,
  PROFILE_VERSION,
  counts,
  defaultProfile,
  excludedIds,
  exportText,
  importText,
  isEmpty,
  isWanted,
  isWatched,
  migrate,
  opinionForStars,
  opinionOf,
  profileForApi,
  rate,
  setOpinion,
  setWant,
  setWatched,
} from "../../web/js/profile.js";

const film = (n, title = `Film ${n}`, year = 2000 + n) => ({ movie_id: `cw-${n}`, title, year });

test("a new profile is empty, versioned, and hides watched films", () => {
  const p = defaultProfile();
  assert.equal(p.version, PROFILE_VERSION);
  assert.equal(p.hideWatched, true);
  assert.deepEqual([p.liked, p.disliked, p.watched, p.want], [[], [], [], []]);
  assert.equal(isEmpty(p), true);
});

test("a version 2 profile (no version field) keeps everything it had", () => {
  const old = {
    liked: ["cw-1"], disliked: ["cw-2"], titles: { "cw-1": "A (2000)" }, weights: { pacing: 0.5 },
    languages: ["en"], genres: ["Drama"], era: "2012", recency: 0.4, recencyTouched: true,
    age: "18-24", region: "india", sex: null, hindiFirst: true, onboarded: true,
  };
  const p = migrate(old);
  assert.equal(p.version, 3);
  assert.deepEqual(p.liked, ["cw-1"]);
  assert.deepEqual(p.disliked, ["cw-2"]);
  assert.equal(p.titles["cw-1"], "A (2000)");
  assert.equal(p.weights.pacing, 0.5);
  assert.deepEqual([p.languages, p.genres, p.yearFrom, p.yearTo, p.recency], [["en"], ["Drama"], 2012, null, 0.4]);
  assert.deepEqual([p.age, p.region, p.hindiFirst, p.onboarded, p.recencyTouched], ["18-24", "india", true, true, true]);
  assert.deepEqual([p.watched, p.want], [[], []]);
  assert.equal(p.hideWatched, true);
});

test("garbage is never trusted: wrong types give a fresh profile", () => {
  for (const bad of [null, undefined, 7, "x", [], [1, 2]]) assert.deepEqual(migrate(bad), defaultProfile());
});

test("migrate drops malformed ids, duplicates and values outside their allowed set", () => {
  const p = migrate({
    liked: ["cw-1", "cw-1", "../etc", "has space", 5, "", "x".repeat(40), "cw-2"],
    languages: ["en", "de", 3], age: "ancient", region: "mars", sex: "robot", era: "1990",
    weights: { pacing: 2, plot: 0.5, acting: 0, ending: "high" }, recency: 9,
  });
  assert.deepEqual(p.liked, ["cw-1", "cw-2"]);
  assert.deepEqual(p.languages, ["en"]);
  assert.deepEqual([p.age, p.region, p.sex, p.yearFrom, p.yearTo, p.recency], [null, null, null, null, null, 0.5]);
  assert.deepEqual(p.weights, { plot: 0.5 });
});

test("migrate keeps the one-list rules: liked beats disliked, watched beats want", () => {
  const p = migrate({ liked: ["cw-1"], disliked: ["cw-1", "cw-2"], watched: ["cw-3"], want: ["cw-3", "cw-4"] });
  assert.deepEqual(p.disliked, ["cw-2"]);
  assert.deepEqual(p.want, ["cw-4"]);
});

test("migrate keeps a rating only for a watched film and only for whole stars 1 to 5", () => {
  const p = migrate({ watched: ["cw-1", "cw-2", "cw-3", "cw-4"], ratings: { "cw-1": 5, "cw-2": 6, "cw-3": 2.5, "cw-9": 4, "cw-4": "4" } });
  assert.deepEqual(p.ratings, { "cw-1": 5 });
});

test("titles are kept only for films the profile mentions and are length-capped", () => {
  const p = migrate({ liked: ["cw-1"], titles: { "cw-1": "T".repeat(500), "cw-9": "Other" } });
  assert.equal(p.titles["cw-1"].length, 200);
  assert.equal("cw-9" in p.titles, false);
});

test("the four old era choices each become a start year, and any becomes no limit", () => {
  assert.equal(migrate({ era: "new" }).yearFrom, 2021);
  assert.equal(migrate({ era: "2012" }).yearFrom, 2012);
  assert.equal(migrate({ era: "2000" }).yearFrom, 2000);
  assert.deepEqual([migrate({ era: "any" }).yearFrom, migrate({ era: "any" }).yearTo], [null, null]);
  assert.deepEqual([migrate({ era: "constructor" }).yearFrom, migrate({ era: 5 }).yearFrom], [null, null]);
});

test("a stored year range wins over an old era, bad years are dropped and a reversed pair is turned round", () => {
  assert.deepEqual(
    [migrate({ era: "2012", yearFrom: 1990, yearTo: 2005 }).yearFrom, migrate({ era: "2012", yearFrom: 1990, yearTo: 2005 }).yearTo],
    [1990, 2005],
  );
  const bad = migrate({ yearFrom: "1990", yearTo: 3000 });
  assert.deepEqual([bad.yearFrom, bad.yearTo], [null, null]);
  const reversed = migrate({ yearFrom: 2010, yearTo: 1990 });
  assert.deepEqual([reversed.yearFrom, reversed.yearTo], [1990, 2010]);
});

test("hideWatched is on unless it was explicitly switched off", () => {
  assert.equal(migrate({}).hideWatched, true);
  assert.equal(migrate({ hideWatched: "no" }).hideWatched, true);
  assert.equal(migrate({ hideWatched: false }).hideWatched, false);
});

test("lists are capped so a request can never exceed what the server accepts", () => {
  const many = Array.from({ length: LIST_CAP + 50 }, (_, i) => `cw-${i}`);
  assert.equal(migrate({ watched: many }).watched.length, LIST_CAP);
  const p = defaultProfile();
  for (let i = 0; i < LIST_CAP + 5; i += 1) setOpinion(p, film(i), "like");
  assert.equal(p.liked.length, LIST_CAP);
});

test("like, dislike and clear move a film between lists and remember its title", () => {
  const p = defaultProfile();
  setOpinion(p, film(1, "Alpha", 1999), "like");
  assert.equal(opinionOf(p, "cw-1"), "like");
  assert.equal(p.titles["cw-1"], "Alpha (1999)");
  setOpinion(p, film(1), "dislike");
  assert.deepEqual([p.liked, p.disliked], [[], ["cw-1"]]);
  setOpinion(p, film(1), null);
  assert.equal(opinionOf(p, "cw-1"), null);
  setOpinion(p, { movie_id: "bad id", title: "x" }, "like");
  assert.equal(p.liked.length, 0);
});

test("watching removes from want, unwatching drops the rating, wanting removes from watched", () => {
  const p = defaultProfile();
  setWant(p, film(1), true);
  assert.equal(isWanted(p, "cw-1"), true);
  setWatched(p, film(1), true);
  assert.deepEqual([isWatched(p, "cw-1"), isWanted(p, "cw-1")], [true, false]);
  rate(p, film(1), 4);
  setWatched(p, film(1), false);
  assert.deepEqual([isWatched(p, "cw-1"), p.ratings["cw-1"]], [false, undefined]);
  setWatched(p, film(2), true);
  setWant(p, film(2), true);
  assert.deepEqual([isWatched(p, "cw-2"), isWanted(p, "cw-2")], [false, true]);
  setWant(p, film(2), false);
  assert.equal(isWanted(p, "cw-2"), false);
});

test("stars map to opinions: 4 and 5 like, 1 and 2 dislike, 3 neither", () => {
  assert.deepEqual([1, 2, 3, 4, 5].map(opinionForStars), ["dislike", "dislike", null, "like", "like"]);
});

test("rating a film marks it watched, stores the stars and sets the matching opinion", () => {
  const p = defaultProfile();
  rate(p, film(1), 5);
  assert.deepEqual([isWatched(p, "cw-1"), p.ratings["cw-1"], opinionOf(p, "cw-1")], [true, 5, "like"]);
  rate(p, film(1), 1);
  assert.deepEqual([p.ratings["cw-1"], opinionOf(p, "cw-1")], [1, "dislike"]);
  rate(p, film(1), 3);
  assert.deepEqual([p.ratings["cw-1"], opinionOf(p, "cw-1")], [3, null]);
  rate(p, film(1), null);
  assert.deepEqual([isWatched(p, "cw-1"), "cw-1" in p.ratings], [true, false]);
});

test("an invalid rating changes nothing", () => {
  const p = defaultProfile();
  const before = JSON.stringify(p);
  for (const bad of [0, 6, 2.5, "4", NaN, undefined]) rate(p, film(1), bad);
  assert.equal(JSON.stringify(p), before);
});

test("excludedIds lists watched films unless the visitor chose to see them, and is a copy", () => {
  const p = defaultProfile();
  setWatched(p, film(1), true);
  const ids = excludedIds(p);
  assert.deepEqual(ids, ["cw-1"]);
  ids.push("cw-99");
  assert.deepEqual(p.watched, ["cw-1"]);
  p.hideWatched = false;
  assert.deepEqual(excludedIds(p), []);
});

test("profileForApi carries only what ranking needs", () => {
  const p = defaultProfile();
  setOpinion(p, film(1), "like");
  setOpinion(p, film(2), "dislike");
  p.weights.pacing = 0.7;
  assert.deepEqual(profileForApi(p), { aspect_weights: { pacing: 0.7 }, liked_movie_ids: ["cw-1"], disliked_movie_ids: ["cw-2"] });
});

test("isEmpty turns false as soon as the visitor says anything", () => {
  const touches = [
    (p) => setOpinion(p, film(1), "like"), (p) => setWatched(p, film(1), true), (p) => setWant(p, film(1), true),
    (p) => { p.weights.pacing = 0.5; }, (p) => { p.languages = ["en"]; }, (p) => { p.favouriteGenres = ["Drama"]; },
    (p) => { p.age = "25-34"; }, (p) => { p.region = "india"; },
  ];
  for (const touch of touches) {
    const p = defaultProfile();
    touch(p);
    assert.equal(isEmpty(p), false);
  }
});

test("counts reports the four list sizes", () => {
  const p = defaultProfile();
  setOpinion(p, film(1), "like");
  setOpinion(p, film(2), "dislike");
  setWatched(p, film(3), true);
  setWant(p, film(4), true);
  setWant(p, film(5), true);
  assert.deepEqual(counts(p), { liked: 1, disliked: 1, watched: 1, want: 2 });
});

test("export then import gives back the same profile", () => {
  const p = defaultProfile();
  rate(p, film(1), 5);
  setWant(p, film(2), true);
  p.languages = ["en", "hi"];
  const back = importText(exportText(p, new Date("2026-10-27T00:00:00Z")));
  assert.equal(back.ok, true);
  assert.deepEqual(back.profile, migrate(p));
});

test("the films-or-series choice starts empty, keeps only the two valid kinds, and old profiles read as empty", () => {
  assert.deepEqual(defaultProfile().kinds, []);
  assert.deepEqual(migrate({ kinds: ["series"] }).kinds, ["series"]);
  assert.deepEqual(migrate({ kinds: ["film", "series", "film"] }).kinds, ["film", "series"]);
  assert.deepEqual(migrate({ kinds: ["movie", 3, "series", null] }).kinds, ["series"]);
  assert.deepEqual(migrate({ kinds: "series" }).kinds, []);
  assert.deepEqual(migrate({ languages: ["en"] }).kinds, []); // a profile saved before series existed
  assert.deepEqual(migrate(null).kinds, []);
});

test("the kinds choice survives an export and an import", () => {
  const p = defaultProfile();
  p.kinds = ["series"];
  const back = importText(exportText(p, new Date("2026-11-01T00:00:00Z")));
  assert.equal(back.ok, true);
  assert.deepEqual(back.profile.kinds, ["series"]);
});

test("import refuses what is not a CineWhy profile, and never throws", () => {
  const good = JSON.parse(exportText(defaultProfile()));
  const cases = [
    "not json", "{}", JSON.stringify({ ...good, app: "other" }), JSON.stringify({ ...good, version: 99 }),
    JSON.stringify({ ...good, version: "3" }), JSON.stringify({ ...good, profile: 5 }), "x".repeat(1_000_001), undefined, null,
  ];
  for (const text of cases) {
    const result = importText(text);
    assert.equal(result.ok, false, String(text).slice(0, 30));
    assert.equal(typeof result.error, "string");
  }
});
