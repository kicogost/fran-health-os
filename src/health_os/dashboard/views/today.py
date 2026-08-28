"""Today — readiness + breakdown, prescription, sleep, weight EWMA, comp countdown."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from health_os.dashboard import data
from health_os.dashboard import theme as ui
from health_os.metrics import baselines, body_comp
from health_os.metrics import load as load_metrics
from health_os.metrics import readiness as readiness_metrics

st.title("Today")

daily = data.daily_metrics_df()
activities = data.activities_df()
bjj = data.bjj_sessions_df()
subjective = data.subjective_log_df()
config = data.load_athlete_config()

if daily.empty:
    st.info("No daily_metrics data yet — run `uv run python scripts/sync.py` first.")
    st.stop()

latest_date = daily["date"].max()
last_row = daily.iloc[-1]

hrv_obs = data.to_tuples(daily, "date", "hrv_overnight_ms")
rhr_obs = data.to_tuples(daily, "date", "resting_hr")
sleep_obs = data.to_tuples(daily, "date", "sleep_total_min")
weight_obs = data.to_tuples(daily, "date", "weight_kg")

hrv_result = baselines.compute_hrv_baseline(hrv_obs)
rhr_result = baselines.compute_rhr_baseline(rhr_obs)
sleep_debt_result = baselines.compute_sleep_debt(sleep_obs)

bjj_cal = config["training_load"]["bjj_rpe_calibration_factor"]
activity_loads = data.to_tuples(activities, "local_date", "training_load")
bjj_loads = data.to_tuples(bjj, "date", "computed_load")
daily_load_series = load_metrics.build_daily_load_series(
    activity_loads, bjj_loads, bjj_calibration_factor=bjj_cal
)
tsb_series = [(d, tsb) for d, _ctl, _atl, tsb in load_metrics.compute_ctl_atl(daily_load_series)]
tsb_zscore_result = load_metrics.compute_tsb_zscore(tsb_series)

hooper_index = None
if not subjective.empty:
    logged = subjective.dropna(subset=["hooper_index"])
    if not logged.empty:
        hooper_index = float(logged["hooper_index"].iloc[-1])


def _if_full(result: dict, key: str) -> float | None:
    return result[key] if result.get("confidence") == "full" else None


score_result = readiness_metrics.compute_readiness_score(
    hrv_deviation_sd=_if_full(hrv_result, "deviation_sd"),
    rhr_deviation_sd=_if_full(rhr_result, "deviation_sd"),
    last_night_sleep_hours=(sleep_obs[-1][1] / 60.0) if sleep_obs else None,
    sleep_debt_hours=sleep_debt_result["debt_hours"]
    if sleep_debt_result["confidence"] != "insufficient_data"
    else None,
    tsb_z_score=_if_full(tsb_zscore_result, "z_score"),
    hooper_index=hooper_index,
    weights=data.readiness_weights(config),
)
score = score_result["score"]
band = ui.band_label(score)

col1, col2 = st.columns([1, 2])
with col1:
    st.metric("Readiness", f"{score:.0f}" if score is not None else "—")
    st.markdown(
        f"**Band:** <span style='color:{ui.band_color(score)}'>{band}</span>",
        unsafe_allow_html=True,
    )
    st.caption(
        f"as of {latest_date} · coverage {score_result['coverage'] * 100:.0f}% · "
        f"confidence: {score_result['confidence']}"
    )
with col2:
    if score_result["components"]:
        st.write("**Component breakdown**")
        for name, comp in score_result["components"].items():
            st.progress(
                min(max(comp["score"] / 100, 0.0), 1.0),
                text=f"{name}: {comp['score']:.0f}  (weight {comp['weight_used'] * 100:.0f}%)",
            )
    else:
        st.info("No components have enough data yet for a readiness score.")

st.divider()
st.subheader("Today's guidance")
_GUIDANCE = {
    "Green": "Train as scheduled. BJJ live rounds fine; lifting days get a load progression "
    "attempt.",
    "Amber": "Train as scheduled, cap intensity. BJJ technical/no-ego rolls; hold calisthenics "
    "load; bike strictly Z2.",
    "Red": "Downgrade, don't delete: BJJ drilling only; calisthenics → mobility + light "
    "kettlebell.",
    "No data": "Not enough data yet for a guidance band.",
}
st.write(_GUIDANCE[band])
st.caption(
    "Simplified preview of the readiness bands from CLAUDE.md's coaching-layer spec — "
    "the full rules engine (safety rails, structural triggers, the 2-red/3-amber rule "
    "before downgrading a session) lands in Phase 7, not implemented here."
)

st.divider()
c1, c2, c3 = st.columns(3)

with c1:
    st.write("**Sleep (last night)**")
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

with c2:
    st.write("**Weight (7-day EWMA)**")
    if weight_obs:
        ewma_series = body_comp.compute_weight_ewma(weight_obs)
        st.metric("EWMA", f"{ewma_series[-1][1]:.2f} kg")
        st.caption(f"last real weigh-in: {weight_obs[-1][1]:.2f} kg on {weight_obs[-1][0]}")
    else:
        st.write("No weight data yet.")

with c3:
    st.write("**Comp countdown**")
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
