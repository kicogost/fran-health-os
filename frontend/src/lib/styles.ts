/** Shared card treatment -- rest-state elevation + a hover lift, per
 * ui-ux-pro-max-skill's motion.csv "Standard" card-hover pattern
 * (y: -4, scale: 1.02-equivalent, boxShadow, 200-300ms) verified before
 * using it, adapted to plain Tailwind transitions rather than adding GSAP
 * as a new dependency for an effect this simple. motion-reduce: variants
 * disable the transform per that same dataset's stated convention (render
 * the final/rest state, skip non-essential motion).
 */
export const CARD_CLASS =
  "rounded-xl border border-border bg-card shadow-sm shadow-black/20 " +
  "transition-all duration-200 ease-out hover:-translate-y-0.5 hover:shadow-lg hover:shadow-black/30 " +
  "motion-reduce:transition-none motion-reduce:hover:translate-y-0"

/** Flat variant -- 2026-08-30, after Francisco pointed at three real design
 * systems (Spotify, Linear, Nike) and split them by role: Spotify's shadow-
 * driven depth for daily-glanceable content cards, Linear's flat hairline-
 * border restraint for dense data screens ("workout logs, progress charts,
 * and PR history need restraint more than personality"). Same border/
 * radius/background tokens as CARD_CLASS (Carbon g100 stays the settled
 * palette, approved twice already, ADR-equivalent history in CLAUDE.md's
 * "Dashboard visual redesign round 2" -- a Linear/Vercel-toned palette was
 * tried and REPLACED by Carbon that round; this borrows Linear's structural
 * principle, not its literal colors, deliberately) -- no shadow, no hover-
 * lift, so it recedes rather than competing with an insight card sitting
 * next to it. Used for chart/raw-number cards; CARD_CLASS stays on
 * insight/hero cards (the plain-language takeaways, and Today's rings),
 * which keep behaving like the "content you open four times a day" surface
 * Spotify's own system is built around.
 */
export const CARD_CLASS_FLAT = "rounded-xl border border-border bg-card"
