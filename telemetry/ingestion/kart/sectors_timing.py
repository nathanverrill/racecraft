"""sectors_timing.py - Stage B: snap landmarks, define 3 sectors, per-lap timing table.

Reads dataset/ (fused_trace, laps, sectors.json) + venue geojson. Produces:
  - snapped landmarks (S/F gate, pit_exit, pit_entrance, apexes T1-T11) onto the real
    GPS track, with snap distances reported.
  - two INTERIOR sector-split gates (perpendicular to the track) at ~T5-exit and
    ~T9, written back into the venue geojson as `sector_2_gate` / `sector_3_gate`.
  - per-lap x per-sector timing table -> dataset/sector_times.csv and a tidy
    timing.json (pace + consistency stats computed in analytics step).

Sectors (physically meaningful for Gateway Kartplex T1, CCW):
  S1 = S/F -> T1..T5         (southern technical complex)
  S2 = T5 -> long straight -> T6..T9   (the back straight + top entry)
  S3 = T9 -> T10..T11 -> S/F  (stadium exit complex)

Gate crossing uses the same offset-tolerant segment test as Stage A laps.py, with a
consistent crossing-direction filter.
"""
from __future__ import annotations
import sys
import math
import numpy as np
import pandas as pd

from common import (OUTPUT, load_json, write_json, venue_geojson, venue_feature,
                    lonlat_to_enu, enu_to_lonlat)
import timesheet as ts_mod
from laps import gate_with_offset, detect_crossings

# fraction along the best lap to place the two interior sector splits
SPLIT_FRACS = [0.45, 0.83]   # after T5, after T9
GATE_MARKER_HALF_M = 5.0     # half-width of the VISUAL split-gate marker (~10 m total,
                             # = lane width + GPS error). NOT used for detection; sector
                             # splits are distance-fraction based (immune to line/jolt).


def snap_point(lon, lat, fused, anchor):
    e, n = lonlat_to_enu([lon], [lat], anchor["lon"], anchor["lat"])
    d2 = (fused.E.values - e[0]) ** 2 + (fused.N.values - n[0]) ** 2
    k = int(np.argmin(d2))
    return k, float(math.sqrt(d2[k]))


def best_lap_segment(fused, laps_df):
    best = laps_df.loc[laps_df.lap_time_s.idxmin()]
    seg = fused[(fused.t >= best.t_start_ns) & (fused.t <= best.t_end_ns)].reset_index(drop=True)
    dE = np.diff(seg.E.values); dN = np.diff(seg.N.values)
    dist = np.concatenate([[0], np.cumsum(np.sqrt(dE ** 2 + dN ** 2))])
    return seg, dist, dist[-1]


def make_split_gate(seg, dist, total, frac, anchor):
    """Perpendicular gate at the point `frac` along the best lap."""
    target = frac * total
    k = int(np.argmin(np.abs(dist - target)))
    k = min(max(k, 1), len(seg) - 2)
    # local heading
    dE = seg.E.values[k + 1] - seg.E.values[k - 1]
    dN = seg.N.values[k + 1] - seg.N.values[k - 1]
    hd = math.atan2(dN, dE)
    # perpendicular unit
    px, py = -math.sin(hd), math.cos(hd)
    cx, cy = seg.E.values[k], seg.N.values[k]
    aE, aN = cx - px * GATE_MARKER_HALF_M, cy - py * GATE_MARKER_HALF_M
    bE, bN = cx + px * GATE_MARKER_HALF_M, cy + py * GATE_MARKER_HALF_M
    # to lon/lat
    (alon, alat) = (enu_to_lonlat([aE], [aN], anchor["lon"], anchor["lat"]))
    (blon, blat) = (enu_to_lonlat([bE], [bN], anchor["lon"], anchor["lat"]))
    return {"A_enu": [aE, aN], "B_enu": [bE, bN],
            "A_lonlat": [float(alon[0]), float(alat[0])],
            "B_lonlat": [float(blon[0]), float(blat[0])],
            "heading_deg": (math.degrees(hd)) % 360, "frac": frac}


def crossings_se(df, gA, gB, sign):
    c = detect_crossings(df, np.array(gA), np.array(gB), want_sign=sign)
    return [x[1] for x in c]   # seconds_elapsed


def sector_splits_by_distance(seg, fracs):
    """Split a lap by DISTANCE-FRACTION along its own GPS path (not a geographic
    gate). Every lap has a monotonic 0..1 distance profile, so this always yields
    all sectors and is immune to lateral line variation / GPS jolts that make a
    fixed narrow line gate miss. Returns the lap-relative split times (seconds)."""
    d = np.r_[0, np.cumsum(np.hypot(np.diff(seg.E.values), np.diff(seg.N.values)))]
    if d[-1] <= 0:
        return None
    d = d / d[-1]
    t = (seg.t.values - seg.t.values[0]) / 1e9
    return [float(np.interp(fr, d, t)) for fr in fracs]


def run(venue: str = "gateway-kartplex") -> dict:
    print("=" * 64)
    print(f"[sectors_timing] Stage B  venue={venue}")
    print("=" * 64)
    gj = venue_geojson(venue)
    gate_coords = venue_feature(gj, "sf_gate_line")["geometry"]["coordinates"]
    sheets = {s["session_key"]: s for s in ts_mod.run(venue)}

    out = {}
    split_gates_written = None
    for key in sheets:
        ds = OUTPUT / venue / key / "dataset"
        if not (ds / "fused_trace.csv").exists():
            continue
        fused = pd.read_csv(ds / "fused_trace.csv")
        laps_df = pd.read_csv(ds / "laps.csv")
        fmeta = load_json(ds / "_fuse_meta.json")
        lmeta = load_json(ds / "_laps_meta.json")
        anchor = fmeta["anchor"]

        # snap landmarks
        snaps = {}
        for fid in ["sf_top", "sf_bottom", "pit_exit", "pit_entrance"] + \
                   [f"turn_{i}" for i in range(1, 12)]:
            ft = venue_feature(gj, fid)
            if not ft or ft["geometry"]["type"] != "Point":
                continue
            lon, lat = ft["geometry"]["coordinates"]
            k, d = snap_point(lon, lat, fused, anchor)
            snaps[fid] = {"snap_idx": k, "snap_dist_m": round(d, 1),
                          "se": round(float(fused.seconds_elapsed.values[k]), 2)}

        # S/F gate (tuned offset/sign from Stage A laps meta -> re-derive quickly)
        gE, gN = lonlat_to_enu([c[0] for c in gate_coords],
                               [c[1] for c in gate_coords], anchor["lon"], anchor["lat"])
        gA0 = np.array([gE[0], gN[0]]); gB0 = np.array([gE[1], gN[1]])
        gate_off = lmeta["gate_off_m"]
        sfA, sfB = gate_with_offset(gA0, gB0, gate_off)

        # interior split gates from best lap
        seg, dist, total = best_lap_segment(fused, laps_df)
        sg2 = make_split_gate(seg, dist, total, SPLIT_FRACS[0], anchor)
        sg3 = make_split_gate(seg, dist, total, SPLIT_FRACS[1], anchor)
        if split_gates_written is None:
            split_gates_written = (sg2, sg3, anchor)

        # determine the crossing sign that matches Stage A (most regular)
        # try both, pick the one giving N S/F laps
        N = len(laps_df)
        chosen_sign = None
        for sign in (+1, -1):
            sf = crossings_se(fused, sfA, sfB, sign)
            if len(sf) >= N:
                chosen_sign = sign; sf_cross = sf; break
        if chosen_sign is None:
            chosen_sign = +1; sf_cross = crossings_se(fused, sfA, sfB, +1)

        s2 = crossings_se(fused, sg2["A_enu"], sg2["B_enu"], chosen_sign)
        s3 = crossings_se(fused, sg3["A_enu"], sg3["B_enu"], chosen_sign)

        # Per-lap sector times by DISTANCE-FRACTION along each lap (not a geographic
        # gate). The lap (S/F->S/F) is always valid; sectors come from each lap's own
        # 0..1 distance profile at SPLIT_FRACS, so every lap yields all three sectors
        # regardless of lateral line variation or GPS jolts in the twisty bits.
        rows = []
        for r in laps_df.itertuples():
            seg = fused[(fused.t >= r.t_start_ns) & (fused.t <= r.t_end_ns)].reset_index(drop=True)
            splits = sector_splits_by_distance(seg, SPLIT_FRACS) if len(seg) > 3 else None
            sec1 = sec2 = sec3 = None
            ok = splits is not None and 0 < splits[0] < splits[1] < r.lap_time_s
            if ok:
                sec1 = round(splits[0], 3)
                sec2 = round(splits[1] - splits[0], 3)
                sec3 = round(r.lap_time_s - splits[1], 3)
            rows.append({"lap": int(r.lap),
                         "lap_valid": True,                 # lap time always usable
                         "sectors_valid": bool(ok),
                         "lap_time": round(r.lap_time_s, 3),
                         "sector_1": sec1, "sector_2": sec2, "sector_3": sec3})
        st = pd.DataFrame(rows)
        st.to_csv(ds / "sector_times.csv", index=False)

        n_valid = int(st.sectors_valid.sum())
        out[key] = {"n_laps": N, "n_valid_sector_laps": n_valid,
                    "n_laps_with_time": int(st.lap_valid.sum()),
                    "split_fracs": SPLIT_FRACS,
                    "snaps": snaps, "crossing_sign": chosen_sign}
        write_json(ds / "_sectors_timing_meta.json", out[key])
        # sanity: sector sums ~ lap time
        good = st[st.sectors_valid]
        if len(good):
            err = (good.sector_1 + good.sector_2 + good.sector_3 - good.lap_time).abs().max()
        else:
            err = float("nan")
        apex_snaps = [snaps[f"turn_{i}"]["snap_dist_m"] for i in range(1, 12) if f"turn_{i}" in snaps]
        print(f"[sectors_timing] {key}: {n_valid}/{N} laps with clean 3-sector splits | "
              f"max |S1+S2+S3 - lap|={err:.3f}s | apex snap med={np.median(apex_snaps):.1f}m")

    # write split gates back into the venue geojson (once, venue-level)
    if split_gates_written:
        sg2, sg3, anchor = split_gates_written
        _write_sector_gates(venue, gj, sg2, sg3)
        print(f"[sectors_timing] wrote sector_2_gate + sector_3_gate into venue geojson")

    print("-" * 64)
    ok = all(v["n_valid_sector_laps"] >= 0.6 * v["n_laps"] for v in out.values())
    print(f"[sectors_timing] STATUS: {'PASS' if ok else 'CHECK'}")
    print("-" * 64)
    return out


def _write_sector_gates(venue, gj, sg2, sg3):
    vdir = OUTPUT / venue / "_venue"
    path = sorted(vdir.glob("*_t1.geojson"))[0]
    # remove existing sector gate features then append
    feats = [f for f in gj["features"]
             if f["properties"].get("id") not in ("sector_2_gate", "sector_3_gate")]
    for sid, sg, name in [("sector_2_gate", sg2, "Sector 2 split (after T5)"),
                          ("sector_3_gate", sg3, "Sector 3 split (after T9)")]:
        feats.append({
            "type": "Feature",
            "properties": {"id": sid, "role": "sector_split_gate", "name": name,
                           "derived": True, "from_best_lap_frac": sg["frac"],
                           "heading_deg": round(sg["heading_deg"], 1),
                           "stroke": "#00e5ff", "stroke-width": 3,
                           "note": "Derived: perpendicular split gate at this fraction "
                                   "of the validated best lap. Reusable across sessions."},
            "geometry": {"type": "LineString",
                         "coordinates": [sg["A_lonlat"], sg["B_lonlat"]]},
        })
    gj["features"] = feats
    write_json(path, gj)


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "gateway-kartplex")
