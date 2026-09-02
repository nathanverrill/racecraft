"""sessions.py - Stage A Step 3 (multi-recording session mapping).

Handles ONE OR MORE recordings per venue. For each recording, detect the main driving
window(s) from GPS motion. Then MAP each timing-sheet to the window that best matches
it, using two simple, physical signals (the sheet lap times are AUTHORITATIVE):

  1. DURATION: window driving duration should ~= sum(sheet lap times) + out/in laps.
     A 7-lap sheet cannot fill a 15-lap run - this alone disambiguates most cases.
  2. STRUCTURE: laps.process_session() anchors the sheet's cumulative lap times to the
     detected S/F crossings; its median crossing-agreement (med_err) confirms the fit.

Wall-clock is authoritative in the sensor data but the sheet clock times here are
approximate, so we rank by (duration mismatch + med_err) and assign greedily 1:1.
Sheets with no acceptable window are carried as telemetry:none (home-page only).

Output: output/<venue>/raw/sessions.json  (+ a mapping REPORT for review)
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

from common import OUTPUT, write_json, load_json, venue_geojson, venue_feature
import timesheet as ts_mod
import fuse as fuse_mod
import laps as laps_mod

MOVE_SPEED = 2.0
OCC_WIN = 7
OCC_THR = 0.3
MIN_RUN_S = 120.0      # a real session is minutes of driving
PAD_S = 5.0
MED_ERR_MAX = 3.0      # s; structural agreement gate
DUR_TOL_FRAC = 0.35    # window vs sheet-sum tolerance (out/in laps + slack)


def _runs(mask):
    out, i, n = [], 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            out.append((i, j - 1)); i = j
        else:
            i += 1
    return out


def detect_windows(loc: pd.DataFrame):
    loc = loc[loc.seconds_elapsed >= 0].reset_index(drop=True)
    se = loc.seconds_elapsed.values
    t = loc.time.values.astype(np.int64)
    sp = loc.speed.values.astype(float)
    sp[sp < 0] = np.nan
    moving = (np.nan_to_num(sp, nan=0.0) > MOVE_SPEED)
    occ = pd.Series(moving.astype(float)).rolling(OCC_WIN, center=True,
                                                  min_periods=1).mean().values
    mv = occ > OCC_THR
    windows = []
    for a, b in _runs(mv):
        if se[b] - se[a] > MIN_RUN_S:
            windows.append({"se0": float(se[a]) - PAD_S, "se1": float(se[b]) + PAD_S,
                            "t0_ns": int(t[a]), "t1_ns": int(t[b]),
                            "dur_s": float(se[b] - se[a])})
    return windows


def score_window_sheet(df, window, sheet, gate_coords=None, anchor=None):
    """Score how well this window fits this sheet: lower is better. Returns
    (score, med_err, start_sec, sign, n_cross) or None if incompatible."""
    sheet_sum = float(np.sum(sheet["lap_times"]))
    dur = window["dur_s"]
    if dur < sheet_sum * (1 - DUR_TOL_FRAC):
        return None
    res = laps_mod.process_session(df, sheet, gate_coords, anchor)
    if res is None:
        return None
    med = res["med_err"]
    # med_err (structural agreement anchoring the sheet's cumulative lap times to the
    # detected S/F crossings) is the honest signal. Add only a light duration prior:
    # the window driving time should be >= the sheet total (a short sheet can't fill a
    # long run); penalize windows much longer than the sheet + out/in allowance.
    dur_pen = max(0.0, dur - (sheet_sum + 120.0)) / 90.0
    score = med + dur_pen
    return score, med, res["start_sec"], res["sign"], res["n_cross"]


def run(venue: str = "gateway-kartplex") -> dict:
    print("=" * 64)
    print(f"[sessions] STEP 3  venue={venue}  (recording -> sheet mapping)")
    print("=" * 64)
    ingest = load_json(OUTPUT / venue / "raw" / "ingest.json")
    recordings = ingest.get("recordings") or [{
        "zip_stem": ingest["zip_stem"], "root": ingest["session_dir"],
        "zip_name": ingest.get("zip_name")}]
    sheets = ts_mod.run(venue)
    sheets.sort(key=lambda s: s["datetime_local"])
    gj = venue_geojson(venue)
    gate_coords = venue_feature(gj, "sf_gate_line")["geometry"]["coordinates"]

    # 1) build candidate windows (fused once) across all recordings
    candidates = []
    for rec in recordings:
        root = Path(rec["root"])
        loc = pd.read_csv(root / "Location.csv")
        wins = detect_windows(loc)
        wins.sort(key=lambda w: w["t0_ns"])
        print(f"[sessions] {rec['zip_name']}: {len(wins)} driving window(s)")
        for wi, w in enumerate(wins):
            try:
                df, meta = fuse_mod.fuse_session(root, w)
            except Exception as e:
                print(f"   window {wi} dur {w['dur_s']:.0f}s -> fuse failed: {e}")
                continue
            scored = {}
            for sh in sheets:
                r = score_window_sheet(df, w, sh, gate_coords, meta["anchor"])
                if r is not None:
                    scored[sh["session_key"]] = r
            candidates.append({"rec": rec["zip_name"], "root": str(root),
                               "win_idx": wi, "window": w, "scored": scored})
            if scored:
                bk = min(scored, key=lambda k: scored[k][0])
                print(f"   window {wi} dur {w['dur_s']:.0f}s -> best {bk} "
                      f"score={scored[bk][0]:.2f} med_err={scored[bk][1]:.2f}s")
            else:
                print(f"   window {wi} dur {w['dur_s']:.0f}s -> no compatible sheet")

    # 2) greedy 1:1 assignment by best score
    pairs = []
    for c in candidates:
        for key, (score, med, start, sign, ncross) in c["scored"].items():
            pairs.append((score, med, start, sign, ncross, c, key))
    pairs.sort(key=lambda p: p[0])
    used_w, used_s, matched = set(), set(), []
    for score, med, start, sign, ncross, c, key in pairs:
        wid = (c["rec"], c["win_idx"])
        if wid in used_w or key in used_s or med > MED_ERR_MAX:
            continue
        used_w.add(wid); used_s.add(key)
        sh = next(s for s in sheets if s["session_key"] == key)
        matched.append({
            "session_key": key, "datetime_local": sh["datetime_local"],
            "event": sh["event"], "recording": c["rec"], "session_dir": c["root"],
            "window": c["window"], "sheet_laps": len(sh["lap_times"]),
            "sheet_best": sh["best_lap"], "match_med_err_s": round(med, 3),
            "match_start_sec": round(start, 2), "match_sign": sign, "telemetry": True})
    matched.sort(key=lambda m: m["datetime_local"])
    unmatched = [s["session_key"] for s in sheets if s["session_key"] not in used_s]

    write_json(OUTPUT / venue / "raw" / "sessions.json",
               {"sessions": matched, "unmatched_sheets": unmatched,
                "med_err_max_s": MED_ERR_MAX})

    print("-" * 64)
    print("[sessions] MAPPING REPORT:")
    for m in matched:
        print(f"   {m['session_key']:>18}  <- {m['recording']}  "
              f"win[{m['window']['dur_s']:.0f}s]  med_err={m['match_med_err_s']}s  "
              f"({m['sheet_laps']} laps, '{m['event']}')")
    if unmatched:
        print(f"   TIMING-ONLY (no telemetry): {unmatched}")
    print("-" * 64)
    ok = len(matched) >= 1
    print(f"[sessions] VALIDATE: matched={len(matched)}/{len(sheets)} sheets "
          f"(med_err gate <{MED_ERR_MAX}s)  STATUS: {'PASS' if ok else 'FAIL'}")
    print("-" * 64)
    if not ok:
        raise SystemExit("[sessions] no sheet matched any recording - STOP.")
    return {"sessions": matched, "unmatched_sheets": unmatched}


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "gateway-kartplex")
