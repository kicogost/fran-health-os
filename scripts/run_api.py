#!/usr/bin/env python3
"""Local API server entrypoint for the React/Tailwind frontend (ADR 0005).

    uv run python scripts/run_api.py

Binds to 127.0.0.1:8000 only — never 0.0.0.0, never exposed beyond this
machine (design principle 1: local-first, no cloud services).

**Normal daily use needs no manual command at all** — `launchd/
com.healthos.api.plist` runs this in the background permanently (RunAtLoad +
KeepAlive), so http://localhost:8000 is just always there. See that file's
own header comment for install/status/removal. That background instance is
started with `--no-reload` (below) since a silently-running service has no
need for uvicorn's file-watcher.

Two ways to run it by hand, day to day vs. while editing the frontend:

- **Daily use (one command)**: build the frontend once —
  `cd frontend && npm run build` — then just run this script and open
  http://localhost:8000. `api/main.py: serve_frontend()` serves the built
  bundle from this same process; rebuild (`npm run build`) after any
  frontend code change to pick it up, since this serves whatever was last
  built, not live source. Not needed if the background LaunchAgent above is
  already running — running this by hand too would fail on "port 8000
  already in use."
- **Active frontend development**: pair with `cd frontend && npm run dev`
  (port 5173, hot reload) instead — visit :5173, not :8000, while doing
  that. Stop the background LaunchAgent first (`launchctl unload
  ~/Library/LaunchAgents/com.healthos.api.plist`) so it isn't also holding
  port 8000 with a stale build while you're iterating.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import uvicorn  # noqa: E402


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--no-reload",
        action="store_true",
        help="Disable uvicorn's file-watcher/auto-restart. Used by the "
        "background LaunchAgent, which has no need for it; leave it on "
        "(the default) when running this by hand during development.",
    )
    args = parser.parse_args(argv)

    uvicorn.run(
        "health_os.api.main:app",
        host="127.0.0.1",
        port=8000,
        reload=not args.no_reload,
        reload_dirs=[str(Path(__file__).resolve().parents[1] / "src")]
        if not args.no_reload
        else None,
    )


if __name__ == "__main__":
    main()
