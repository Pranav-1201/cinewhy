/* The receipt: the product's promise made visible. Each aspect is a line item with one plain word for
   how reviewers felt (Loved, Liked, Mixed, Disliked, Panned), a thin diverging bar, what the word
   rests on ("Based on 238 review sentences about acting"), and the verbatim review sentences behind
   it, each stamped with the site it came from. Quotes are never generated or trimmed. The raw score
   is not printed; it sits in a hover title for the curious. */

import { h } from "./dom.js";
import { basisLine, reviewsLine, signed, sourceOf, sourceStamp, verdictFor } from "./format.js";
import { labelOf } from "./state.js";

/** Lines from a film page's aspects (AspectDetail). */
export const linesFromAspects = (aspects) =>
  aspects.map((a) => ({ aspect: a.aspect, score: a.score, support: a.support, quotes: a.evidence, weight: 0 }));

/** Lines from a recommendation's reasons (Reason). */
export const linesFromReasons = (reasons) =>
  reasons.map((r) => ({ aspect: r.aspect, score: r.movie_score, support: null, quotes: r.evidence, weight: r.user_weight }));

function bar(name, score) {
  const fill = h("span", { class: `fill ${score >= 0 ? "pos" : "neg"}`, vars: { "--w": `${Math.min(1, Math.abs(score)) * 50}%` } });
  return h("div", { class: "dbar", role: "img", "aria-label": `${name}: ${verdictFor(score)}` }, fill);
}

function quote(evidence) {
  const source = sourceOf(evidence.source_review_id);
  return h(
    "blockquote", {}, `“${evidence.text}”`,
    h("span", { class: "stamp" }, sourceStamp(source.label),
      evidence.source_url ? [" · ", h("a", { href: evidence.source_url, target: "_blank", rel: "noopener noreferrer", text: `Read more on ${source.label}` })] : null));
}

/**
 * @param {{title: string, lines: object[], bySource?: object, maxQuotes?: number, animate?: boolean, heading?: string}} options
 * A line may carry `supportNouns: [one, many]` to say what its count counts (default: review sentences).
 */
export function receipt({ title, lines, bySource, maxQuotes = 2, animate = true, heading = "What reviewers say" }) {
  const el = h(
    "article", { class: `receipt${animate ? " unfurl" : ""}`, "aria-label": `Review evidence for ${title}` },
    h("h3", { text: heading }),
    h("p", { class: "sub", text: reviewsLine(bySource) }));
  // One sentence often evidences two aspects; show it once and give the other line a different one.
  const shown = new Set();
  for (const line of lines) {
    const name = labelOf(line.aspect);
    const fresh = line.quotes.filter((q) => !shown.has(q.text)).slice(0, maxQuotes);
    fresh.forEach((q) => shown.add(q.text));
    const verdict = verdictFor(line.score);
    const basis = basisLine(line.support, name, line.supportNouns);
    el.append(
      h("div", { class: "line" },
        h("span", { text: line.weight > 0 ? `${name}, which you care about` : name }),
        h("span", { class: "dots", "aria-hidden": "true" }),
        h("span", { class: `value verdict-${verdict.toLowerCase()}`, title: `Score ${signed(line.score)}, on a scale from −1 (all criticism) to +1 (all praise)`, text: verdict })),
      bar(name, line.score),
      basis ? h("p", { class: "basis", text: basis }) : null,
      ...fresh.map(quote));
  }
  el.append(h("div", { class: "scale", "aria-hidden": "true" }, h("span", { text: "Panned" }), h("span", { text: "Loved" })));
  return el;
}
