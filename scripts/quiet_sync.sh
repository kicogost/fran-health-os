#!/bin/bash
# Built 2026-08-29: Francisco wanted the morning briefing ready before an
# 8:15am ride-planning decision, which meant moving the daily morning job
# earlier (see launchd/com.healthos.morning.plist) -- but an early-morning
# run alone can't see that day's *own* activities (a ride done at midday) or
# a same-day Renpho weigh-in that lands on iCloud later in the morning.
# Rather than syncing constantly (health data only updates a few times a
# day at most -- polling every few minutes would gain nothing), this is one
# extra quiet pass in the evening that catches the rest of the day: sync +
# recompute derived metrics, no briefing, no notification on success. The
# NEXT morning's early run then already has a complete picture of
# yesterday, instead of needing an ad hoc "can you check" like the one that
# prompted building this.
#
# Same non-fatal-sync-error handling as morning_run.sh, same reasoning:
# sync_garmin() already degrades gracefully and logs to ingest_runs itself.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

LOG_DIR="$REPO_ROOT/data/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/quiet_sync.log"
TODAY_LOCAL="$(TZ=Europe/Madrid date +%Y-%m-%d)"

{
  echo "===== $(TZ=Europe/Madrid date '+%Y-%m-%d %H:%M:%S %Z') ====="

  echo "--- sync ---"
  /opt/homebrew/bin/uv run python scripts/sync.py
  SYNC_EXIT=$?

  echo "--- compute derived metrics ---"
  /opt/homebrew/bin/uv run python scripts/compute_derived.py

  echo ""
} >> "$LOG_FILE" 2>&1

# Deliberately silent on success -- this run isn't meant to be read, only to
# make tomorrow morning's real briefing complete. Only surface a
# notification if something actually needs attention.
if [ "$SYNC_EXIT" -ne 0 ]; then
  NOTE_TEXT="Evening sync had errors -- check data/logs/quiet_sync.log."
  NOTE_TEXT_ESCAPED="$(printf '%s' "$NOTE_TEXT" | sed 's/[\\"]/\\&/g')"
  osascript -e "display notification \"$NOTE_TEXT_ESCAPED\" with title \"Health OS — $TODAY_LOCAL\"" \
    >> "$LOG_FILE" 2>&1
fi

exit 0
