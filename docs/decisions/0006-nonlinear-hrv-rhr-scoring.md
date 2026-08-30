# 6. Score HRV/RHR deviation with a power-law curve, not linearly

Date: 2026-08-30
Status: Accepted
Supersedes: the linear mapping in `metrics/readiness.py: _hrv_component_score()` /
`_rhr_component_score()` (built 2026-08-28, per the kickoff doc's "35% HRV deviation
from baseline, in SD units, clamped to ±2 / 15% resting HR deviation, inverted")

## Context

Francisco looked at a real day's readiness breakdown and asked why RHR being "only
2bpm off" (50bpm baseline → 52bpm) scored a 24/100 — a number that visually reads as
a serious problem. The underlying deviation was +1.04 SD, and the existing formula
(`score = 50 + 25 * clamp(deviation_sd, -2, 2)`, inverted for RHR) spends a full
quarter of the entire 0-100 range on the first SD of deviation.

He asked directly whether this scaling is too aggressive, and — before agreeing and
just picking a fix — asked to research how WHOOP and Garmin actually do this, and
what the peer-reviewed literature says, rather than guessing at a "feels better"
curve.

## Research findings (full detail in CLAUDE.md's dated entry; summary here)

- **Neither WHOOP nor Garmin discloses their actual scoring formula.** Confirmed
  across three independent tiers: WHOOP's own developer docs and support content
  (inputs only, explicitly "proprietary" methodology), Garmin's own manuals (inputs
  and score color-bands disclosed, no formula or weighting), and — most
  importantly — Doherty et al. 2025 (*Translational Exercise and Biomedicine*,
  peer-reviewed), which surveyed 14 composite health scores across 10 manufacturers
  and found **none disclose their weighting, and none are validated against
  clinical/performance outcomes.** There is nothing to copy here even in principle.
- **No peer-reviewed source validates a specific curve shape** (linear, quadratic,
  sigmoid, or otherwise) for mapping a physiological deviation onto a bounded
  decision-support score. A confirmed gap, not an assumption of settledness.
- **Indirect evidence does support moving away from linear, in one specific
  direction.** Three independent findings converge: real device data (Sekiguchi et
  al., peer-reviewed, Olympic athletes) shows day-to-day HRV noise is genuinely
  small (~5% CV) relative to real training-driven shifts (10-45%); a large real
  dataset (Terra Research, ~100k HRV readings) shows ~1-in-3 days naturally lands
  beyond ±1 SD and only ~1-in-23 beyond ±2 SD, confirming 1 SD is a routine,
  common event, not a rare one; and established sports-science convention (Hopkins'
  "smallest worthwhile change," Plews et al.'s HRV-specific application of it)
  already treats small deviations below a threshold as noise rather than signal.
- **The specific curve family matters, and one obvious-sounding choice is wrong.**
  A sigmoid/logistic curve (steepest near baseline, flattening at the extremes —
  what "nonlinear" naively suggests, and what the one specific formula circulating
  online claiming to be WHOOP's actual math uses, self-described by its own author
  as an *invented approximation, not a reverse-engineered fact*) would move the
  score **harder** on ordinary 1-SD noise than the current linear model — the
  opposite of the goal. Only a power-law/quadratic-family curve (flat near
  baseline, steep toward the extremes) achieves what was actually wanted. Verified
  by direct calculation before deciding, not assumed from the shape's name.

## Decision

**Replace the linear mapping with a quadratic one, same ±2 SD boundary and same
0/100 endpoints, flat middle:**

```
score = 50 + 50 * sign(x) * (clamp(x, -2, 2) / 2) ** 2
```

(inverted for RHR, same as the linear version was). At x=0: score=50 (unchanged).
At x=±2 (the clamp boundary): score=0/100 (unchanged — the original spec's ±2 SD
"full range" boundary is preserved exactly). At x=±1 (a routine, ~1-in-3-days
event): score moves only to 37.5/62.5, not 25/75 — the middle of the range is
genuinely flatter, exactly the effect the research confirmed was the right
direction for a power-law shape and confirmed a sigmoid would NOT have delivered.

## Honesty about what this is and isn't

- The **family choice** (power-law/convex-in-the-middle, not sigmoid) is supported
  by the indirect evidence above — this is a considered call, not a coin flip.
- The **specific exponent (2, i.e. quadratic)** has zero direct empirical
  validation anywhere in the literature found. It's the simplest member of the
  correct family, chosen as a documented, revisable default — same spirit as this
  project's other seed-phase numbers (`metrics/baselines.py`'s HRV thresholds,
  `deload`'s MIN_N=30 and 2-of-5 marker count). Not presented as more validated
  than it is.
- A more rigorous future version could anchor the curve's flatness to the
  athlete's own measured day-to-day noise floor (the Plews/Hopkins SWC convention,
  ~0.5x the day-to-day coefficient of variation) rather than a fixed exponent —
  noted as a real, not-yet-built improvement, not done now since it requires
  computing a genuinely different quantity (short-window day-to-day variability)
  than the existing 60-day population SD the baseline already tracks.

## Alternatives considered

- **Keep linear.** Rejected — the whole reason this ADR exists: a common, routine
  1 SD deviation already consuming a quarter of the score range doesn't match how
  routine that deviation actually is (confirmed via real base-rate data above), and
  is inconsistent with how every other structural trigger in this project already
  treats single-day fluctuation (multi-day sustain requirements throughout
  `coach/rules.py`, the deload system's own bidirectional-and-sustained design).
- **Sigmoid/logistic curve.** Considered, since it's the more commonly-assumed
  shape of "nonlinear" scoring (and the shape the one speculative WHOOP-formula
  online actually uses) — rejected once the direct calculation showed it would
  move the score harder on ordinary noise than linear already does, the opposite
  of the stated goal.
- **Try to match WHOOP's or Garmin's actual formula.** Not possible — confirmed
  disclosed nowhere, across every tier of source checked, including a peer-reviewed
  cross-manufacturer survey that found the entire industry withholds this.

## Consequences

- `metrics/readiness.py: _hrv_component_score()` / `_rhr_component_score()`
  rewritten; both call sites that compute readiness (`coach/briefing.py` for the
  live Today page, `metrics/derived_daily.py` for the persisted history) use the
  same function, so no dual-call-site drift risk here (unlike the earlier
  TSB-staleness and sleep-quality-blend fixes, which had to fix two independent
  implementations).
- Historical `derived_daily` readiness scores recomputed so the Trends chart
  reflects the corrected curve throughout, not just going forward.
- Every existing test asserting an exact linear-mapping score value needed
  updating to the new quadratic expectation — not a silent behavior change, the
  test suite is the record of exactly what changed and why.
