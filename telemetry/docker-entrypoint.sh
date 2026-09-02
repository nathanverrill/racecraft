#!/bin/sh
set -e
cd /app/ingestion
VENUE="${VENUE:-gateway-kartplex}"

echo "=== Stage A: recording -> validated dataset ($VENUE) ==="
python kart/run.py "$VENUE"
echo
echo "=== Stage B: analytics, coaching, dashboards ==="
python kart/run_stage_b.py "$VENUE"
echo
echo "=== Coaching debrief ==="
python kart/show_coaching.py "$VENUE"

if [ "$1" = "--no-serve" ]; then exit 0; fi
echo
echo "Dashboards: http://localhost:8800/  (Ctrl-C to stop)"
exec python -m http.server 8800 --bind 0.0.0.0 -d /app/ingestion/output
