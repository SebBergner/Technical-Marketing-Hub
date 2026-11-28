/* Dates as the pages print them (WS-G, 2026-11-28: one copy instead of one
 * per page). Two kinds of input:
 *
 *  - a day, "2024-03-12" (a demo's date): read as local midnight, so it
 *    never slips to the day before west of UTC;
 *  - a timestamp, "2026-11-28T13:31:00Z" (when something happened): shown
 *    in the viewer's own time zone -- App Service runs in UTC. */

function day(iso) {
  return new Date(iso + "T00:00:00");
}

/* Month day, year -- "Mar 12, 2024" -- everywhere in the Hub (Liwei,
 * 2026-10-26; it was day month year). Migration passes "en-GB" and keeps
 * its "12 Mar 2024". An unreadable date comes back as it was given. */
function fullDate(iso, locale) {
  var d = day(iso);
  return isNaN(d) ? iso
    : d.toLocaleDateString(locale || "en-US", { day: "numeric", month: "short", year: "numeric" });
}

//: The year only when it is not this one: "21 May" alone read the same
//: for 2024 and 2026 (2026-10-01).
function uploadedLabel(iso) {
  if (!iso) return "";
  var d = day(iso);
  if (isNaN(d)) return "";
  var opts = { day: "numeric", month: "short" };
  if (d.getFullYear() !== new Date().getFullYear()) opts.year = "numeric";
  return d.toLocaleDateString("en-US", opts);
}

/* The day of a timestamp, "Nov 28, 2026" (locale: the viewer's unless
 * given). */
function stampDay(iso, locale) {
  return new Date(iso).toLocaleDateString(locale,
    { month: "short", day: "numeric", year: "numeric" });
}

/* Day and time of a timestamp, in the viewer's locale and zone; "—" for
 * none. Admin and Content health. */
function when(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export { fullDate, stampDay, uploadedLabel, when };
