/* CineWhy front end. No build step; no innerHTML with server data (everything goes through
   textContent), which is what lets the server send a strict Content-Security-Policy. */
(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);

  /** Create an element. Children may be strings (inserted as text) or nodes. */
  function h(tag, props = {}, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) {
      if (kid === null || kid === undefined || kid === false) continue;
      el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }

  const signed = (x) => (x >= 0 ? "+" : "−") + Math.abs(x).toFixed(2);
  const pct = (x, digits = 1) => (100 * x).toFixed(digits) + "%";

  // ---- state (taste profile lives in this browser only; the server stores nothing) --------
  const KEY = "cinewhy.profile.v1";
  const state = { weights: {}, liked: [], disliked: [], titles: {} };
  try {
    Object.assign(state, JSON.parse(localStorage.getItem(KEY) || "{}"));
  } catch (_) { /* private mode or corrupt value: start empty */ }
  const save = () => {
    try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (_) { /* ignore */ }
  };

  let aspects = [];
  const label = (id) => (aspects.find((a) => a.aspect === id) || { label: id }).label;

  async function api(path, options) {
    const response = await fetch(path, options);
    if (!response.ok) {
      let detail = "";
      try {
        const body = await response.json();
        detail = body.error_id ? ` (error id ${body.error_id})` : body.detail ? `: ${body.detail}` : "";
      } catch (_) { /* no JSON body */ }
      throw new Error(`Request failed (${response.status})${detail}`);
    }
    return response.json();
  }
  const post = (path, body) =>
    api(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  const debounce = (fn, ms) => {
    let t;
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
  };

  // ---- the diverging bar: centre = 0, blue right = praise, red left = criticism -----------
  function dbar(name, value, support) {
    const half = Math.min(1, Math.abs(value)) * 50;
    const fill = h("span", { class: "fill " + (value >= 0 ? "pos" : "neg") });
    fill.style.width = half + "%";
    return h("div", { class: "dbar", role: "img", "aria-label": `${name}: ${signed(value)}${support ? `, from ${support} sentences` : ""}` },
      h("span", { text: name }),
      h("span", { class: "track" }, fill),
      h("span", { class: "val" }, signed(value), support ? h("small", { text: ` n=${support}` }) : null));
  }

  function quote(e) {
    const cite = h("cite", {}, `${signed(e.polarity)} · aclImdb review ${e.source_review_id} `,
      e.source_url ? h("a", { href: e.source_url, target: "_blank", rel: "noopener noreferrer", text: "film's reviews on IMDb" }) : null);
    return h("blockquote", {}, "“" + e.text + "”", cite);
  }

  // ---- tabs --------------------------------------------------------------------------------
  const tabs = ["discover", "analyze", "eval"];
  function showTab(name) {
    for (const t of tabs) {
      $("#tab-" + t).setAttribute("aria-selected", String(t === name));
      $("#panel-" + t).hidden = t !== name;
    }
    if (name === "eval") renderEval();
  }
  for (const t of tabs) $("#tab-" + t).addEventListener("click", () => showTab(t));

  // ---- taste: sliders, search, list --------------------------------------------------------
  function renderSliders() {
    const box = $("#sliders");
    box.replaceChildren();
    for (const a of aspects) {
      const out = h("span", { text: (state.weights[a.aspect] || 0) ? pct(state.weights[a.aspect], 0) : "off" });
      const input = h("input", { type: "range", id: "w-" + a.aspect, min: "0", max: "1", step: "0.05", value: String(state.weights[a.aspect] || 0) });
      input.addEventListener("input", () => {
        const v = Number(input.value);
        if (v > 0) state.weights[a.aspect] = v; else delete state.weights[a.aspect];
        out.textContent = v > 0 ? pct(v, 0) : "off";
        save(); refresh();
      });
      box.append(h("div", { class: "slider" },
        h("label", { for: "w-" + a.aspect }, h("span", { text: a.label }), out),
        h("p", { class: "desc", text: a.description }), input));
    }
  }

  function setOpinion(movie, opinion) {
    state.titles[movie.movie_id] = movie.title + (movie.year ? ` (${movie.year})` : "");
    const drop = (list) => list.filter((id) => id !== movie.movie_id);
    state.liked = drop(state.liked);
    state.disliked = drop(state.disliked);
    if (opinion === "like") state.liked.push(movie.movie_id);
    if (opinion === "dislike") state.disliked.push(movie.movie_id);
    save(); renderList(); refresh();
  }
  const opinionOf = (id) => (state.liked.includes(id) ? "like" : state.disliked.includes(id) ? "dislike" : null);

  function opinionButtons(movie, onChange) {
    const make = (kind, text) => {
      const b = h("button", { class: "mini", type: "button", "aria-pressed": String(opinionOf(movie.movie_id) === kind), text });
      b.addEventListener("click", () => { setOpinion(movie, opinionOf(movie.movie_id) === kind ? null : kind); onChange && onChange(); });
      return b;
    };
    return h("span", { class: "acts" }, make("like", "Like"), make("dislike", "Skip"));
  }

  function renderList() {
    const ul = $("#my-films");
    ul.replaceChildren();
    const row = (id, cls) => h("li", { class: cls },
      state.titles[id] || id,
      h("button", { type: "button", "aria-label": "Remove " + (state.titles[id] || id), text: "×", onclick: () => {
        state.liked = state.liked.filter((x) => x !== id);
        state.disliked = state.disliked.filter((x) => x !== id);
        save(); renderList(); refresh();
      } }));
    for (const id of state.liked) ul.append(row(id, "liked"));
    for (const id of state.disliked) ul.append(row(id, "disliked"));
    if (!state.liked.length && !state.disliked.length) ul.append(h("li", { class: "meta", text: "Nothing yet." }));
  }

  const doSearch = debounce(async () => {
    const q = $("#search").value.trim();
    const ul = $("#search-results");
    ul.replaceChildren();
    if (!q) return;
    try {
      const movies = await api("/search?limit=8&q=" + encodeURIComponent(q));
      if (!movies.length) ul.append(h("li", { class: "meta", text: "No match in this catalogue." }));
      for (const m of movies) {
        ul.append(h("li", {},
          h("span", { class: "t" }, h("button", { class: "ghost", type: "button", text: `${m.title}${m.year ? ` (${m.year})` : ""}`, onclick: () => openMovie(m.movie_id) })),
          opinionButtons(m, doSearch)));
      }
    } catch (err) {
      ul.append(h("li", { class: "meta", text: err.message }));
    }
  }, 250);
  $("#search").addEventListener("input", doSearch);
  $("#reset").addEventListener("click", () => {
    state.weights = {}; state.liked = []; state.disliked = [];
    save(); renderSliders(); renderList(); refresh();
  });

  // ---- recommendations ---------------------------------------------------------------------
  let refreshSeq = 0;
  async function recommendNow() {
    const mine = ++refreshSeq;  // a slow earlier response must not overwrite a newer one
    const banner = $("#rec-banner");
    const list = $("#recs");
    banner.textContent = "Working...";
    try {
      const body = await post("/recommend", {
        profile: { aspect_weights: state.weights, liked_movie_ids: state.liked, disliked_movie_ids: state.disliked },
        limit: 12,
      });
      if (mine !== refreshSeq) return;
      const explicit = Object.keys(state.weights).length > 0;
      banner.textContent = body.cold_start
        ? "Showing the most-liked films. Move a slider or like a film to personalise."
        : explicit
          ? "Ranked by viewers with similar taste and by how reviewers rate each film on the aspects you chose."
          : "Ranked by viewers with similar taste. Aspects shown are what this film's reviewers praise most.";
      list.replaceChildren(...body.items.map(renderRec));
      if (!body.items.length) banner.textContent = "Nothing to show yet.";
    } catch (err) {
      if (mine === refreshSeq) banner.textContent = err.message;
    }
  }
  const refresh = debounce(recommendNow, 300);

  function renderRec(item) {
    const m = item.movie;
    const card = h("li", { class: "card rec" },
      h("header", {},
        h("h3", {}, h("button", { type: "button", text: m.title + (m.year ? ` (${m.year})` : ""), onclick: () => openMovie(m.movie_id) })),
        h("span", { class: "meta", text: (m.genres || []).join(" · ") })),
      h("div", {}, opinionButtons(m, null)));
    if (item.is_fallback) {
      card.append(h("p", { class: "meta", text: "Popular pick: no personal reason to show." }));
    }
    for (const r of item.reasons) {
      const why = r.user_weight > 0
        ? `Because you care about ${label(r.aspect)} (${pct(r.user_weight, 0)})`
        : `Praised for ${label(r.aspect)}`;
      card.append(h("div", { class: "reason" },
        h("div", { class: "why", text: why }),
        dbar(`Film's ${label(r.aspect).toLowerCase()}`, r.movie_score, 0),
        r.evidence.slice(0, 2).map(quote)));
    }
    return card;
  }

  // ---- movie page --------------------------------------------------------------------------
  async function openMovie(id) {
    const dialog = $("#movie-dialog");
    const body = $("#movie-body");
    body.replaceChildren(h("p", { text: "Loading..." }));
    dialog.showModal();
    try {
      const d = await api("/movie/" + encodeURIComponent(id));
      const m = d.movie;
      body.replaceChildren(
        h("h2", { id: "movie-title", text: m.title + (m.year ? ` (${m.year})` : "") }),
        h("p", { class: "meta" }, (m.genres || []).join(" · "), " · ",
          `${d.rating_count.toLocaleString()} MovieLens ratings (adjusted mean ${d.mean_rating}) · ${d.review_count} reviews read · `,
          h("a", { href: d.imdb_url, target: "_blank", rel: "noopener noreferrer", text: "IMDb" })),
        opinionButtons(m, null),
        h("h3", { text: "What reviewers say, by aspect" }),
        h("p", { class: "hint", text: "Blue to the right is praise, red to the left is criticism. n is how many review clauses the score is based on; aspects with fewer than 3 are not shown." }),
        d.aspects.length ? null : h("p", { text: "Not enough reviews mention any single aspect to score it." }),
        d.aspects.map((a) => h("div", {}, dbar(label(a.aspect), a.score, a.support), a.evidence.slice(0, 2).map(quote))));
    } catch (err) {
      body.replaceChildren(h("p", { text: err.message }));
    }
  }

  // ---- analyze a review --------------------------------------------------------------------
  const SAMPLE = "The acting was brilliant and the soundtrack was wonderful, but the pacing dragged badly in the middle. The ending was a letdown. I would happily watch it again.";
  $("#sample").addEventListener("click", () => { $("#review-text").value = SAMPLE; });
  $("#analyze").addEventListener("click", async () => {
    const out = $("#analysis");
    const text = $("#review-text").value.trim();
    if (!text) { out.replaceChildren(h("p", { text: "Paste some text first." })); return; }
    out.replaceChildren(h("p", { text: "Analyzing..." }));
    try {
      const r = await post("/analyze", { text });
      const paragraphs = r.sentences.map((s) => h("span", {},
        s.clauses.map((c) => {
          const strongest = c.mentions.slice().sort((a, b) => Math.abs(b.polarity) - Math.abs(a.polarity))[0];
          const cls = strongest && Math.abs(strongest.polarity) >= 0.2 ? (strongest.polarity > 0 ? "pos" : "neg") : "";
          return h("span", { class: "clause" },
            h("mark", { class: cls, text: c.text }),
            c.mentions.map((m) => h("span", { class: "chip", text: `${label(m.aspect)} ${signed(m.polarity)}` })), " ");
        })));
      out.replaceChildren(
        h("p", {}, paragraphs),
        h("h3", { text: "Summary by aspect" }),
        ...(r.summary.length ? r.summary.map((s) => dbar(label(s.aspect), s.polarity, s.mentions)) : [h("p", { class: "meta", text: "No aspect was judged in this text." })]),
        h("p", { class: "callout", text: `Whole review reads as ${r.overall >= 0 ? "positive" : "negative"} (${signed(r.overall)}). Clause scores are noisier than whole-review scores: see "How well does it work?"` }));
    } catch (err) {
      out.replaceChildren(h("p", { text: err.message }));
    }
  });

  // ---- evaluation tab: every number comes from the server's eval.json ----------------------
  function wilson(hits, n) {
    if (!n) return [0, 1];
    const z = 1.96, p = hits / n, d = 1 + z * z / n;
    const c = (p + z * z / (2 * n)) / d;
    const half = z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d;
    return [Math.max(0, c - half), Math.min(1, c + half)];
  }
  const prop = (o) => {
    const [lo, hi] = wilson(o.hits, o.n);
    return `${pct(o.hits / o.n)} [${pct(lo)}, ${pct(hi)}] (n=${o.n})`;
  };
  const ci = (i) => `${pct(i.mean)} [${pct(i.lo)}, ${pct(i.hi)}]`;
  const diff = (i) => `${i.mean >= 0 ? "+" : "−"}${(Math.abs(i.mean) * 100).toFixed(1)} pts [${(i.lo * 100).toFixed(1)}, ${(i.hi * 100).toFixed(1)}]`;
  const table = (head, rows) => h("div", { class: "tablewrap" }, h("table", {},
    h("thead", {}, h("tr", {}, head.map((t) => h("th", { text: t })))),
    h("tbody", {}, rows.map((r) => h("tr", {}, r.map((c, i) => h("td", { class: i ? "num" : "", text: c })))))));

  let evalDone = false;
  async function renderEval() {
    if (evalDone) return;
    const root = $("#eval");
    try {
      const e = await api("/metrics");
      if (!e.catalogue) { root.replaceChildren(h("p", { text: "No evaluation was built with these artifacts." })); return; }
      const c = e.catalogue, rec = e.recommender, pol = e.polarity, j = e.join_check;
      const byName = Object.fromEntries(rec.methods.map((m) => [m.name, m]));
      const d20 = (a, b) => rec.differences.find((x) => x.a === a && x.b === b && x.k === 20);
      const cards = [];

      cards.push(h("div", { class: "card" }, h("h2", { text: "What it is built from" }),
        h("p", {}, `${c.films.toLocaleString()} films that appear in both IMDb review data and MovieLens, ${c.reviews.toLocaleString()} reviews read, ${c.evidence_sentences.toLocaleString()} quotable sentences selected, ${c.ratings.toLocaleString()} ratings used for collaborative filtering.`),
        j ? h("p", { class: "callout" }, `Join check: ${pct(j.own_title_rate)} of reviews mention their own film's title, against ${pct(j.other_title_rate)} when each film's reviews are paired with a different film's title (n=${j.n_reviews.toLocaleString()}). A wrong join would make the first number collapse to the second.`) : null));

      if (pol) {
        const names = Object.keys(pol.cv);
        cards.push(h("div", { class: "card" }, h("h2", { text: "Polarity model (positive vs negative)" }),
          table(["Candidate", "5-fold CV accuracy (mean ± std)"], names.map((n) => [n, `${pct(pol.cv[n].mean, 2)} ± ${(pol.cv[n].std * 100).toFixed(2)}`])),
          h("p", {}, `Shipped: ${pol.shipped} (${pol.shipped_reason}). On the official held-out test split, evaluated once: `, h("b", { text: `${pct(pol.official_test_accuracy, 2)} ± ${(pol.official_test_ci95 * 100).toFixed(2)}` }), ` (95% CI, n=${pol.official_test_n.toLocaleString()}).`),
          h("p", { class: "meta", text: "That is whole reviews. Judging single clauses is harder, measured below." })));
      }

      const g = e.gold && e.gold.heldout;
      if (g) {
        cards.push(h("div", { class: "card" }, h("h2", { text: "Aspect detection and clause polarity" }),
          table(["Measure (held-out hand-labelled clauses)", "Result [95% Wilson interval]"], [
            ["Lexicon precision: flagged clauses really about that aspect", prop(g.detector_precision)],
            ["Polarity sign correct (clear-cut clauses)", prop(g.polarity_accuracy)],
            ["Polarity sign correct, only clauses strong enough to be quoted", prop(g.polarity_accuracy_confident)],
          ]),
          h("p", { class: "callout", text: e.gold_note + " Samples are small, hence the wide intervals. Recall of the aspect lexicon cannot be measured from this sample." })));
      }

      const row = (n, title) => [title, ci(byName[n].hit_rate[10]), ci(byName[n].hit_rate[20])];
      const hy = d20("hybrid", "cf"), cp = d20("cf", "popularity"), ap = d20("aspect", "popularity");
      cards.push(h("div", { class: "card" }, h("h2", { text: "Recommender (held-out users)" }),
        h("p", { class: "hint", text: `For each of ${rec.n_test_users.toLocaleString()} test users never used to fit the model, one liked film is hidden and the model sees up to ${rec.seeds_per_user} others. Hit-rate@k is how often the hidden film is in the top k of ${c.films.toLocaleString()}. Intervals are bootstrap 95%.` }),
        table(["Method", "Hit-rate@10", "Hit-rate@20"], [
          row("popularity", "Most-liked films (baseline)"),
          row("cf", "Collaborative filtering only"),
          row("aspect", "Aspect fit only"),
          row("hybrid", "CF + aspect fit (what you see)"),
        ]),
        h("p", {}, "Paired differences at k=20: ",
          h("b", { text: "CF over baseline " }), diff(cp.diff), "; ",
          h("b", { text: "aspect-only over baseline " }), diff(ap.diff), "; ",
          h("b", { text: "hybrid vs CF " }), diff(hy.diff), "."),
        h("p", { class: "callout", text: `Honest reading: collaborative filtering does the heavy lifting. Aspect fit alone is no better than the popularity baseline at predicting what a viewer liked. Blending it in costs ${(Math.abs(hy.diff.mean) * 100).toFixed(1)} points of hit-rate@20 against pure CF (share chosen on separate validation users as the largest that stays within one standard error). What it buys is that every pick can be explained with real sentences.` })));

      cards.push(h("div", { class: "card" }, h("h2", { text: "Limits you should know about" }),
        h("ul", {},
          ["Aspect scores come from 10-30 reviews per film, mostly written years ago. Treat them as hints, not verdicts.",
           "The polarity model was trained on whole reviews and applied to clauses; negation inside short clauses ('aren't terrible') can still fool it.",
           "The aspect lexicon is word-list based and has no measured recall.",
           "Gold labels were written by the assistant that built the system, not by independent annotators.",
           "Slider weights you set yourself cannot be validated offline: there is no ground truth for stated preferences.",
           "The catalogue is limited to films present in both datasets (mostly released before 2012)."].map((t) => h("li", { text: t })))));

      root.replaceChildren(h("div", { class: "grid2" }, cards));
      evalDone = true;
    } catch (err) {
      root.replaceChildren(h("p", { text: err.message }));
    }
  }

  // ---- boot --------------------------------------------------------------------------------
  (async () => {
    try {
      const [health, list] = await Promise.all([api("/health"), api("/aspects")]);
      aspects = list;
      $("#build").textContent = "artifacts " + health.manifest.slice(0, 12);
      renderSliders(); renderList(); recommendNow();
    } catch (err) {
      $("#build").textContent = "server unreachable";
      $("#rec-banner").textContent = err.message;
    }
  })();
})();
