/* The film drawer: poster, facts, the full receipt, and where to read the real reviews. */

import { api } from "./api.js";
import { $, clear, fill, h } from "./dom.js";
import { languageName, runtimeLabel } from "./format.js";
import { linesFromAspects, receipt } from "./receipt.js";
import { isWanted, isWatched, opinionOf, setOpinion, setWant, setWatched } from "./state.js";
import { poster } from "./tile.js";

/** The yes/no answers the visitor can give about a film, each with its two wordings. */
function answers(movie) {
  const id = movie.movie_id;
  const opinion = (kind) => ({
    isOn: () => opinionOf(id) === kind,
    flip: () => setOpinion(movie, opinionOf(id) === kind ? null : kind),
  });
  return [
    { ...opinion("like"), off: "Like", on: "Liked" },
    { ...opinion("dislike"), off: "Not for me", on: "Marked as not for me" },
    { isOn: () => isWatched(id), flip: () => setWatched(movie, !isWatched(id)), off: "I've watched it", on: "Watched" },
    { isOn: () => isWanted(id), flip: () => setWant(movie, !isWanted(id)), off: "Want to watch", on: "On my list" },
  ];
}

/** The answer buttons. After any click every button re-reads the profile, because one answer can
    change another (watching a film takes it off the want-to-watch list). */
function actions(movie, d) {
  const specs = answers(movie);
  const buttons = specs.map(() => h("button", { class: "btn", type: "button" }));
  const sync = () => buttons.forEach((button, i) => {
    const on = specs[i].isOn();
    button.setAttribute("aria-pressed", String(on));
    button.textContent = on ? specs[i].on : specs[i].off;
  });
  buttons.forEach((button, i) => button.addEventListener("click", () => {
    specs[i].flip();
    sync();
    document.dispatchEvent(new CustomEvent("cinewhy:opinion"));
  }));
  sync();
  return h(
    "div", { class: "film-actions" },
    buttons,
    h("a", { class: "btn", href: d.imdb_url, target: "_blank", rel: "noopener noreferrer", text: "IMDb" }),
    d.rt_url ? h("a", { class: "btn", href: d.rt_url, target: "_blank", rel: "noopener noreferrer", text: "Rotten Tomatoes" }) : null);
}

function body(d) {
  const m = d.movie;
  const chips = [m.year ? String(m.year) : "", languageName(d.language), runtimeLabel(d.runtime_minutes), ...(m.genres || []).slice(0, 3)].filter(Boolean);
  const ratings = d.rating_count > 0
    ? `${d.rating_count.toLocaleString("en")} MovieLens ratings, adjusted mean ${d.mean_rating}.`
    : "No MovieLens ratings, so there is no “viewers like you” signal for this film. It is placed by its reviews and its IMDb score.";
  return [
    h("div", { class: "film-head" },
      poster(m, { language: d.language }),
      h("div", {}, h("h2", { id: "film-title", text: m.title }), h("div", { class: "meta" }, chips.map((c) => h("span", { class: "chip static", text: c }))))),
    d.overview ? h("p", { class: "film-overview", text: d.overview }) : null,
    actions(m, d),
    d.aspects.length
      ? receipt({ title: m.title, lines: linesFromAspects(d.aspects), bySource: d.reviews_by_source, heading: `What reviewers say about ${m.title}` })
      : h("p", { class: "film-overview", text: "Not enough reviews mention any single aspect to score it." }),
    h("p", { class: "film-links", text: ratings }),
  ];
}

export async function openFilm(id) {
  const dialog = $("#film-dialog");
  const target = $("#film-body");
  clear(target);
  target.append(h("div", { class: "skeleton tall", role: "status", "aria-label": "Loading the film" }));
  if (!dialog.open) dialog.showModal();
  try {
    fill(target, body(await api(`/movie/${encodeURIComponent(id)}`)));
  } catch (err) {
    target.replaceChildren(h("p", { class: "film-overview", text: err.message }));
  }
}
