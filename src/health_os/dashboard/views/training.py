"""Training — load by day/sport, CTL/ATL/TSB, monotony/strain, calisthenics progression."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from health_os.dashboard import data
from health_os.dashboard import theme as ui
from health_os.metrics import load as load_metrics

st.title("Training")

activities = data.activities_df()
bjj = data.bjj_sessions_df()
config = data.load_athlete_config()

if activities.empty and bjj.empty:
    st.info("No activities or BJJ sessions logged yet.")
    st.stop()

bjj_cal = config["training_load"]["bjj_rpe_calibration_factor"]
activity_loads = data.to_tuples(activities, "local_date", "training_load")
bjj_loads = data.to_tuples(bjj, "date", "computed_load")
daily_load_series = load_metrics.build_daily_load_series(
    activity_loads, bjj_loads, bjj_calibration_factor=bjj_cal
)

if not daily_load_series:
    st.warning(
        "No `training_load` data exists yet to build a load series from — see "
        "CLAUDE.md's training-load build-out notes: Strava's `training_load` column "
        "is stale (pre-June 2026, runs only), Garmin has none at all on this account, "
        "and no BJJ sessions have been logged yet. Log a BJJ session "
        "(`uv run python scripts/log_bjj.py`) to get this started."
    )
else:
    with st.container(border=True):
        ui.eyebrow("CTL / ATL / TSB")
        ctl_atl_tsb = load_metrics.compute_ctl_atl(daily_load_series)
        dates = [d for d, _, _, _ in ctl_atl_tsb]
        fig = ui.base_figure(height=420)
        fig.add_trace(
            go.Scatter(
                x=dates,
                y=[c for _, c, _, _ in ctl_atl_tsb],
                mode="lines",
                name="CTL (fitness)",
                line=dict(color=ui.ACCENT["ctl"], width=2.5),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=dates,
                y=[a for _, _, a, _ in ctl_atl_tsb],
                mode="lines",
                name="ATL (fatigue)",
                line=dict(color=ui.ACCENT["atl"], width=2.5),
            )
        )
        fig.add_bar(
            x=dates,
            y=[t for _, _, _, t in ctl_atl_tsb],
            name="TSB (freshness)",
            marker_color=ui.AMBER,
            opacity=0.4,
        )
        st.plotly_chart(fig, width="stretch")

        tsb_series = [(d, t) for d, _, _, t in ctl_atl_tsb]
        tsb_z = load_metrics.compute_tsb_zscore(tsb_series)
        if tsb_z["confidence"] == "full":
            st.caption(
                f"Latest TSB z-score vs. own trailing 90-day distribution: {tsb_z['z_score']:.2f}"
            )

    with st.container(border=True):
        ui.eyebrow("Monotony / strain (trailing 7 days)")
        mono = load_metrics.compute_monotony_strain(daily_load_series)
        if mono["confidence"] == "insufficient_data":
            st.write("Not enough days of load data yet (need 7).")
        elif mono["confidence"] == "undefined_zero_variance":
            st.write(
                f"Weekly load: {mono['weekly_load']:.0f}. Monotony undefined "
                "(zero variance this week)."
            )
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("Weekly load", f"{mono['weekly_load']:.0f}")
            c2.metric(
                "Monotony",
                f"{mono['monotony']:.2f}",
                delta="high" if mono["flag_high_monotony"] else None,
            )
            c3.metric("Strain", f"{mono['strain']:.0f}")
            if mono["flag_high_monotony"]:
                st.caption("⚠️ Monotony > 2.0 — little hard/easy contrast this week.")

    with st.container(border=True):
        ui.eyebrow("Load by day and sport")
        if not activities.empty:
            by_sport = (
                activities.dropna(subset=["training_load"])
                .groupby(["local_date", "sport"])["training_load"]
                .sum()
                .reset_index()
            )
            if not by_sport.empty:
                fig2 = ui.base_figure()
                for sport, group in by_sport.groupby("sport"):
                    fig2.add_bar(
                        x=group["local_date"], y=group["training_load"], name=sport or "unknown"
                    )
                fig2.update_layout(barmode="stack")
                st.plotly_chart(fig2, width="stretch")
            else:
                st.write("No activities have a `training_load` value yet to break down by sport.")

with st.container(border=True):
    ui.eyebrow("Calisthenics progression")
    st.info(
        "Not tracked yet — there's no logging mechanism for calisthenics sets/reps/load "
        "progression in the schema (only BJJ sessions and Garmin/Strava activities are "
        "logged). A real gap, not a bug: this page won't invent a chart with nothing "
        "behind it."
    )
