/* The receipt: the product's promise made visible. Each aspect is a line item with a dotted leader
   to its score, a thin diverging bar, and the verbatim review sentences behind it, each stamped
   with the site it came from. Quotes are never generated or trimmed. */

import { h } from "./dom.js";
import { reviewsLine, signed, sourceOf } from "./format.js";
import { labelOf } from "./state.js";

/** Lines from a film page's aspects (AspectDetail). */
export const linesFromAspects = (aspects) =>
  aspects.map((a) => ({ aspect: a.aspect, score: a.score, support: a.support, quotes: a.evidence, weight: 0 }));

/** Lines from a recommendation's reasons (Reason). */
export const linesFromReasons = (reasons) =>
  reasons.map((r) => ({ aspect: r.aspect, score: r.movie_score, support: null, quotes: r.evidence, weight: r.user_weight }));

function bar(name, score) {
  const fill = h("span", { class: `fill ${score >= 0 ? "pos" : "neg"}`, vars: { "--w": `${Math.min(1, Math.abs(score)) * 50}%` } });
  return h("div", { class: "dbar", role: "img", "aria-label": `${name}: ${signed(score)}` }, fill);
}

function quote(evidence) {
  const source = sourceOf(evidence.source_review_id);
  return h(
    "blockquote", {}, `“${evidence.text}”`,
    h("span", { class: "stamp" }, `${source.label} review`,
      evidence.source_url ? [" ", h("a", { href: evidence.source_url, target: "_blank", rel: "noopener noreferrer", text: "see the film's reviews" })] : null));
}

/**
 * @param {{title: string, lines: object[], bySource?: object, maxQuotes?: number, animate?: boolean, heading?: string}} options
 */
export function receipt({ title, lines, bySource, maxQuotes = 2, animate = true, heading = "Why this film" }) {
  const el = h(
    "article", { class: `receipt${animate ? " unfurl" : ""}`, "aria-label": `Review evidence for ${title}` },
    h("h3", { text: heading }),
    h("p", { class: "sub", text: reviewsLine(bySource) }));
  for (const line of lines) {
    const name = labelOf(line.aspect);
    el.append(
      h("div", { class: "line" },
        h("span", { text: line.weight > 0 ? `${name}, which you care about` : name }),
        h("span", { class: "dots", "aria-hidden": "true" }),
        h("span", { class: "value" }, signed(line.score),
          line.support ? h("span", { class: "support", text: ` (${line.support.toLocaleString("en")} sentences)` }) : null)),
      bar(name, line.score),
      ...line.quotes.slice(0, maxQuotes).map(quote));
  }
  el.append(h("div", { class: "scale", "aria-hidden": "true" }, h("span", { text: "Criticism" }), h("span", { text: "Praise" })));
  return el;
}
