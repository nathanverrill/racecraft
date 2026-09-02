"""show_coaching.py - print the coaching debrief and next-session strategy for
every session of a venue. Reads dataset/coaching.json written by Stage B.

  python kart/show_coaching.py [venue]
"""
import json
import sys
from pathlib import Path

from common import OUTPUT


def show(venue: str) -> None:
    vdir = OUTPUT / venue
    sessions = sorted(p for p in vdir.iterdir()
                      if p.is_dir() and (p / "dataset" / "coaching.json").exists())
    if not sessions:
        sys.exit(f"no coaching.json under {vdir}; run run_stage_b.py first")

    for sdir in sessions:
        c = json.loads((sdir / "dataset" / "coaching.json").read_text())
        d = c["debrief"]
        print("=" * 72)
        print(f"{venue}  {c['session_key']}")
        print("=" * 72)
        print(d["headline"])
        print(d["consistency_overall"])
        print(f"Biggest opportunity: {d['biggest_opportunity']}")
        print(f"Weakest sector:      {d['weakest_sector']}")

        print("\nSector consistency (0-100):")
        for s in c["sector_consistency"].values():
            print(f"  {s['name']:<22} {s['consistency_score']:>5.0f}   sigma {s['std_s']:.2f}s")

        print("\nNext-session strategy:")
        for item in c["next_session_strategy"]:
            print(f"  {item['priority']}. {item['where']} ({item['why']})")
            print(f"     {item['do']}")

        print("\nSession plan:")
        for line in c["session_plan"]:
            print(f"  - {line}")

        inc = c["incidents"].get("incident_laps", [])
        if inc:
            print("\nIncident laps:")
            for i in inc:
                print(f"  lap {i['lap']:>2}  {i['lap_time']:.3f}s  lost {i['lost_s']:.1f}s  "
                      f"peak {i['peak_g']:.1f} g  {i['likely']}")

        print("\nCaveats:")
        for k, v in c["honesty_notes"].items():
            print(f"  {k}: {v}")
        print()


if __name__ == "__main__":
    show(sys.argv[1] if len(sys.argv) > 1 else "gateway-kartplex")
