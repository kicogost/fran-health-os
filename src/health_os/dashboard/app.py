"""Health OS dashboard entrypoint (Phase 5).

    uv run streamlit run src/health_os/dashboard/app.py

Read-only pages first (Today, Trends, Training, Comp Prep, Data Health), plus
the Log page (BJJ/wellness/waist forms) — kickoff doc's "read-only first,
then logging forms" phrasing describes the build order, not a permanent
split; all six pages ship together here.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import streamlit as st  # noqa: E402

from health_os.dashboard import theme  # noqa: E402

theme.configure_page("Health OS")

pages = [
    st.Page("views/today.py", title="Today", icon="🏠", default=True),
    st.Page("views/trends.py", title="Trends", icon="📈"),
    st.Page("views/training.py", title="Training", icon="🏋️"),
    st.Page("views/comp_prep.py", title="Comp Prep", icon="🥋"),
    st.Page("views/log.py", title="Log", icon="✍️"),
    st.Page("views/data_health.py", title="Data Health", icon="🩺"),
]

st.navigation(pages).run()
