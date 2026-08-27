# 3. Drop ACWR, use CTL/ATL/TSB as the sole training-load-ratio signal

Date: 2026-08-27
Status: Accepted
Supersedes: the ACWR spec in the kickoff doc, section 6 ("Acute:chronic workload ratio")

## Context

The kickoff doc explicitly specced ACWR (acute = 7-day rolling load sum, chronic =
28-day rolling average of those sums, sweet spot 0.8-1.3) as one of the required
Phase 4 derived metrics. It was built that way first (`metrics/load.py:
compute_acwr()`, 4 tests, all passing).

While researching proprietary training-load options more broadly (see CLAUDE.md's
"proprietary training-load/readiness build-out" section), it became clear the
sports science literature has moved firmly against ACWR: Impellizzeri et al. and
multiple systematic reviews document "severe mathematical coupling," a lack of
coherent causal interpretation, and inconsistent injury association across
meta-analyses — strong enough criticism that recommending training decisions off
of it was flagged as a real caveat, not a footnote, in the original build-out.

Once that was surfaced, Francisco asked directly to drop it rather than keep a
metric already flagged as scientifically shaky, and use only the better-regarded
alternative instead.

## Decision

**Remove `compute_acwr()` entirely. CTL/ATL/TSB (the Banister impulse-response
model — the same math TrainingPeaks calls the Performance Manager Chart) is the
sole training-load-ratio signal in this system.**

## Reasoning

- CTL/ATL/TSB doesn't share ACWR's specific "coupling" flaw (the acute window
  being a subset of the chronic window, which is a major source of the
  criticized mathematical artifacts) — it uses two independent exponentially-
  weighted series instead of a ratio of overlapping rolling sums.
- It's current best practice in endurance-training-load monitoring, not a
  fringe alternative — well understood, widely used, and easy to explain (CTL =
  fitness, ATL = fatigue, TSB = freshness).
- Maintaining two training-load-ratio metrics side by side, one of which is
  explicitly caveated as scientifically weak, adds surface area and confusion
  for no real benefit once a better one exists. One clear signal beats two
  signals of different trustworthiness.

## Alternatives considered

- **Keep both, ACWR clearly caveated.** This was the initial build (see git
  history) — rejected once Francisco weighed in: if a metric's own
  documentation says "don't fully trust this," better to not compute it at all
  than to have it sitting in the data asking to be misread later, including by
  a future coaching-layer rule that might not carry the caveat forward
  correctly.

## Consequences

- `metrics/load.py` module docstring, `CLAUDE.md`'s target-spec sections
  (readiness score components, structural triggers, weekly retro, dashboard
  training page) all needed updating to replace ACWR-based language with TSB-
  based language — done as part of this change.
- Kickoff doc section 6 is now out of date on this specific point.
  `HEALTH_OS_KICKOFF.md` is preserved verbatim as originally written (per its
  own stated role); `CLAUDE.md` is the living doc that wins when they disagree,
  per its own header — this ADR is the record of that specific disagreement and
  why.
- The exact numeric thresholds for "what counts as concerning TSB" still need
  calibrating against Francisco's own load-unit scale once enough data exists —
  same open item ACWR would have had anyway (kickoff doc's own sweet-spot
  numbers were never validated for this specific unit system either).
