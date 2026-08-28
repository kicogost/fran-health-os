"""Today — readiness + breakdown, prescription, sleep, weight EWMA, comp countdown."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from health_os.dashboard import data
from health_os.dashboard import theme as ui
from health_os.metrics import baselines, body_comp
from health_os.metrics import load as load_metrics
from health_os.metrics import readiness as readiness_metrics

# Day-and-session-aware guidance (Francisco asked directly, 2026-08-28: "today
# it's friday... you should suggest me how to do open mat, not generic for the
# week"). Still a simplified preview, not Phase 7's real rules engine — no
# structural triggers, no injury-guardrail integration (neck niggle -> no
# pressing progression), no 2-red/3-amber gating before downgrading a session.
# It IS a real (session_type, band) -> instruction lookup, deterministic, not
# invented per the coaching-layer's own "rules first" principle — just a
# smaller, earlier slice of it than the full engine will be.
_SESSION_GUIDANCE = {
    ("bjj", "no_gi_technical"): {
        "Green": "Live rounds in the rolling portion are fine.",
        "Amber": "Keep the rolling portion technical/no-ego — drilling stays full effort.",
        "Red": "Drilling only — skip the live rolling portion entirely.",
    },
    ("bjj", "hard_rounds"): {
        "Green": "Full send — the week's highest-intensity day, and you're green-lit for it.",
        "Amber": "Show up, but self-select intensity — push 2-3 rounds, ease off the rest.",
        "Red": "Downgrade to drilling/positional work only — the wrong day to push through red.",
    },
    ("bjj", "open_mat"): {
        "Green": "Go hard — full rounds at competition-style pace is fine.",
        "Amber": "Cap it — aim for roughly 2/3 of your usual rounds, technical focus on the rest.",
        "Red": "Drilling only if you go at all — skip live rolling entirely.",
    },
    ("bike", "easy_z2"): {
        "Green": "Upper end of your range is fine, Z3 included if legs feel good.",
        "Amber": "Strictly Z2, stay toward the lower end of your usual range.",
        "Red": "Z2 only, and consider cutting the ride short.",
    },
    ("calisthenics", "strength_a"): {
        "Green": "Attempt a load progression.",
        "Amber": "Hold current load, don't push a new PR.",
        "Red": "Mobility + light kettlebell instead of the full session.",
    },
    ("calisthenics", "strength_b"): {
        "Green": "Attempt a load progression.",
        "Amber": "Hold current load, don't push a new PR.",
        "Red": "Mobility + light kettlebell instead of the full session.",
    },
    ("rest", None): {
        "Green": "Full rest as scheduled.",
        "Amber": "Rest day — good timing.",
        "Red": "Rest day — good timing, lean into it.",
    },
}


def _today_weekday_name() -> str:
    return datetime.now(ZoneInfo("Europe/Madrid")).strftime("%A").lower()


def _scheduled_sessions_today(config: dict) -> list[dict]:
    for day_entry in config["comp_prep"]["weekly_template"]:
        if day_entry["day"] == _today_weekday_name():
            return day_entry["sessions"]
    return []


def _guidance_lines(sessions: list[dict], band: str) -> list[str]:
    lines = []
    for s in sessions:
        session_type, subtype = s["type"], s.get("subtype")
        table = _SESSION_GUIDANCE.get((session_type, subtype)) or _SESSION_GUIDANCE.get(
            (session_type, None)
        )
        label = session_type.replace("_", " ").title()
        if subtype:
            label += f" ({subtype.replace('_', ' ')})"
        detail = s.get("format") or s.get("notes")
        if band == "No data":
            instruction = "no readiness score yet to calibrate intensity — go by feel."
        elif table:
            instruction = table[band]
        else:
            instruction = "no guidance rule written for this session type yet."
        line = f"**{label}** — {instruction}"
        if detail:
            line += f"  \n<span style='color:{ui.MUTED};font-size:0.85rem;'>{detail}</span>"
        lines.append(line)
    return lines


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
                band,
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
    sessions_today = _scheduled_sessions_today(config)
    ui.eyebrow(f"Today's guidance — {_today_weekday_name().capitalize()}")
    if not sessions_today:
        st.markdown("##### Nothing scheduled today per `comp_prep.weekly_template`.")
    else:
        for line in _guidance_lines(sessions_today, band):
            st.markdown(f"##### {line}", unsafe_allow_html=True)
    st.caption(
        "Simplified preview: today's scheduled session(s) × readiness band, from a "
        "deterministic lookup — not yet Phase 7's real rules engine (no structural "
        "triggers, no injury-guardrail integration, no 2-red/3-amber gating before "
        "downgrading a session)."
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
