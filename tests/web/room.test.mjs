// Tests for web/js/room.js (codes, invite links, the join request, wording), run by Node's built-in
// test runner. tests/test_web_logic.py runs this file as part of the normal pytest run.
import assert from "node:assert/strict";
import { test } from "node:test";

import { defaultProfile } from "../../web/js/profile.js";
import {
  codeFromHash, explain, headcount, inviteLink, isCode, joinBody, normaliseCode, parseSession,
  serialiseSession,
} from "../../web/js/room.js";

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
  // Deliberate change (D-046): tonight's mood comes from the room quiz, so the visitor's own
  // language and kind filters are not sent.
  assert.equal("languages" in body, false);
  assert.equal("kinds" in body, false);
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

test("the head count says how many people are in the room", () => {
  const room = (n) => ({ max_members: 5, members: Array.from({ length: n }, () => ({})) });
  assert.equal(headcount(room(1)), "1 of 5 person is here");
  assert.equal(headcount(room(3)), "3 of 5 people are here");
});
