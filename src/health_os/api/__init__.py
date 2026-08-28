"""Local-only FastAPI backend bridging the existing `core`/`metrics`/`coach`
Python modules to the React/Tailwind frontend (ADR 0005). Never exposed
beyond localhost — design principle 1 (local-first, no cloud services).

Every route is a thin wrapper over one real assembly function (e.g.
`api/today.py: build_today_payload()`) that does the actual work and is
tested independently of FastAPI/HTTP entirely — the same "one real
computation, not duplicated per caller" discipline `coach/briefing.py`
already established for the CLI and the Streamlit dashboard.
"""
