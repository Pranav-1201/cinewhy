/* Poster tiles. A poster is a gradient tile with the title on it, covered by the real poster once
   it loads: a missing or slow image leaves a deliberate-looking tile, never a hole. */

import { h, icon } from "./dom.js";
import { hueOf } from "./format.js";
import { isWanted, isWatched, labelOf, opinionOf, setOpinion, setWant, setWatched } from "./state.js";

export function poster(movie, { language = null, isNew = false } = {}) {
  const el = h(
    "span", { class: "poster", vars: { "--hue": hueOf(movie.movie_id) } },
    h("span", { class: "fallback", "aria-hidden": "true", text: movie.title }));
  if (movie.poster_url) {
    const img = h("img", { src: movie.poster_url, alt: "", loading: "lazy", decoding: "async" });
    img.addEventListener("load", () => img.classList.add("loaded"));
    img.addEventListener("error", () => img.remove());
    el.append(img);
  }
  if (isNew) el.append(h("span", { class: "badge", text: "New" }));
  if (language === "hi") el.append(h("span", { class: "badge lang", text: "Hindi" }));
  return el;
}

/** The three quick answers on a tile: like, seen it, want to watch. One answer can change another
    (seeing a film takes it off the want-to-watch list), so every button re-reads after a click. */
export function tileActions(movie) {
  const id = movie.movie_id;
  const specs = [
    { cls: "like", glyph: "heart", label: `Like ${movie.title}`, isOn: () => opinionOf(id) === "like",
      flip: () => setOpinion(movie, opinionOf(id) === "like" ? null : "like") },
    { cls: "seen", glyph: "eye", label: `I have watched ${movie.title}`, isOn: () => isWatched(id),
      flip: () => setWatched(movie, !isWatched(id)) },
    { cls: "save", glyph: "bookmark", label: `Want to watch ${movie.title}`, isOn: () => isWanted(id),
      flip: () => setWant(movie, !isWanted(id)) },
  ];
  const buttons = specs.map((spec) => h("button", {
    class: `tile-act ${spec.cls}`, type: "button", "aria-label": spec.label, title: spec.label,
  }, icon(spec.glyph, spec.glyph !== "eye")));
  const sync = () => buttons.forEach((button, i) => button.setAttribute("aria-pressed", String(specs[i].isOn())));
  buttons.forEach((button, i) => button.addEventListener("click", (event) => {
    event.stopPropagation();
    specs[i].flip();
    sync();
    document.dispatchEvent(new CustomEvent("cinewhy:opinion"));
  }));
  sync();
  return h("div", { class: "tile-acts" }, buttons);
}

/** One list item for a rail. `item` is a DiscoverItem from the server. */
export function tile(item, open) {
  const m = item.movie;
  const top = item.reasons?.[0];
  // The plainest reason first: a film the visitor already liked that this one resembles.
  const why = item.because
    ? `Because you liked ${item.because}`
    : top
      ? (top.user_weight > 0 ? `Matches your ${labelOf(top.aspect).toLowerCase()}` : `Praised for ${labelOf(top.aspect).toLowerCase()}`)
      : null;
  const button = h(
    "button", {
      class: "tile-btn", type: "button",
      "aria-label": `${m.title}${m.year ? `, ${m.year}` : ""}. Open details`,
      onclick: () => open(m.movie_id),
    },
    poster(m, { language: item.language, isNew: item.is_new }),
    h("span", { class: "tile-title", text: m.title }),
    h("span", { class: "tile-meta", text: m.year ? String(m.year) : "" }),
    why ? h("span", { class: "tile-why", text: why }) : null);
  return h("li", { class: "tile" }, button, tileActions(m));
}

