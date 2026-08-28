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
