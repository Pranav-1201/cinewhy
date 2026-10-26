/* The year range a visitor chooses: a span from some year to some year, or no limit at all. No DOM and
   no network, so Node tests it (tests/web/years.test.mjs).

   `null` for either end means "no limit that way". A range that covers the whole catalogue is the same
   as no range: it is never sent to the server and never shown as a choice the visitor made. */

export const OLD_SCHOOL_TO = 1989; // "Old school" is before 1990
export const NEW_FROM = 2021; // "New" is 2021 onward

const clampTo = (value, low, high) => Math.min(high, Math.max(low, value));

/**
 * A valid pair from whatever was chosen: whole years inside the catalogue's span, from not after to,
 * and null for an end that sits at the edge of the span (no limit). Bad input becomes null.
 */
export function normaliseYears(from, to, oldest, newest) {
  const clean = (v) => (Number.isInteger(v) ? clampTo(v, oldest, newest) : null);
  let a = clean(from);
  let b = clean(to);
  if (a !== null && b !== null && a > b) [a, b] = [b, a];
  return { from: a !== null && a <= oldest ? null : a, to: b !== null && b >= newest ? null : b };
}

/** The `from_year` / `to_year` a ranking request carries: only the ends that actually narrow the range. */
export function requestYears(from, to, oldest, newest) {
  const { from: a, to: b } = normaliseYears(from, to, oldest, newest);
  const request = {};
  if (a !== null) request.from_year = a;
  if (b !== null) request.to_year = b;
  return request;
}

/** "old" for the Old school preset, "new" for the New preset, else null. */
export function activePreset(from, to, oldest, newest) {
  const { from: a, to: b } = normaliseYears(from, to, oldest, newest);
  if (a === null && b === OLD_SCHOOL_TO) return "old";
  if (a === NEW_FROM && b === null) return "new";
  return null;
}

/** The range in words, for the label beside the bar. */
export function describeYears(from, to, oldest, newest) {
  const { from: a, to: b } = normaliseYears(from, to, oldest, newest);
  if (a === null && b === null) return "Any year";
  if (a === null) return b === OLD_SCHOOL_TO ? `Before ${OLD_SCHOOL_TO + 1}` : `Up to ${b}`;
  if (b === null) return `${a} onward`;
  return a === b ? String(a) : `${a} to ${b}`;
}

/** The years a preset stands for, as a pair ready to store. */
export const presetYears = (preset) => (preset === "old" ? { from: null, to: OLD_SCHOOL_TO } : { from: NEW_FROM, to: null });
