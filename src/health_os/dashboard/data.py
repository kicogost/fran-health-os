"""Shared data-loading for the dashboard — every page goes through here,
never opens its own ad-hoc query (design principle 3: one canonical store,
one access path).

A fresh, short-lived `sqlite3.Connection` is opened per query rather than
cached as a resource: SQLite connections aren't safe to share across
Streamlit's script-rerun/thread model, and a local file connection is cheap
enough that this costs nothing measurable. What IS cached (`st.cache_data`)
is the query *result* — plain DataFrames, which are picklable and cheap to
compare for Streamlit's cache-invalidation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import yaml

from health_os.coach import briefing
from health_os.core import db

CACHE_TTL_S = 60  # short enough that a fresh `scripts/sync.py` run shows up quickly
CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "athlete.yaml"


def to_tuples(df: pd.DataFrame, date_col: str, value_col: str) -> list[tuple[str, float]]:
    """(date, value) pairs, sorted ascending, nulls dropped — the shape every
    `metrics/*.py` function expects. Never fills a gap; a missing day is
    just absent from the list (design principle 6).
    """
    clean = df[[date_col, value_col]].dropna().sort_values(date_col)
    return list(clean.itertuples(index=False, name=None))


@st.cache_data(ttl=CACHE_TTL_S)
def load_athlete_config() -> dict[str, Any]:
    with CONFIG_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def readiness_weights(config: dict[str, Any]) -> dict[str, float]:
    """Adapts `config/athlete.yaml: readiness_score`'s `weight_<name>` keys to
    the `{"hrv": ..., "sleep": ...}` shape `compute_readiness_score()` wants.
    """
    section = config["readiness_score"]
    return {
        "hrv": section["weight_hrv"],
        "sleep": section["weight_sleep"],
        "rhr": section["weight_rhr"],
        "tsb": section["weight_tsb"],
        "subjective": section["weight_subjective"],
    }


@st.cache_data(ttl=CACHE_TTL_S)
def daily_metrics_df() -> pd.DataFrame:
    conn = db.init_db()
    try:
        return pd.read_sql_query("SELECT * FROM daily_metrics ORDER BY date", conn)
    finally:
        conn.close()


@st.cache_data(ttl=CACHE_TTL_S)
def activities_df() -> pd.DataFrame:
    conn = db.init_db()
    try:
        return pd.read_sql_query("SELECT * FROM activities ORDER BY local_date, start_utc", conn)
    finally:
        conn.close()


@st.cache_data(ttl=CACHE_TTL_S)
def bjj_sessions_df() -> pd.DataFrame:
    conn = db.init_db()
    try:
        return pd.read_sql_query("SELECT * FROM bjj_sessions ORDER BY date", conn)
    finally:
        conn.close()


@st.cache_data(ttl=CACHE_TTL_S)
def subjective_log_df() -> pd.DataFrame:
    conn = db.init_db()
    try:
        return pd.read_sql_query("SELECT * FROM subjective_log ORDER BY date", conn)
    finally:
        conn.close()


@st.cache_data(ttl=CACHE_TTL_S)
def body_measurements_df() -> pd.DataFrame:
    conn = db.init_db()
    try:
        return pd.read_sql_query("SELECT * FROM body_measurements ORDER BY date", conn)
    finally:
        conn.close()


@st.cache_data(ttl=CACHE_TTL_S)
def ingest_runs_df() -> pd.DataFrame:
    conn = db.init_db()
    try:
        return pd.read_sql_query(
            "SELECT * FROM ingest_runs ORDER BY started_at DESC LIMIT 100", conn
        )
    finally:
        conn.close()


@st.cache_data(ttl=CACHE_TTL_S)
def daily_plan(today: str) -> dict[str, Any]:
    """The real coaching-rules output for `today` — `coach/briefing.py:
    compute_daily_plan()`, the same computation `scripts/briefing.py` prints
    from the CLI, not a dashboard-only preview. Cached the same way every
    other loader here is (`today` alone is the cache key; a fresh
    `scripts/sync.py`/log entry shows up within the TTL, same as everywhere
    else on this page).
    """
    conn = db.init_db()
    try:
        return briefing.compute_daily_plan(conn, load_athlete_config(), today)
    finally:
        conn.close()


def clear_all_caches() -> None:
    """Called after any write from the Log page — otherwise a form submit
    wouldn't show up until the 60s TTL expires."""
    st.cache_data.clear()


def smooth_for_display(
    observations: list[tuple[str, float]], span_days: int = 7
) -> list[tuple[str, float]]:
    """Same recursive-EWMA math as `metrics.body_comp.compute_weight_ewma()`,
    but kept separate and generic rather than reusing that function outside
    its documented domain (weight trend analysis) — this one is purely for
    chart smoothing (HRV/RHR/sleep) and makes no analytical claims of its own.
    """
    if not observations:
        return []
    alpha = 2.0 / (span_days + 1)
    result: list[tuple[str, float]] = []
    ewma: float | None = None
    for day, value in observations:
        ewma = value if ewma is None else alpha * value + (1 - alpha) * ewma
        result.append((day, ewma))
    return result
