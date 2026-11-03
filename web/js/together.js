/* Watch together: the dialog where two or more people join a room, agree to share, answer a short
   mood quiz, swipe through cards of titles the whole group could enjoy, and open the group's picks.
   The rules live in room.js and swipecore.js (tested in Node); cards.js draws and animates one card;
   this file moves between the screens and talks to the server.

   What it promises, and where that is kept true:
   * nobody's library leaves the browser before they tick "I agree" (the join button is disabled
     until then, and the server refuses a join that does not say so);
   * everything answered in the room (quiz, swipes, the top pick) stays in the room: this file never
     writes to the visitor's own profile, and the rules screen says so before anyone begins;
   * a room's data lives in the server's memory only, and goes when the person leaves, the host
     closes it, or it sits unused for three hours;
   * the member's secret lives in this tab's sessionStorage (so a reload does not drop them out) and
     is sent as a header, never put in an address;
   * the group's picks never redraw by themselves: a Refresh button brings them up to date. */

import { api, post } from "./api.js";
import { buildCard } from "./cards.js";
import { $, fill, h } from "./dom.js";
import { yearAndKind } from "./format.js";
import { codeFromHash, explain, headcount, inviteLink, isCode, joinBody, normaliseCode, parseSession, serialiseSession } from "./room.js";
import { state } from "./state.js";
import * as sc from "./swipecore.js";
import { poster } from "./tile.js";

const SESSION_KEY = "cinewhy.room";
const RULES_KEY = "cinewhy.room.rules"; // the room code the rules were last read for (this tab)
const POLL_MS = 4000;
const BATCH = 20; // cards fetched at a time
const ARROWS = { left: "←", up: "↑", down: "↓", right: "→" };
const titles = new Map(); // film id to title, for the likes line

let ctxRef = null;
let session = null; // { code, token } while in a room
let room = null; // the last RoomView the server sent
let view = "room"; // room, rules, quiz, swipe or results
let timer = null;
let ui = {}; // the live parts of the screen being shown
// The swipe session: only the current page knows these, and all of it is answered into the room.
let deck = sc.makeDeck();
let handle = null; // the card on screen
let myTop = null; // { id, title } once the member has named a top pick on this page
let loading = false;
let answered = 0;
let replacing = false; // the member confirmed replacing their top pick
let results = null; // the last results the page fetched

const body = () => $("#together-body");
const dialog = () => $("#together-dialog");
const me = () => room?.members.find((m) => m.is_you);

function remember() {
  try {
    if (session) sessionStorage.setItem(SESSION_KEY, serialiseSession(session));
    else sessionStorage.removeItem(SESSION_KEY);
  } catch (_) { /* blocked storage: a reload simply leaves the room */ }
}

function recall() {
  try { return parseSession(sessionStorage.getItem(SESSION_KEY)); } catch (_) { return null; }
}

const rulesRead = () => { try { return sessionStorage.getItem(RULES_KEY) === session?.code; } catch (_) { return false; } };
const markRulesRead = () => { try { sessionStorage.setItem(RULES_KEY, session.code); } catch (_) { /* asked again next time */ } };

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
  document.removeEventListener("keydown", onKey);
  session = null; room = null; results = null; handle = null; myTop = null;
  deck = sc.makeDeck(); answered = 0; loading = false; replacing = false;
  remember();
  drawStart(message);
}

async function poll() {
  if (!session || !dialog().open) return;
  try {
    const next = await api(roomPath(), { headers: withToken() });
    const moved = !room || next.version !== room.version || next.activity !== room.activity;
    room = next;
    if (!moved) return;
    if (view === "room") paintMembers();
    if (view === "results") paintStale();
  } catch (err) {
    if (/\(404\)/.test(err.message)) leaveView("That room was closed or has expired.");
  }
}

// --- the start of it: begin a room, or enter a code -----------------------------------------------

function drawStart(message = "") {
  view = "start";
  const code = h("input", { id: "tg-code", type: "text", maxlength: "9", autocomplete: "off", autocapitalize: "characters", spellcheck: "false", placeholder: "Room code" });
  const note = h("p", { id: "tg-note", class: "note", role: "status", text: message });
  const enter = () => {
    if (!isCode(code.value)) { note.textContent = "A room code is six letters and numbers."; return; }
    drawConsent(normaliseCode(code.value));
  };
  code.addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); enter(); } });
  fill(body(),
    h("h2", { id: "together-title", text: "Watch together" }),
    h("p", { class: "lede", text: "Pick something the whole group will like. Everyone in the room shares their library for as long as they stay, answers a short mood quiz, and swipes through titles. Nothing is kept once the room is gone." }),
    h("div", { class: "tg-start" },
      h("button", { class: "btn primary", type: "button", text: "Start a room", onclick: () => drawConsent(null) }),
      h("div", { class: "tg-join" },
        h("label", { class: "sr-only", for: "tg-code", text: "Room code" }), code,
        h("button", { class: "btn", type: "button", text: "Join", onclick: enter }))),
    note);
}

// --- agreeing to share -----------------------------------------------------------------------------

function drawConsent(code, message = "") {
  view = "consent";
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
      room = joined.room; results = null; deck = sc.makeDeck(); myTop = null; answered = 0;
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
      h("p", { text: "The people in the room can see which films you liked. Then you will answer a quiz and swipe cards: those answers stay in the room too, and nothing here changes your own profile. You can leave at any time and everything of yours goes with you." })),
    h("label", { class: "tg-agree", for: "tg-agree" }, agree, h("span", { text: "I agree to share this with the people in the room, for as long as I am in it." })),
    h("div", { class: "sheet-actions" },
      go, h("button", { class: "btn", type: "button", text: "Back", onclick: () => drawStart() })),
    note);
  name.focus();
}

// --- the room: who is here, and where to go next -----------------------------------------------------

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
  if (!ids.length) { line.textContent = "No likes in their library yet"; return line; }
  const paint = () => {
    const names = ids.map((id) => titles.get(id) ?? "…");
    const more = member.liked_movie_ids.length > ids.length ? `, and ${member.liked_movie_ids.length - ids.length} more` : "";
    line.textContent = `Likes ${names.join(", ")}${more}`;
  };
  paint();
  Promise.all(ids.map(titleOf)).then(paint);
  return line;
}

function progress(member) {
  const parts = [member.quiz_done ? "quiz done" : "quiz not done", `${member.swipe_count} answered`];
  if (member.has_top) parts.push("top pick chosen");
  return parts.join(", ");
}

function memberRow(member) {
  return h("li", { class: "tg-member" },
    h("span", { class: "tg-name", text: member.name }),
    member.is_host ? h("span", { class: "chip static", text: "Host" }) : null,
    member.is_you ? h("span", { class: "chip static", text: "You" }) : null,
    h("span", { class: "sub", text: progress(member) }),
    likesLine(member));
}

async function copy(text, note) {
  try {
    await navigator.clipboard.writeText(text);
    note.textContent = "Copied.";
  } catch (_) { note.textContent = "Select it and copy it by hand."; }
}

function drawRoom() {
  view = "room";
  document.removeEventListener("keydown", onKey);
  const link = inviteLink(window.location.href, session.code);
  const note = h("p", { id: "tg-note", class: "note", role: "status" });
  const linkBox = h("input", { id: "tg-link", type: "text", readonly: true, value: link, "aria-label": "Invite link" });
  linkBox.addEventListener("focus", () => linkBox.select());
  ui = {
    members: h("ul", { class: "tg-members", id: "tg-members" }),
    count: h("p", { class: "note", id: "tg-count" }),
    start: h("button", { class: "btn primary", id: "tg-start", type: "button", onclick: begin }),
    close: h("button", { class: "btn", id: "tg-close", type: "button", text: "Close room for everyone", onclick: closeRoom }),
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
      ui.start,
      h("button", { class: "btn", id: "tg-open-results", type: "button", text: "See the group's picks", onclick: drawResults }),
      h("button", { class: "btn", id: "tg-leave", type: "button", text: "Leave room", onclick: leave }),
      ui.close),
    note);
  paintMembers();
}

function paintMembers() {
  if (!ui.members?.isConnected) return;
  ui.members.replaceChildren(...room.members.map(memberRow));
  ui.count.textContent = room.members.length < 2
    ? `${headcount(room)}. You can start swiping alone; the picks get better as friends join.`
    : headcount(room);
  ui.start.textContent = me()?.quiz_done ? "Keep swiping" : "Start swiping";
  ui.close.hidden = !me()?.is_host;
}

/** From the room to the cards: the rules once, then the quiz if not answered, then the deck. */
function begin() {
  if (!rulesRead()) drawRules();
  else if (!me()?.quiz_done) drawQuiz();
  else drawSwipe();
}

// --- the rules, before anyone begins ---------------------------------------------------------------

function drawRules() {
  view = "rules";
  const R = sc.RULES;
  fill(body(),
    h("h2", { id: "together-title", text: R.title }),
    h("ol", { class: "sw-steps" }, R.steps.map((text) => h("li", { text }))),
    h("h3", { class: "subhead", text: "The four swipes" }),
    h("ul", { class: "sw-rules", id: "tg-rules" }, R.swipes.map((s) => h("li", {},
      h("span", { class: `sw-arrow ${s.action}`, "aria-hidden": "true", text: ARROWS[s.direction] }), s.label))),
    h("p", { class: "note", text: R.topPick }),
    h("p", { class: "note", text: R.mouse }),
    h("h3", { class: "subhead", text: "The group's picks" }),
    h("p", { class: "note", text: R.results }),
    h("h3", { class: "subhead", text: "Your privacy" }),
    R.privacy.map((text) => h("p", { class: "note", text })),
    h("div", { class: "sheet-actions" },
      h("button", { class: "btn primary", id: "tg-rules-ok", type: "button", text: "Got it, let's start", onclick: () => { markRulesRead(); begin(); } }),
      h("button", { class: "btn", type: "button", text: "Back", onclick: drawRoom })));
}

// --- the mood quiz -------------------------------------------------------------------------------------

function chipGroup(options) {
  const chosen = new Set();
  const buttons = options.map(([value, text]) => {
    const button = h("button", { class: "chip", type: "button", "aria-pressed": "false", text });
    button.addEventListener("click", () => {
      if (chosen.has(value)) chosen.delete(value); else chosen.add(value);
      button.setAttribute("aria-pressed", String(chosen.has(value)));
    });
    return button;
  });
  return { el: h("div", { class: "chip-group wrap" }, buttons), read: () => [...chosen] };
}

function drawQuiz() {
  view = "quiz";
  const kinds = chipGroup(sc.KIND_OPTIONS);
  const languages = chipGroup(sc.LANGUAGE_OPTIONS);
  const genres = chipGroup(sc.genreOptions(ctxRef.facets?.genres));
  const note = h("p", { id: "tg-note", class: "note", role: "status" });
  const send = async (skip) => {
    note.textContent = "";
    const answer = skip ? sc.quizBody([], [], []) : sc.quizBody(kinds.read(), languages.read(), genres.read());
    try {
      room = await postInRoom("/quiz", answer);
      drawSwipe();
    } catch (err) { note.textContent = explain(err.message); }
  };
  fill(body(),
    h("h2", { id: "together-title", text: "What do you feel like tonight?" }),
    h("p", { class: "lede", text: "Pick as many as you like, or none. This is only your mood for this session: it is not saved to your profile. The group's list leans towards what most of you pick, and still shows the rest, just lower." }),
    h("div", { class: "field" }, h("span", { class: "field-label", text: "Films or series" }), kinds.el),
    h("div", { class: "field" }, h("span", { class: "field-label", text: "Language" }), languages.el),
    h("div", { class: "field" }, h("span", { class: "field-label", text: "Genre" }), genres.el),
    h("div", { class: "sheet-actions" },
      h("button", { class: "btn primary", id: "tg-quiz-go", type: "button", text: "Start swiping", onclick: () => send(false) }),
      h("button", { class: "btn", id: "tg-quiz-skip", type: "button", text: "No preference, skip", onclick: () => send(true) }),
      h("button", { class: "btn", type: "button", text: "Back", onclick: drawRoom })),
    note);
}

// --- the swipe cards -----------------------------------------------------------------------------------

function onKey(event) {
  if (view !== "swipe" || !dialog().open || (ui.confirm && !ui.confirm.hidden)) return;
  const action = sc.keyAction(event.key);
  if (!action || !handle) return;
  event.preventDefault(); // arrows must not scroll the dialog while swiping
  handle.fling(sc.DIRECTION_OF[action]);
}

function drawSwipe() {
  view = "swipe";
  document.removeEventListener("keydown", onKey);
  document.addEventListener("keydown", onKey);
  ui = {
    stage: h("div", { class: "sw-stage", id: "sw-stage", "aria-live": "polite" }),
    count: h("span", { class: "sub", id: "sw-count" }),
    confirm: h("div", { class: "sw-confirm", id: "sw-confirm", role: "alertdialog", hidden: true }),
    note: h("p", { id: "tg-note", class: "note", role: "status" }),
  };
  const buttons = [["pass", "left"], ["seen", "up"], ["top", "down"], ["want", "right"]].map(([action, direction]) =>
    h("button", { class: `btn sw-btn ${action}`, type: "button", "data-action": action, onclick: () => handle?.fling(direction) },
      h("span", { class: "arrow", "aria-hidden": "true", text: ARROWS[direction] }), sc.LABELS[action]));
  fill(body(),
    h("div", { class: "sw-bar" },
      h("button", { class: "btn", id: "sw-people", type: "button", text: "People", onclick: drawRoom }),
      ui.count,
      h("button", { class: "btn", id: "sw-results", type: "button", text: "Group's picks", onclick: drawResults })),
    ui.stage,
    h("div", { class: "sw-buttons" }, buttons),
    h("p", { class: "sw-hint", text: "Drag the card, use the buttons, or press the arrow keys." }),
    ui.confirm, ui.note);
  if (sc.current(deck)) showCard(); else loadMore();
}

function preload() {
  for (const card of sc.upcoming(deck, 3)) {
    if (card.movie.poster_url) { const img = new Image(); img.src = card.movie.poster_url; }
  }
}

function showCard() {
  if (view !== "swipe" || !ui.stage?.isConnected) return;
  ui.count.textContent = `${answered} answered`;
  ui.confirm.hidden = true;
  const card = sc.current(deck);
  if (!card) {
    handle = null;
    const message = loading
      ? "Finding titles for the group…"
      : "That is every title the group can be offered right now. Open the group's picks to see where you stand.";
    fill(ui.stage, h("p", { class: "note sw-empty", id: "sw-empty", text: message }));
    return;
  }
  handle = buildCard(card, { onDecide: (action, flown) => answer(card, action, flown), guard: (direction, held) => guardTop(card, direction, held) });
  const behind = sc.upcoming(deck, 1)[0];
  fill(ui.stage,
    behind ? h("div", { class: "sw-card sw-behind", "aria-hidden": "true" }, h("div", { class: "sw-poster" }, poster(behind.movie, { language: behind.language }))) : null,
    handle.el);
  preload();
}

async function loadMore() {
  if (loading || deck.exhausted) { showCard(); return; }
  loading = true;
  if (!sc.current(deck)) showCard();
  try {
    const out = await postInRoom("/deck", { count: BATCH, held_movie_ids: sc.heldIds(deck) });
    sc.add(deck, out.cards);
    if (out.exhausted) deck.exhausted = true;
  } catch (err) {
    if (/\(404\)/.test(err.message)) { leaveView("That room was closed or has expired."); return; }
    if (ui.note?.isConnected) ui.note.textContent = explain(err.message);
  } finally {
    loading = false;
  }
  if (view === "swipe" && !handle) showCard();
}

/** A second top pick must be confirmed before the card leaves. Returns false to keep the card. */
function guardTop(card, direction, cardHandle) {
  if (sc.ACTIONS[direction] !== "top" || replacing) return true;
  const hasTop = myTop?.id || me()?.has_top;
  if (!hasTop || myTop?.id === card.movie.movie_id) return true;
  askReplace(card, cardHandle);
  return false;
}

function askReplace(card, cardHandle) {
  const old = myTop?.title ? `“${myTop.title}”` : "your current top pick";
  ui.confirm.hidden = false;
  fill(ui.confirm,
    h("p", { text: `Make “${card.movie.title}” your top pick instead of ${old}? Your old top pick will still count a little more than a normal right swipe.` }),
    h("div", { class: "sheet-actions" },
      h("button", { class: "btn primary", id: "sw-replace-yes", type: "button", text: "Yes, change it",
        onclick: () => { ui.confirm.hidden = true; replacing = true; cardHandle.fling("down"); } }),
      h("button", { class: "btn", id: "sw-replace-no", type: "button", text: "No, keep it", onclick: () => { ui.confirm.hidden = true; } })));
}

async function answer(card, action, cardHandle) {
  const replace = replacing;
  replacing = false;
  const id = card.movie.movie_id;
  try {
    const ack = await postInRoom("/swipe", { movie_id: id, action, replace });
    titles.set(id, card.movie.title);
    if (action === "top") myTop = { id, title: card.movie.title };
    else if (myTop?.id === id) myTop = null;
    answered = ack.swipe_count;
    if (room) room.activity += 1; // our own answer: the results already made are now behind
  } catch (err) {
    cardHandle.snapBack();
    if (/top_exists/.test(err.message)) { askReplace(card, cardHandle); return; }
    if (/\(404\)/.test(err.message)) { leaveView("That room was closed or has expired."); return; }
    if (ui.note?.isConnected) ui.note.textContent = explain(err.message);
    return;
  }
  sc.advance(deck);
  showCard();
  if (sc.needsMore(deck)) loadMore();
}

// --- the group's picks ----------------------------------------------------------------------------------

function resultRow(entry) {
  const movie = entry.card.movie;
  const open = () => ctxRef.open(movie.movie_id);
  return h("li", { class: "tg-card" },
    h("button", { class: "tg-poster", type: "button", "aria-label": `${movie.title}. Open details`, onclick: open }, poster(movie, { language: entry.card.language })),
    h("div", { class: "tg-info" },
      h("button", { class: "name", type: "button", text: movie.title, onclick: open }),
      h("p", { class: "sub", text: yearAndKind(movie) }),
      h("ul", { class: "tg-fits" }, entry.members.map((fit) => {
        const r = sc.reaction(fit);
        return h("li", { class: `tg-fit ${r.tone}`, text: r.text });
      }))));
}

function paintStale() {
  if (!ui.stale?.isConnected) return;
  ui.stale.textContent = results && sc.isStale(results.activity, room.activity)
    ? "People have answered more since this list was made. Press Refresh to include them."
    : "";
}

function paintResults() {
  if (!ui.list?.isConnected || !results) return;
  fill(ui.list,
    results.top.length
      ? [h("h3", { class: "subhead", text: "Top picks" }), h("ol", { class: "tg-list", id: "tg-top" }, results.top.map(resultRow))]
      : h("p", { class: "note", text: "Nothing fits the group yet. Swipe a few cards and refresh." }),
    results.close.length
      ? [h("h3", { class: "subhead", text: "Also close" }), h("ol", { class: "tg-list", id: "tg-close-list" }, results.close.map(resultRow))]
      : null,
    results.notes.map((text) => h("p", { class: "note", text })));
  paintStale();
}

async function loadResults() {
  ui.refresh.disabled = true;
  ui.note.textContent = "";
  try {
    results = await postInRoom("/results");
    paintResults();
  } catch (err) {
    if (/\(404\)/.test(err.message)) { leaveView("That room was closed or has expired."); return; }
    ui.note.textContent = explain(err.message);
  }
  ui.refresh.disabled = false;
}

function drawResults() {
  view = "results";
  document.removeEventListener("keydown", onKey);
  ui = {
    refresh: h("button", { class: "btn primary", id: "tg-refresh", type: "button", text: "Refresh", onclick: loadResults }),
    stale: h("p", { class: "note", id: "tg-stale", role: "status" }),
    list: h("div", { id: "tg-results", "aria-live": "polite" }),
    note: h("p", { id: "tg-note", class: "note", role: "status" }),
  };
  fill(body(),
    h("h2", { id: "together-title", text: "The group's picks" }),
    h("p", { class: "lede", text: "The best titles for everyone so far, then the next-closest. This list stays as it is until you press Refresh." }),
    h("div", { class: "sheet-actions" },
      ui.refresh,
      h("button", { class: "btn", id: "tg-keep-swiping", type: "button", text: "Keep swiping", onclick: () => (me()?.quiz_done ? drawSwipe() : begin()) }),
      h("button", { class: "btn", id: "tg-to-room", type: "button", text: "People", onclick: drawRoom })),
    ui.stale, ui.note, ui.list);
  loadResults();
}

async function leave() {
  try { await postInRoom("/leave"); } catch (_) { /* already gone is fine */ }
  leaveView("You left the room, and everything you shared or answered was removed from it.");
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
  if (view === "swipe" && sc.current(deck)) drawSwipe(); else drawRoom();
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
  dialog().addEventListener("close", () => { stopPolling(); document.removeEventListener("keydown", onKey); });
  const code = codeFromHash(window.location.hash);
  if (window.location.hash.includes("room=")) {
    // The code has been read; take it out of the address so a reload does not ask again.
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
  }
  return code;
}
