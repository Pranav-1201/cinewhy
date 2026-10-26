/* Poster tiles. A poster is a gradient tile with the title on it, covered by the real poster once
   it loads: a missing or slow image leaves a deliberate-looking tile, never a hole. */

import { h, icon } from "./dom.js";
import { hueOf } from "./format.js";
import { labelOf, opinionOf, setOpinion } from "./state.js";

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

/** The like button used on tiles, the spotlight and the film drawer. */
export function likeButton(movie) {
  const button = h("button", {
    class: "like", type: "button", "aria-pressed": String(opinionOf(movie.movie_id) === "like"),
    "aria-label": `Like ${movie.title}`,
  }, icon("heart", true));
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    setOpinion(movie, opinionOf(movie.movie_id) === "like" ? null : "like");
    button.setAttribute("aria-pressed", String(opinionOf(movie.movie_id) === "like"));
    document.dispatchEvent(new CustomEvent("cinewhy:opinion"));
  });
  return button;
}

/** One list item for a rail. `item` is a DiscoverItem from the server. */
export function tile(item, open) {
  const m = item.movie;
  const top = item.reasons?.[0];
  const why = top
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
  return h("li", { class: "tile" }, button, likeButton(m));
}

/** Average hue (0-359) of the vivid pixels in a poster, or null when the image cannot be read. */
export function sampleHue(url) {
  return new Promise((resolve) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      try {
        const canvas = document.createElement("canvas");
        canvas.width = 24; canvas.height = 36;
        const ctx = canvas.getContext("2d", { willReadFrequently: true });
        ctx.drawImage(img, 0, 0, 24, 36);
        const { data } = ctx.getImageData(0, 0, 24, 36);
        let x = 0, y = 0, weight = 0;
        for (let i = 0; i < data.length; i += 4) {
          const r = data[i] / 255, g = data[i + 1] / 255, b = data[i + 2] / 255;
          const max = Math.max(r, g, b), min = Math.min(r, g, b);
          const sat = max === 0 ? 0 : (max - min) / max;
          const w = sat * max; // vivid and bright pixels decide the colour; greys and shadows do not
          if (w < 0.05) continue;
          let hue;
          if (max === min) continue;
          if (max === r) hue = ((g - b) / (max - min)) % 6;
          else if (max === g) hue = (b - r) / (max - min) + 2;
          else hue = (r - g) / (max - min) + 4;
          const angle = (hue * 60 + 360) % 360 * (Math.PI / 180);
          x += Math.cos(angle) * w; y += Math.sin(angle) * w; weight += w;
        }
        resolve(weight > 0 ? Math.round(((Math.atan2(y, x) * 180) / Math.PI + 360) % 360) : null);
      } catch (_) { resolve(null); } // a tainted canvas throws: fall back to the id-based hue
    };
    img.onerror = () => resolve(null);
    img.src = url;
  });
}
