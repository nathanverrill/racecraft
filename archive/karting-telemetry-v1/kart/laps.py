"""Lap detection with the REAL start/finish gate (bottom-center).

The gate is the user-identified real-life start/finish line: the break in
the pit trace at ~E12,N-12, where the kart crosses heading West at ~68 km/h.
Crossings bound the laps; we validate against the official timing sheet.

Out-lap / in-lap and pit visits don't cross this gate cleanly, so they
simply don't produce crossings. Intervals outside 30-70s are dropped.
"""
import numpy as np
import pandas as pd

from session_config import (OFFICIAL as _OFF, GATE_XY, GATE_DIR,
                            GATE_HALF_WIDTH)
OFFICIAL = np.array(_OFF)


def crossings(E, N, t, vE, vN, gate_xy=GATE_XY, gate_dir=GATE_DIR,
              half_width=GATE_HALF_WIDTH, min_speed=6.0,
              align_cos=0.85, dedup_gap=20.0):
    """Forward gate crossings. To reject spurious crossings caused by a SPIN
    (kart clipping the gate line sideways mid-spin), require travel to be
    well-aligned with the gate direction (align_cos) and de-duplicate any
    two crossings closer than dedup_gap seconds (keep the first).
    """
    nx, ny = gate_dir
    tx, ty = -ny, nx
    dx, dy = E - gate_xy[0], N - gate_xy[1]
    s = dx * nx + dy * ny
    lat = dx * tx + dy * ty
    spd = np.hypot(vE, vN)
    vmag = np.clip(spd, 1e-6, None)
    align = (vE * nx + vN * ny) / vmag      # cos angle between travel & gate dir
    out = []
    for i in range(1, len(s)):
        if s[i - 1] < 0 <= s[i]:
            frac = -s[i - 1] / (s[i] - s[i - 1])
            latc = lat[i - 1] + frac * (lat[i] - lat[i - 1])
            if (abs(latc) <= half_width and spd[i] > min_speed
                    and align[i] >= align_cos):     # going straight through, not sideways
                tc = t[i - 1] + frac * (t[i] - t[i - 1])
                if out and (tc - out[-1]) < dedup_gap:
                    continue                         # spin double-clip: drop
                out.append(tc)
    return np.array(out)


def main():
    df = pd.read_csv("kart/fused_trace.csv")
    ct = crossings(df.E.values, df.N.values, df.seconds_elapsed.values,
                   df.vE.values, df.vN.values)
    laps = np.diff(ct)
    print(f"Gate crossings: {len(ct)}  -> {len(laps)} intervals")
    print("raw interval times:", np.round(laps, 2))

    valid = (laps > 30) & (laps < 70)
    flying = laps[valid]
    keep_idx = np.where(valid)[0]
    print(f"\nFlying laps detected: {len(flying)} (official: {len(OFFICIAL)})")

    # Auto-align to official: if we detected MORE flying intervals than the
    # official count (e.g. a leading out-lap crossing or a mid-spin split),
    # slide a window to find the contiguous run that best matches official.
    no = len(OFFICIAL)
    best_off = 0
    if len(flying) > no:
        best_rmse = np.inf
        for off in range(len(flying) - no + 1):
            w = flying[off:off + no]
            r = np.sqrt(np.mean((w - OFFICIAL) ** 2))
            if r < best_rmse:
                best_rmse, best_off = r, off
        print(f"Auto-aligned: dropped {best_off} leading interval(s), "
              f"RMSE {best_rmse:.3f}s")
        flying = flying[best_off:best_off + no]
        keep_idx = keep_idx[best_off:best_off + no]

    n = min(len(flying), no)
    rmse = np.sqrt(np.mean((flying[:n] - OFFICIAL[:n]) ** 2))
    print(f"RMSE vs official (first {n}): {rmse:.3f}s\n")
    print(f"{'Lap':>3} {'Detected':>9} {'Official':>9} {'Diff':>7}")
    for i in range(n):
        print(f"{i+1:>3} {flying[i]:>9.3f} {OFFICIAL[i]:>9.3f} {flying[i]-OFFICIAL[i]:>+7.3f}")

    # robust boundary list: each kept interval contributes its start; append
    # the end of the last kept interval.
    starts = ct[keep_idx]
    ends = ct[keep_idx + 1]
    np.save("kart/lap_bounds.npy", np.column_stack([starts, ends]))
    np.save("kart/gate.npy", np.array([*GATE_XY, *GATE_DIR]))
    print("\nSaved", len(keep_idx), "flying-lap [start,end] bounds.")


if __name__ == "__main__":
    main()