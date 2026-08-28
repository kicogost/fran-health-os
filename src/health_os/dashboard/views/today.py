"""Today — readiness + breakdown, prescription, sleep, weight EWMA, comp countdown."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from health_os.dashboard import data
from health_os.dashboard import theme as ui
from health_os.metrics import body_comp

st.title("Today")

daily = data.daily_metrics_df()
config = data.load_athlete_config()

if daily.empty:
    st.info("No daily_metrics data yet — run `uv run python scripts/sync.py` first.")
    st.stop()

latest_date = daily["date"].max()
last_row = daily.iloc[-1]
weight_obs = data.to_tuples(daily, "date", "weight_kg")

plan = data.daily_plan(latest_date)
score_result = plan["score_result"]
score = score_result["score"]
band = plan["band"]
band_title = band.replace("_", " ").title()

COMPONENT_LABELS = {
    "hrv": "HRV",
    "sleep": "Sleep",
    "rhr": "RHR",
    "tsb": "Freshness",
    "subjective": "Wellness",
}

with st.container(border=True):
    col_ring, col_components = st.columns([1, 2], vertical_alignment="center")
    with col_ring:
        ui.eyebrow("Readiness")
        st.markdown(
            ui.ring_svg(
                f"{score:.0f}" if score is not None else "–",
                band_title,
                score,
                ui.band_color(score),
                size=180,
            ),
            unsafe_allow_html=True,
        )
        st.caption(
            f"as of {latest_date} · coverage {score_result['coverage'] * 100:.0f}% · "
            f"confidence: {score_result['confidence']}"
        )
    with col_components:
        ui.eyebrow("Components")
        if score_result["components"]:
            comp_cols = st.columns(len(score_result["components"]))
            for col, (key, comp) in zip(comp_cols, score_result["components"].items(), strict=True):
                with col:
                    st.markdown(
                        ui.mini_ring_svg(comp["score"], ui.band_color(comp["score"])),
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f"<div style='text-align:center;font-weight:600;font-size:0.85rem;'>"
                        f"{comp['score']:.0f}</div>"
                        f"<div style='text-align:center;color:{ui.MUTED};font-size:0.72rem;'>"
                        f"{COMPONENT_LABELS.get(key, key)}</div>",
                        unsafe_allow_html=True,
                    )
        else:
            st.info("No components have enough data yet for a readiness score.")

with st.container(border=True):
    ui.eyebrow(f"Today's guidance — {plan['weekday_name'].capitalize()}")
    if not plan["sessions"]:
        st.markdown("##### Nothing scheduled today per `comp_prep.weekly_template`.")
    else:
        for session in plan["sessions"]:
            line = f"**{session['label']}** — {session['instruction']}"
            detail = session.get("format") or session.get("notes")
            if detail:
                line += f"  \n<span style='color:{ui.MUTED};font-size:0.85rem;'>{detail}</span>"
            st.markdown(f"##### {line}", unsafe_allow_html=True)

    flags = plan["structural_flags"]
    warnings = []
    if flags["downgrade_to_rest"]:
        warnings.append(
            "2+ consecutive red days or 3 amber days in a row — consider downgrading further."
        )
    if flags["hrv_sustained_low"]:
        warnings.append("HRV has sat >1 SD below baseline for 3 straight days.")
    if flags["tsb_persistently_negative"]:
        warnings.append("TSB has been negative for 4+ straight days.")
    if flags["monotony_strain"]:
        warnings.append("High monotony this week with strain in the recent top quartile.")
    for w in warnings:
        st.warning(f"⚠ Structural: {w}")

    st.caption(
        "Real coaching-rules output (`coach/rules.py` + `coach/briefing.py`, Phase 7) — "
        "the same computation `scripts/briefing.py` prints from the CLI, not a "
        "dashboard-only preview."
    )

c1, c2, c3 = st.columns(3)

with c1, st.container(border=True):
    ui.eyebrow("Sleep (last night)")
    if pd.notna(last_row.get("sleep_total_min")):
        st.metric("Total sleep", f"{last_row['sleep_total_min'] / 60:.1f}h")
        stages = ["sleep_deep_min", "sleep_light_min", "sleep_rem_min", "sleep_awake_min"]
        parts = [
            f"{s.removeprefix('sleep_').removesuffix('_min')} {last_row[s]:.0f}m"
            for s in stages
            if pd.notna(last_row.get(s))
        ]
        if parts:
            st.caption(" · ".join(parts))
    else:
        st.write("No sleep data for the most recent day.")

with c2, st.container(border=True):
    ui.eyebrow("Weight (7-day EWMA)")
    if weight_obs:
        ewma_series = body_comp.compute_weight_ewma(weight_obs)
        st.metric("EWMA", f"{ewma_series[-1][1]:.2f} kg")
        st.caption(f"last real weigh-in: {weight_obs[-1][1]:.2f} kg on {weight_obs[-1][0]}")
    else:
        st.write("No weight data yet.")

with c3, st.container(border=True):
    ui.eyebrow("Comp countdown")
    if weight_obs:
        trend = body_comp.weight_trend_ols(weight_obs)
        ewma_series = body_comp.compute_weight_ewma(weight_obs)
        countdown = body_comp.comp_countdown(
            current_weight_kg=ewma_series[-1][1],
            trend_slope_kg_per_week=trend["slope_kg_per_week"],
            comp_date=config["goals"]["primary"]["date"],
            weight_limit_kg=config["goals"]["primary"]["weight_division_kg"],
            today=latest_date,
        )
        st.metric("kg to lose", f"{countdown['kg_remaining']:.2f}")
        st.caption(f"{countdown['weeks_remaining']:.1f} weeks left")
        req = countdown["required_kg_per_week"]
        if req is not None:
            flag = "  ⚠️ over 0.7 red line" if countdown["red_flag"] else ""
            st.write(f"Required: **{req:.2f} kg/wk**{flag}")
    else:
        st.write("No weight data yet.")

if plan["nutrition_focus"] or plan["trend_observation"]:
    with st.container(border=True):
        ui.eyebrow("Nutrition & trend")
        st.write(plan["nutrition_focus"])
        if plan["trend_observation"]:
            st.write(f"**Trend:** {plan['trend_observation']}")
