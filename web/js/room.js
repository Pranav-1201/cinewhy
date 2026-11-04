/* Watch together, the parts that need no browser: room codes and invite links, what a join request
   carries, how a server refusal is worded, and how one member stands on one title. No DOM, no
   network, no storage, so Node tests every rule here (tests/web/room.test.mjs). together.js draws
   the dialog and talks to the server using these. */

import { profileForApi } from "./profile.js";

// The server's code alphabet leaves out 0, O, 1, I and L, so a code read aloud is not mistaken.
const CODE = /^[A-HJKMNP-Z2-9]{6}$/;
const SECRET = /^[A-Za-z0-9_-]{10,64}$/;
const NAME_CAP = 30;

/** A code as typed or pasted: spaces and dashes dropped, upper case. */
export const normaliseCode = (text) => String(text ?? "").replace(/[\s-]+/g, "").toUpperCase();

export const isCode = (text) => CODE.test(normaliseCode(text));

/** The room code in a page address like `https://host/#room=ABC234`, or null. */
export function codeFromHash(hash) {
  const found = /(?:^#|&)room=([^&]*)/.exec(String(hash ?? ""));
  if (!found) return null;
  try {
    const code = normaliseCode(decodeURIComponent(found[1]));
    return isCode(code) ? code : null;
  } catch (_) { return null; /* a malformed escape in a pasted link */ }
}

/** The link a host sends to a friend. The code sits after `#`, so it never reaches a server log. */
export const inviteLink = (pageUrl, code) => `${String(pageUrl).split("#")[0]}#room=${normaliseCode(code)}`;

/**
 * What joining sends: the whole library the visitor has built (watched, want to watch, liked, not
 * for me, taste weights) and the words "I agree". Star ratings are already in it as likes (4 and
 * 5 stars) and dislikes (1 and 2), which is how the ranking has always read them. The visitor's own
 * language and kind filters are NOT sent: tonight's mood is the room quiz's job, asked fresh.
 */
export function joinBody(p, name) {
  return {
    name: String(name ?? "").trim().slice(0, NAME_CAP),
    consent: true,
    profile: profileForApi(p),
    watched_movie_ids: p.watched,
    want_movie_ids: p.want,
  };
}

const REFUSALS = {
  not_found: "That room is not open any more, or the code is wrong.",
  full: "That room is full.",
  forbidden: "Only the person who opened the room can close it.",
  busy: "The server is holding as many rooms as it can. Try again in a little while.",
  need_more_people: "Waiting for a second person to join.",
  "consent required": "Joining needs you to agree to share your library with the room.",
};

/** A short sentence for an error from `api()` ("Request failed (404): not_found"). */
export function explain(message) {
  const found = /\): (.+)$/.exec(String(message ?? ""));
  return REFUSALS[found?.[1]] ?? "Something went wrong. Please try again.";
}

/** What a tab remembers so a reload does not drop it from its room (the secret never leaves it). */
export const serialiseSession = (s) => JSON.stringify({ code: s.code, token: s.token });

export function parseSession(text) {
  try {
    const value = JSON.parse(text);
    if (isCode(value?.code) && typeof value.token === "string" && SECRET.test(value.token)) {
      return { code: normaliseCode(value.code), token: value.token };
    }
  } catch (_) { /* nothing saved, or not ours */ }
  return null;
}

/** "2 of 5 people are here", the line under the member list. */
export const headcount = (room) => `${room.members.length} of ${room.max_members} ${room.members.length === 1 ? "person is" : "people are"} here`;

