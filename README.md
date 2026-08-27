# Health OS

A local-first, personal health data warehouse and coaching layer, built on Francisco's
wearable data (Garmin, Strava, Apple Health, manual BJJ logs). One SQLite database, one
user, tuned for a jiu jitsu competitor rather than a generic fitness consumer.

There is no product here — this is a single-user tool. See [`CLAUDE.md`](CLAUDE.md) for
the full context, design principles, and build-phase status, and
[`HEALTH_OS_KICKOFF.md`](HEALTH_OS_KICKOFF.md) for the original spec this project was
built from.

## Status

Phase 0 (repo scaffold) complete. See `CLAUDE.md` for what's next.

## Setup

```bash
uv sync                      # install dependencies (Python 3.12+)
cp .env.example .env         # fill in Garmin/Strava credentials once ingestion lands
```

There is no runnable pipeline yet — Phase 1 (schema/DB layer) hasn't landed.

## Repo layout

```
config/          athlete profile, goals, training architecture, source settings
data/raw/        immutable downloads from each source (gitignored)
data/health.db   the one canonical SQLite store (gitignored)
src/health_os/   ingest / core / metrics / coach / dashboard packages
scripts/         sync.py, backfill.py, log_bjj.py entrypoints
tests/           pytest suite (ingest + metrics layers are mandatory-tested)
docs/decisions/  ADRs for non-obvious choices
```

## Design principles

Local-first, raw data is immutable, one canonical store, idempotent ingestion, explicit
deduplication with an audit trail, never invent data, timezone-aware (UTC stored,
Europe/Madrid rendered), secrets in `.env` only, every derived number traceable back to
its inputs. Full detail in `CLAUDE.md`.
