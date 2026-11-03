/* People: the "Starring" line on a film page, and a person's page. A person is found by name in the
   search box. Their page is the film drawer showing the titles they are billed in, ranked for the
   visitor by the server: the visitor's taste if it is known, popularity and recency if not. */

import { post } from "./api.js";
import { $, clear, fill, h } from "./dom.js";
import { openFilm } from "./film.js";
import { excludedIds, profileForApi, state } from "./state.js";
import { tile } from "./tile.js";

export const TOP = 40;

/** The request for a person's titles. Searching for a person is an explicit ask, so the era,
    language and genre chips do not narrow it; films the visitor has watched are still left out
    unless they chose to see them. */
export function personRequest(personId) {
  const req = { person_id: personId, limit: TOP, recency: state.recency, profile: profileForApi() };
  const watched = excludedIds();
  if (watched.length) req.exclude_movie_ids = watched;
  return req;
}

/** "Starring A, B, C" under a film's overview; each name opens that person's titles. Nothing when
    the build has no cast for the film. */
export function starring(cast) {
  if (!cast?.length) return null;
  return h("p", { class: "starring" },
    h("span", { class: "starring-label", text: "Starring " }),
    ...cast.flatMap((person, i) => [
      i ? ", " : null,
      h("button", { class: "link-btn", type: "button", onclick: () => openPerson(person), text: person.name }),
    ]));
}

/** The words above a person's list. */
export function personIntro(name, shown) {
  return shown
    ? `Titles with ${name}, best first for you${shown >= TOP ? ` (the top ${TOP})` : ""}.`
    : `Nothing left to recommend with ${name}: you have already rated or watched what we have.`;
}

/** Show a person's top titles in the film drawer. A tile opens that film in the same drawer. */
export async function openPerson(person) {
  const dialog = $("#film-dialog");
  const target = $("#film-body");
  clear(target);
  target.append(h("div", { class: "skeleton tall", role: "status", "aria-label": `Finding titles with ${person.name}` }));
  if (!dialog.open) dialog.showModal();
  try {
    const { items } = await post("/discover", personRequest(person.id));
    fill(target, [
      h("h2", { id: "film-title", text: person.name }),
      h("p", { class: "film-overview", text: personIntro(person.name, items.length) }),
      items.length ? h("ul", { class: "person-grid", "aria-label": `Titles with ${person.name}` }, items.map((item) => tile(item, openFilm))) : null,
    ]);
  } catch (err) {
    target.replaceChildren(h("p", { class: "film-overview", text: err.message }));
  }
}
