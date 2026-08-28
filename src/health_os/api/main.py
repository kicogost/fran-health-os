"""FastAPI app — the local API layer for the React/Tailwind frontend (ADR
0005). Run via `scripts/run_api.py`; binds to 127.0.0.1 only, never 0.0.0.0
(design principle 1: local-first, no cloud services, no exposure beyond
this machine).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from health_os.api.today import build_today_payload
from health_os.core import db

CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "athlete.yaml"

app = FastAPI(title="Health OS API")

# The Vite dev server (localhost:5173) and this API (localhost:8000) run as
# two separate local processes during development -- both bound to
# localhost only, never exposed beyond this machine. In production (the
# built React bundle served as static files, see docs/decisions/0005), this
# CORS layer becomes unnecessary but stays harmless (same-origin requests
# don't consult it).
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
