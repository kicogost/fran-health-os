# 7. Rebuild the readiness score's architecture from an evidence review

Date: 2026-08-30
Status: Accepted
Supersedes: parts of the original kickoff-doc design (section 6) and the
2026-08-28 build-out documented in CLAUDE.md; extends, does not reverse,
ADR 0006 (the quadratic HRV/RHR curve shape stays, gains a noise floor on top).

## Context

Francisco asked, after ADR 0006's curve-shape fix, a sharper question: the
`±2 SD = full range` boundary, the 60-day baseline window, the fixed 8h sleep
need, and the 35/25/15/15/10 weight split were all **inherited from the
original kickoff-doc spec, written before any of this was built** — never
themselves researched. He asked for the whole architecture to be re-derived
from real evidence, "keep what's genuinely useful and scrap what's not,"
using this session's `research-synthesist`-style methodology.

## Research approach

Four parallel deep-research passes (HRV/RHR baseline methodology; sleep
need/debt/quality; whether TSB belongs in a same-day score plus composite
weighting; the single-composite-number paradigm and Oura's published
science as a comparison point) plus direct primary-source verification
(Hopkins' original SWC paper, two real Firstbeat white papers, Garmin's own
HRV Status documentation, several load-bearing 2025-2026 papers read
directly rather than trusted from secondary summaries). Full source table,
evidence tiers, and independence grading in CLAUDE.md's dated entry.

**A finding worth recording on its own merits**: three independent search
passes (two subagents, one direct) all surfaced the same two fabricated
"studies" — a "2024 Frontiers in Physiology WHOOP-recovery-vs-cortisol"
paper and a "2023 JSMS WHOOP-vs-subjective-fatigue" paper, both traced to
content-farm pages laundered into confident prose by AI search summaries.
Neither exists on PubMed, Frontiers, or anywhere else. Exactly the failure
mode this methodology exists to catch.

**The header finding underneath every verdict below**: no commercial
wearable — Oura, WHOOP, Garmin, or any of the 10 vendors a 2025 peer-reviewed
survey (Doherty et al., *Translational Exercise and Biomedicine*) checked —
discloses its actual composite formula, and none have the *composite* itself
(as opposed to some raw sensor inputs) validated against a real outcome.
There was never anything to reverse-engineer.

## Decisions

Francisco was asked directly on the three genuinely open judgment calls
(no validated answer exists in the literature for any of them); his answers
are recorded here as decisions, not assumptions.

### 1. HRV/RHR baseline window — kept at 60 days, gained a noise floor

**Research finding**: a 7-day rolling window with either a coefficient-of-
variation dispersion measure or an individually-calibrated smallest-
worthwhile-change (SWC) is the actual design used in three independent
HRV-guided-training RCT programs (Finland, Spain) that showed a real
performance benefit over fixed programming — a genuinely better-evidenced
alternative to 60-day population SD. But the CV-specific version of this
recommendation traces substantially through one overlapping author lineage
(Plews/Buchheit/Laursen), including a foundational **n=2 case report** — not
independent multi-lab replication at the standard "well-established" should
require.

**Decision**: keep the 60-day rolling median/SD baseline (stable, already
built, survives an occasional missed night) rather than rearchitect to a
7-day window. Instead, layer the evidence-backed **SWC noise floor** on top
(a small dead zone before ADR 0006's quadratic curve starts moving the score
at all) — this uses data already computed (the existing population SD), no
new baseline machinery required, and doesn't bet the whole architecture on
the narrower evidence base behind the 7-day-window recommendation.

**RHR baseline methodology specifically has no independent research base at
all** (confirmed gap, not an access failure) — every real study borrows HRV
convention wholesale. Left unchanged (60-day, same structure as HRV) with
that gap now documented explicitly rather than presented as evidence-based.

### 2. SWC/noise-floor gating — added

A `HRV_RHR_NOISE_FLOOR_SD = 0.2` dead zone (Hopkins' generic population SWC
default — 0.2× SD, which is exactly what `deviation_sd` is already expressed
in units of) sits below ADR 0006's quadratic curve: a deviation smaller than
this reads as flat-50 (no real signal), not just "dampened." Real precedent:
Firstbeat's own disclosed HRV Recovery methodology already applies an SWC
floor before scaling, and all three RCT programs above use an SWC gate
operationally. Whether this hybrid (gate-then-continuous) actually
outperforms pure continuous scoring has never been tested head-to-head for
this exact purpose anywhere in the literature — adopting it is well-
precedented engineering practice, not a proven-superior method.

### 3. Sleep — need reframed as a band; quality blend reduced, not removed

**Fixed 8.0h need → 7-9h band.** A single point target contradicts the sleep
consensus itself (the NSF's own adult recommendation is a 7-9h range,
deliberately not a point value). Any night in that range now earns full
quantity credit; the rolling 14-day debt calculation's own "nightly need"
constant dropped from 8.0h to 7.0h (the band's low edge) for the same
reason. The 14-day debt *window* itself is untouched — genuinely unresolved
either way, no study anywhere compares 7 vs 14 vs 21 vs 30 days for
real-world debt tracking, so there's nothing evidence-based to change
toward.

**Sleep-quality blend (Garmin's REM/deep/restlessness score, added
2026-08-28) reduced from 50/50 to 25%.** Two independent findings converge:
Knufinke et al. 2018 (n=98 elite athletes) found sleep duration significant
and sleep-stage/efficiency measures **not** significant for next-day
performance; a real, independent, multi-device PSG validation study found
Garmin's own consumer sleep-stage classification scored **worst of 6 devices
tested** (κ=0.21, "fair," vs. a same-generation company-reported 0.54) — the
exact layer this quality score is built on. Full removal would be the more
evidence-aligned choice on this alone, but Francisco specifically asked for
this signal one day earlier (2026-08-30) and, asked directly, chose to keep
it at reduced weight rather than drop it — the REM/deep signal still counts,
just not as an equal partner to duration+debt.

### 4. TSB in the daily composite — removed permanently

Two current (2026), though not fully independent (two shared authors),
academic sources explicitly argue same-day "readiness" and multi-week
"training-stress state" are different constructs that shouldn't be fused
into one number — most directly, Kruczek, Rebelo, Gabbett & Nowak 2026
(*Frontiers in Physiology*, Perspective): *"readiness must not be
conceptualised as a unitary latent state adequately captured by a single
dashboard metric."* Reinforced circumstantially: both Garmin's Training
Readiness and WHOOP's Recovery keep multi-week load trends **out** of their
same-day scores entirely, presenting them as separate charts — exactly the
structure this project's own Training page already uses for CTL/ATL/TSB.

TSB was already zero-weighted as of 2026-08-30 (a training-load
data-coverage bug, documented in CLAUDE.md and the now-removed
`weight_tsb` config comment) — this decision makes that removal
**permanent and structural**, not contingent on the coverage bug ever being
fixed. TSB remains a real, computed trend elsewhere (`metrics/load.py`, the
Training page, the `tsb_persistently_negative` structural trigger) — it is
simply never folded back into `compute_readiness_score()`.

**Confidence, stated plainly**: moderate, not high. This rests on 2025-2026
perspective/narrative pieces from a partially-overlapping author cluster,
not a large body of independent converging work. The document most likely
to settle this authoritatively either way — Bourdon et al. 2017's IJSPP
consensus statement — could not be read in full text by this review (403s
on four mirror attempts) — a real, acknowledged gap, not silence-as-
agreement.

### 5. Composite weighting — hrv/sleep/rhr unchanged, subjective raised

No peer-reviewed study anywhere empirically derives or validates relative
weights across HRV/RHR/sleep/subjective/load against a real outcome —
confirmed by independent search passes, not merely unfound. The pre-existing
35/25/15 split for hrv/sleep/rhr is therefore kept (there is no better
number in the literature to move it toward).

**Subjective (Hooper) raised from 0.10 to 0.25** — the entirety of TSB's
freed weight. Real, named tension: Saw, Main & Gastin 2016 (systematic
review, 56 studies) found subjective wellness measures track training-load
effects with sensitivity/consistency *at least* equal to, arguably better
than, the objective measures they reviewed — yet this composite had
subjective weighted lowest of all five components. Asked directly, Francisco
chose to raise it. No literature number specifically validates "25" — giving
subjective the entirety of TSB's freed weight, rather than splitting it
across all four survivors, was chosen as the simpler, more explicable rule
given that no validated split exists either way.

### 6. Single 0-100 composite number — kept, not restructured (for now)

Confirmed (Doherty et al. 2025, re-graded here as a narrative evaluation of
company disclosures in a brand-new, not-yet-indexed journal, one co-author
being Oura's own paid Data Science Advisor — not the "systematic review"
tier a first read suggested; plus independent PubMed querying) that no
commercial composite score has a peer-reviewed validation of the composite
itself against a real outcome. Current academic voices (Rebelo 2026;
Kruczek/Gabbett 2026) argue for decomposed/quadrant presentation over a
single number; none argue for a single number beyond company marketing
copy.

**Decision**: keep computing and displaying the single composite (it is,
by construction, more transparent than any of the ten commercial scores
Doherty et al. surveyed — none of which disclose their formulas at all).
Did not restructure the Today page's visual hierarchy (component breakdown
promoted to equal or greater prominence than the single ring) as part of
this pass — that page's current design was deliberately iterated on and
approved twice already this session, and this evidence, while real, is
recent and narrow (2025-2026, overlapping authors) rather than a settled
multi-decade consensus. Worth revisiting if it comes up again, not acted on
unilaterally here.

## Consequences

- `metrics/readiness.py`: `DEFAULT_READINESS_WEIGHTS` drops `"tsb"`, raises
  `"subjective"` to 0.25; `_tsb_component_score()` removed;
  `compute_readiness_score()` no longer accepts `tsb_z_score`;
  `_deviation_to_score()` gains `HRV_RHR_NOISE_FLOOR_SD`;
  `_sleep_component_score()` reframed around `SLEEP_BAND_LOW_HOURS` (7.0) and
  a new `SLEEP_QUALITY_BLEND_WEIGHT` (0.25, down from an even blend).
- `metrics/baselines.py`: `DEFAULT_NIGHTLY_NEED_HOURS` 8.0 → 7.0.
- `config/athlete.yaml`: `readiness_score.weight_tsb` removed entirely (not
  just left at 0.0); `weight_subjective` 0.10 → 0.25.
- Both call sites that assemble the composite (`coach/briefing.py` for the
  live Today page, `metrics/derived_daily.py` for the persisted history)
  updated together — no dual-call-site drift, same discipline as ADR 0006.
  `tsb_series`/`compute_tsb_zscore()` themselves are NOT removed from either
  module — only the wiring that fed TSB into the composite is gone; the
  separate `tsb_persistently_negative` structural trigger and the
  `tsb_zscore` derived-daily metric are unaffected.
- Historical `derived_daily` readiness scores recomputed so the Trends chart
  reflects the corrected architecture throughout, not just going forward.
- Every existing readiness test asserting an exact pre-rebuild score value
  needed updating to the new expectation — the test suite is the record of
  exactly what changed and why, same as ADR 0006.

## Alternatives considered

- **Switch the HRV/RHR baseline to a 7-day rolling window.** The
  better-evidenced option on its own terms, but asked directly, Francisco
  chose the lower-risk path (keep 60 days, add the noise floor) given the
  narrower, single-lineage evidence base behind the specific 7-day
  recommendation and the larger rearchitecting cost (baseline computation,
  the seed-phase concept, every sustained-trigger function in
  `coach/rules.py`).
- **Remove the sleep-quality blend entirely.** Better supported by the
  device-validation evidence alone, but rejected because it would silently
  walk back a feature Francisco explicitly asked for one day earlier;
  reducing its weight instead keeps the signal without treating unreliable
  data as an equal partner to duration.
- **Leave TSB zero-weighted rather than remove it.** Rejected — a stopgap
  for a data bug and a considered evidence-based exclusion are different
  claims, and leaving it as a "temporary" 0.0 forever would misrepresent
  which one this is.
- **Invent a new weight split across all four surviving components instead
  of giving TSB's freed weight entirely to subjective.** Rejected as more
  arbitrary, not less — no evidence favors a specific alternative split, and
  "give the freed weight to the one component the evidence says was
  under-weighted" is a simpler, more explicable rule than an invented
  four-way redistribution.
- **Restructure the Today page to de-emphasize the single number.**
  Real, current evidence exists for this, but it's recent and narrow, and
  the page's current hierarchy was already twice deliberately designed and
  approved this session. Deferred rather than acted on unilaterally.
