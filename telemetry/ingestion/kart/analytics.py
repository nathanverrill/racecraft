"""analytics.py - Stage B: consistency & improvement analytics (the priority).

Reads dataset/ (sector_times.csv, laps.csv, fused_trace.csv, aligned_100hz.parquet,
sectors.json) and writes dataset/analytics.json (+ delta arrays). All Stage A data is
treated as read-only.

Computes, for laps and each of the 3 sectors:
  - pace: best / mean / median
  - consistency: std and CV (std/mean)  <- headline metric
  - theoretical best lap = sum of best sector times; gap vs actual best
  - opportunity ranking per sector = pace_gap (mean-best) + consistency_cost (P90-P50)
  - priority-quadrant point per sector (x=pace_gap, y=std)
  - delta-time vs reference (best valid) lap: cumulative gained/lost vs distance
  - per-corner (T1-T11): racing-line lateral spread (std of cross-track vs ref line),
    apex min-speed distribution, braking-point consistency (std of brake-onset
    distance before apex), head-yaw lookahead proxy (honest label).
"""
from __future__ import annotations
import sys
import numpy as np
import pandas as pd

from common import OUTPUT, load_json, write_json
import timesheet as ts_mod

SECTORS = ["sector_1", "sector_2", "sector_3"]
SECTOR_NAMES = {"sector_1": "S1 (S/F->T5)", "sector_2": "S2 (straight->T9)",
                "sector_3": "S3 (T9->S/F)"}
BRAKE_DECEL = -2.0     # m/s^2 sustained -> braking onset


def pace_consistency(series):
    s = series.dropna().values
    if len(s) == 0:
        return {}
    mean = float(np.mean(s)); std = float(np.std(s, ddof=1)) if len(s) > 1 else 0.0
    return {"n": int(len(s)), "best": float(np.min(s)), "mean": mean,
            "median": float(np.median(s)), "std": std,
            "cv": float(std / mean) if mean else 0.0,
            "p90": float(np.percentile(s, 90)), "p50": float(np.percentile(s, 50))}


def reference_lap(laps_df, st):
    """Best VALID lap (clean sectors) as ghost reference; fallback to fastest lap."""
    valid = st[st.sectors_valid]
    if len(valid):
        lap = int(valid.loc[valid.lap_time.idxmin()].lap)
    else:
        lap = int(laps_df.loc[laps_df.lap_time_s.idxmin()].lap)
    return lap


def lap_distance_profile(fused, t0_ns, t1_ns):
    seg = fused[(fused.t >= t0_ns) & (fused.t <= t1_ns)].reset_index(drop=True)
    dE = np.diff(seg.E.values); dN = np.diff(seg.N.values)
    dist = np.concatenate([[0], np.cumsum(np.sqrt(dE ** 2 + dN ** 2))])
    return seg, dist


def delta_vs_reference(fused, laps_df, ref_lap, sel_lap):
    """Cumulative time delta vs reference lap as a function of normalized distance."""
    r = laps_df[laps_df.lap == ref_lap].iloc[0]
    s = laps_df[laps_df.lap == sel_lap].iloc[0]
    rseg, rdist = lap_distance_profile(fused, r.t_start_ns, r.t_end_ns)
    sseg, sdist = lap_distance_profile(fused, s.t_start_ns, s.t_end_ns)
    # normalize distance 0..1; map to elapsed time within lap
    rt = (rseg.t.values - rseg.t.values[0]) / 1e9
    stt = (sseg.t.values - sseg.t.values[0]) / 1e9
    rfrac = rdist / rdist[-1]; sfrac = sdist / sdist[-1]
    grid = np.linspace(0, 1, 200)
    rtime = np.interp(grid, rfrac, rt)
    stime = np.interp(grid, sfrac, stt)
    delta = stime - rtime   # + = slower than reference
    return grid.tolist(), [round(float(d), 3) for d in delta]


def per_corner(fused, laps_df, st, sectors_json, ref_lap, use_laps=None):
    """Line spread, apex min-speed, braking-point std, head-yaw lookahead per corner.
    use_laps: explicit list of laps to include (clean laps); defaults to valid laps."""
    corners = sectors_json.get("corners", [])
    valid_laps = use_laps if use_laps is not None else st[st.sectors_valid].lap.tolist()
    if ref_lap not in valid_laps and valid_laps:
        ref_lap = valid_laps[0]
    # adaptive apex window: half the distance to the nearest neighbour corner so
    # closely-spaced turns (e.g. T8/T9 ~0.008 frac apart) don't bleed into each other.
    cfracs = [c["dist_frac"] for c in corners]
    halfwin = {}
    for i, c in enumerate(corners):
        gaps = []
        if i > 0:
            gaps.append(cfracs[i] - cfracs[i - 1])
        if i < len(corners) - 1:
            gaps.append(cfracs[i + 1] - cfracs[i])
        hw = (min(gaps) * 0.45) if gaps else 0.02
        halfwin[c["num"]] = float(np.clip(hw, 0.004, 0.02))
    # reference lap geometry for cross-track reference
    r = laps_df[laps_df.lap == ref_lap].iloc[0]
    rseg, rdist = lap_distance_profile(fused, r.t_start_ns, r.t_end_ns)
    rfrac = rdist / rdist[-1]
    out = []
    for c in corners:
        cf = c["dist_frac"]
        # window +/-3% of lap around apex
        results = {"num": c["num"], "name": c["name"], "sector": c["sector"],
                   "dist_frac": cf}
        apex_speeds, apex_pts, brake_dists = [], [], []
        hw = halfwin[c["num"]]
        for lap in valid_laps:
            lp = laps_df[laps_df.lap == lap].iloc[0]
            seg, dist = lap_distance_profile(fused, lp.t_start_ns, lp.t_end_ns)
            frac = dist / dist[-1]
            win = (frac > cf - hw) & (frac < cf + hw)
            if win.sum() < 2:
                continue
            # apex = min-speed point in the window (more meaningful than fixed frac)
            wi = np.where(win)[0]
            kmin = wi[np.argmin(seg.speed.values[wi])]
            apex_speeds.append(float(seg.speed.values[kmin]))
            apex_pts.append((seg.E.values[kmin], seg.N.values[kmin]))
            # braking onset: last point before apex where decel sustained
            pre = (frac > cf - 0.10) & (frac <= cf)
            if pre.sum() > 5:
                sp = seg.speed.values[pre]; dd = dist[pre]
                acc = np.gradient(sp, np.maximum(dd, 1e-6))
                bo = np.where(acc < BRAKE_DECEL)[0]
                if len(bo):
                    brake_dists.append(float(dd[-1] - dd[bo[0]]))
        # line spread = RMS distance of apex points from their centroid (clean laps)
        if len(apex_pts) >= 2:
            ap = np.array(apex_pts)
            line_spread = float(np.sqrt(np.mean(np.sum((ap - ap.mean(0)) ** 2, axis=1))))
        else:
            line_spread = None
        results["apex_speed_mean_ms"] = _m(apex_speeds, np.mean)
        results["apex_speed_std_ms"] = _m(apex_speeds, lambda v: np.std(v, ddof=1) if len(v) > 1 else 0)
        results["line_spread_std_m"] = round(line_spread, 2) if line_spread is not None else None
        results["brake_point_std_m"] = _m(brake_dists, lambda v: np.std(v, ddof=1) if len(v) > 1 else 0)
        out.append(results)
    return out


def math_hypot(a, b):
    return float(np.hypot(a, b))


def _m(v, fn):
    return round(float(fn(np.array(v))), 3) if len(v) else None


def lookahead_proxy(parquet, fused, laps_df, st, sectors_json, ref_lap, use_laps=None):
    """Head-yaw vs kart heading near each corner: positive = head turned toward the
    upcoming corner direction early. HONESTLY a head-orientation proxy, not gaze.
    Requires AirPods head-motion (head_yaw); returns [] if not recorded."""
    df = parquet
    if "head_yaw" not in df.columns:
        return []   # no AirPods head-motion in this recording
    valid_laps = use_laps if use_laps is not None else st[st.sectors_valid].lap.tolist()
    corners = sectors_json.get("corners", [])
    out = []
    for c in corners:
        cf = c["dist_frac"]
        vals = []
        for lap in valid_laps:
            lp = laps_df[laps_df.lap == lap].iloc[0]
            seg = df[(df.t >= lp.t_start_ns) & (df.t <= lp.t_end_ns)].reset_index(drop=True)
            if len(seg) < 10:
                continue
            d = np.cumsum(np.r_[0, np.hypot(np.diff(seg.E), np.diff(seg.N))])
            frac = d / d[-1]
            # approach window: just before apex
            win = (frac > cf - 0.05) & (frac < cf)
            if win.sum() < 3:
                continue
            # head yaw relative to kart heading change ahead
            head = seg.head_yaw.values[win]
            vals.append(float(np.nanmean(head)))
        out.append({"num": c["num"], "head_yaw_approach_mean_rad": _m(vals, np.mean),
                    "n": len(vals)})
    return out


def run(venue: str = "gateway-kartplex") -> dict:
    print("=" * 64)
    print(f"[analytics] Stage B  venue={venue}")
    print("=" * 64)
    sheets = {s["session_key"]: s for s in ts_mod.run(venue)}
    out = {}
    for key in sheets:
        ds = OUTPUT / venue / key / "dataset"
        if not (ds / "sector_times.csv").exists():
            continue
        st = pd.read_csv(ds / "sector_times.csv")
        laps_df = pd.read_csv(ds / "laps.csv")
        fused = pd.read_csv(ds / "fused_trace.csv")
        sectors_json = load_json(ds / "sectors.json")
        parquet = pd.read_parquet(ds / "aligned_100hz.parquet")

        # ---- clean-lap classification ------------------------------------
        # An incident lap (spin / big time loss) is NOT representative inconsistency.
        # Definition: lap_time > best*1.05 (captures spins & the lost hairpin-impact
        # lap). NOTE: peak-g is NOT used to exclude laps - 4.5-7g kerb strikes are
        # NORMAL on this outdoor track and occur on fast laps too (incl. the hard
        # hairpin wall hit on an otherwise quick lap). We report peak-g as context.
        best_t = st.lap_time.min()
        incident_laps, lap_peak_g = [], {}
        for r in laps_df.itertuples():
            seg = parquet[(parquet.t >= r.t_start_ns) & (parquet.t <= r.t_end_ns)]
            pk = float(seg.acc_mag.max() / 9.80665) if len(seg) else 0.0
            lap_peak_g[int(r.lap)] = round(pk, 1)
            if r.lap_time_s > best_t * 1.05:
                incident_laps.append(int(r.lap))
        clean_mask = ~st.lap.isin(incident_laps)
        st_clean = st[clean_mask]
        n_clean = int(clean_mask.sum())

        # pace + consistency  (CONSISTENCY from clean laps; pace/best from all)
        lap_stats = pace_consistency(st.lap_time)
        lap_stats_clean = pace_consistency(st_clean.lap_time)
        sector_stats = {s: pace_consistency(st[s]) for s in SECTORS}
        sector_stats_clean = {s: pace_consistency(st_clean[s]) for s in SECTORS}
        theoretical_best = sum(sector_stats[s]["best"] for s in SECTORS
                               if sector_stats[s])
        gap_to_theoretical = lap_stats["best"] - theoretical_best

        # opportunity ranking: pace_gap + consistency_cost (P90-P50), CLEAN laps
        opp = []
        for s in SECTORS:
            ss = sector_stats_clean[s] or sector_stats[s]
            if not ss:
                continue
            pace_gap = ss["mean"] - ss["best"]
            cons_cost = ss["p90"] - ss["p50"]
            opp.append({"sector": s, "name": SECTOR_NAMES[s],
                        "pace_gap_s": round(pace_gap, 3),
                        "consistency_cost_s": round(cons_cost, 3),
                        "std_s": round(ss["std"], 3), "cv": round(ss["cv"], 4),
                        "opportunity_s": round(pace_gap + cons_cost, 3),
                        "quadrant_x_pace_gap": round(pace_gap, 3),
                        "quadrant_y_std": round(ss["std"], 3)})
        opp.sort(key=lambda o: o["opportunity_s"], reverse=True)

        ref_lap = reference_lap(laps_df, st)
        clean_laps = st_clean.lap.tolist()

        # delta vs reference for every lap
        deltas = {}
        for lap in laps_df.lap.tolist():
            grid, d = delta_vs_reference(fused, laps_df, ref_lap, lap)
            deltas[str(lap)] = d
        deltas["_grid"] = grid

        corners = per_corner(fused, laps_df, st, sectors_json, ref_lap, use_laps=clean_laps)
        look = lookahead_proxy(parquet, fused, laps_df, st, sectors_json, ref_lap,
                               use_laps=clean_laps)

        analytics = {
            "venue": venue, "session_key": key,
            "reference_lap": ref_lap,
            "lap": lap_stats,
            "lap_clean": lap_stats_clean,
            "sectors": {s: sector_stats_clean[s] or sector_stats[s] for s in SECTORS},
            "sectors_all_laps": {s: sector_stats[s] for s in SECTORS},
            "sector_names": SECTOR_NAMES,
            "n_laps": int(len(st)),
            "n_clean_laps": n_clean,
            "incident_laps": incident_laps,
            "lap_peak_g": lap_peak_g,
            "clean_lap_def": "lap_time <= best*1.05 (incident=slow lap; peak-g is info only)",
            "theoretical_best_lap_s": round(theoretical_best, 3),
            "actual_best_lap_s": round(lap_stats["best"], 3),
            "gap_to_theoretical_s": round(gap_to_theoretical, 3),
            "opportunity_ranking": opp,
            "priority_quadrant": [{"sector": o["sector"], "name": o["name"],
                                   "x_pace_gap": o["quadrant_x_pace_gap"],
                                   "y_std": o["quadrant_y_std"]} for o in opp],
            "delta_vs_reference": deltas,
            "per_corner": corners,
            "lookahead_head_orientation_proxy": look,
            "notes": {"lookahead": "head-ORIENTATION (AirPods yaw) proxy for gaze, "
                                   "approximate, drifts; NOT eye-tracking.",
                      "consistency": "consistency/line stats use CLEAN laps only "
                                     "(incident laps flagged separately)."},
        }
        write_json(ds / "analytics.json", analytics)
        out[key] = analytics

        print(f"[analytics] {key}: best {lap_stats['best']:.3f}s  "
              f"theoretical {theoretical_best:.3f}s  gap {gap_to_theoretical:.3f}s  "
              f"clean {n_clean}/{len(st)} laps  clean lap CV {lap_stats_clean['cv']*100:.1f}%  "
              f"incidents={incident_laps}")

    print("-" * 64)
    print(f"[analytics] STATUS: PASS  ({len(out)} sessions)")
    print("-" * 64)
    return out


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "gateway-kartplex")
