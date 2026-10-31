/* The profile sheet: a summary of what the visitor has told us, shortcuts to the library and the
   rating dialog, the three tools that used to sit in the top bar, and the profile as a file to keep
   or move to another browser. Nothing here talks to the server. */

import { $, h } from "./dom.js";
import { importText } from "./profile.js";
import { counts, exportText, replaceProfile, resetTaste } from "./state.js";

const say = (text) => { $("#profile-message").textContent = text; };

function summary() {
  const n = counts();
  $("#profile-summary").replaceChildren(...[
    ["Watched", n.watched], ["Want to watch", n.want], ["Liked", n.liked], ["Not for me", n.disliked],
  ].map(([label, value]) => h("div", {}, h("dt", { text: label }), h("dd", { text: String(value) }))));
}

export function openProfile() {
  say("");
  summary();
  const dialog = $("#profile-dialog");
  if (!dialog.open) dialog.showModal();
}

/** Wire the sheet's buttons once, at boot. `ctx.refresh` redraws the shelves; `ctx.syncFilters` the chips. */
export function initProfile(ctx) {
  $("#profile-export").addEventListener("click", () => {
    const url = URL.createObjectURL(new Blob([exportText()], { type: "application/json" }));
    const link = h("a", { href: url, download: "cinewhy-profile.json" });
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    say("Your profile was downloaded as cinewhy-profile.json.");
  });

  $("#profile-import").addEventListener("change", async (event) => {
    const file = event.target.files[0];
    event.target.value = ""; // so choosing the same file again still fires
    if (!file) return;
    const result = importText(await file.text());
    if (!result.ok) { say(result.error); return; }
    replaceProfile(result.profile);
    ctx.syncFilters();
    ctx.refresh();
    summary();
    say("Profile loaded.");
  });

  // Two presses, not a browser confirm box: the second press within four seconds does it.
  const reset = $("#profile-reset");
  let armed = null;
  reset.addEventListener("click", () => {
    if (armed === null) {
      reset.textContent = "Press again to erase everything";
      armed = setTimeout(() => { armed = null; reset.textContent = "Reset everything"; }, 4000);
      return;
    }
    clearTimeout(armed);
    armed = null;
    reset.textContent = "Reset everything";
    resetTaste();
    ctx.syncFilters();
    ctx.refresh();
    summary();
    say("Everything was erased from this browser.");
  });
}
