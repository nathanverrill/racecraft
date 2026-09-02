"""timesheet.py - Stage A Step 2.

LOAD the pre-extracted timing-sheet *.json (NO vision/OCR). Normalize each into a
canonical timesheet dict that downstream steps consume.

Supports TWO on-disk schemas:
  (A) FLAT (original June-25 gateway-kartplex): top-level date/time/event/lapTimes[]
      with l["time"], bestLap, driver, kartNumber, ...
  (B) NESTED (reversed event export): {session:{type,date,time,configuration,...},
      driver:{name,proskill,...}, laps:[{time_seconds,best_lap}],
      results:{best_lap_seconds, average_lap_seconds, position, field_size},
      field_results:[...], leaderboards:{...}}
`time` may be 24h "HH:MM" (A) or 12h "3:45 PM" (B).

Canonical dict adds (beyond the historical keys the pipeline already used):
  - avg_lap            mean of all laps (or verbatim results.average_lap_seconds)
  - ranking_metric     "best" (practice/quali) or "average" (race)
  - configuration      e.g. "Reverse" (None if not present)
  - field_size, position, session_type
  - consistency        {n, mean, std, cv} computed straight from the sheet lap times
                       (so every session has a consistency headline even with NO
                        telemetry)

VALIDATE (generalized, data-driven): >=1 sheet parsed; each has >0 laps; best lap in
a sane physical band (20-120 s). No hardcoded lap counts / bests.

Returns a list of canonical timesheet dicts (sorted by datetime).
"""
from __future__ import annotations
import sys
from datetime import datetime

from common import INBOX, OUTPUT, load_json, write_json

SANE_LAP_MIN = 20.0
SANE_LAP_MAX = 120.0


def _parse_time(time_: str) -> str:
    """Return 24h 'HH:MM' from either '14:40' (24h) or '3:45 PM' (12h)."""
    t = time_.strip()
    for fmt in ("%H:%M", "%I:%M %p", "%I:%M%p"):
        try:
            return datetime.strptime(t, fmt).strftime("%H:%M")
        except ValueError:
            continue
    raise ValueError(f"unparseable time: {time_!r}")


def _session_key(date: str, time24: str) -> str:
    """'2026-07-01' + '15:45' -> '2026-07-01_15-45' (output folder name)."""
    hh, mm = time24.split(":")[:2]
    return f"{date}_{hh}-{mm}"


def _consistency(lap_times: list[float]) -> dict:
    """std / cv of the sheet lap times (all laps). Cheap, telemetry-free."""
    import numpy as np
    s = np.asarray([t for t in lap_times if t is not None], dtype=float)
    if len(s) == 0:
        return {}
    mean = float(np.mean(s))
    std = float(np.std(s, ddof=1)) if len(s) > 1 else 0.0
    return {"n": int(len(s)), "mean": round(mean, 3), "std": round(std, 3),
            "cv": round(std / mean, 4) if mean else 0.0}


def _is_nested(raw: dict) -> bool:
    return isinstance(raw.get("session"), dict) or "laps" in raw


def _normalize_nested(raw: dict, src_name: str) -> dict:
    sess = raw.get("session", {})
    drv = raw.get("driver", {})
    res = raw.get("results", {})
    date = sess.get("date")
    time_ = sess.get("time")
    if not date or not time_:
        raise ValueError(f"{src_name}: missing session.date/session.time")
    time24 = _parse_time(time_)
    dt = datetime.strptime(f"{date} {time24}", "%Y-%m-%d %H:%M")

    laps = raw.get("laps", [])
    lap_times = [float(l["time_seconds"]) for l in laps if l.get("time_seconds") is not None]

    best = res.get("best_lap_seconds")
    if best is None and lap_times:
        best = min(lap_times)
    avg = res.get("average_lap_seconds")
    if avg is None and lap_times:
        avg = sum(lap_times) / len(lap_times)

    stype = (sess.get("type") or "").lower()
    ranking = "average" if "race" in stype else "best"

    driver_name = drv.get("name") if isinstance(drv, dict) else None
    proskill = drv.get("proskill") if isinstance(drv, dict) else None

    return {
        "source_json": src_name,
        "schema": "nested",
        "session_key": _session_key(date, time24),
        "datetime_local": dt.isoformat(),
        "date": date,
        "time": time24,
        "time_raw": time_,
        "venue": sess.get("track"),
        "configuration": sess.get("configuration"),
        "session_type": sess.get("type"),
        "event": sess.get("format") or sess.get("type"),
        "driver": driver_name or sess.get("driver"),
        "kart_number": _driver_kart(raw, driver_name),
        "position": sess.get("position") or res.get("position"),
        "field_size": res.get("field_size"),
        "lap_times": lap_times,
        "best_lap": float(best) if best is not None else None,
        "avg_lap": round(float(avg), 3) if avg is not None else None,
        "avg_lap_basis": "mean of all laps",
        "ranking_metric": ranking,
        "total_laps": res.get("laps_completed", len(lap_times)),
        "scheduled_laps": res.get("scheduled_laps"),
        "consistency": _consistency(lap_times),
        "proSkill": (proskill or {}).get("score") if isinstance(proskill, dict) else None,
        "proSkillRank": (proskill or {}).get("global_rank") if isinstance(proskill, dict) else None,
        "field_results": raw.get("field_results"),
        "leaderboards": raw.get("leaderboards"),
        "charts": raw.get("charts"),
        "_raw": raw,
    }


def _driver_kart(raw: dict, driver_name: str | None):
    """Find the driver's kart number from field_results if present."""
    for fr in raw.get("field_results", []) or []:
        if driver_name and fr.get("driver") == driver_name:
            return fr.get("kart")
    return None


def _normalize_flat(raw: dict, src_name: str) -> dict:
    date = raw.get("date")
    time_ = raw.get("time")
    if not date or not time_:
        raise ValueError(f"{src_name}: missing authoritative date/time")
    time24 = _parse_time(time_)
    dt = datetime.strptime(f"{date} {time24}", "%Y-%m-%d %H:%M")
    laps = raw.get("lapTimes", [])
    lap_times = [float(l["time"]) for l in laps]
    best = raw.get("bestLap")
    if best is None and lap_times:
        best = min(lap_times)
    avg = (sum(lap_times) / len(lap_times)) if lap_times else None
    return {
        "source_json": src_name,
        "schema": "flat",
        "session_key": _session_key(date, time24),
        "datetime_local": dt.isoformat(),
        "date": date,
        "time": time24,
        "time_raw": time_,
        "venue": raw.get("track"),
        "configuration": raw.get("configuration"),
        "session_type": raw.get("event"),
        "event": raw.get("event"),
        "driver": raw.get("driver"),
        "kart_number": raw.get("kartNumber") or raw.get("kart"),
        "position": raw.get("position"),
        "field_size": raw.get("totalRacers"),
        "lap_times": lap_times,
        "best_lap": float(best) if best is not None else None,
        "avg_lap": round(float(avg), 3) if avg is not None else None,
        "avg_lap_basis": "mean of all laps",
        "ranking_metric": "best",
        "total_laps": raw.get("totalLaps", len(lap_times)),
        "scheduled_laps": None,
        "consistency": _consistency(lap_times),
        "proSkill": raw.get("proSkill"),
        "proSkillRank": raw.get("proSkillRank"),
        "proSkillPercentage": raw.get("proSkillPercentage"),
        "totalRacers": raw.get("totalRacers"),
        "racerSince": raw.get("racerSince"),
        "visitNumber_UNRELIABLE": raw.get("visitNumber"),
        "raceNumber_UNRELIABLE": raw.get("raceNumber"),
        "leaderboards": raw.get("leaderboards"),
        "_raw": raw,
    }


def normalize(raw: dict, src_name: str) -> dict:
    return (_normalize_nested if _is_nested(raw) else _normalize_flat)(raw, src_name)


def run(venue: str = "gateway-kartplex") -> list[dict]:
    print("=" * 64)
    print(f"[timesheet] STEP 2  venue={venue}")
    print("=" * 64)
    venue_inbox = INBOX / venue
    sheets_files = sorted(venue_inbox.glob("*.json"))
    if not sheets_files:
        raise FileNotFoundError(f"no timing-sheet *.json in {venue_inbox}")

    sheets = [normalize(load_json(f), f.name) for f in sheets_files]
    sheets.sort(key=lambda s: s["datetime_local"])  # chronological

    for s in sheets:
        n = len(s["lap_times"])
        head = (f"best={s['best_lap']:.3f}s" if s["ranking_metric"] == "best"
                else f"avg={s['avg_lap']:.3f}s (best {s['best_lap']:.3f}s)")
        cv = s["consistency"].get("cv", 0.0) * 100
        print(f"[timesheet] {s['source_json']}: {s['datetime_local']} "
              f"'{s['event']}' cfg={s['configuration']} driver={s['driver']} "
              f"laps={n} {head} pos={s['position']} CV={cv:.1f}% -> key {s['session_key']}")
        print(f"            lap_times={['%.3f' % t for t in s['lap_times']]}")

    write_json(OUTPUT / venue / "raw" / "timesheets.json", {"sheets": sheets})

    # ---- VALIDATION GATE (data-driven) ----
    problems = []
    if len(sheets) < 1:
        problems.append("no sheets")
    for s in sheets:
        if len(s["lap_times"]) < 1:
            problems.append(f"{s['source_json']}: 0 laps")
        b = s["best_lap"]
        if b is None or not (SANE_LAP_MIN <= b <= SANE_LAP_MAX):
            problems.append(f"{s['source_json']}: best_lap {b} out of "
                            f"[{SANE_LAP_MIN},{SANE_LAP_MAX}]s")
    ok = not problems
    print("-" * 64)
    print(f"[timesheet] VALIDATE: n_sheets={len(sheets)} "
          f"bests={['%.3f' % s['best_lap'] for s in sheets if s['best_lap']]}")
    if problems:
        print(f"[timesheet] problems: {problems}")
    print(f"[timesheet] STATUS: {'PASS' if ok else 'CHECK'}")
    print("-" * 64)
    return sheets


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "gateway-kartplex")
