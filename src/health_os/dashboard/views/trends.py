"""Trends — weight/HRV/RHR/sleep stages over 30/90/365-day windows."""

from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from health_os.dashboard import data
from health_os.dashboard import theme as ui

st.title("Trends")

daily = data.daily_metrics_df()
if daily.empty:
    st.info("No daily_metrics data yet.")
    st.stop()

window_days = st.radio("Window", [30, 90, 365], index=1, horizontal=True)
cutoff = (date.fromisoformat(daily["date"].max()) - timedelta(days=window_days - 1)).isoformat()
windowed = daily[daily["date"] >= cutoff]


def _chart(column: str, label: str, unit: str, color_key: str) -> None:
    obs = data.to_tuples(windowed, "date", column)
    if not obs:
        st.write(f"No {label} data in this window.")
        return
    smoothed = data.smooth_for_display(obs)
    fig = ui.base_figure()
    ui.add_raw_and_smoothed(
        fig,
        [d for d, _ in obs],
        [v for _, v in obs],
        [d for d, _ in smoothed],
        [v for _, v in smoothed],
        name=label,
        color=ui.ACCENT[color_key],
    )
    fig.update_layout(title=f"{label} ({unit})")
    st.plotly_chart(fig, width="stretch")


st.subheader("Weight")
_chart("weight_kg", "Weight", "kg", "weight")

st.subheader("HRV (overnight)")
_chart("hrv_overnight_ms", "HRV", "ms", "hrv")

st.subheader("Resting heart rate")
_chart("resting_hr", "RHR", "bpm", "rhr")

st.subheader("Sleep stages")
stage_cols = {
    "sleep_deep_min": ("Deep", "#3fb950"),
    "sleep_light_min": ("Light", "#58a6ff"),
    "sleep_rem_min": ("REM", "#a371f7"),
    "sleep_awake_min": ("Awake", "#f85149"),
}
have_any = any(windowed[c].notna().any() for c in stage_cols)
if not have_any:
    st.write("No sleep stage data in this window.")
else:
    fig = ui.base_figure()
    for col, (label, color) in stage_cols.items():
        obs = data.to_tuples(windowed, "date", col)
        if not obs:
            continue
        fig.add_bar(x=[d for d, _ in obs], y=[v for _, v in obs], name=label, marker_color=color)
    fig.update_layout(barmode="stack", title="Sleep stages (minutes)")
    st.plotly_chart(fig, width="stretch")
