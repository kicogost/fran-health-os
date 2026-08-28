#!/bin/bash
# The "one command each morning" flow (kickoff doc's definition-of-done for
# v1): sync Garmin + weight, recompute everything, print a briefing — plus
# the weekly retro on Sundays. This is the script launchd actually runs
# (see docs/launchd/com.healthos.morning.plist) — kept as a separate .sh
# rather than inlined in the plist so it's runnable and testable by hand
# too: `bash scripts/morning_run.sh`.
#
# Deliberately does NOT `set -e` across the sync step: a transient Garmin API
# failure (network blip, a real 429, MFA somehow re-triggering) shouldn't
# prevent the briefing from still running against whatever data already
# exists — sync_garmin() already degrades gracefully and logs failures to
# ingest_runs itself; this wrapper just makes sure a bad sync doesn't also
# swallow the briefing.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

LOG_DIR="$REPO_ROOT/data/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/morning_run.log"
TODAY_LOCAL="$(TZ=Europe/Madrid date +%Y-%m-%d)"
WEEKDAY="$(TZ=Europe/Madrid date +%A)"

{
  echo "===== $(TZ=Europe/Madrid date '+%Y-%m-%d %H:%M:%S %Z') ====="

  echo "--- sync ---"
  /opt/homebrew/bin/uv run python scripts/sync.py
  SYNC_EXIT=$?

  echo "--- briefing ---"
  BRIEFING_OUTPUT="$(/opt/homebrew/bin/uv run python scripts/briefing.py)"
  echo "$BRIEFING_OUTPUT"

  if [ "$WEEKDAY" = "Sunday" ]; then
    echo "--- weekly retro ---"
    /opt/homebrew/bin/uv run python scripts/weekly_retro.py
  fi

  echo ""
} >> "$LOG_FILE" 2>&1

# A lightweight at-a-glance signal, independent of opening the dashboard or
# the log file -- macOS's built-in notification center, no new dependency.
READINESS_LINE="$(echo "$BRIEFING_OUTPUT" | grep '^Readiness:' | head -1)"
if [ "$SYNC_EXIT" -ne 0 ]; then
  NOTE_TEXT="Sync had errors today -- check data/logs/morning_run.log. $READINESS_LINE"
else
  NOTE_TEXT="$READINESS_LINE"
fi
osascript -e "display notification \"$NOTE_TEXT\" with title \"Health OS — $TODAY_LOCAL\"" \
  >> "$LOG_FILE" 2>&1

exit 0
