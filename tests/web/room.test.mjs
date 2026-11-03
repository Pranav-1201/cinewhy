// Tests for web/js/room.js (codes, invite links, the join request, wording), run by Node's built-in
// test runner. tests/test_web_logic.py runs this file as part of the normal pytest run.
import assert from "node:assert/strict";
import { test } from "node:test";

import { defaultProfile } from "../../web/js/profile.js";
import {
  canAsk, codeFromHash, explain, headcount, inviteLink, isCode, isStale, joinBody,
  normaliseCode, parseSession, serialiseSession, standing,
} from "../../web/js/room.js";

const fit = (extra = {}) => ({ name: "Ann", percentile: 0.8, saw_it: false, disliked: false, wants: false, ...extra });

test("a code typed with spaces, dashes or lower case is the same code", () => {
  assert.equal(normaliseCode(" ab2-c d3 "), "AB2CD3");
  assert.ok(isCode("abc-234"));
});

test("a code with a look-alike character or the wrong length is not a code", () => {
  for (const bad of ["ABC23", "ABC2345", "ABCO23", "ABCI23", "ABCL23", "ABC 1 23", "", null, undefined]) {
    assert.equal(isCode(bad), false, String(bad));
  }
});

test("the invite link carries the code after a hash, and replaces an old one", () => {
  assert.equal(inviteLink("https://cinewhy.example/", "abc-234"), "https://cinewhy.example/#room=ABC234");
  assert.equal(inviteLink("https://cinewhy.example/#room=ZZZZZZ", "ABC234"), "https://cinewhy.example/#room=ABC234");
});

test("the code is read back out of an invite link, and only a valid one", () => {
  assert.equal(codeFromHash("#room=ABC234"), "ABC234");
  assert.equal(codeFromHash("#x=1&room=abc-234"), "ABC234");
  assert.equal(codeFromHash("#room=ABC234%20"), "ABC234");
  for (const bad of ["", "#", "#room=", "#room=SHORT", "#room=%E0%A4%A", "#other=ABC234", undefined]) {
    assert.equal(codeFromHash(bad), null, String(bad));
  }
});

test("joining sends the whole library and the agreement", () => {
  const p = defaultProfile();
  Object.assign(p, {
    liked: ["cw-1"], disliked: ["cw-2"], watched: ["cw-1", "cw-3"], want: ["cw-4"],
    weights: { pacing: 0.5 }, languages: ["en"], kinds: ["film"],
  });
  const body = joinBody(p, "  Ann  ");
  assert.equal(body.name, "Ann");
  assert.equal(body.consent, true);
  assert.deepEqual(body.profile, { aspect_weights: { pacing: 0.5 }, liked_movie_ids: ["cw-1"], disliked_movie_ids: ["cw-2"] });
  assert.deepEqual(body.watched_movie_ids, ["cw-1", "cw-3"]);
  assert.deepEqual(body.want_movie_ids, ["cw-4"]);
  assert.deepEqual([body.languages, body.kinds], [["en"], ["film"]]);
});

test("a long name is cut to what the server keeps", () => {
  assert.equal(joinBody(defaultProfile(), "x".repeat(100)).name.length, 30);
});

test("a refusal from the server becomes a plain sentence, and an unknown one a generic line", () => {
  assert.match(explain("Request failed (404): not_found"), /not open any more/);
  assert.match(explain("Request failed (409): full"), /full/);
  assert.match(explain("Request failed (400): consent required"), /agree/);
  assert.match(explain("Request failed (500) (error id abc)"), /Something went wrong/);
  assert.match(explain(undefined), /Something went wrong/);
});

test("a saved session round-trips, and anything else is ignored", () => {
  const saved = serialiseSession({ code: "ABC234", token: "x".repeat(22), extra: "dropped" });
  assert.deepEqual(parseSession(saved), { code: "ABC234", token: "x".repeat(22) });
  for (const bad of [null, "", "{", "{}", JSON.stringify({ code: "ABC234" }), JSON.stringify({ code: "nope", token: "x".repeat(22) }), JSON.stringify({ code: "ABC234", token: "short" })]) {
    assert.equal(parseSession(bad), null, String(bad));
  }
});

test("the head count and when a list can be asked for", () => {
  const room = (n) => ({ max_members: 5, members: Array.from({ length: n }, () => ({})) });
  assert.equal(headcount(room(1)), "1 of 5 person is here");
  assert.equal(headcount(room(3)), "3 of 5 people are here");
  assert.equal(canAsk(room(1)), false);
  assert.equal(canAsk(room(2)), true);
});

test("a list is out of date once the room's version moves on", () => {
  assert.equal(isStale(null, { version: 3 }), false); // no list yet
  assert.equal(isStale(3, { version: 3 }), false);
  assert.equal(isStale(2, { version: 3 }), true);
});

test("what a member has said comes before how well a title fits", () => {
  assert.deepEqual(standing(fit({ disliked: true, saw_it: true, wants: true })), { tone: "warn", text: "did not like it" });
  assert.deepEqual(standing(fit({ saw_it: true, wants: true })), { tone: "warn", text: "has seen it" });
  assert.deepEqual(standing(fit({ wants: true })), { tone: "good", text: "wants to watch it" });
  assert.deepEqual(standing(fit({ percentile: 0.876 })), { tone: "plain", text: "88% fit" });
});

test("a plain fit names the liked title it is closest to, when there is one", () => {
  assert.equal(standing(fit({ because: "Heat" })).text, "80% fit, like Heat");
  assert.equal(standing(fit({ because: null })).text, "80% fit");
});
