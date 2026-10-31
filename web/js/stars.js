/* A row of five star buttons. `current` is 0 to 5; `onPick(n)` is called with the star pressed.
   Pressing the star that is already chosen clears it (onPick(null)), so a rating can be taken back. */

import { h, icon } from "./dom.js";

export function starRow(current, onPick, label = "Rating") {
  const buttons = [1, 2, 3, 4, 5].map((n) => h("button", {
    class: "star", type: "button", "aria-label": `${n} of 5 stars`, title: `${n} of 5`,
  }, icon("star", true)));
  const paint = (value) => buttons.forEach((button, i) => button.setAttribute("aria-pressed", String(i < value)));
  buttons.forEach((button, i) => button.addEventListener("click", () => {
    const next = i + 1 === current ? null : i + 1;
    current = next ?? 0;
    paint(current);
    onPick(next);
  }));
  paint(current);
  return h("span", { class: "stars", role: "group", "aria-label": label }, buttons);
}
