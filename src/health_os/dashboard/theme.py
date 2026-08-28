"""Shared dark theme + chart helpers for the dashboard (Phase 5).

One place for the "raw points always shown behind smoothed lines, lighter
shade" rule (kickoff doc's dashboard spec) so every page draws it the same
way instead of re-inventing the styling per chart.
"""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

BG = "#0e1117"
PANEL = "#161b22"
GRID = "#262c36"
TEXT = "#e6e6e6"
MUTED = "#8b949e"

# One accent colour per recurring series, kept consistent across pages so
# "HRV" always means the same colour whether you're on Today or Trends.
ACCENT = {
    "weight": "#58a6ff",
    "hrv": "#3fb950",
    "rhr": "#f85149",
    "sleep": "#a371f7",
    "tsb": "#d29922",
    "ctl": "#58a6ff",
    "atl": "#f85149",
    "load": "#8b949e",
}

GREEN = "#3fb950"
AMBER = "#d29922"
RED = "#f85149"


def configure_page(title: str) -> None:
    st.set_page_config(page_title=f"Health OS — {title}", layout="wide")
    st.markdown(
        f"""
        <style>
        .stApp {{ background-color: {BG}; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def band_color(score: float | None) -> str:
    """Kickoff doc readiness bands: Green >=75, Amber 55-74, Red <55."""
    if score is None:
        return MUTED
    if score >= 75:
        return GREEN
    if score >= 55:
        return AMBER
    return RED


def band_label(score: float | None) -> str:
    if score is None:
        return "No data"
    if score >= 75:
        return "Green"
    if score >= 55:
        return "Amber"
    return "Red"


def base_figure(*, height: int = 360) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor=BG,
        plot_bgcolor=PANEL,
        font=dict(color=TEXT),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis=dict(gridcolor=GRID, zeroline=False),
        yaxis=dict(gridcolor=GRID, zeroline=False),
        hovermode="x unified",
    )
    return fig


def add_raw_and_smoothed(
    fig: go.Figure,
    dates_raw: list[str],
    values_raw: list[float],
    dates_smooth: list[str],
    values_smooth: list[float],
    *,
    name: str,
    color: str,
    y2: bool = False,
) -> None:
    """Raw points as faint markers, smoothed series as a solid line on top —
    the dashboard-wide convention for "don't hide the noise, but don't let it
    dominate either" (kickoff doc dashboard spec).
    """
    fig.add_trace(
        go.Scatter(
            x=dates_raw,
            y=values_raw,
            mode="markers",
            marker=dict(size=5, color=color, opacity=0.25),
            name=f"{name} (raw)",
            showlegend=False,
            yaxis="y2" if y2 else "y",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=dates_smooth,
            y=values_smooth,
            mode="lines",
            line=dict(width=2.5, color=color),
            name=name,
            yaxis="y2" if y2 else "y",
        )
    )
