"""Shared dark theme + chart helpers for the dashboard (Phase 5).

Visual language inspired by the ring-gauge/card style Francisco pointed to
(WHOOP's app) — our own colors and components, not WHOOP's actual brand
assets (those are proprietary, gated behind their design-guidelines PDF).
One place for this so every page looks like the same product instead of six
independently-styled Streamlit defaults.
"""

from __future__ import annotations

from math import pi

import plotly.graph_objects as go
import streamlit as st

from health_os.coach.rules import classify_readiness_band

# IBM Carbon's g100 dark theme tokens (carbondesignsystem.com) — a real,
# published, accessibility-tested dark palette built specifically for dense
# dashboards, rather than colors eyeballed from screenshots.
BG = "#161616"  # Carbon $background
PANEL = "#262626"  # Carbon $layer-01
PANEL_BORDER = "#393939"  # Carbon $border-subtle / $layer-02
TRACK = "#393939"  # the "empty" part of a ring gauge — same as border, one depth step up from PANEL
GRID = "#393939"
TEXT = "#f4f4f4"  # Carbon $text-primary
MUTED = "#8d8d8d"  # Carbon $text-helper

# One accent colour per recurring series, kept consistent across pages so
# "HRV" always means the same colour whether you're on Today or Trends.
# Green/amber/red/blue are Carbon's own support/interactive colors.
ACCENT = {
    "weight": "#78a9ff",
    "hrv": "#42be65",
    "rhr": "#fa4d56",
    "sleep": "#f1c21b",
    "tsb": "#78a9ff",
    "ctl": "#78a9ff",
    "atl": "#fa4d56",
    "load": "#8d8d8d",
}

GREEN = "#42be65"
AMBER = "#f1c21b"
RED = "#fa4d56"
BLUE = "#78a9ff"


FONT_STACK = "'Inter', -apple-system, system-ui, sans-serif"


def configure_page(title: str) -> None:
    st.set_page_config(page_title=f"Health OS — {title}", layout="wide")
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

        html, body, .stApp {{ background-color: {BG}; }}
        .stApp, .stApp * {{ font-family: {FONT_STACK} !important; }}
        #MainMenu, footer, header {{ visibility: hidden; }}
        .block-container {{ padding-top: 2.5rem; padding-bottom: 4rem; max-width: 1200px; }}

        /* Sidebar: match the main content's depth instead of Streamlit's
        unstyled default gray, which reads as a visible seam between the two. */
        section[data-testid="stSidebar"] {{
            background-color: {BG};
            border-right: 1px solid {PANEL_BORDER};
        }}
        section[data-testid="stSidebar"] * {{ font-family: {FONT_STACK} !important; }}

        /* st.container(border=True) -> a card. Subtle border, soft shadow for
        depth instead of a bright outline (Linear/Vercel-style minimal dark
        UI). Padding/margin follow Carbon's 8px-based spacing scale (16px =
        spacing-05, 24px = spacing-06) rather than arbitrary numbers -- a
        uniform bottom margin means pages don't need manual st.write("")
        spacers between cards. */
        div[data-testid="stVerticalBlockBorderWrapper"] {{
            background-color: {PANEL};
            border: 1px solid {PANEL_BORDER} !important;
            border-radius: 12px !important;
            box-shadow: 0 1px 3px rgba(0,0,0,0.4);
            padding: 20px 24px;
            margin-bottom: 24px;
        }}
        /* the wrapper above adds its own padding; the inner block Streamlit
        nests inside it would otherwise add a second layer of default gap */
        div[data-testid="stVerticalBlockBorderWrapper"] > div {{ gap: 0.6rem; }}

        [data-testid="stMetricValue"] {{
            font-size: 2rem;
            font-weight: 700;
            letter-spacing: -0.02em;
        }}
        [data-testid="stMetricLabel"] {{
            color: {MUTED};
            text-transform: uppercase;
            letter-spacing: 0.06em;
            font-size: 0.68rem;
            font-weight: 600;
        }}
        [data-testid="stMetricDelta"] {{ font-size: 0.8rem; }}
        h1 {{ font-weight: 800; letter-spacing: -0.02em; margin-bottom: 1.5rem; }}
        h2, h3 {{ font-weight: 700; letter-spacing: -0.01em; }}
        p, span, label, .stMarkdown {{ color: {TEXT}; }}
        .hos-eyebrow {{
            color: {MUTED};
            text-transform: uppercase;
            letter-spacing: 0.07em;
            font-size: 0.68rem;
            font-weight: 600;
            margin-bottom: 12px;
        }}
        /* tabs, radio, and form widgets: quiet the default Streamlit chrome */
        button[data-baseweb="tab"] {{ font-weight: 600; }}
        div[data-testid="stForm"] {{ border: none; padding: 0; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


_BAND_COLORS = {"green": GREEN, "amber": AMBER, "red": RED, "no_data": MUTED}


def band_color(score: float | None) -> str:
    """Maps a readiness score to its display color. Threshold classification
    itself lives in `coach/rules.py: classify_readiness_band()` — the
    canonical single source for the 75/55 cutoffs — this just adds the UI
    color mapping on top rather than keeping its own duplicate thresholds.
    """
    return _BAND_COLORS[classify_readiness_band(score)]


def ring_svg(
    value_label: str,
    sub_label: str,
    pct: float | None,
    color: str,
    *,
    size: int = 160,
    stroke: int = 12,
) -> str:
    """A rounded-cap circular progress ring (WHOOP-style "Recovery ring"),
    pure inline SVG — no JS, no chart library chrome to suppress. `pct` is
    0-100; `None` renders an empty track only (no data, not a fake zero).
    """
    r = (size - stroke) / 2
    cx = cy = size / 2
    circumference = 2 * pi * r
    fraction = 0.0 if pct is None else max(0.0, min(1.0, pct / 100.0))
    offset = circumference * (1 - fraction)
    ring_color = TRACK if pct is None else color
    return f"""
    <div style="display:flex;flex-direction:column;align-items:center;">
      <svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">
        <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{TRACK}" stroke-width="{stroke}"/>
        <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{ring_color}"
          stroke-width="{stroke}" stroke-linecap="round"
          stroke-dasharray="{circumference:.2f}" stroke-dashoffset="{offset:.2f}"
          transform="rotate(-90 {cx} {cy})"/>
        <text x="{cx}" y="{cy - 2}" text-anchor="middle" dominant-baseline="middle"
          font-size="{size * 0.22:.0f}" font-weight="700" fill="{TEXT}"
          font-family="-apple-system, sans-serif">{value_label}</text>
        <text x="{cx}" y="{cy + size * 0.16:.0f}" text-anchor="middle" dominant-baseline="middle"
          font-size="{size * 0.075:.0f}" fill="{MUTED}" letter-spacing="1"
          font-family="-apple-system, sans-serif">{sub_label.upper()}</text>
      </svg>
    </div>
    """


def mini_ring_svg(pct: float, color: str, *, size: int = 64, stroke: int = 7) -> str:
    """Small ring with just the arc, no text — for compact component rows."""
    r = (size - stroke) / 2
    cx = cy = size / 2
    circumference = 2 * pi * r
    fraction = max(0.0, min(1.0, pct / 100.0))
    offset = circumference * (1 - fraction)
    return f"""
    <svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">
      <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{TRACK}" stroke-width="{stroke}"/>
      <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="{stroke}"
        stroke-linecap="round" stroke-dasharray="{circumference:.2f}"
        stroke-dashoffset="{offset:.2f}" transform="rotate(-90 {cx} {cy})"/>
    </svg>
    """


def eyebrow(text: str) -> None:
    """Small uppercase muted label above a card's content — WHOOP's "SLEEP",
    "RECOVERY" style section headers."""
    st.markdown(f'<div class="hos-eyebrow">{text}</div>', unsafe_allow_html=True)


def base_figure(*, height: int = 360) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor=PANEL,
        plot_bgcolor=PANEL,
        font=dict(color=TEXT, family="Inter, -apple-system, sans-serif"),
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
