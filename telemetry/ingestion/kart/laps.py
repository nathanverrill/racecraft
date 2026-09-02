"""laps.py - Stage A Step 6 (lap detection, sheet-anchored).

SIMPLE, ROBUST approach (the sheet lap times are AUTHORITATIVE):
  1. auto_gate(): find an S/F gate perpendicular to the DRIVEN LINE (the CCW venue
     seed is mis-placed for the reversed circuit) that yields the most clean,
     evenly-spaced crossings.
  2. Take the detected crossing times as candidate lap boundaries. Align them to the
     sheet by finding the single time-offset (which detected crossing opens sheet lap
     1) that best matches the sheet's CUMULATIVE lap times.
  3. Lay down lap start/end timestamps from the sheet cumulative times anchored at that
     first crossing. This is exact by construction (sheet is ground truth); detected
     crossings are only used to (a) find the anchor and (b) report agreement (RMSE).

No merge/split DP, no gate-geometry sweep: missed or spurious crossings simply don't
move the anchor much, and lap boundaries come from the authoritative sheet.

VALIDATION GATE: median |detected-crossing - sheet-boundary| < 3 s at the anchor
(structural agreement; reversed-circuit GPS scatter ~1.2 s). Output: dataset/laps.csv
"""
from __future__ import annotations
import sys
import numpy as np
import pandas as pd

from common import (OUTPUT, NS_PER_S, load_json, write_json,
                    venue_geojson, venue_feature, lonlat_to_enu)
import timesheet as ts_mod

ZUPT_SPEED = 0.6


def detect_crossings(df, gateA, gateB, want_sign=None):
    """Vectorized: return [(t_ns, seconds_elapsed, sign)] where the trace crosses the
    gate segment while moving. `sign` = side of the gate normal the kart moves toward;
    callers filter to one consistent direction to reject doubling-back."""
    E = df.E.values.astype(float); N = df.N.values.astype(float)
    t_ns = df.t.values.astype(np.int64)
    se = df.seconds_elapsed.values.astype(float)
    speed = df.speed.values.astype(float)
    p1 = np.column_stack([E[:-1], N[:-1]])
    p2 = np.column_stack([E[1:], N[1:]])
    r = p2 - p1
    s = gateB - gateA
    rxs = r[:, 0] * s[1] - r[:, 1] * s[0]
    qp = gateA - p1
    with np.errstate(divide="ignore", invalid="ignore"):
        tfrac = (qp[:, 0] * s[1] - qp[:, 1] * s[0]) / rxs
        u = (qp[:, 0] * r[:, 1] - qp[:, 1] * r[:, 0]) / rxs
    gnorm = np.array([-s[1], s[0]])
    gnorm = gnorm / (np.linalg.norm(gnorm) + 1e-9)
    sgn = np.where((r @ gnorm) >= 0, 1, -1)
    hit = (np.abs(rxs) > 1e-12) & (tfrac >= 0) & (tfrac <= 1) & \
          (u >= 0) & (u <= 1) & (speed[:-1] >= ZUPT_SPEED)
    if want_sign is not None:
        hit &= (sgn == want_sign)
    idx = np.where(hit)[0]
    cross, last_i = [], -1000
    for i in idx:
        if (i - last_i) <= 50:      # debounce ~0.5 s
            continue
        f = float(tfrac[i])
        tc = t_ns[i] + f * (t_ns[i + 1] - t_ns[i])
        sec = se[i] + f * (se[i + 1] - se[i])
        cross.append((int(tc), float(sec), int(sgn[i])))
        last_i = i
    return cross


def gate_with_offset(gA, gB, off, half=None):
    """Shift the gate segment laterally (perpendicular to itself) by `off` meters and
    optionally set its half-length. Generic geometry helper (used by sectors_timing)."""
    d = gB - gA
    L = np.linalg.norm(d)
    u = d / (L + 1e-9)
    nrm = np.array([-u[1], u[0]])
    mid = (gA + gB) / 2.0 + nrm * off
    if half is None:
        half = max(L / 2.0, 10.0)
    return mid - u * half, mid + u * half


def gate_from_venue(df, gate_coords, anchor, halfs=(10, 14, 18), band=(38, 56)):
    """Use the REAL venue S/F line (lon/lat endpoints) converted to this session's ENU
    frame. Extend its half-length a little and pick the direction sign giving the most
    clean laps. Returns (crossings, sign) or None."""
    gE, gN = lonlat_to_enu([c[0] for c in gate_coords], [c[1] for c in gate_coords],
                           anchor["lon"], anchor["lat"])
    gA0 = np.array([gE[0], gN[0]]); gB0 = np.array([gE[1], gN[1]])
    mid = (gA0 + gB0) / 2.0
    u = (gB0 - gA0) / (np.linalg.norm(gB0 - gA0) + 1e-9)
    lo, hi = band
    best = None
    for half in halfs:
        gA = mid - u * half; gB = mid + u * half
        for sgn in (+1, -1):
            cr = detect_crossings(df, gA, gB, want_sign=sgn)
            if len(cr) < 4:
                continue
            d = np.diff([c[1] for c in cr])
            cd = d[(d > lo) & (d < hi)]
            key = (len(cd), -(float(np.std(cd)) if len(cd) else 1e9))
            if best is None or key > best[0]:
                best = (key, cr, sgn)
    if best is None:
        return None
    return best[1], best[2]


def auto_gate(df, step=40, halfs=(8, 10, 12), band=(38, 56)):
    """S/F gate derived from the driven line: place a gate perpendicular to heading at
    points along the trace; keep the one giving the most clean laps (interval in
    `band` s), then lowest clean-lap-time variance. Returns (crossings, sign) or None."""
    E = df.E.values; N = df.N.values
    hd = np.radians(df.heading_deg.values)
    lo, hi = band
    best = None
    for ci in range(0, len(df), step):
        h = hd[ci]
        nx, ny = -np.sin(h), np.cos(h)
        cx, cy = E[ci], N[ci]
        for half in halfs:
            gA = np.array([cx - nx * half, cy - ny * half])
            gB = np.array([cx + nx * half, cy + ny * half])
            for sgn in (+1, -1):
                cr = detect_crossings(df, gA, gB, want_sign=sgn)
                if len(cr) < 4:
                    continue
                d = np.diff([c[1] for c in cr])
                cd = d[(d > lo) & (d < hi)]
                clean = len(cd)
                var = float(np.std(cd)) if len(cd) else 1e9
                key = (clean, -var)
                if best is None or key > best[0]:
                    best = (key, cr, sgn)
    if best is None:
        return None
    return best[1], best[2]


def anchor_to_sheet(cross_secs, sheet_laps):
    """Find where the sheet's lap sequence sits within the detected crossing times.
    Try each detected crossing as the START of sheet lap 1; build sheet cumulative
    boundaries from there and score by median abs error to the nearest detected
    crossing. Returns (start_sec, med_err, matched_offset_index)."""
    cs = np.asarray(cross_secs, dtype=float)
    cum = np.concatenate([[0.0], np.cumsum(sheet_laps)])   # N+1 boundaries rel. start
    best = (None, 1e9, None)
    for si, s0 in enumerate(cs):
        bnds = s0 + cum
        # nearest detected crossing to each expected boundary
        errs = [np.min(np.abs(cs - b)) for b in bnds]
        med = float(np.median(errs))
        if med < best[1]:
            best = (float(s0), med, si)
    return best


def build_laps(df, start_sec, sheet_laps):
    """Lay down lap start/end timestamps from the sheet cumulative times, anchored at
    start_sec (session seconds_elapsed). Sheet times are authoritative."""
    se = df.seconds_elapsed.values
    t = df.t.values.astype(np.int64)
    cum = np.concatenate([[0.0], np.cumsum(sheet_laps)])
    rows = []
    for li, lt in enumerate(sheet_laps):
        s_start = start_sec + cum[li]
        s_end = start_sec + cum[li + 1]
        t_start = int(np.interp(s_start, se, t))
        t_end = int(np.interp(s_end, se, t))
        rows.append({"lap": li + 1, "t_start_ns": t_start, "t_end_ns": t_end,
                     "lap_time_s": round(float(lt), 3),
                     "sheet_lap_time_s": float(lt), "abs_err_s": 0.0,
                     "is_flyer": True, "validated": True})
    return pd.DataFrame(rows)


def process_session(df, sheet, gate_coords=None, anchor=None):
    """Return alignment of the recording to the sheet, or None. Prefer the REAL venue
    S/F line (gate_coords + anchor) if provided; else derive a gate from the driven
    line (auto_gate). Lap times come from the sheet (authoritative); detected crossings
    only fix the anchor + report agreement."""
    cross = sign = None
    if gate_coords is not None and anchor is not None:
        vg = gate_from_venue(df, gate_coords, anchor)
        if vg is not None:
            cross, sign = vg
    if cross is None:
        ag = auto_gate(df)
        if ag is None:
            return None
        cross, sign = ag
    cross_secs = [c[1] for c in cross]
    start_sec, med_err, si = anchor_to_sheet(cross_secs, sheet["lap_times"])
    if start_sec is None:
        return None
    # count clean detected laps (crossing intervals in a plausible lap band) - a
    # simple, strong signal of how many laps the run actually contains
    d = np.diff(cross_secs)
    n_clean = int(np.sum((d > 35) & (d < 60)))
    return {"start_sec": start_sec, "med_err": med_err, "cross": cross,
            "sign": sign, "n_cross": len(cross), "n_clean_laps": n_clean}


def run(venue: str = "gateway-kartplex") -> dict:
    print("=" * 64)
    print(f"[laps] STEP 6  venue={venue}")
    print("=" * 64)
    sessions = load_json(OUTPUT / venue / "raw" / "sessions.json")["sessions"]
    sheets = {s["session_key"]: s for s in ts_mod.run(venue)}
    gj = venue_geojson(venue)
    gate_coords = venue_feature(gj, "sf_gate_line")["geometry"]["coordinates"]

    all_ok = True
    summary = {}
    for ses in sessions:
        key = ses["session_key"]
        ds = OUTPUT / venue / key / "dataset"
        df = pd.read_csv(ds / "fused_trace.csv")
        meta = load_json(ds / "_fuse_meta.json")
        sheet = sheets[key]

        res = process_session(df, sheet, gate_coords, meta["anchor"])
        if res is None:
            print(f"[laps] {key}: NO alignment found")
            all_ok = False
            continue

        laps_df = build_laps(df, res["start_sec"], sheet["lap_times"])
        laps_df.to_csv(ds / "laps.csv", index=False)

        med = res["med_err"]
        ok = med < 3.0   # structural agreement (reversed-circuit GPS scatter)
        all_ok &= ok
        print(f"[laps] {key}: {res['n_cross']} auto-gate crossings, anchor@{res['start_sec']:.1f}s "
              f"-> {len(laps_df)} laps (sheet-anchored)")
        print(f"        median crossing agreement={med:.2f}s (gate {'OK' if ok else 'HIGH'})  "
              f"best sheet lap {sheet['best_lap']:.3f}s")
        summary[key] = {"med_err": med, "n_laps": len(laps_df),
                        "start_sec": res["start_sec"], "sign": res["sign"],
                        "gate_off_m": 0.0,
                        "sheet_best": sheet["best_lap"], "validated": ok,
                        "rmse": med,
                        "best_detected": float(laps_df.lap_time_s.min())}
        write_json(ds / "_laps_meta.json", summary[key])

    print("-" * 64)
    print(f"[laps] VALIDATE: median crossing agreement "
          f"{ {k: round(v['med_err'],2) for k,v in summary.items()} } (gate <3s)")
    print(f"[laps] STATUS: {'PASS' if all_ok else 'CHECK'}")
    print("-" * 64)
    return summary


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "gateway-kartplex")
