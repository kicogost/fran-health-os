"""Spearman-rank correlation engine between logged signals — the kickoff
doc's originally-specced "Correlation engine (Spearman rho with n/p)",
deferred multiple times (see CLAUDE.md's weekly-retro and readiness-score
sections) pending enough real data to trust. Built 2026-08-30 once
Francisco asked directly for active pattern-detection in the Q&A coach, on
his own explicit condition: "not because 2 weeks in a row something
happens means it's because of something... enough data to make an
educated accurate decision."

Two honesty gates enforce that, not one:

1. **Minimum sample size** (`MIN_N`) before a correlation is even
   attempted. Spearman's rho is genuinely unstable at small n regardless of
   what p-value it happens to produce — a "significant" result from 8 days
   is not trustworthy just because the arithmetic runs. 30 is a
   conventional floor for a reasonably stable rank-correlation estimate;
   documented here as an explicit, revisable choice, same as this
   project's other seed-phase thresholds (`metrics/baselines.py`'s 21-day
   HRV seed / 60-day computed baseline).
2. **Multiple-comparison correction** (Bonferroni) across however many
   pairs actually had enough data to test. Testing several candidate pairs
   and reporting whichever happens to clear p<0.05 is exactly how spurious
   "findings" get manufactured — the more pairs tested, the higher the
   chance one clears an uncorrected threshold by pure noise. This is the
   specific failure mode a comparison project (earlyaidopters/health-os)
   fell into by having an LLM assert a causal story from a single day's
   coincidence every morning, with no statistics behind it at all — this
   module exists specifically not to do that, even in an automated,
   deterministic form.

Design principle 6 discipline: a pair with insufficient data is reported
as `confidence="insufficient_data"`, never silently omitted and never
computed anyway with a caveat buried in prose. `CorrelationResult` carries
n, rho, and the raw + corrected p-value together, so any claim this module
does make is fully traceable back to its inputs (design principle 9).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from scipy import stats

MIN_N = 30
DEFAULT_ALPHA = 0.05


@dataclass(slots=True)
class CorrelationResult:
    x_name: str
    y_name: str
    n: int
    rho: float | None
    p_value: float | None
    alpha_used: float | None
    confidence: str  # "insufficient_data" | "not_significant" | "significant"
    description: str | None = None

    @property
    def significant(self) -> bool:
        return self.confidence == "significant"


def compute_correlation(
    x: list[float | None],
    y: list[float | None],
    x_name: str,
    y_name: str,
    *,
    alpha: float = DEFAULT_ALPHA,
    description: str | None = None,
) -> CorrelationResult:
    """Pure function: Spearman rank correlation between two same-length
    series, pairwise-dropping any date where either side is `None` (a day
    logged for one signal but not the other contributes nothing, rather
    than being coerced into a fabricated pair).

    Below `MIN_N` real pairs, returns `insufficient_data` with `rho`/
    `p_value` both `None` — never computed-anyway-with-a-caveat. `alpha`
    here is the threshold BEFORE any multiple-comparison correction;
    `compute_correlation_panel()` re-applies a corrected alpha across a
    whole batch of these.
    """
    if len(x) != len(y):
        raise ValueError(f"x and y must be the same length, got {len(x)} and {len(y)}")

    pairs = [(a, b) for a, b in zip(x, y, strict=True) if a is not None and b is not None]
    n = len(pairs)

    if n < MIN_N:
        return CorrelationResult(
            x_name, y_name, n, None, None, None, "insufficient_data", description
        )

    xs, ys = zip(*pairs, strict=True)
    rho, p_value = stats.spearmanr(xs, ys)
    confidence = "significant" if p_value < alpha else "not_significant"
    return CorrelationResult(
        x_name, y_name, n, float(rho), float(p_value), alpha, confidence, description
    )


def compute_correlation_panel(
    named_series: dict[str, list[float | None]],
    pairs: list[tuple[str, str, str]],
    *,
    alpha: float = DEFAULT_ALPHA,
) -> list[CorrelationResult]:
    """Run `compute_correlation()` over every `(x_key, y_key, description)`
    in `pairs`, each keyed into `named_series` (all series must be the same
    length and date-aligned by the caller — this function only does the
    statistics, not the joining).

    The Bonferroni correction is applied only across pairs that actually
    had `n >= MIN_N` real observations -- an insufficient-data pair was
    never really "tested" in the multiple-comparisons sense, so it
    shouldn't shrink the significance bar for the pairs that were.
    """
    raw = [
        compute_correlation(
            named_series[x_key], named_series[y_key], x_key, y_key, description=desc
        )
        for x_key, y_key, desc in pairs
    ]
    num_tested = sum(1 for r in raw if r.confidence != "insufficient_data")
    if num_tested == 0:
        return raw

    corrected_alpha = alpha / num_tested
    corrected: list[CorrelationResult] = []
    for r in raw:
        if r.confidence == "insufficient_data":
            corrected.append(r)
            continue
        confidence = "significant" if r.p_value < corrected_alpha else "not_significant"
        corrected.append(
            CorrelationResult(
                r.x_name,
                r.y_name,
                r.n,
                r.rho,
                r.p_value,
                corrected_alpha,
                confidence,
                r.description,
            )
        )
    return corrected


# The candidate pairs actually checked -- deliberately small and grounded
# only in fields that are already logged for real, not a speculative
# fishing expedition. Each documents WHY it might matter, not just that the
# columns happen to both exist. hooper_index -> readiness_score is flagged
# as partially circular (hooper_index is one of five weighted readiness
# components, at 10%) but kept -- still informative on the other 90%, and
# honesty about the overlap belongs in the description, not in silently
# dropping the pair.
_CANDIDATE_PAIRS: list[tuple[str, str, str]] = [
    ("sleep_quality", "hrv_overnight_ms", "subjective sleep quality vs. measured overnight HRV"),
    ("stress", "resting_hr", "subjective stress vs. measured resting heart rate"),
    ("fatigue", "sleep_total_min", "subjective fatigue vs. total sleep minutes"),
    (
        "hooper_index",
        "readiness_score",
        "Hooper-Mackinnon wellness index vs. the computed readiness score "
        "(hooper_index is itself ~10% of readiness_score's weight -- partially "
        "circular, still informative on the other components)",
    ),
]


def build_daily_metrics_correlation_panel(
    conn: sqlite3.Connection, *, alpha: float = DEFAULT_ALPHA
) -> list[CorrelationResult]:
    """DB-facing assembly: joins `daily_metrics`, `subjective_log`, and
    `derived_daily` (readiness_score) on date across the FULL available
    history (no arbitrary recency window — more real history only helps
    the n-based confidence gate above, never hurts it), then runs
    `compute_correlation_panel()` over `_CANDIDATE_PAIRS`.

    Kept separate from the pure functions above so those stay unit-testable
    against plain lists with zero DB setup — this function is the one
    integration point, tested against a real (if small) SQLite fixture
    instead.
    """
    rows = conn.execute(
        """
        SELECT
            dm.date,
            sl.sleep_quality,
            sl.stress,
            sl.fatigue,
            sl.hooper_index,
            dm.hrv_overnight_ms,
            dm.resting_hr,
            dm.sleep_total_min,
            dd.value AS readiness_score
        FROM daily_metrics dm
        LEFT JOIN subjective_log sl ON sl.date = dm.date
        LEFT JOIN derived_daily dd
            ON dd.date = dm.date AND dd.metric_name = 'readiness_score'
        ORDER BY dm.date
        """
    ).fetchall()

    named_series: dict[str, list[float | None]] = {
        "sleep_quality": [],
        "stress": [],
        "fatigue": [],
        "hooper_index": [],
        "hrv_overnight_ms": [],
        "resting_hr": [],
        "sleep_total_min": [],
        "readiness_score": [],
    }
    for row in rows:
        for key in named_series:
            named_series[key].append(row[key])

    return compute_correlation_panel(named_series, _CANDIDATE_PAIRS, alpha=alpha)


def correlation_result_to_dict(result: CorrelationResult) -> dict[str, Any]:
    """JSON-ready shape for the API layer / Q&A coach context."""
    return {
        "x_name": result.x_name,
        "y_name": result.y_name,
        "description": result.description,
        "n": result.n,
        "rho": result.rho,
        "p_value": result.p_value,
        "alpha_used": result.alpha_used,
        "confidence": result.confidence,
    }
