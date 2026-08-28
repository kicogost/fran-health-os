"""Log — BJJ session, daily wellness (Hooper-Mackinnon), waist measurement.

Same rules as the CLI scripts these mirror (`scripts/log_bjj.py`,
`log_wellness.py`, `log_measurement.py`): upsert on the table's natural key,
warn before overwriting an existing entry, let the dataclasses' own
`__post_init__` validation do the actual checking rather than duplicating it
here. A tri-state ("skip" / yes / no) select is used for boolean fields
instead of a checkbox — a checkbox can't represent "not answered today,"
which several of these fields genuinely need (design principle 6).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from health_os.core import db
from health_os.core.models import (
    SESSION_FEELINGS,
    BjjSession,
    BodyMeasurement,
    CalisthenicsSession,
    SubjectiveLogEntry,
    merge_subjective_log_entry,
)
from health_os.dashboard import data

st.title("Log")


def _today() -> str:
    return datetime.now(ZoneInfo("Europe/Madrid")).date().isoformat()


def _tri_state(label: str, key: str) -> bool | None:
    choice = st.selectbox(label, ["Skip", "Yes", "No"], key=key)
    return {"Skip": None, "Yes": True, "No": False}[choice]


tab_bjj, tab_calisthenics, tab_wellness, tab_waist = st.tabs(
    ["BJJ session", "Calisthenics", "Daily wellness", "Waist"]
)

with tab_bjj:
    session_type = st.selectbox(
        "Session type", ["class", "open_mat", "gi_drilling"], key="bjj_type"
    )
    rolling = session_type in ("class", "open_mat")
    # Outside the form (same reason as session_type above): a date_input INSIDE
    # an st.form doesn't rerun until submit, so the "already logged" check
    # below could otherwise only ever see today's date, never a backdated one
    # being entered -- a real bug (found 2026-08-28) that let a backdated
    # submission silently overwrite an existing day's entry with no warning.
    bjj_date = st.date_input(
        "Date", value=datetime.fromisoformat(_today()), key="bjj_date"
    ).isoformat()

    conn = db.init_db()
    try:
        existing = conn.execute(
            "SELECT duration_min, session_rpe, computed_load FROM bjj_sessions "
            "WHERE date = ? AND session_type = ?",
            (bjj_date, session_type),
        ).fetchone()
    finally:
        conn.close()
    if existing is not None:
        st.warning(
            f"Already logged for {bjj_date}: {existing['duration_min']}min "
            f"@ RPE {existing['session_rpe']} (load {existing['computed_load']:.0f}). "
            "Submitting again will overwrite it."
        )

    with st.container(border=True), st.form("bjj_form"):
        duration_min = st.number_input("Duration (min)", min_value=1, max_value=600, value=90)
        session_rpe = st.slider("Session RPE", 1, 10, 7)
        rounds_rolled = rounds_gassed = None
        session_feeling = None
        if rolling:
            rounds_rolled = st.number_input("Rounds rolled", min_value=0, max_value=30, value=6)
            rounds_gassed = st.number_input(
                "Rounds gassed on", min_value=0, max_value=int(rounds_rolled), value=0
            )
            session_feeling = st.select_slider(
                "Feeling at the end", SESSION_FEELINGS, value="tired"
            )
        niggles = st.text_input("Niggles (free text)", key="bjj_niggles")
        notes = st.text_area("Notes", key="bjj_notes")
        submitted = st.form_submit_button("Log session")

    if submitted:
        try:
            session = BjjSession(
                date=bjj_date,
                session_type=session_type,
                duration_min=int(duration_min),
                session_rpe=session_rpe,
                rounds_rolled=int(rounds_rolled) if rounds_rolled is not None else None,
                rounds_gassed=int(rounds_gassed) if rounds_gassed is not None else None,
                session_feeling=session_feeling,
                niggles=niggles or None,
                notes=notes or None,
            )
        except ValueError as exc:
            st.error(str(exc))
        else:
            conn = db.init_db()
            try:
                db.upsert(conn, "bjj_sessions", session.to_row(), ["date", "session_type"])
            finally:
                conn.close()
            data.clear_all_caches()
            st.success(
                f"Logged: {session.date} {session.session_type} — load {session.computed_load:.0f}"
            )
            if session.session_feeling == "dizzy":
                st.warning("Logged 'dizzy' — that's more than normal hard-training fatigue.")

with tab_calisthenics:
    cal_session_type = st.selectbox("Session type", ["strength_a", "strength_b"], key="cal_type")
    # Outside the form -- see the BJJ tab's comment above for why (real bug,
    # found 2026-08-28: an in-form date_input can't be seen by a pre-form
    # overwrite check until submit).
    cal_date = st.date_input(
        "Date", value=datetime.fromisoformat(_today()), key="cal_date"
    ).isoformat()

    conn = db.init_db()
    try:
        existing = conn.execute(
            "SELECT session_rpe FROM calisthenics_sessions WHERE date = ? AND session_type = ?",
            (cal_date, cal_session_type),
        ).fetchone()
    finally:
        conn.close()
    if existing is not None:
        st.warning(
            f"Already logged for {cal_date} ({cal_session_type}). "
            "Submitting again will overwrite it."
        )

    prescribed = (
        data.load_athlete_config()["comp_prep"]["strength_sessions"]
        .get(cal_session_type, {})
        .get("exercises", [])
    )

    with st.container(border=True), st.form("calisthenics_form"):
        exercise_inputs = []
        for raw in prescribed:
            name = raw.split(":")[0].strip()
            st.caption(raw)
            c1, c2, c3 = st.columns(3)
            sets = c1.number_input(
                "Sets", min_value=0, max_value=20, value=0, key=f"cal_sets_{name}"
            )
            reps = c2.number_input(
                "Reps", min_value=0, max_value=100, value=0, key=f"cal_reps_{name}"
            )
            added_weight = c3.number_input(
                "Added kg",
                min_value=0.0,
                max_value=100.0,
                value=0.0,
                step=0.5,
                key=f"cal_wt_{name}",
            )
            exercise_inputs.append((name, sets, reps, added_weight))
        cal_rpe = st.slider("Session RPE", 1, 10, 6, key="cal_rpe")
        cal_notes = st.text_input("Notes", key="cal_notes")
        submitted = st.form_submit_button("Log session")

    if submitted:
        exercises = [
            {
                "exercise": name,
                "sets": int(sets),
                "reps": int(reps) if reps else None,
                "added_weight_kg": added_weight or None,
                "notes": None,
            }
            for name, sets, reps, added_weight in exercise_inputs
            if sets > 0
        ]
        try:
            session = CalisthenicsSession(
                date=cal_date,
                session_type=cal_session_type,
                session_rpe=cal_rpe,
                exercises=exercises or None,
                notes=cal_notes or None,
            )
        except ValueError as exc:
            st.error(str(exc))
        else:
            conn = db.init_db()
            try:
                db.upsert(conn, "calisthenics_sessions", session.to_row(), ["date", "session_type"])
            finally:
                conn.close()
            data.clear_all_caches()
            suffix = f" — {len(exercises)} exercises logged" if exercises else ""
            st.success(f"Logged: {session.date} {session.session_type}{suffix}")

with tab_wellness:
    # Outside the form -- see the BJJ tab's comment above for why (real bug,
    # found 2026-08-28: an in-form date_input can't be seen by a pre-form
    # overwrite check until submit).
    wellness_date = st.date_input(
        "Date", value=datetime.fromisoformat(_today()), key="wellness_date"
    ).isoformat()

    conn = db.init_db()
    try:
        existing = conn.execute(
            "SELECT hooper_index FROM subjective_log WHERE date = ?", (wellness_date,)
        ).fetchone()
    finally:
        conn.close()
    if existing is not None:
        st.warning(
            f"Already logged for {wellness_date} (hooper_index={existing['hooper_index']}). "
            "Submitting again will overwrite it."
        )

    log_wellness_scores = st.checkbox("Log the 4 wellness scores today", value=True)

    with st.container(border=True), st.form("wellness_form"):
        sleep_quality = stress = fatigue = muscle_soreness = None
        if log_wellness_scores:
            st.caption("1 = best, 10 = worst")
            sleep_quality = st.slider("Sleep quality", 1, 10, 5)
            stress = st.slider("Stress", 1, 10, 5)
            fatigue = st.slider("Fatigue", 1, 10, 5)
            muscle_soreness = st.slider("Muscle soreness", 1, 10, 5)
        protein_hit = _tri_state("Hit 180g protein", "protein_hit")
        social_meal = _tri_state("Social meal", "social_meal")
        gassed = _tri_state("Gassed today", "gassed")
        niggles = st.text_input("Niggles (free text)", key="wellness_niggles")
        day_note = st.text_area("Day note", key="wellness_day_note")
        submitted = st.form_submit_button("Log wellness")

    if submitted:
        try:
            entry = SubjectiveLogEntry(
                date=wellness_date,
                protein_hit=protein_hit,
                gassed=gassed,
                social_meal=social_meal,
                niggles=niggles or None,
                day_note=day_note or None,
                sleep_quality=sleep_quality,
                stress=stress,
                fatigue=fatigue,
                muscle_soreness=muscle_soreness,
            )
        except ValueError as exc:
            st.error(str(exc))
        else:
            conn = db.init_db()
            try:
                # Merge with any existing row for this date FIRST -- see
                # merge_subjective_log_entry's docstring: hooper_index needs
                # all 4 sub-scores, which may have been logged in an earlier,
                # separate submission (a real bug otherwise, found 2026-08-28).
                entry = merge_subjective_log_entry(conn, entry)
                db.upsert(conn, "subjective_log", entry.to_row(), ["date"])
            finally:
                conn.close()
            data.clear_all_caches()
            msg = f"Logged: {entry.date}"
            if entry.hooper_index is not None:
                msg += f" — hooper_index {entry.hooper_index} (4=excellent, 40=terrible)"
            st.success(msg)

with tab_waist:
    # Outside the form -- see the BJJ tab's comment above for why (real bug,
    # found 2026-08-28: an in-form date_input can't be seen by a pre-form
    # overwrite check until submit).
    waist_date = st.date_input(
        "Date", value=datetime.fromisoformat(_today()), key="waist_date"
    ).isoformat()

    conn = db.init_db()
    try:
        existing = conn.execute(
            "SELECT value_cm FROM body_measurements WHERE date = ? AND measurement_type = 'waist'",
            (waist_date,),
        ).fetchone()
    finally:
        conn.close()
    if existing is not None:
        st.warning(
            f"Already logged for {waist_date} ({existing['value_cm']} cm). "
            "Submitting again will overwrite it."
        )

    with st.container(border=True), st.form("waist_form"):
        value_cm = st.number_input(
            "Waist (cm)", min_value=40.0, max_value=200.0, value=86.0, step=0.1
        )
        notes = st.text_input("Notes", key="waist_notes")
        submitted = st.form_submit_button("Log measurement")

    if submitted:
        measurement = BodyMeasurement(
            date=waist_date, measurement_type="waist", value_cm=value_cm, notes=notes or None
        )
        conn = db.init_db()
        try:
            db.upsert(conn, "body_measurements", measurement.to_row(), ["date", "measurement_type"])
        finally:
            conn.close()
        data.clear_all_caches()
        st.success(f"Logged: {measurement.date} waist = {measurement.value_cm} cm")
