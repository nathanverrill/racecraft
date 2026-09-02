"""Define 3 mini-sectors and build the best-lap distance model.

Reference lap = lap 11 (best). We resample it by cumulative distance to
build s(t) and position(s), used for distance-aligned delta and sector
splits. Sectors (user): 1=lead-in+long straight, 2=hairpin, 3=bottom esses.
"""
import numpy as np, pandas as pd
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLIPPED = HERE.parent / "clipped"
BEST_LAP = 11   # 1-indexed


def best_lap_frame():
    df = pd.read_csv(CLIPPED / "fused_trace.csv")
    b = np.load(CLIPPED / "lap_bounds_race.npy")
    lo, hi = b[BEST_LAP - 1]
    t = df.seconds_elapsed_race.values
    m = (t >= lo) & (t <= hi)
    bl = df[m].reset_index(drop=True).copy()
    bl["lap_t"] = bl.seconds_elapsed_race - lo
    # cumulative distance along best lap
    dE = np.diff(bl.E.values, prepend=bl.E.values[0])
    dN = np.diff(bl.N.values, prepend=bl.N.values[0])
    bl["dist"] = np.cumsum(np.hypot(dE, dN))
    return bl


def main():
    bl = best_lap_frame()
    total = bl.dist.iloc[-1]
    print(f"Best lap (lap {BEST_LAP}): {bl.lap_t.iloc[-1]:.3f}s, length {total:.1f} m")
    # print waypoints every ~10% of distance to identify features by E,N
    print(f"\n{'%dist':>6} {'dist_m':>7} {'lap_t':>6} {'E':>6} {'N':>6} {'mph':>5}")
    for frac in np.linspace(0, 1, 21):
        i = np.searchsorted(bl.dist.values, frac * total)
        i = min(i, len(bl) - 1)
        r = bl.iloc[i]
        print(f"{frac*100:5.0f}% {r.dist:7.1f} {r.lap_t:6.2f} {r.E:6.1f} {r.N:6.1f} {r.speed*2.237:5.1f}")


if __name__ == "__main__":
    main()