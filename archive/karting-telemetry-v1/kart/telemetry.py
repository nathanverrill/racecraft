"""Telemetry engine: distance model, delta-vs-best, sectors, accel.

Reference = best lap (lap 11). All laps are aligned to the best lap by
TRACK DISTANCE (proper F1 delta): for any (E,N) on the current lap we find
the nearest point along the best-lap path -> its distance s -> the best
lap's time at s. Delta = current_time_in_lap - best_time_at_s.
"""
import numpy as np
import pandas as pd
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLIPPED = HERE.parent / "clipped"
from session_config import BEST_LAP, SECTOR_FRAC
G = 9.81


def load():
    df = pd.read_csv(CLIPPED / "fused_trace.csv")
    bounds = np.load(CLIPPED / "lap_bounds_race.npy")
    return df, bounds


def lap_slice(df, bounds, lap):
    lo, hi = bounds[lap - 1]
    t = df.seconds_elapsed_race.values
    m = (t >= lo) & (t <= hi)
    s = df[m].reset_index(drop=True).copy()
    s["lap_t"] = s.seconds_elapsed_race - lo
    return s


def add_distance(s):
    dE = np.diff(s.E.values, prepend=s.E.values[0])
    dN = np.diff(s.N.values, prepend=s.N.values[0])
    s["dist"] = np.cumsum(np.hypot(dE, dN))
    return s


def longitudinal_g(s):
    """Accel/brake from speed derivative (m/s^2 -> g). +ve accel, -ve brake."""
    v = s.speed.values
    t = s.seconds_elapsed_race.values
    a = np.gradient(v, t)
    # light smoothing
    k = 7
    a = np.convolve(a, np.ones(k)/k, mode="same")
    return a / G


class BestRef:
    """Best-lap reference for distance-aligned delta + sectors."""
    def __init__(self):
        df, bounds = load()
        bl = add_distance(lap_slice(df, bounds, BEST_LAP))
        self.E = bl.E.values
        self.N = bl.N.values
        self.dist = bl.dist.values
        self.lap_t = bl.lap_t.values
        self.total = self.dist[-1]
        self.best_time = self.lap_t[-1]
        self.long_g = longitudinal_g(bl)
        self.speed_mph = bl.speed.values * 2.237
        self.sector_dist = [f * self.total for f in SECTOR_FRAC]

    def nearest_s(self, e, n, hint=0):
        """Distance along best lap of the nearest path point to (e,n).
        `hint` is the last index, to search locally (monotonic progress)."""
        lo = max(0, hint - 50)
        hi = min(len(self.E), hint + 400)
        d2 = (self.E[lo:hi] - e) ** 2 + (self.N[lo:hi] - n) ** 2
        j = lo + int(np.argmin(d2))
        return j

    def time_at_s(self, idx):
        return self.lap_t[idx]

    def sector_of(self, dist):
        for k in range(3):
            if self.sector_dist[k] <= dist < self.sector_dist[k + 1]:
                return k + 1
        return 3


def compute_delta(lap_s, ref):
    """For a current-lap slice, return arrays: delta vs best, sector id,
    matched best-lap index, distance."""
    lap_s = add_distance(lap_s)
    E, N = lap_s.E.values, lap_s.N.values
    lap_t = lap_s.lap_t.values
    delta = np.zeros(len(E))
    sect = np.zeros(len(E), int)
    hint = 0
    for i in range(len(E)):
        j = ref.nearest_s(E[i], N[i], hint)
        hint = j
        delta[i] = lap_t[i] - ref.time_at_s(j)
        sect[i] = ref.sector_of(ref.dist[j])
    return delta, sect, lap_s.dist.values


if __name__ == "__main__":
    ref = BestRef()
    print(f"Best lap {BEST_LAP}: {ref.best_time:.3f}s, {ref.total:.1f} m")
    print("Sector boundaries (m):", np.round(ref.sector_dist, 1))
    df, bounds = load()
    # sanity: delta of best lap vs itself ~ 0
    bl = lap_slice(df, bounds, BEST_LAP)
    d, sct, dist = compute_delta(bl, ref)
    print(f"self-delta max |{np.abs(d).max():.3f}|s (should be ~0)")
    # sector times of the best lap
    for k in range(1, 4):
        m = sct == k
        if m.any():
            print(f"  S{k}: {bl.lap_t.values[m][-1]-bl.lap_t.values[m][0]:.2f}s")

# ---------- Tier 1 analysis helpers ----------

def detect_flags(df, tcol="seconds_elapsed_race"):
    """Per-sample flag state: 0 green, 1 yellow (spin), 2 red (contact).
    Yellow: |yaw_rate|>4 rad/s sustained (spin/slide).
    Red: raw jolt acc_mag>50 m/s^2 (wall contact) -> latches ~2.5s.
    """
    import numpy as np
    n = len(df)
    flag = np.zeros(n, int)
    yaw = df["yaw_rate"].abs().values
    acc = df["acc_mag"].values if "acc_mag" in df else np.zeros(n)
    t = df[tcol].values
    flag[yaw > 4.0] = 1
    red_t = t[acc > 50.0]
    for rt in red_t:
        flag[(t >= rt) & (t <= rt + 2.5)] = 2
    # extend yellow a touch so it doesn't flicker
    yfor = 1.0
    yt = t[flag == 1]
    for rt in yt:
        m = (t >= rt) & (t <= rt + yfor) & (flag == 0)
        flag[m] = 1
    return flag


def per_lap_sector_times(df, bounds, ref, tcol="seconds_elapsed_race"):
    """Return (nlaps x 3) sector times for every lap, using the best-lap
    distance model to assign sectors consistently. Also returns session
    best per sector and the theoretical-best lap (sum of fastest sectors).
    """
    import numpy as np
    nlaps = len(bounds)
    secs = np.full((nlaps, 3), np.nan)
    for li in range(nlaps):
        lo, hi = bounds[li]
        t = df[tcol].values
        m = (t >= lo) & (t <= hi)
        if not m.any():
            continue
        s = df[m].reset_index(drop=True).copy()
        s["lap_t"] = s[tcol].values - lo
        s = add_distance(s)
        # map each sample to a sector by nearest best-lap distance
        hint = 0
        sect = np.zeros(len(s), int)
        E, N = s.E.values, s.N.values
        for i in range(len(s)):
            j = ref.nearest_s(E[i], N[i], hint); hint = j
            sect[i] = ref.sector_of(ref.dist[j])
        for k in range(3):
            mm = sect == (k + 1)
            if mm.any():
                secs[li, k] = s["lap_t"].values[mm][-1] - s["lap_t"].values[mm][0]
    sess_best = np.nanmin(secs, axis=0)
    theo_best = float(np.nansum(sess_best))
    return secs, sess_best, theo_best
