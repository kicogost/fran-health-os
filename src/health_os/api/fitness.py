"""VO2max section (Trends page) -- one read-only assembly function, same
"thin API over the real metric" shape as the other api/ modules. All the
estimation logic lives in metrics/vo2max.py; this only fetches inputs."""

from __future__ import annotations

import sqlite3
from typing import Any

from health_os.metrics.body_comp import compute_weight_ewma
from health_os.metrics.vo2max import bjj_rest_recovery, build_vo2max_summary


def _col(conn: sqlite3.Connection, column: str, as_of: str) -> list[tuple[str, float]]:
    rows = conn.execute(
        f"SELECT date, {column} AS v FROM daily_metrics "  # noqa: S608 - fixed column names only
        f"WHERE {column} IS NOT NULL AND date <= ? ORDER BY date",
        (as_of,),
    ).fetchall()
    return [(r["date"], float(r["v"])) for r in rows]


def _bjj_recovery_sessions(conn: sqlite3.Connection, as_of: str) -> list[dict[str, Any]]:
    """Round-to-rest heart-rate drop per auto-segmented BJJ session. Context
    for the VO2max section only, never an input to the estimate."""
    rows = conn.execute(
        """SELECT s.activity_id, a.local_date AS day, s.label,
                  s.start_s, s.end_s, s.avg_hr
           FROM activity_auto_segments s JOIN activities a USING (activity_id)
           WHERE a.local_date <= ?
           ORDER BY a.start_utc, s.segment_index""",
        (as_of,),
    ).fetchall()
    by_activity: dict[str, dict[str, Any]] = {}
    for r in rows:
        entry = by_activity.setdefault(r["activity_id"], {"date": r["day"], "segments": []})
        entry["segments"].append(dict(r))
    sessions = []
    for entry in by_activity.values():
        drop = bjj_rest_recovery(entry["segments"])
        if drop is not None:
            sessions.append({"date": entry["date"], "avg_drop_bpm": drop})
    return sessions


def build_fitness_payload(
    conn: sqlite3.Connection, config: dict[str, Any], as_of: str
) -> dict[str, Any]:
    hr_max = float(config["fitness"]["hr_max_bpm"])
    summary = build_vo2max_summary(
        vo2_obs=_col(conn, "vo2max", as_of),
        rhr_obs=_col(conn, "resting_hr", as_of),
        hrv_obs=_col(conn, "hrv_overnight_ms", as_of),
        weight_ewma=compute_weight_ewma(_col(conn, "weight_kg", as_of)),
        hr_max=hr_max,
        as_of=as_of,
    )
    summary["bjj_recovery"] = _bjj_recovery_sessions(conn, as_of)
    return summary
