/* The top pick and "Show me another", the logic only: no DOM, no network, so Node's test runner can
   exercise it (tests/web/picks.test.mjs). rails.js draws it.

   The server ranks the picks once; this walks down that ranking. A queue holds the ids in rank
   order, where the visitor is, and every id they have been shown, so the button never brings back a
   title they already passed. When the ranking runs out the caller asks the server for more and
   appends them. A title marked "Want to watch" is not touched by any of this: pressing the button is
   looking at more choices, not rejecting this one. */

const SEEN_CAP = 500;

export const makeQueue = () => ({ ids: [], at: 0, seen: [] });

export const currentId = (q) => q.ids[q.at] ?? null;
export const canGoBack = (q) => q.at > 0;
export const hasNext = (q) => q.at + 1 < q.ids.length;
/** The ids after the one being shown: what the row under the top pick lists. */
export const upcoming = (q) => q.ids.slice(q.at + 1);

function see(q) {
  const id = currentId(q);
  if (id !== null && !q.seen.includes(id)) q.seen = [...q.seen, id].slice(-SEEN_CAP);
}

/** Put a freshly ranked list in the queue after a page draw. The title already on show stays on
    show if it is still in the list (so a click on Like does not jerk the page to another film);
    otherwise the first title the visitor has not been shown; otherwise the top. */
export function load(q, ids) {
  const shown = currentId(q);
  q.ids = [...new Set(ids)];
  const keep = shown === null ? -1 : q.ids.indexOf(shown);
  if (keep >= 0) q.at = keep;
  else {
    const fresh = q.ids.findIndex((id) => !q.seen.includes(id));
    q.at = fresh >= 0 ? fresh : 0;
  }
  see(q);
  return q;
}

/** Step to the next title. "moved" when there was one, "more" when the list has run out and the
    caller should fetch and `append` more (then call `next` again). */
export function next(q) {
  if (!hasNext(q)) return "more";
  q.at += 1;
  see(q);
  return "moved";
}

/** Add ids from the server to the end, skipping any already in the queue or already shown.
    Returns how many were added. */
export function append(q, ids) {
  const have = new Set([...q.ids, ...q.seen]);
  const fresh = [...new Set(ids)].filter((id) => !have.has(id));
  q.ids = [...q.ids, ...fresh];
  return fresh.length;
}

/** Step back to the title before this one, if there is one. */
export function previous(q) {
  if (!canGoBack(q)) return false;
  q.at -= 1;
  return true;
}
