#!/bin/sh
# Default: serve the web front end (home page with a "Begin analysis" button).
# --batch: run the pipeline headless, print the debrief, and exit.
set -e
cd /app/ingestion
VENUE="${VENUE:-gateway-kartplex}"

if [ "$1" = "--batch" ] || [ "$1" = "--no-serve" ]; then
  python kart/run.py "$VENUE"
  python kart/run_stage_b.py "$VENUE"
  python kart/show_coaching.py "$VENUE"
  exit 0
fi

exec python kart/webapp.py --venue "$VENUE" --port 8800
