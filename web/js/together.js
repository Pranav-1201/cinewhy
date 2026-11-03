/* Watch together: the dialog where two or more people join a room, agree to share, and ask for
   something they can all watch. The rules (codes, links, wording, how a member stands on a title)
   are in room.js and tested in Node; this file draws them and talks to the server.

   What it promises, and where that is kept true:
   * nobody's library leaves the browser before they tick "I agree" (the join button is disabled
     until then, and the server refuses a join that does not say so);
   * a room's data lives in the server's memory only, and goes when the person leaves, the host
     closes it, or it sits unused for three hours;
   * the member's secret lives in this tab's sessionStorage (so a reload does not drop them out) and
     is sent as a header, never put in an address. */

import { api, post } from "./api.js";
import { $, fill, h } from "./dom.js";
import { yearAndKind } from "./format.js";
import {
  canAsk, codeFromHash, explain, headcount, inviteLink, isCode, isStale, joinBody, normaliseCode,
  parseSession, serialiseSession, standing,
} from "./room.js";
import { state } from "./state.js";
import { poster } from "./tile.js";

const SESSION_KEY = "cinewhy.room";
const POLL_MS = 4000;
const BATCH = 6; // titles per list; "Show me others" asks for the next best six
const titles = new Map(); // film id to title, for the likes line

let ctxRef = null;
let session = null; // { code, token } while in a room
let room = null; // the last RoomView the server sent
let result = null; // { version, items, notes, exhausted } for the list on screen
let shown = []; // every title put in front of this room, so "others" are new ones
let timer = null;
let ui = {}; // the live parts of the room view

const body = () => $("#together-body");
const dialog = () => $("#together-dialog");

function remember() {
  try {
    if (session) sessionStorage.setItem(SESSION_KEY, serialiseSession(session));
    else sessionStorage.removeItem(SESSION_KEY);
  } catch (_) { /* blocked storage: a reload simply leaves the room */ }
}

function recall() {
  try { return parseSession(sessionStorage.getItem(SESSION_KEY)); } catch (_) { return null; }
}

const withToken = (extra = {}) => ({ "X-Room-Token": session.token, ...extra });
const roomPath = (suffix = "") => `/rooms/${session.code}${suffix}`;
const postInRoom = (suffix, payload) => api(roomPath(suffix), {
  method: "POST", headers: withToken({ "content-type": "application/json" }), body: JSON.stringify(payload ?? {}),
});

function stopPolling() { clearInterval(timer); timer = null; }

function startPolling() {
  stopPolling();
  timer = setInterval(poll, POLL_MS);
}

/** Leave the room view (the server has forgotten the room, or this person left it). */
function leaveView(message) {
  stopPolling();
  session = null; room = null; result = null; shown = [];
  remember();
  drawStart(message);
}

async function poll() {
  if (!session || !dialog().open) return;
  try {
    const next = await api(roomPath(), { headers: withToken() });
    const moved = !room || next.version !== room.version;
    room = next;
    if (moved) { paintMembers(); paintResults(); }
  } catch (err) {
    if (/\(404\)/.test(err.message)) leaveView("That room was closed or has expired.");
  }
}

// --- the start of it: begin a room, or enter a code -----------------------------------------------

function drawStart(message = "") {
  const code = h("input", { id: "tg-code", type: "text", maxlength: "9", autocomplete: "off", autocapitalize: "characters", spellcheck: "false", placeholder: "Room code" });
  const note = h("p", { id: "tg-note", class: "note", role: "status", text: message });
  const enter = () => {
    if (!isCode(code.value)) { note.textContent = "A room code is six letters and numbers."; return; }
    drawConsent(normaliseCode(code.value));
  };
  code.addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); enter(); } });
  fill(body(),
    h("h2", { id: "together-title", text: "Watch together" }),
    h("p", { class: "lede", text: "Pick something the whole group will like. Everyone in the room shares their library for as long as they stay, and nothing is kept once the room is gone." }),
    h("div", { class: "tg-start" },
      h("button", { class: "btn primary", type: "button", text: "Start a room", onclick: () => drawConsent(null) }),
      h("div", { class: "tg-join" },
        h("label", { class: "sr-only", for: "tg-code", text: "Room code" }), code,
        h("button", { class: "btn", type: "button", text: "Join", onclick: enter }))),
    note);
}

// --- agreeing to share -----------------------------------------------------------------------------

function drawConsent(code, message = "") {
  const name = h("input", { id: "tg-name", type: "text", maxlength: "30", autocomplete: "nickname", placeholder: "Your name" });
  const agree = h("input", { id: "tg-agree", type: "checkbox" });
  const go = h("button", { class: "btn primary", type: "button", text: code ? `Join room ${code}` : "Start the room" });
  go.disabled = true;
  agree.addEventListener("change", () => { go.disabled = !agree.checked; });
  const note = h("p", { id: "tg-note", class: "note", role: "status", text: message });
  go.addEventListener("click", async () => {
    go.disabled = true;
    note.textContent = "";
    try {
      const target = code ?? (await post("/rooms", {})).code;
      const joined = await post(`/rooms/${target}/join`, joinBody(state, name.value));
      session = { code: target, token: joined.token };
      remember();
      room = joined.room; result = null; shown = [];
      drawRoom();
      startPolling();
    } catch (err) {
      note.textContent = explain(err.message);
      go.disabled = !agree.checked;
    }
  });
  fill(body(),
    h("h2", { id: "together-title", text: code ? `Join room ${code}` : "Start a room" }),
    h("div", { class: "field" }, h("label", { for: "tg-name", text: "What should the others call you?" }), name),
    h("div", { class: "tg-share" },
      h("p", { text: "To find something you can all watch, this room needs to see:" }),
      h("ul", {},
        h("li", { text: "the films you have watched and the ones you want to watch" }),
        h("li", { text: "the films you liked and the ones that were not for you" }),
        h("li", { text: "your taste settings" })),
      h("p", { text: "The people in the room can see which films you liked. Nothing else leaves your browser, and nothing is saved: you can leave at any time and your library goes with you." })),
    h("label", { class: "tg-agree", for: "tg-agree" }, agree, h("span", { text: "I agree to share this with the people in the room, for as long as I am in it." })),
    h("div", { class: "sheet-actions" },
      go, h("button", { class: "btn", type: "button", text: "Back", onclick: () => drawStart() })),
    note);
  name.focus();
}

// --- inside the room -------------------------------------------------------------------------------

async function titleOf(id) {
  if (titles.has(id)) return titles.get(id);
  try {
    const detail = await api(`/movie/${encodeURIComponent(id)}`);
    titles.set(id, detail.movie.title);
  } catch (_) { titles.set(id, id); }
  return titles.get(id);
}

/** "Likes: A, B, C" for a member, drawn at once from what is known and completed as titles arrive. */
function likesLine(member) {
  const line = h("span", { class: "sub" });
  const ids = member.liked_movie_ids.slice(0, 4);
  if (!ids.length) { line.textContent = "No likes yet"; return line; }
  const paint = () => {
    const names = ids.map((id) => titles.get(id) ?? "…");
    const more = member.liked_movie_ids.length > ids.length ? `, and ${member.liked_movie_ids.length - ids.length} more` : "";
    line.textContent = `Likes ${names.join(", ")}${more}`;
  };
  paint();
  Promise.all(ids.map(titleOf)).then(paint);
  return line;
}

function memberRow(member) {
  return h("li", { class: "tg-member" },
    h("span", { class: "tg-name", text: member.name }),
    member.is_host ? h("span", { class: "chip static", text: "Host" }) : null,
    member.is_you ? h("span", { class: "chip static", text: "You" }) : null,
    h("span", { class: "sub", text: `${member.watched_count} watched, ${member.want_count} to watch` }),
    likesLine(member));
}

async function copy(text, note) {
  try {
    await navigator.clipboard.writeText(text);
    note.textContent = "Copied.";
  } catch (_) { note.textContent = "Select it and copy it by hand."; }
}

function drawRoom() {
  const link = inviteLink(window.location.href, session.code);
  const note = h("p", { id: "tg-note", class: "note", role: "status" });
  const linkBox = h("input", { id: "tg-link", type: "text", readonly: true, value: link, "aria-label": "Invite link" });
  linkBox.addEventListener("focus", () => linkBox.select());
  ui = {
    members: h("ul", { class: "tg-members", id: "tg-members" }),
    count: h("p", { class: "note", id: "tg-count" }),
    find: h("button", { class: "btn primary", id: "tg-find", type: "button", text: "Find something for us", onclick: () => find(false) }),
    close: h("button", { class: "btn", id: "tg-close", type: "button", text: "Close room for everyone", onclick: closeRoom }),
    results: h("div", { id: "tg-results", "aria-live": "polite" }),
    note,
  };
  fill(body(),
    h("h2", { id: "together-title", text: "Watch together" }),
    h("div", { class: "tg-code" },
      h("span", { class: "sub", text: "Room code" }), h("strong", { id: "tg-code-text", text: session.code }),
      h("button", { class: "btn", type: "button", text: "Copy code", onclick: () => copy(session.code, note) })),
    h("div", { class: "tg-invite" },
      linkBox, h("button", { class: "btn", type: "button", text: "Copy invite link", onclick: () => copy(link, note) })),
    ui.members, ui.count,
    h("div", { class: "sheet-actions" },
      ui.find, h("button", { class: "btn", id: "tg-leave", type: "button", text: "Leave room", onclick: leave }), ui.close),
    note, ui.results);
  paintMembers();
  paintResults();
}

const me = () => room?.members.find((m) => m.is_you);

function paintMembers() {
  if (!ui.members?.isConnected) return;
  ui.members.replaceChildren(...room.members.map(memberRow));
  ui.count.textContent = headcount(room);
  ui.find.disabled = !canAsk(room);
  ui.close.hidden = !me()?.is_host;
}

function card(entry) {
  const movie = entry.item.movie;
  const open = () => ctxRef.open(movie.movie_id);
  return h("li", { class: "tg-card" },
    h("button", { class: "tg-poster", type: "button", "aria-label": `${movie.title}. Open details`, onclick: open }, poster(movie, { language: entry.item.language })),
    h("div", { class: "tg-info" },
      h("button", { class: "name", type: "button", text: movie.title, onclick: open }),
      h("p", { class: "sub", text: yearAndKind(movie) }),
      h("ul", { class: "tg-fits" }, entry.members.map((fit) => {
        const s = standing(fit);
        return h("li", { class: `tg-fit ${s.tone}`, text: `${fit.name} ${s.text}` });
      }))));
}

function paintResults() {
  if (!ui.results?.isConnected) return;
  if (!result) {
    fill(ui.results, canAsk(room) ? null : h("p", { class: "note", text: "Waiting for a second person. Send them the code or the link." }));
    return;
  }
  const stale = isStale(result.version, room);
  fill(ui.results,
    stale ? h("p", { class: "note", text: "Someone joined or left since this list was made. Ask again to include everyone." }) : null,
    result.items.length
      ? h("ol", { class: "tg-list" }, result.items.map(card))
      : h("p", { class: "note", text: result.exhausted ? "That is everything this group agrees on right now." : "Nothing fits everyone yet." }),
    result.notes.map((text) => h("p", { class: "note", text })),
    result.items.length
      ? h("div", { class: "sheet-actions" }, h("button", { class: "btn", id: "tg-more", type: "button", text: "Show me others", onclick: () => find(true) }))
      : null);
}

async function find(others) {
  ui.find.disabled = true;
  ui.note.textContent = "";
  try {
    const out = await postInRoom("/recommend", { limit: BATCH, exclude_movie_ids: others ? shown.slice(-500) : [] });
    if (!others) shown = [];
    shown.push(...out.items.map((entry) => entry.item.movie.movie_id));
    result = { version: room.version, items: out.items, notes: out.notes, exhausted: others && !out.items.length };
  } catch (err) {
    if (/\(404\)/.test(err.message)) { leaveView("That room was closed or has expired."); return; }
    ui.note.textContent = explain(err.message);
  }
  ui.find.disabled = !canAsk(room);
  paintResults();
}

async function leave() {
  try { await postInRoom("/leave"); } catch (_) { /* already gone is fine */ }
  leaveView("You left the room, and your library was removed from it.");
}

async function closeRoom() {
  try {
    await postInRoom("/close");
    leaveView("The room is closed.");
  } catch (err) { ui.note.textContent = explain(err.message); }
}

// --- opening it ------------------------------------------------------------------------------------

/** Show the dialog. `joinCode` is a code from an invite link, which goes straight to the agreement. */
export async function openTogether(ctx, joinCode = null) {
  ctxRef = ctx;
  if (!dialog().open) dialog().showModal();
  if (!session) {
    if (joinCode) drawConsent(joinCode); else drawStart();
    return;
  }
  fill(body(), h("p", { class: "note", text: "Opening your room." }));
  try {
    room = await api(roomPath(), { headers: withToken() });
  } catch (err) {
    leaveView(/\(404\)/.test(err.message) ? "That room was closed or has expired." : explain(err.message));
    return;
  }
  drawRoom();
  if (joinCode && joinCode !== session.code) {
    ui.note.textContent = `You are already in room ${session.code}. Leave it first to join ${joinCode}.`;
  }
  startPolling();
}

/** Wire the dialog and pick up a room this tab was already in. Returns a code found in the address
    (an invite link) so the page can open straight to it. */
export function initTogether(ctx) {
  ctxRef = ctx;
  session = recall();
  dialog().addEventListener("close", stopPolling);
  const code = codeFromHash(window.location.hash);
  if (window.location.hash.includes("room=")) {
    // The code has been read; take it out of the address so a reload does not ask again.
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
  }
  return code;
}
