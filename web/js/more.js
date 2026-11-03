/* "Show more" on one row, the parts that need no browser: what the request carries and which of the
   titles that come back are really new. No DOM, no network, so Node tests every rule here
   (tests/web/more.test.mjs). rails.js draws the button and sends the request.

   The page no longer redraws by itself when a visitor likes or marks a title (D-045): a row stays as
   it is until the visitor reloads, changes a filter, or presses Show more on that row. Show more
   adds the next titles AFTER the last one, ranked with everything the visitor has said so far. */

export const MORE_LIMIT = 20; // titles added per press, the same as a row holds to begin with
export const EXCLUDE_CAP = 3000; // the server refuses more than this many excluded ids

/**
 * The /shelves request for the next titles of one row.
 *
 * `base` is the request every row shares (filters, taste, recency, and the watched ids in
 * `exclude_movie_ids`). `shown` is every title already on the page, in any row or the top pick, so a
 * title is never offered twice. The titles on screen go first: if the two lists together ever pass
 * the server's cap, it is the tail of the watched list that is dropped, never something the visitor
 * can see.
 */
export function moreRequest(base, shelfId, shown) {
  const { exclude_movie_ids: watched = [], ...rest } = base;
  const ids = [...new Set([...shown, ...watched])].slice(0, EXCLUDE_CAP);
  return { ...rest, only: shelfId, limit: MORE_LIMIT, exclude_movie_ids: ids };
}

/** The titles of row `shelfId` in a /shelves answer that are not on the page yet (empty when the row has no more). */
export function freshItems(response, shelfId, shown) {
  const shelf = (response?.shelves ?? []).find((s) => s.id === shelfId);
  return (shelf?.items ?? []).filter((item) => !shown.has(item.movie.movie_id));
}
