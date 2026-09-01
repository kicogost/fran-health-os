/** Today's date as "YYYY-MM-DD" in the BROWSER'S LOCAL timezone.
 *
 * Deliberately NOT `new Date().toISOString().slice(0, 10)` -- `toISOString()`
 * always renders the UTC calendar date, which is wrong for up to a couple of
 * hours around local midnight. Confirmed: a clock reading 2026-09-01 00:30 in
 * Madrid (CEST, UTC+2) still returns "2026-08-31" from the ISO-string
 * approach. Every Log tab's date picker should default to what the user's
 * own clock says today is, not UTC's -- previously each of the 4 Log tabs
 * (LogBjjTab/LogCalisthenicsTab/LogWellnessTab/LogWaistTab) duplicated the
 * buggy version independently; this is the one shared fix.
 *
 * No date library needed -- `getFullYear()`/`getMonth()`/`getDate()` already
 * read in the browser's local timezone.
 */
export function todayLocal(): string {
  const now = new Date()
  const year = now.getFullYear()
  const month = String(now.getMonth() + 1).padStart(2, "0")
  const day = String(now.getDate()).padStart(2, "0")
  return `${year}-${month}-${day}`
}
