/* DOM helpers. Everything the page shows from the server goes through textContent via `h`, never
   innerHTML: the server's content-security-policy and the "no markup from data" rule depend on it.
   Styles are set as custom properties through the CSSOM (`vars`), never as inline style text. */

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/** Create an element. Children may be strings (inserted as text), nodes, or nested arrays. */
export function h(tag, props = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k === "vars") for (const [name, value] of Object.entries(v)) el.style.setProperty(name, String(value));
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

const SVG = "http://www.w3.org/2000/svg";
const ICONS = {
  heart: "M12 21s-7.5-4.6-9.6-9.2C.9 8.5 2.9 4.5 6.6 4.5c2 0 3.5 1 5.4 3 1.9-2 3.4-3 5.4-3 3.7 0 5.7 4 4.2 7.3C19.5 16.4 12 21 12 21z",
  left: "M15 5l-7 7 7 7",
  right: "M9 5l7 7-7 7",
};

/** A small inline icon built with DOM calls (no markup string). `filled` draws a solid shape. */
export function icon(name, filled = false) {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(SVG, "path");
  path.setAttribute("d", ICONS[name]);
  if (!filled) {
    for (const [k, v] of Object.entries({ fill: "none", stroke: "currentColor", "stroke-width": "2", "stroke-linecap": "round", "stroke-linejoin": "round" })) path.setAttribute(k, v);
  }
  svg.append(path);
  return svg;
}

export const clear = (el) => el.replaceChildren();

export function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

/** True when the visitor asked the system for less motion. */
export const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
