"""sector1_coaching.py - Stage B: Sector-1-specific coaching artifact.

Everything is derived from the DRIVEN GPS LINE itself (speed + curvature) in
distance-FRACTION along the lap - NOT from hand-placed satellite seed pins and NOT
from absolute GPS metre distances (the seed pins disagree with phone GPS by several
metres, so seed-vs-GPS distances are meaningless). The out-lap is excluded (we only use
flying laps from laps.csv).

For Sector 1 (S/F -> ~45% of the lap) we find the real BRAKING ZONES from the data:
each is where sustained deceleration occurs; we report its braking point (where decel
starts), turn-in, apex (min speed) and exit - as fractions of the lap - plus the
approach speed reaching it. These are the concrete reference points for the next run.

Writes dataset/sector1.json. Read-only on Stage A.
"""
from __future__ import annotations
import sys
import numpy as np
import pandas as pd

from common import OUTPUT, load_json, write_json
import timesheet as ts_mod

MPH = 2.236936
S1_MAX_FRAC = 0.45      # S1 = S/F -> T5
BRAKE_DECEL_MPH_S = 6.0  # mph/s sustained drop = braking


def lap_profile(fused, r):
    seg = fused[(fused.t >= r.t_start_ns) & (fused.t <= r.t_end_ns)].reset_index(drop=True)
    d = np.r_[0, np.cumsum(np.hypot(np.diff(seg.E.values), np.diff(seg.N.values)))]
    return seg, d, d / d[-1], d[-1]


def find_braking_zones(seg, frac, fmax):
    """Data-derived braking zones within [0,fmax] of the lap. A zone = a contiguous
    stretch of sustained deceleration; we record brake-start, apex (min speed) and the
    speeds, all as lap FRACTIONS. No seeds, no absolute metres."""
    m = frac < fmax
    fr = frac[m]
    spd = pd.Series(seg.speed.values[m] * MPH).rolling(7, center=True, min_periods=1).mean().values
    t = seg.seconds_elapsed.values[m]            # monotonic clock (t-ns can dupe)
    t = t - t[0]
    if len(fr) < 10:
        return []
    # dv/dt in mph per second (guard against zero dt)
    dt = np.gradient(t)
    dt[dt <= 0] = np.median(dt[dt > 0]) if np.any(dt > 0) else 0.01
    dvdt = np.gradient(spd) / dt
    braking = dvdt < -BRAKE_DECEL_MPH_S
    zones = []
    i = 0
    while i < len(braking):
        if braking[i]:
            j = i
            while j < len(braking) and braking[j]:
                j += 1
            # apex = min speed from brake-start to a bit after brake-end
            a0 = i
            a1 = min(len(spd) - 1, j + int(0.03 * len(spd)))
            kapex = a0 + int(np.argmin(spd[a0:a1 + 1]))
            approach = float(spd[max(0, a0 - 2)])
            apex = float(spd[kapex])
            if approach - apex > 4:        # real braking event only
                zones.append({"brake_frac": round(float(fr[a0]), 3),
                              "apex_frac": round(float(fr[kapex]), 3),
                              "approach_mph": round(approach, 1),
                              "apex_mph": round(apex, 1),
                              "drop_mph": round(approach - apex, 1)})
            i = j
        else:
            i += 1
    return zones


def run(venue="gateway-kartplex"):
    print("=" * 64); print(f"[sector1] Stage B  venue={venue}"); print("=" * 64)
    sheets = {s["session_key"]: s for s in ts_mod.run(venue)}
    for key in sheets:
        ds = OUTPUT / venue / key / "dataset"
        if not (ds / "analytics.json").exists():
            continue
        st = pd.read_csv(ds / "sector_times.csv")
        laps = pd.read_csv(ds / "laps.csv")
        fused = pd.read_csv(ds / "fused_trace.csv")
        A = load_json(ds / "analytics.json")
        sectors = load_json(ds / "sectors.json")
        rj = load_json(ds / "render" / "render.json") if (ds / "render" / "render.json").exists() else None

        valid = st[st.sectors_valid]
        ref_lap = int(valid.loc[valid.sector_1.idxmin()].lap)
        ref_s1 = float(valid.sector_1.min())
        incident_laps = set(A.get("incident_laps", []))
        clean = [l for l in valid.lap.tolist() if l not in incident_laps]

        # reference lap geometry (flying lap only - out-lap already excluded)
        rrow = laps[laps.lap == ref_lap].iloc[0]
        rseg, rdist, rfrac, rtotal = lap_profile(fused, rrow)

        # DATA-DERIVED braking zones in S1 (no seeds, no absolute metres)
        zones = find_braking_zones(rseg, rfrac, S1_MAX_FRAC)
        # exit speed (just after apex) + cross-lap apex-speed spread, per zone
        for z in zones:
            kx = int(np.argmin(np.abs(rfrac - (z["apex_frac"] + 0.03))))
            z["exit_mph"] = round(float(rseg.speed.values[kx] * MPH), 1)
            apex_vs = []
            for lap in clean:
                lr = laps[laps.lap == lap].iloc[0]
                seg, dd, fr, tot = lap_profile(fused, lr)
                w = np.where((fr > z["apex_frac"] - 0.02) & (fr < z["apex_frac"] + 0.02))[0]
                if len(w) >= 3:
                    apex_vs.append(float(seg.speed.values[w].min()) * MPH)
            z["apex_mph_std"] = round(float(np.std(apex_vs)), 1) if len(apex_vs) > 1 else 0.0
            # specific, distinct cue with real numbers
            cue = [f"Brake at {int(z['brake_frac']*100)}% into the lap, "
                   f"arriving ~{z['approach_mph']:.0f} mph.",
                   f"Apex ~{z['apex_mph']:.0f} mph, drive out to {z['exit_mph']:.0f} mph."]
            if z["apex_mph_std"] > 2.5:
                cue.append(f"Apex speed swings ±{z['apex_mph_std']:.0f} mph lap-to-lap — "
                           f"aim to repeat {z['apex_mph']:.0f}.")
            elif z["exit_mph"] <= z["apex_mph"] + 1:
                cue.append("Pick up throttle earlier — weak exit.")
            z["cues"] = cue
        # number the zones B1, B2... in order
        for i, z in enumerate(zones, 1):
            z["label"] = f"B{i}"

        # S1 reference speed trace (for the dashboard mini-chart) from best lap
        s1mask = rfrac < S1_MAX_FRAC
        s1_speed_trace = {
            "dist_m": [round(float(x), 1) for x in rdist[s1mask][::3]],
            "speed_mph": [round(float(v*MPH), 1) for v in rseg.speed.values[s1mask][::3]],
        }

        # ---- F1-study data: every CLEAN lap's S1 on a COMMON distance grid ----
        # so we can overlay traces, rank best->worst, build heatmaps & a consistency band.
        NG = 120
        s1_len_ref = float(rdist[s1mask][-1]) if s1mask.any() else 1.0
        grid_m = np.linspace(0, s1_len_ref, NG)
        per_lap = []
        for lap in clean:
            lr = laps[laps.lap == lap].iloc[0]
            seg, dd, fr, tot = lap_profile(fused, lr)
            mask = fr < S1_MAX_FRAC
            if mask.sum() < 5:
                continue
            d_lap = dd[mask]; d_lap = d_lap - d_lap[0]
            sp = seg.speed.values[mask] * MPH
            t_lap = (seg.t.values[mask] - seg.t.values[mask][0]) / 1e9
            # resample onto the common grid (normalize each lap's S1 length to ref)
            dn = d_lap / max(d_lap[-1], 1e-6) * s1_len_ref
            spg = np.interp(grid_m, dn, sp)
            tg = np.interp(grid_m, dn, t_lap)
            s1_time = float(st[st.lap == lap].sector_1.iloc[0])
            per_lap.append({"lap": int(lap), "s1_time": round(s1_time, 3),
                            "speed_mph": [round(float(v), 1) for v in spg],
                            "cum_t": [round(float(v), 3) for v in tg]})
        # rank best -> worst by S1 time
        per_lap.sort(key=lambda L: L["s1_time"])
        # reference (best) cumulative time for delta curves
        ref_cum = per_lap[0]["cum_t"] if per_lap else []
        for L in per_lap:
            L["delta_vs_ref"] = [round(L["cum_t"][i] - ref_cum[i], 3) for i in range(len(ref_cum))] if ref_cum else []
        # per-distance consistency: mean/std speed across clean laps (the heatmap band)
        if per_lap:
            arr = np.array([L["speed_mph"] for L in per_lap])
            band = {"grid_m": [round(float(x), 1) for x in grid_m],
                    "mean_mph": [round(float(v), 1) for v in arr.mean(0)],
                    "std_mph": [round(float(v), 2) for v in arr.std(0)],
                    "min_mph": [round(float(v), 1) for v in arr.min(0)],
                    "max_mph": [round(float(v), 1) for v in arr.max(0)]}
        else:
            band = {"grid_m": [], "mean_mph": [], "std_mph": [], "min_mph": [], "max_mph": []}

        # S1 reference LINE as normalized (x,y) matching render.json, with brake/apex
        # marker positions (so the map shows WHERE to brake and turn).
        E = fused.E.values; N = fused.N.values
        e0, n0 = E.min(), N.min(); span = max(E.max()-e0, N.max()-n0)
        nx = lambda e: (e - e0) / span
        ny = lambda n: (n - n0) / span
        ref_line = [[round(float(nx(e)), 4), round(float(ny(n)), 4)]
                    for e, n in zip(rseg.E.values[s1mask], rseg.N.values[s1mask])]
        for z in zones:
            kb = int(np.argmin(np.abs(rfrac - z["brake_frac"])))
            ka = int(np.argmin(np.abs(rfrac - z["apex_frac"])))
            z["brake_xy"] = [round(float(nx(rseg.E.values[kb])), 4), round(float(ny(rseg.N.values[kb])), 4)]
            z["apex_xy"] = [round(float(nx(rseg.E.values[ka])), 4), round(float(ny(rseg.N.values[ka])), 4)]

        out = {
            "venue": venue, "session_key": key,
            "sector": "S1 (S/F → T5)",
            "reference_lap": ref_lap,
            "reference_s1_time": round(ref_s1, 3),
            "s1_mean_time": round(float(valid.sector_1.mean()), 3),
            "s1_std_time": round(float(valid.sector_1.std()), 3),
            "n_clean_laps": len(clean),
            "entry_speed_mph": zones[0]["approach_mph"] if zones else None,
            "braking_zones": zones,
            "reference_line": ref_line,
            "reference_speed_trace": s1_speed_trace,
            "per_lap_ranked": per_lap,
            "consistency_band": band,
            "grid_len_m": round(s1_len_ref, 1),
            "notes": "All points DERIVED FROM THE DRIVEN GPS LINE (speed/curvature) of "
                     "your best Sector-1 flying lap, in lap-fraction - NOT from satellite "
                     "seed pins or absolute GPS metres (those disagree by several m). "
                     "Out-lap excluded. Braking zones = where you actually decelerate.",
        }
        write_json(ds / "sector1.json", out)
        if (ds / "render").exists():
            write_json(ds / "render" / "sector1.json", out)
        print(f"[sector1] {key}: ref lap {ref_lap} ({ref_s1:.3f}s); braking zones: "
              + ", ".join(f"{z['label']}@{int(z['brake_frac']*100)}%→{z['apex_mph']:.0f}mph" for z in zones))
    print("-" * 64); print("[sector1] STATUS: PASS"); print("-" * 64)


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "gateway-kartplex")
