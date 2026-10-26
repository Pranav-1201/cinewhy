/* Dialogs: taste dials, the optional first-visit questions, and the review analyzer. Every answer
   stays in this browser. Nothing here is required: skipping any question is always allowed. */

import { post } from "./api.js";
import { $, clear, h } from "./dom.js";
import { pct, recencyForAge, signed } from "./format.js";
import { receipt } from "./receipt.js";
import { labelOf, resetTaste, save, state } from "./state.js";

const AGES = [["under-18", "Under 18"], ["18-24", "18 to 24"], ["25-34", "25 to 34"], ["35-44", "35 to 44"], ["45+", "45 and over"]];
const REGIONS = [["india", "India"], ["north-america", "North America"], ["europe", "Europe"], ["elsewhere", "Somewhere else"]];
const LANGUAGES = [["en", "English"], ["hi", "Hindi"]];
const SEXES = [["female", "Woman"], ["male", "Man"], ["other", "Another way"]];

/** Chip group inside `root`. Returns a function that reads the current choices. */
function chipGroup(root, options, chosen, multi) {
  const selected = new Set(chosen);
  clear(root);
  const buttons = options.map(([value, text]) => {
    const button = h("button", { class: "chip", type: "button", "aria-pressed": String(selected.has(value)), text });
    button.addEventListener("click", () => {
      if (selected.has(value)) selected.delete(value);
      else { if (!multi) selected.clear(); selected.add(value); }
      buttons.forEach((b, i) => b.setAttribute("aria-pressed", String(selected.has(options[i][0]))));
    });
    return button;
  });
  root.append(...buttons);
  return () => [...selected];
}

export function openTaste(ctx) {
  const box = $("#dials");
  clear(box);
  const recency = $("#recency");
  const recencyOut = $("#recency-out");
  const words = (v) => (v === 0 ? "No preference" : pct(v, 0));
  recency.value = String(state.recency);
  recencyOut.textContent = words(state.recency);
  recency.oninput = () => {
    state.recency = Number(recency.value);
    state.recencyTouched = true;
    recencyOut.textContent = words(state.recency);
    save(); ctx.refresh();
  };
  for (const a of ctx.aspects) {
    const out = h("output", { text: state.weights[a.aspect] ? pct(state.weights[a.aspect], 0) : "off" });
    const input = h("input", { type: "range", id: `w-${a.aspect}`, min: "0", max: "1", step: "0.05", value: String(state.weights[a.aspect] || 0) });
    input.addEventListener("input", () => {
      const v = Number(input.value);
      if (v > 0) state.weights[a.aspect] = v; else delete state.weights[a.aspect];
      out.textContent = v > 0 ? pct(v, 0) : "off";
      save(); ctx.refresh();
    });
    box.append(h("div", { class: "dial" }, h("label", { for: `w-${a.aspect}` }, h("span", { text: a.label }), out), h("p", { class: "desc", text: a.description }), input));
  }
  $("#taste-dialog").showModal();
}

export function openOnboarding(ctx) {
  const readLang = chipGroup($("#ob-lang"), LANGUAGES, state.languages, true);
  const readAge = chipGroup($("#ob-age"), AGES, state.age ? [state.age] : [], false);
  const readRegion = chipGroup($("#ob-region"), REGIONS, state.region ? [state.region] : [], false);
  const sexField = $("#ob-sex-field");
  // Sex is asked only when the server reports a measured demographic prior that uses it.
  sexField.hidden = !ctx.facets.demographics_enabled;
  const readSex = chipGroup($("#ob-sex"), SEXES, state.sex ? [state.sex] : [], false);
  $("#ob-note").textContent = ctx.facets.demographics_enabled
    ? "Age sets how much newer films come first, region decides which shelf leads, and your answers also tune the first page. You can change all of it under Your taste."
    : "Age sets how much newer films come first and region decides which shelf leads. Nothing else is inferred from your answers. You can change both under Your taste.";
  const form = $("#onboard-form");
  form.onsubmit = (event) => {
    if (event.submitter?.value === "save") {
      state.languages = readLang();
      state.age = readAge()[0] ?? null;
      state.region = readRegion()[0] ?? null;
      state.sex = sexField.hidden ? null : (readSex()[0] ?? null);
      state.hindiFirst = state.region === "india";
      if (!state.recencyTouched) state.recency = recencyForAge(state.age);
    }
    state.onboarded = true;
    save();
    ctx.syncFilters();
    ctx.refresh();
  };
  $("#onboard-dialog").showModal();
}

const SAMPLE = "The acting was brilliant and the soundtrack was wonderful, but the pacing dragged badly in the middle. The ending was a letdown. I would happily watch it again.";

function wireReviewDialog() {
  $("#sample").addEventListener("click", () => { $("#review-text").value = SAMPLE; });
  $("#analyze").addEventListener("click", async () => {
    const out = $("#analysis");
    const text = $("#review-text").value.trim();
    if (!text) { out.replaceChildren(h("p", { class: "note", text: "Paste some text first." })); return; }
    out.replaceChildren(h("p", { class: "note", text: "Reading it." }));
    try {
      const r = await post("/analyze", { text });
      const body = r.sentences.map((s) => h("span", {}, s.clauses.map((c) => {
        const strongest = c.mentions.slice().sort((a, b) => Math.abs(b.polarity) - Math.abs(a.polarity))[0];
        const tone = strongest && Math.abs(strongest.polarity) >= 0.2 ? (strongest.polarity > 0 ? "pos" : "neg") : "";
        return h("span", { class: "clause" }, h("mark", { class: tone, text: c.text }),
          c.mentions.map((m) => h("span", { class: "chip static", text: `${labelOf(m.aspect)} ${signed(m.polarity)}` })), " ");
      })));
      const lines = r.summary.map((s) => ({ aspect: s.aspect, score: s.polarity, support: s.mentions, supportLabel: "mentions", quotes: [], weight: 0 }));
      out.replaceChildren(
        h("p", { class: "analysis-text" }, body),
        lines.length ? receipt({ title: "your review", lines, heading: "What your review says", animate: false }) : h("p", { class: "note", text: "No aspect was judged in this text." }),
        h("p", { class: "note", text: `The whole review reads as ${r.overall >= 0 ? "positive" : "negative"} (${signed(r.overall)}). Single clauses are harder to judge than whole reviews; see How it works for how often it is right.` }));
    } catch (err) {
      out.replaceChildren(h("p", { class: "note", text: err.message }));
    }
  });
}

export function initDialogs(ctx) {
  for (const dialog of document.querySelectorAll("dialog")) {
    dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  }
  for (const button of document.querySelectorAll("[data-close]")) {
    button.addEventListener("click", () => button.closest("dialog").close());
  }
  $("#reset").addEventListener("click", () => {
    resetTaste(); ctx.syncFilters(); openTaste(ctx); ctx.refresh();
  });
  $("#redo-onboarding").addEventListener("click", () => { $("#taste-dialog").close(); openOnboarding(ctx); });
  wireReviewDialog();
}
