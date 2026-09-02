"""ghost.py - Stage B creative: build a "ghost battle" artifact per session.

Stitches the IDEAL lap (best S1 + best S2 + best S3, possibly from different laps) and
pairs it against the actual best lap so the dashboard can race them head-to-head with a
live gap. Writes dataset/render/ghost.json:
  - best lap: normalized (x,y), speed, cumulative-distance-vs-time
  - ideal lap: the three best sectors concatenated, re-based to a common distance axis
  - per-distance time delta (ideal vs best)
Both sampled on a common distance grid so the front end can place each "car" by the
SAME progress fraction and read the time gap.
"""
from __future__ import annotations
import sys
import numpy as np
import pandas as pd

from common import OUTPUT, load_json, write_json
import timesheet as ts_mod

SPLIT = [0.45, 0.83]
NGRID = 400


def lap_arrays(fused, r):
    seg = fused[(fused.t >= r.t_start_ns) & (fused.t <= r.t_end_ns)].reset_index(drop=True)
    d = np.r_[0, np.cumsum(np.hypot(np.diff(seg.E.values), np.diff(seg.N.values)))]
    frac = d / d[-1]
    t = (seg.t.values - seg.t.values[0]) / 1e9
    return seg, frac, t, d


def run(venue="gateway-kartplex"):
    print("=" * 64); print(f"[ghost] Stage B  venue={venue}"); print("=" * 64)
    sheets = {s["session_key"]: s for s in ts_mod.run(venue)}
    for key in sheets:
        ds = OUTPUT / venue / key / "dataset"
        if not (ds / "render" / "render.json").exists():
            continue
        fused = pd.read_csv(ds / "fused_trace.csv")
        laps = pd.read_csv(ds / "laps.csv")
        st = pd.read_csv(ds / "sector_times.csv")
        analytics = load_json(ds / "analytics.json")
        anchor = load_json(ds / "_fuse_meta.json")["anchor"]

        ref = analytics["reference_lap"]
        rrow = laps[laps.lap == ref].iloc[0]
        rseg, rfrac, rt, rd = lap_arrays(fused, rrow)

        # normalized coords (match render.json normalization)
        rj = load_json(ds / "render" / "render.json")
        # recover normalization from track bbox used in render (E0,N0,span)
        E = fused.E.values; N = fused.N.values
        e0, n0 = E.min(), N.min(); span = max(E.max()-e0, N.max()-n0)
        nx = lambda e: (e - e0) / span
        ny = lambda n: (n - n0) / span

        grid = np.linspace(0, 1, NGRID)
        best = {
            "lap": int(ref),
            "lap_time": float(analytics["actual_best_lap_s"]),
            "x": [round(float(nx(v)), 4) for v in np.interp(grid, rfrac, rseg.E.values)],
            "y": [round(float(ny(v)), 4) for v in np.interp(grid, rfrac, rseg.N.values)],
            "speed_mph": [round(float(v), 1) for v in np.interp(grid, rfrac, rseg.speed.values*2.236936)],
            "t": [round(float(v), 3) for v in np.interp(grid, rfrac, rt)],
        }

        # ideal: best sector times -> cumulative target time at split fractions
        ss = analytics["sectors"]
        bs1, bs2, bs3 = ss["sector_1"]["best"], ss["sector_2"]["best"], ss["sector_3"]["best"]
        ideal_total = bs1 + bs2 + bs3
        # build ideal time-vs-frac piecewise-linear through the split fractions, using
        # the best lap's geometry (same line) but the best-sector PACE.
        split_t = [0, bs1, bs1+bs2, ideal_total]
        split_f = [0, SPLIT[0], SPLIT[1], 1.0]
        ideal_t = np.interp(grid, split_f, split_t)
        ideal = {
            "lap_time": round(float(ideal_total), 3),
            "x": best["x"], "y": best["y"],   # same racing line, ideal pace
            "t": [round(float(v), 3) for v in ideal_t],
        }
        # delta vs best at each grid point (ideal is the target -> negative = ahead)
        delta = [round(float(ideal_t[i] - best["t"][i]), 3) for i in range(NGRID)]

        write_json(ds / "render" / "ghost.json",
                   {"session_key": key, "n": NGRID, "grid": [round(float(g), 4) for g in grid],
                    "best": best, "ideal": ideal, "delta_ideal_minus_best": delta,
                    "note": "ideal = best S1+S2+S3 pace on the best-lap line; race the "
                            "gold ideal ghost vs your real best lap."})
        print(f"[ghost] {key}: best {best['lap_time']:.3f}s vs ideal {ideal['lap_time']:.3f}s "
              f"(gain {best['lap_time']-ideal['lap_time']:.3f}s)")
    print("-" * 64); print("[ghost] STATUS: PASS"); print("-" * 64)


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "gateway-kartplex")
