/* "How it works": every number comes from the server's eval.json, written when the artifacts were
   built. Nothing here is typed in by hand, so the page cannot drift from what was measured, and a
   field an older build lacks simply omits its card instead of printing NaN. */

import { api } from "./api.js";
import { $, h } from "./dom.js";
import { pct, signed, wilson } from "./format.js";
import { labelOf } from "./state.js";

const has = (x) => typeof x === "number" && Number.isFinite(x);
const SOURCE_NAMES = { acl: "aclImdb (IMDb reviews to 2011)", ebd: "IMDb reviews (to about 2020)", rt: "Rotten Tomatoes users" };
const SHORT = { acl: "aclImdb", ebd: "IMDb", rt: "Rotten Tomatoes" };

const table = (head, rows) => h("div", { class: "tablewrap" }, h("table", {},
  h("thead", {}, h("tr", {}, head.map((t) => h("th", { text: t })))),
  h("tbody", {}, rows.map((r) => h("tr", {}, r.map((c, i) => h("td", { class: i ? "num" : "", text: c })))))));

const prop = (o) => {
  const [lo, hi] = wilson(o.hits, o.n);
  return `${pct(o.hits / o.n)} [${pct(lo)}, ${pct(hi)}] (n=${o.n})`;
};
const interval = (i) => `${pct(i.mean)} [${pct(i.lo)}, ${pct(i.hi)}]`;
const diff = (i) => `${i.mean >= 0 ? "+" : "−"}${(Math.abs(i.mean) * 100).toFixed(1)} pts [${(i.lo * 100).toFixed(1)}, ${(i.hi * 100).toFixed(1)}]`;

function builtFrom(e) {
  const c = e.catalogue;
  if (!c) return null;
  const grid = c.films_by_language_and_era || {};
  const eras = [["pre2000", "Before 2000"], ["2000-2011", "2000 to 2011"], ["2012+", "2012 onward"]];
  const langs = [["en", "English"], ["hi", "Hindi"], ["te", "Telugu"], ["ja", "Japanese"], ["fr", "French"]];
  const rows = langs.filter(([l]) => eras.some(([k]) => grid[`${l}/${k}`])).map(([l, name]) => [name, ...eras.map(([k]) => (grid[`${l}/${k}`] || 0).toLocaleString("en"))]);
  return h("div", { class: "how-card" }, h("h3", { text: "What it is built from" }),
    h("p", { text: `${c.films.toLocaleString("en")} films, ${c.reviews?.toLocaleString("en") ?? "many"} reviews read, ${c.evidence_sentences?.toLocaleString("en") ?? "many"} sentences chosen as quotable.` }),
    rows.length ? table(["Films by", ...eras.map(([, t]) => t)], rows) : null,
    has(c.films_with_ratings) ? h("p", { text: `${c.films_with_ratings.toLocaleString("en")} of ${c.films.toLocaleString("en")} films have any MovieLens rating. The rest are placed by their reviews and IMDb scores instead of by viewers with similar taste.` }) : null,
    e.sources?.reviews ? h("p", { class: "note", text: e.sources.reviews }) : null);
}

function joinCard(e) {
  const j = e.join_check;
  if (!j || has(j.own_title_rate)) return null; // older builds had one combined number
  const rows = Object.keys(j).filter((k) => j[k]?.n_reviews).map((k) => [SOURCE_NAMES[k] || k, j[k].n_reviews.toLocaleString("en"), pct(j[k].own_title_rate), pct(j[k].other_title_rate)]);
  if (!rows.length) return null;
  return h("div", { class: "how-card" }, h("h3", { text: "Are the reviews about the right film?" }),
    h("p", { text: "Rotten Tomatoes and IMDb reviews are matched to films by title and year, so a wrong match is possible. As a check, how often does a review name its own film, against how often it names the next film's title?" }),
    table(["Source", "Reviews checked", "Name their own film", "Name another film"], rows),
    h("p", { class: "callout", text: "A wrong match would make the first number fall to the second. Rotten Tomatoes reviews are short, so they name their film less often, but the gap is still large." }));
}

function readingCard(e) {
  const doc = e.polarity_domain;
  const d = doc?.by_source;
  const before = doc?.before_retraining; // present once the model was retrained on mixed sources
  const pol = e.polarity;
  if (!d && !pol) return null;
  const rows = [];
  if (pol && has(pol.official_test_accuracy)) {
    const label = before ? "aclImdb (its official test split)" : "aclImdb (what it was trained on)";
    const row = [label, pol.official_test_n?.toLocaleString("en") ?? "", `${pct(pol.official_test_accuracy)} ± ${(pol.official_test_ci95 * 100).toFixed(1)}`];
    rows.push(before ? [...row, "", "", ""] : [...row, "", ""]);
  }
  for (const k of Object.keys(d || {})) {
    const s = d[k];
    if (!s?.n) continue;
    const row = [SHORT[k] || k, s.n.toLocaleString("en"), `${pct(s.accuracy)} [${pct(s.ci95[0])}, ${pct(s.ci95[1])}]`];
    if (before) row.push(before[k]?.n ? pct(before[k].accuracy) : "");
    row.push(pct(s.positive_recall), pct(s.negative_recall));
    rows.push(row);
  }
  const head = before
    ? ["Source", "Reviews", "Right (95% interval)", "Before retraining", "Praise found", "Criticism found"]
    : ["Source", "Reviews", "Right (95% interval)", "Praise found", "Criticism found"];
  const intro = before
    ? "The model that decides whether a sentence is praise or criticism first learned from IMDb reviews written in 2011, and was weak on newer text. It was retrained on those plus Rotten Tomatoes and later IMDb reviews. These scores use only films held out of that training, with each reviewer's own star rating as the answer, and the same reviews were scored by the earlier model."
    : "The model that decides whether a sentence is praise or criticism learned from IMDb reviews written in 2011. We tested it on newer text from each source, using each reviewer's own star rating as the answer.";
  const worst = Object.entries(d || {}).filter(([, s]) => s?.n).sort((a, b) => a[1].accuracy - b[1].accuracy)[0];
  return h("div", { class: "how-card" }, h("h3", { text: "Does it read newer reviews correctly?" }),
    h("p", { text: intro }),
    table(head, rows),
    worst ? h("p", { class: "callout", text: `It is weakest on ${SHORT[worst[0]] || worst[0]} text (${pct(worst[1].accuracy)}). Treat scores for films whose evidence mostly comes from there as less certain.` }) : null);
}

function aspectCard(e) {
  const rg = e.random_gold;
  if (!rg?.c) return null;
  const clean = rg.c, pooled = rg.clean_pooled_b_c;
  return h("div", { class: "how-card" }, h("h3", { text: "Does it find what reviewers talk about?" }),
    h("p", { text: `Measured on ${clean.n_clauses} clauses drawn at random from reviews it never saw, so misses count as well as hits.` }),
    table(["Measure", "Result [95% interval]"], [
      ["Real aspect mentions it finds", prop(clean.detector_recall)],
      ["Flagged mentions that are really about that aspect", prop(clean.detector_precision)],
      ["Praise or criticism read correctly" + (pooled ? " (two samples pooled)" : ""), prop(pooled ? pooled.polarity_accuracy : clean.polarity_accuracy)],
    ]),
    h("p", { class: "callout", text: `Read this plainly: the aspect finder found ${pct(clean.detector_recall.hits / clean.detector_recall.n, 0)} of the real mentions, and ${pct(1 - clean.detector_precision.hits / clean.detector_precision.n, 0)} of what it flagged was not really about that aspect. The scores and quotes you see are a sample of what was said, not all of it.` }),
    e.gold_note ? h("p", { class: "note", text: e.gold_note }) : null);
}

function sliderCard(e) {
  const sc = e.slider_check;
  if (!sc) return null;
  return h("div", { class: "how-card" }, h("h3", { text: "Do the dials do what they say?" }),
    h("p", { text: "Each aspect dial was pushed to the top and the first 20 films compared with the default list." }),
    table(["Aspect", "Default list", "Dial at 100%", "Lift"], Object.keys(sc).map((a) => [labelOf(a), signed(sc[a].default), signed(sc[a].steered), signed(sc[a].lift)])),
    h("p", { class: "callout", text: "This shows the dials steer the results the way they are labelled. It does not show that your stated preferences predict what you will enjoy: there is no way to test that offline." }));
}

function recommenderCard(e) {
  const rec = e.recommender;
  if (!rec?.methods) return null;
  const by = Object.fromEntries(rec.methods.map((m) => [m.name, m]));
  const d20 = (a, b) => rec.differences.find((x) => x.a === a && x.b === b && x.k === 20);
  const cf = d20("cf", "popularity"), hy = d20("hybrid", "cf");
  const row = (n, t) => [t, interval(by[n].hit_rate[10]), interval(by[n].hit_rate[20])];
  return h("div", { class: "how-card" }, h("h3", { text: "Does it find films people liked?" }),
    h("p", { text: `For ${rec.n_test_users.toLocaleString("en")} MovieLens users held out of the fitting, one film they liked was hidden and the model saw up to ${rec.seeds_per_user} others. Hit rate is how often the hidden film lands in the top 10 or 20 of ${e.catalogue.films.toLocaleString("en")}.` }),
    table(["Method", "In the top 10", "In the top 20"], [row("popularity", "Most popular (baseline)"), row("cf", "Viewers with similar taste"), row("aspect", "Matching review aspects"), row("hybrid", "Both together (what you see)")]),
    cf && hy ? h("p", { class: "callout", text: `Viewers with similar taste beat the baseline by ${diff(cf.diff)} at 20. Adding review aspects changes that by ${diff(hy.diff)}, and buys the ability to show real sentences for every pick.` }) : null,
    h("p", { class: "note", text: "These users rated films on MovieLens, which mostly covers English-language films; Hindi films cannot be measured this way." }));
}

function recencyCard(e) {
  const r = e.recency;
  if (!r?.cold_start?.by_recency?.length) return null;
  const size = r.cold_start.page_size;
  const rows = r.cold_start.by_recency.map((row) => [
    row.recency === 0 ? "No preference" : pct(row.recency, 0),
    `${row.from_2000} of ${row.films}`,
    `${row.from_2012} of ${row.films}`,
    String(row.median_year),
  ]);
  const cost = r.cost;
  const costRows = cost ? Object.values(cost.settings).sort((a, b) => a.recency - b.recency).map((s) => {
    const d = s.vs_hybrid?.[20];
    return d ? [pct(s.recency, 0), interval(s.hit_rate[20]), diff(d)] : null;
  }).filter(Boolean) : [];
  return h("div", { class: "how-card" }, h("h3", { text: "Does “how new” do what it says?" }),
    h("p", { text: `With nothing known about you, the first ${size} films at each setting. ${pct(r.cold_start.catalogue_share_from_2000, 0)} of the catalogue is from 2000 on.` }),
    table(["How new", "From 2000 on", "From 2012 on", "Median year"], rows),
    costRows.length ? h("p", { text: "What it costs: for held-out MovieLens users, how often a film they liked stays in the top 20 when the newer-film lift is added." }) : null,
    costRows.length ? table(["How new", "Hit rate at 20", "Change [95% interval]"], costRows) : null,
    h("p", { class: "note", text: (r.note || "").replaceAll("`", "") }));
}

function limitsCard(e) {
  const c = e.catalogue || {};
  const items = [];
  if (has(c.films_with_ratings) && has(c.films)) items.push(`${(c.films - c.films_with_ratings).toLocaleString("en")} films have no MovieLens ratings, so they have no “viewers like you” signal.`);
  items.push("Aspect scores come from the reviews we could match to each film. Treat them as hints, not verdicts.");
  const rc = e.random_gold?.c?.detector_recall;
  if (rc?.n) items.push(`The aspect finder is a word list: on fresh text it found ${pct(rc.hits / rc.n, 0)} of real mentions.`);
  items.push("Quality labels for aspect tests were written by the assistant that built the system, not by independent annotators.");
  items.push("Dial settings you choose cannot be validated offline: there is no ground truth for stated preferences.");
  return h("div", { class: "how-card" }, h("h3", { text: "Limits you should know about" }), h("ul", {}, items.map((t) => h("li", { text: t }))));
}

export async function renderAbout() {
  const root = $("#about-body");
  root.replaceChildren(h("h2", { id: "about-title", text: "How it works" }), h("p", { class: "lede", text: "Loading the numbers." }));
  try {
    const e = await api("/metrics");
    if (!e.catalogue) { root.replaceChildren(h("h2", { id: "about-title", text: "How it works" }), h("p", { class: "lede", text: "No evaluation was built with these artifacts." })); return; }
    const cards = [builtFrom(e), joinCard(e), readingCard(e), aspectCard(e), sliderCard(e), recommenderCard(e), recencyCard(e), limitsCard(e)].filter(Boolean);
    root.replaceChildren(
      h("h2", { id: "about-title", text: "How it works" }),
      h("p", { class: "lede", text: "Every pick is backed by real review sentences. These are the measured limits of the machinery behind them, written when this build was made." }),
      h("div", { class: "how-grid" }, cards));
  } catch (err) {
    root.replaceChildren(h("h2", { id: "about-title", text: "How it works" }), h("p", { class: "lede", text: err.message }));
  }
}
