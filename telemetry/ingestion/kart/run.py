"""run.py - chain the full Stage A pipeline for a venue (NO vision).

  python kart/run.py [venue]      # default venue = gateway-kartplex

Runs steps 1..7 in order; each step self-validates and the hard gates (sessions,
laps) raise SystemExit on failure, leaving the last good checkpoint intact.
"""
import sys

import ingest
import timesheet
import sessions
import sync
import fuse
import laps
import write_dataset


def main(venue="gateway-kartplex"):
    ingest.run(venue)        # 1
    timesheet.run(venue)     # 2
    sessions.run(venue)      # 3  (gate)
    sync.run(venue)          # 4
    fuse.run(venue)          # 5
    laps.run(venue)          # 6  (gate)
    write_dataset.run(venue)  # 7
    print("\n[run] Stage A complete for venue:", venue)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "gateway-kartplex")
