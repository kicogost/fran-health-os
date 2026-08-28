"""Data health — freshness, missing days, dedupe log, last ingest runs.

Not optional (kickoff doc dashboard spec): this is how pipeline breakage
gets noticed rather than silently going stale.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from health_os.dashboard import data
from health_os.dashboard import theme as ui

st.title("Data Health")

daily = data.daily_metrics_df()
activities = data.activities_df()
ingest_runs = data.ingest_runs_df()

with st.container(border=True):
    ui.eyebrow("Freshness")
    today = date.today().isoformat()
    FRESHNESS_COLUMNS = {
        "weight_kg": "Weight",
        "hrv_overnight_ms": "HRV",
        "resting_hr": "RHR",
        "sleep_total_min": "Sleep",
        "training_readiness": "Training readiness",
    }
    cols = st.columns(len(FRESHNESS_COLUMNS))
    for col, (field, label) in zip(cols, FRESHNESS_COLUMNS.items(), strict=True):
        if daily.empty or daily[field].dropna().empty:
            col.metric(label, "no data")
            continue
        last_date = daily.dropna(subset=[field])["date"].max()
        days_stale = (date.fromisoformat(today) - date.fromisoformat(last_date)).days
        col.metric(
            label,
            f"{days_stale}d ago" if days_stale > 0 else "today",
            help=f"last: {last_date}",
        )

with st.container(border=True):
    ui.eyebrow("Missing days (trailing 30)")
    if not daily.empty:
        cutoff = (date.fromisoformat(daily["date"].max()) - timedelta(days=29)).isoformat()
        expected = pd.date_range(cutoff, daily["date"].max(), freq="D").strftime("%Y-%m-%d")
        present = set(daily["date"])
        missing = [d for d in expected if d not in present]
        if missing:
            st.warning(
                f"{len(missing)} of 30 days have no daily_metrics row at all: {', '.join(missing)}"
            )
        else:
            st.success("Every day in the trailing 30 has at least one daily_metrics field.")
    else:
        st.info("No daily_metrics data yet.")

with st.container(border=True):
    ui.eyebrow("Dedupe log")
    if not activities.empty:
        merged = activities[activities["merged_from"].notna() & (activities["merged_from"] != "[]")]
        if merged.empty:
            st.write("No cross-source merges recorded.")
        else:
            st.write(f"{len(merged)} activities have absorbed at least one duplicate:")
            st.dataframe(
                merged[["activity_id", "source", "local_date", "sport", "merged_from"]],
                width="stretch",
                hide_index=True,
            )
    else:
        st.info("No activities yet.")

with st.container(border=True):
    ui.eyebrow("Recent ingest runs")
    if ingest_runs.empty:
        st.info("No ingest runs recorded yet.")
    else:
        display = ingest_runs.copy()
        display["errors"] = display["errors"].apply(
            lambda e: "" if e in (None, "[]", "null") else e
        )

        def _row_style(row: pd.Series) -> list[str]:
            color = "background-color: #3a1f1f" if row["status"] == "failed" else ""
            return [color] * len(row)

        st.dataframe(
            display.style.apply(_row_style, axis=1),
            width="stretch",
            hide_index=True,
        )
