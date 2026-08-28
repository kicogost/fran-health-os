import { useEffect, useState } from "react"

/** Animates a number from 0 up to `target` on mount/change -- the "real-time
 * number animation" pattern for data-dense/financial dashboards (verified
 * against nextlevelbuilder/ui-ux-pro-max-skill's actual reasoning data
 * before using it, not just eyeballed: ui-reasoning.csv's "Financial
 * Dashboard" row lists "Real-time number animations" as a key effect for
 * exactly this kind of readiness/status dashboard).
 *
 * Respects prefers-reduced-motion (motion.csv's own stated convention
 * throughout: "when reduced-motion matches, skip non-essential motion and
 * render the final state immediately") -- and, per oxlint's own
 * set-state-in-effect guidance, the "nothing to animate" cases (no target,
 * or reduced motion) are derived directly at render time rather than pushed
 * through a synchronous setState call inside the effect.
 */
export function useCountUp(target: number | null, duration = 800): number | null {
  const [animatedValue, setAnimatedValue] = useState<number | null>(null)
  const reducedMotion =
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches

  useEffect(() => {
    if (target === null || reducedMotion) return

    let raf: number
    const start = performance.now()
    const tick = (now: number) => {
      const progress = Math.min(1, (now - start) / duration)
      const eased = 1 - (1 - progress) ** 3 // ease-out cubic
      setAnimatedValue(target * eased)
      if (progress < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [target, duration, reducedMotion])

  if (target === null || reducedMotion) return target
  return animatedValue ?? 0
}
