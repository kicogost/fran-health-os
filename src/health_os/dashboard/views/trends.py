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
    with st.container(border=True):
        ui.eyebrow(f"{label} ({unit})")
        obs = data.to_tuples(windowed, "date", column)
        if not obs:
            st.write(f"No {label.lower()} data in this window.")
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
        st.plotly_chart(fig, width="stretch")


_chart("weight_kg", "Weight", "kg", "weight")
_chart("hrv_overnight_ms", "HRV (overnight)", "ms", "hrv")
_chart("resting_hr", "Resting heart rate", "bpm", "rhr")

stage_cols = {
    "sleep_deep_min": ("Deep", ui.GREEN),
    "sleep_light_min": ("Light", ui.BLUE),
    "sleep_rem_min": ("REM", "#a371f7"),
    "sleep_awake_min": ("Awake", ui.RED),
}
with st.container(border=True):
    ui.eyebrow("Sleep stages (minutes)")
    have_any = any(windowed[c].notna().any() for c in stage_cols)
    if not have_any:
        st.write("No sleep stage data in this window.")
    else:
        fig = ui.base_figure()
        for col, (label, color) in stage_cols.items():
            obs = data.to_tuples(windowed, "date", col)
            if not obs:
                continue
            fig.add_bar(
                x=[d for d, _ in obs], y=[v for _, v in obs], name=label, marker_color=color
            )
        fig.update_layout(barmode="stack")
        st.plotly_chart(fig, width="stretch")
