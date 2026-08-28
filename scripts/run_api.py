#!/usr/bin/env python3
"""Local API server entrypoint for the React/Tailwind frontend (ADR 0005).

    uv run python scripts/run_api.py

Binds to 127.0.0.1:8000 only — never 0.0.0.0, never exposed beyond this
machine (design principle 1: local-first, no cloud services). Pair with
`cd frontend && npm run dev` for the Vite dev server during development.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import uvicorn  # noqa: E402


def main() -> None:
    uvicorn.run(
        "health_os.api.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_dirs=[str(Path(__file__).resolve().parents[1] / "src")],
    )


if __name__ == "__main__":
    main()
