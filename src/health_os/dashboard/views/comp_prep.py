"""Comp prep — weight trajectory vs. the required line, projected finish + uncertainty."""

from __future__ import annotations

from datetime import date, timedelta

import plotly.graph_objects as go
import streamlit as st

from health_os.dashboard import data
from health_os.dashboard import theme as ui
from health_os.metrics import body_comp

st.title("Comp Prep")

config = data.load_athlete_config()
goal = config["goals"]["primary"]
comp_date = goal["date"]
weight_limit_kg = goal["weight_division_kg"]

st.caption(f"{goal['name']} — {comp_date} — {weight_limit_kg} kg division")

daily = data.daily_metrics_df()
weight_obs = data.to_tuples(daily, "date", "weight_kg")

if not weight_obs:
    st.info("No weight data yet.")
    st.stop()

today = weight_obs[-1][0]
ewma_series = body_comp.compute_weight_ewma(weight_obs)
trend = body_comp.weight_trend_ols(weight_obs)
countdown = body_comp.comp_countdown(
    current_weight_kg=ewma_series[-1][1],
    trend_slope_kg_per_week=trend["slope_kg_per_week"],
    comp_date=comp_date,
    weight_limit_kg=weight_limit_kg,
    today=today,
)

with st.container(border=True):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Current (EWMA)", f"{countdown['current_weight_kg']:.2f} kg")
    c2.metric("kg to lose", f"{countdown['kg_remaining']:.2f}")
    c3.metric("Weeks left", f"{countdown['weeks_remaining']:.1f}")
    req = countdown["required_kg_per_week"]
    c4.metric(
        "Required kg/wk",
        f"{req:.2f}" if req is not None else "—",
        delta="over red line" if countdown["red_flag"] else None,
        delta_color="inverse",
    )
    if trend["confidence"] == "insufficient_data":
        st.caption(
            "Trend slope: insufficient data (needs 3+ real weigh-ins in the trailing 21 days)."
        )
    else:
        actual = countdown["actual_kg_per_week"]
        st.caption(
            f"Actual trend: {actual:.2f} kg/wk (95% CI [{-trend['ci_high_kg_per_week']:.2f}, "
            f"{-trend['ci_low_kg_per_week']:.2f}], n={trend['n']})"
        )


comp_d = date.fromisoformat(comp_date)
today_d = date.fromisoformat(today)
n_weeks = max(int((comp_d - today_d).days / 7), 0) + 1
projection_dates = [(today_d + timedelta(weeks=i)).isoformat() for i in range(n_weeks + 1)]

required_path = [
    countdown["current_weight_kg"]
    - (countdown["current_weight_kg"] - weight_limit_kg) * (i / max(n_weeks, 1))
    for i in range(n_weeks + 1)
]

with st.container(border=True):
    ui.eyebrow("Weight trajectory vs. required path")
    fig = ui.base_figure(height=440)
    fig.add_trace(
        go.Scatter(
            x=[d for d, _ in weight_obs],
            y=[w for _, w in weight_obs],
            mode="markers",
            marker=dict(size=5, color=ui.ACCENT["weight"], opacity=0.3),
            name="raw weigh-ins",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[d for d, _ in ewma_series],
            y=[w for _, w in ewma_series],
            mode="lines",
            line=dict(color=ui.ACCENT["weight"], width=2.5),
            name="EWMA",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=projection_dates,
            y=required_path,
            mode="lines",
            line=dict(color=ui.GREEN, width=2, dash="dash"),
            name="required path",
        )
    )
    if trend["confidence"] != "insufficient_data":
        slope_week = trend["slope_kg_per_week"]
        ci_low, ci_high = trend["ci_low_kg_per_week"], trend["ci_high_kg_per_week"]
        proj_mid = [countdown["current_weight_kg"] + slope_week * i for i in range(n_weeks + 1)]
        proj_low = [countdown["current_weight_kg"] + ci_low * i for i in range(n_weeks + 1)]
        proj_high = [countdown["current_weight_kg"] + ci_high * i for i in range(n_weeks + 1)]
        fig.add_trace(
            go.Scatter(
                x=projection_dates,
                y=proj_high,
                mode="lines",
                line=dict(width=0),
                showlegend=False,
            )
        )
        fig.add_trace(
            go.Scatter(
                x=projection_dates,
                y=proj_low,
                mode="lines",
                line=dict(width=0),
                fill="tonexty",
                fillcolor="rgba(224,149,75,0.15)",
                name="projection 95% CI",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=projection_dates,
                y=proj_mid,
                mode="lines",
                line=dict(color=ui.AMBER, width=2, dash="dot"),
                name="projected (current trend)",
            )
        )
    fig.add_hline(
        y=weight_limit_kg, line_color=ui.RED, line_dash="dot", annotation_text="division limit"
    )
    st.plotly_chart(fig, width="stretch")

    if trend["confidence"] == "insufficient_data":
        st.caption(
            "Projection band not shown — not enough recent weigh-ins for a trend "
            "(design principle 6: never show a confidence interval from too few points)."
        )
