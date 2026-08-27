#!/usr/bin/env python3
"""Preview: weight trend + comp countdown against real data (kickoff doc section 6).

    uv run python scripts/weight_report.py

This is a preview of a slice of Phase 4, run ahead of the rest of it because
weight has no Garmin dependency to reconcile — see metrics/body_comp.py's module
docstring. It reads `daily_metrics.weight_kg` and `config/athlete.yaml`'s comp
date/weight limit, prints the numbers, and stops there: it does not write to
`derived_daily` (that lands with the full Phase 4 metric suite) and does not
touch the dashboard (Phase 5).
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from health_os.core import db  # noqa: E402
from health_os.core.timezones import DEFAULT_TZ  # noqa: E402
from health_os.metrics.body_comp import (  # noqa: E402
    comp_countdown,
    compute_weight_ewma,
    weight_trend_ols,
)

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "athlete.yaml"


def load_weight_observations(conn) -> list[tuple[str, float]]:
    rows = conn.execute(
        "SELECT date, weight_kg FROM daily_metrics WHERE weight_kg IS NOT NULL ORDER BY date ASC"
    ).fetchall()
    return [(row["date"], row["weight_kg"]) for row in rows]


def main(argv: list[str] | None = None) -> int:
    conn = db.init_db()
    try:
        observations = load_weight_observations(conn)
    finally:
        conn.close()

    if not observations:
        print("No weight data in daily_metrics yet — run scripts/backfill.py first.")
        return 1

    athlete = yaml.safe_load(CONFIG_PATH.read_text())
    comp_date = athlete["goals"]["primary"]["date"]
    weight_limit_kg = athlete["goals"]["primary"]["weight_division_kg"]

    ewma = compute_weight_ewma(observations)
    current_ewma_date, current_ewma_weight = ewma[-1]
    latest_raw_date, latest_raw_weight = observations[-1]

    trend = weight_trend_ols(observations)
    today = datetime.now(ZoneInfo(DEFAULT_TZ)).date().isoformat()
    countdown = comp_countdown(
        current_weight_kg=current_ewma_weight,
        trend_slope_kg_per_week=trend["slope_kg_per_week"],
        comp_date=comp_date,
        weight_limit_kg=weight_limit_kg,
        today=today,
    )

    print(f"Weight data: {len(observations)} days, {observations[0][0]} to {latest_raw_date}")
    print(f"Latest raw weigh-in: {latest_raw_weight:.2f} kg on {latest_raw_date}")
    print(f"7-day EWMA (as of {current_ewma_date}): {current_ewma_weight:.2f} kg")
    print()

    if trend["confidence"] == "insufficient_data":
        print(f"21-day trend: insufficient data (n={trend['n']}, need >= 5 points in the window)")
    else:
        ci_low, ci_high = trend["ci_low_kg_per_week"], trend["ci_high_kg_per_week"]
        print(
            f"21-day trend: {trend['slope_kg_per_week']:+.3f} kg/week "
            f"(95% CI [{ci_low:+.3f}, {ci_high:+.3f}], n={trend['n']})"
        )
    print()

    print(f"Comp: {comp_date}, division limit {weight_limit_kg:.2f} kg")
    print(
        f"  {countdown['days_remaining']} days / {countdown['weeks_remaining']:.1f} weeks remaining"
    )
    print(f"  kg remaining to lose: {countdown['kg_remaining']:+.2f} kg")
    if countdown["required_kg_per_week"] is not None:
        print(f"  required rate: {countdown['required_kg_per_week']:+.3f} kg/week")
    if countdown["actual_kg_per_week"] is not None:
        print(f"  actual rate (from trend): {countdown['actual_kg_per_week']:+.3f} kg/week")
    verdict = "RED — cut is now a performance-risk problem" if countdown["red_flag"] else "on track"
    print(f"  {verdict}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
