"""FastAPI app — the local API layer for the React/Tailwind frontend (ADR
0005). Run via `scripts/run_api.py`; binds to 127.0.0.1 only, never 0.0.0.0
(design principle 1: local-first, no cloud services, no exposure beyond
this machine).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from health_os.api import log as log_api
from health_os.api.comp_prep import build_comp_prep_payload
from health_os.api.data_health import build_data_health_payload
from health_os.api.today import build_today_payload
from health_os.api.training import build_training_payload
from health_os.api.trends import ALLOWED_WINDOW_DAYS, build_trends_payload
from health_os.core import db
from health_os.core.timezones import to_local_date
from health_os.metrics.correlations import (
    build_daily_metrics_correlation_panel,
    correlation_result_to_dict,
)

CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "athlete.yaml"
FRONTEND_DIST_DIR = Path(__file__).resolve().parents[3] / "frontend" / "dist"

app = FastAPI(title="Health OS API")

# The Vite dev server (localhost:5173) and this API (localhost:8000) run as
# two separate local processes during active frontend development -- both
# bound to localhost only, never exposed beyond this machine. For daily use
# once the frontend isn't being actively edited, `serve_frontend()` below
# serves the built bundle from this same process instead, so CORS becomes
# unnecessary but stays harmless (same-origin requests don't consult it).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _load_config() -> dict[str, Any]:
    with CONFIG_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


@app.get("/api/today")
def get_today() -> dict[str, Any]:
    conn = db.init_db()
    try:
        row = conn.execute("SELECT MAX(date) AS d FROM daily_metrics").fetchone()
        latest_date = row["d"] if row else None
        if latest_date is None:
            raise HTTPException(
                status_code=404,
                detail="No daily_metrics data yet -- run scripts/sync.py first.",
            )
        return build_today_payload(conn, _load_config(), latest_date)
    finally:
        conn.close()


@app.get("/api/trends")
def get_trends(window_days: int = 90) -> dict[str, Any]:
    if window_days not in ALLOWED_WINDOW_DAYS:
        raise HTTPException(
            status_code=422,
            detail=f"window_days must be one of {ALLOWED_WINDOW_DAYS}, got {window_days}",
        )
    conn = db.init_db()
    try:
        return build_trends_payload(conn, window_days)
    finally:
        conn.close()


@app.get("/api/training")
def get_training() -> dict[str, Any]:
    conn = db.init_db()
    try:
        # Same "latest daily_metrics date" convention as /api/today -- used
        # here only to measure load-data staleness against, not to bound
        # any query (build_training_payload's own queries are unbounded by
        # design, same as before this param was added).
        row = conn.execute("SELECT MAX(date) AS d FROM daily_metrics").fetchone()
        as_of_date = row["d"] if row and row["d"] else to_local_date(datetime.now(UTC))
        return build_training_payload(conn, _load_config(), as_of_date)
    finally:
        conn.close()


@app.get("/api/comp-prep")
def get_comp_prep() -> dict[str, Any]:
    conn = db.init_db()
    try:
        return build_comp_prep_payload(conn, _load_config())
    finally:
        conn.close()


@app.get("/api/data-health")
def get_data_health() -> dict[str, Any]:
    conn = db.init_db()
    try:
        return build_data_health_payload(conn)
    finally:
        conn.close()


@app.get("/api/insights/correlations")
def get_correlations() -> list[dict[str, Any]]:
    """Real, statistically-gated correlations between logged signals
    (metrics/correlations.py) -- most will read "insufficient_data" until
    enough wellness logging accumulates (MIN_N=30 real paired days), which
    is the honest, expected state right now, not a bug. Feeds both a
    dashboard surface and (once built) the Q&A coach's grounding context.
    """
    conn = db.init_db()
    try:
        results = build_daily_metrics_correlation_panel(conn)
        return [correlation_result_to_dict(r) for r in results]
    finally:
        conn.close()


@app.get("/api/log/prescribed-exercises")
def get_prescribed_exercises(session_type: str) -> list[str]:
    return log_api.prescribed_exercises(_load_config(), session_type)


@app.get("/api/log/bjj")
def get_log_bjj(date: str, session_type: str) -> dict[str, Any] | None:
    conn = db.init_db()
    try:
        return log_api.get_existing_bjj(conn, date, session_type)
    finally:
        conn.close()


@app.post("/api/log/bjj")
def post_log_bjj(req: log_api.BjjSessionRequest) -> dict[str, Any]:
    conn = db.init_db()
    try:
        try:
            session = log_api.save_bjj(conn, req)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return session.to_row(include_none=True)
    finally:
        conn.close()


@app.get("/api/log/wellness")
def get_log_wellness(date: str) -> dict[str, Any] | None:
    conn = db.init_db()
    try:
        return log_api.get_existing_wellness(conn, date)
    finally:
        conn.close()


@app.post("/api/log/wellness")
def post_log_wellness(req: log_api.WellnessRequest) -> dict[str, Any]:
    conn = db.init_db()
    try:
        try:
            entry = log_api.save_wellness(conn, req)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return entry.to_row(include_none=True)
    finally:
        conn.close()


@app.get("/api/log/waist")
def get_log_waist(date: str) -> dict[str, Any] | None:
    conn = db.init_db()
    try:
        return log_api.get_existing_waist(conn, date)
    finally:
        conn.close()


@app.post("/api/log/waist")
def post_log_waist(req: log_api.WaistRequest) -> dict[str, Any]:
    conn = db.init_db()
    try:
        try:
            measurement = log_api.save_waist(conn, req)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return measurement.to_row(include_none=True)
    finally:
        conn.close()


@app.get("/api/log/calisthenics")
def get_log_calisthenics(date: str, session_type: str) -> dict[str, Any] | None:
    conn = db.init_db()
    try:
        return log_api.get_existing_calisthenics(conn, date, session_type)
    finally:
        conn.close()


@app.post("/api/log/calisthenics")
def post_log_calisthenics(req: log_api.CalisthenicsRequest) -> dict[str, Any]:
    conn = db.init_db()
    try:
        try:
            session = log_api.save_calisthenics(conn, req)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return session.to_row(include_none=True)
    finally:
        conn.close()


def _safe_dist_file(full_path: str) -> Path | None:
    """Resolves `full_path` against FRONTEND_DIST_DIR, refusing to serve
    anything that escapes it (e.g. a `../../` traversal attempt) -- returns
    the real file if it exists inside dist, None otherwise (including
    "resolves outside dist entirely").
    """
    dist_root = FRONTEND_DIST_DIR.resolve()
    candidate = (dist_root / full_path).resolve()
    if candidate != dist_root and dist_root not in candidate.parents:
        return None
    return candidate if candidate.is_file() else None


# Registered LAST, deliberately -- every /api/* route above is an exact path
# match registered earlier, so it always wins; this generic path parameter
# only ever catches what nothing else claimed. Resolves the "not yet done"
# production-serving decision flagged in docs/decisions/0005: once
# `npm run build` has produced frontend/dist, `uv run python
# scripts/run_api.py` alone serves the whole app on :8000 -- no separate
# `npm run dev` process needed for day-to-day use (still useful during
# active frontend editing, for hot reload). Falls back to index.html for
# any path that isn't a real built file (e.g. /log, /trends/90) so React
# Router's client-side routes work on a hard refresh or a direct link, not
# only when reached via in-app navigation.
@app.get("/{full_path:path}")
def serve_frontend(full_path: str) -> FileResponse:
    index_file = FRONTEND_DIST_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "Frontend not built. Run `npm run build` in frontend/ once "
                "(or after any frontend change), or use `cd frontend && "
                "npm run dev` for active local development."
            ),
        )
    file_path = _safe_dist_file(full_path) if full_path else None
    return FileResponse(file_path or index_file)
