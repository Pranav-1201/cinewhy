/* The film drawer: poster, facts, the full receipt, and where to read the real reviews. */

import { api } from "./api.js";
import { $, clear, h } from "./dom.js";
import { languageName, runtimeLabel } from "./format.js";
import { linesFromAspects, receipt } from "./receipt.js";
import { opinionOf, setOpinion } from "./state.js";
import { poster } from "./tile.js";

/** A button that toggles one opinion (like, or dislike) for a film and tells the page. */
function opinionButton(movie, kind, offText, onText) {
  const button = h("button", { class: "btn", type: "button" });
  const sync = () => {
    const on = opinionOf(movie.movie_id) === kind;
    button.setAttribute("aria-pressed", String(on));
    button.textContent = on ? onText : offText;
  };
  button.addEventListener("click", () => {
    setOpinion(movie, opinionOf(movie.movie_id) === kind ? null : kind);
    sync();
    document.dispatchEvent(new CustomEvent("cinewhy:opinion"));
  });
  sync();
  return button;
}

function actions(movie, d) {
  return h(
    "div", { class: "film-actions" },
    opinionButton(movie, "like", "Like", "Liked"),
    opinionButton(movie, "dislike", "Not for me", "Marked as not for me"),
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
      ? receipt({ title: m.title, lines: linesFromAspects(d.aspects), bySource: d.reviews_by_source, heading: `Receipt for ${m.title}` })
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
    target.replaceChildren(...body(await api(`/movie/${encodeURIComponent(id)}`)));
  } catch (err) {
    target.replaceChildren(h("p", { class: "film-overview", text: err.message }));
  }
}
