"""coaching.py - Stage B: turn the dataset into a COACHING DEBRIEF + next-session
STRATEGY, focused on the driver's real questions:
  - best line / where to look
  - consistency rating per SECTOR and per TURN
  - where to improve the most
  - karting best-practice suggestions
  - a debrief (what happened) + strategy (what to do next session)

Reads dataset/ (fused_trace, laps, sector_times, sectors.json, analytics.json,
aligned_100hz.parquet). Writes dataset/coaching.json. Read-only on Stage A.

Honest labelling: head-yaw is a HEAD-ORIENTATION proxy for gaze (AirPods), not eye
tracking; RPM is low-confidence and not used. Line/braking come from GPS+IMU.
"""
from __future__ import annotations
import sys
import numpy as np
import pandas as pd

from common import OUTPUT, load_json, write_json, lonlat_to_enu
import timesheet as ts_mod

G = 9.80665
MPH = 2.236936


# ----------------------------------------------------------------------------
# robust per-corner geometry & consistency
# ----------------------------------------------------------------------------
def corner_window_idx(frac_profile, cf, half=0.025):
    return np.where((frac_profile > cf - half) & (frac_profile < cf + half))[0]


def analyze_corners(fused, laps_df, st, sectors_json, exclude_laps=None):
    """For each turn, across CLEAN laps: apex speed (mean/std), racing-line lateral
    spread vs the MEAN line, braking-point mean/std, min-speed point, entry/exit
    speed. Returns list of dicts + a consistency score 0-100 per turn."""
    corners = sectors_json.get("corners", [])
    exclude = set(exclude_laps or [])
    laps = [l for l in laps_df.lap.tolist() if l not in exclude]
    # precompute per-lap (frac, E, N, speed, t)
    perlap = {}
    for r in laps_df.itertuples():
        if r.lap in exclude:
            continue
        seg = fused[(fused.t >= r.t_start_ns) & (fused.t <= r.t_end_ns)].reset_index(drop=True)
        if len(seg) < 10:
            continue
        d = np.r_[0, np.cumsum(np.hypot(np.diff(seg.E.values), np.diff(seg.N.values)))]
        frac = d / d[-1]
        perlap[r.lap] = {"frac": frac, "E": seg.E.values, "N": seg.N.values,
                         "spd": seg.speed.values, "dist": d}

    results = []
    cfracs = [c["dist_frac"] for c in corners]
    for i, c in enumerate(corners):
        cf = c["dist_frac"]
        # adaptive window: half the gap to nearest neighbour corner (closely-spaced
        # stadium turns must not bleed into each other), clamped to [0.004, 0.02].
        gaps = []
        if i > 0:
            gaps.append(cfracs[i] - cfracs[i - 1])
        if i < len(corners) - 1:
            gaps.append(cfracs[i + 1] - cfracs[i])
        hw = float(np.clip((min(gaps) * 0.45) if gaps else 0.02, 0.004, 0.02))
        apex_speeds, apex_pts, brake_dists, entry_spd, exit_spd = [], [], [], [], []
        for lap, P in perlap.items():
            w = corner_window_idx(P["frac"], cf, half=hw)
            if len(w) < 2:
                continue
            kmin = w[np.argmin(P["spd"][w])]
            apex_speeds.append(float(P["spd"][kmin]))
            apex_pts.append((P["E"][kmin], P["N"][kmin]))
            # entry = speed ~2.5% before apex, exit ~2.5% after
            ie = np.argmin(np.abs(P["frac"] - (cf - 0.025)))
            ix = np.argmin(np.abs(P["frac"] - (cf + 0.025)))
            entry_spd.append(float(P["spd"][ie])); exit_spd.append(float(P["spd"][ix]))
            # braking onset distance before apex: scan back for sustained decel
            pre = np.where((P["frac"] > cf - 0.12) & (P["frac"] <= cf))[0]
            if len(pre) > 6:
                sp = P["spd"][pre]; dd = P["dist"][pre]
                dv = np.gradient(sp, np.maximum(np.gradient(dd), 1e-6))
                on = np.where(dv < -1.5)[0]
                if len(on):
                    brake_dists.append(float(dd[-1] - dd[on[0]]))
        if len(apex_pts) < 3:
            continue
        apex_pts = np.array(apex_pts)
        centroid = apex_pts.mean(axis=0)
        line_spread = float(np.sqrt(np.mean(np.sum((apex_pts - centroid) ** 2, axis=1))))
        apex_v = np.array(apex_speeds)
        # consistency score: PRIMARILY apex-speed repeatability (clean, meaningful).
        # Absolute apex-position spread is dominated by GPS noise (~3.5m * sqrt2 per
        # pair), so line spread is only a SOFT secondary signal, not the headline.
        v_cv = float(np.std(apex_v) / (np.mean(apex_v) + 1e-6))
        v_pen = np.clip(v_cv / 0.12, 0, 1)                 # apex-speed CV 0..12%
        line_pen = np.clip((line_spread - 4.0) / 8.0, 0, 1)  # only >4m starts to count
        score = float(round(100 * (1 - 0.75 * v_pen - 0.25 * line_pen), 0))
        results.append({
            "num": c["num"], "name": c["name"], "sector": c["sector"],
            "dist_frac": cf,
            "apex_speed_mph_mean": round(float(np.mean(apex_v)) * MPH, 1),
            "apex_speed_mph_std": round(float(np.std(apex_v)) * MPH, 2),
            "apex_speed_cv": round(v_cv, 3),
            "line_spread_m": round(line_spread, 2),
            "entry_speed_mph": round(float(np.mean(entry_spd)) * MPH, 1),
            "exit_speed_mph": round(float(np.mean(exit_spd)) * MPH, 1),
            "brake_point_std_m": round(float(np.std(brake_dists)), 2) if len(brake_dists) > 2 else None,
            "consistency_score": max(0.0, min(100.0, score)),
            "n_laps": len(apex_v),
        })
    return results


def sector_consistency(analytics):
    """Per-sector consistency rating 0-100 from CV (lower CV -> higher score)."""
    out = {}
    for sk in ["sector_1", "sector_2", "sector_3"]:
        cv = analytics["sectors"][sk]["cv"]
        score = float(round(100 * (1 - np.clip(cv / 0.12, 0, 1)), 0))  # cv 0..12% scale
        out[sk] = {"name": analytics["sector_names"][sk],
                   "cv_pct": round(cv * 100, 1),
                   "std_s": round(analytics["sectors"][sk]["std"], 3),
                   "consistency_score": max(0.0, min(100.0, score))}
    return out


# ----------------------------------------------------------------------------
# karting best-practice rules engine -> concrete cues per turn
# ----------------------------------------------------------------------------
def best_practice_cues(corners, look):
    look_by = {l["num"]: l for l in look}
    cues = []
    for c in corners:
        c_cues = []
        # 1) line consistency
        if c["line_spread_m"] > 2.5:
            c_cues.append("Inconsistent line — pick ONE reference (brake marker, apex "
                          "kerb, exit point) and repeat it every lap.")
        # 2) apex speed consistency
        if c["apex_speed_cv"] > 0.10:
            c_cues.append("Apex speed varies lap-to-lap — commit to a repeatable "
                          "minimum speed; trail-brake smoothly to the apex rather than "
                          "braking different amounts each lap.")
        # 3) low apex speed relative to entry (over-slowing)
        if c["entry_speed_mph"] - c["apex_speed_mph_mean"] > 12:
            c_cues.append("Big entry→apex speed drop — likely over-braking/early apex. "
                          "Carry more minimum speed; brake later but lighter, get the "
                          "car rotated and back to throttle earlier.")
        # 4) exit < apex (not feeding throttle on exit)
        if c["exit_speed_mph"] < c["apex_speed_mph_mean"] + 1:
            c_cues.append("Weak exit acceleration — aim to be at a wide-open throttle "
                          "earlier; a good exit pays down the whole next straight.")
        # 5) braking-point variability
        if c["brake_point_std_m"] and c["brake_point_std_m"] > 4:
            c_cues.append("Braking point wanders — use a fixed visual brake marker.")
        # 6) lookahead (head orientation proxy)
        lk = look_by.get(c["num"])
        if lk and lk.get("head_yaw_approach_mean_rad") is not None:
            if abs(lk["head_yaw_approach_mean_rad"]) < 0.08:
                c_cues.append("Head/eyes appear fixed ahead on entry — practice looking "
                              "THROUGH the corner to the apex/exit earlier (head-"
                              "orientation proxy, approximate).")
        if c_cues:
            cues.append({"num": c["num"], "name": c["name"], "sector": c["sector"],
                         "consistency_score": c["consistency_score"],
                         "cues": c_cues})
    return cues


# ----------------------------------------------------------------------------
# debrief + strategy assembly
# ----------------------------------------------------------------------------
def build_debrief(analytics, sec_cons, corners, cues, laps_df, st):
    an = analytics
    gap = an["gap_to_theoretical_s"]
    # weakest sector & turn
    worst_sector = max(sec_cons.values(), key=lambda s: 100 - s["consistency_score"])
    worst_turns = sorted(corners, key=lambda c: c["consistency_score"])[:3]
    best_turns = sorted(corners, key=lambda c: -c["consistency_score"])[:3]
    opp = an["opportunity_ranking"]

    clean = st[st.sectors_valid]
    n_clean = int((clean.lap_time <= clean.lap_time.min() * 1.03).sum())

    debrief = {
        "headline": f"Best lap {an['actual_best_lap_s']:.3f}s · theoretical best "
                    f"{an['theoretical_best_lap_s']:.3f}s · {gap:.2f}s left on the table "
                    f"by not stringing your best sectors together.",
        "consistency_overall": f"{n_clean}/{len(clean)} laps within 3% of your best — "
                               f"work on repeatability before chasing peak pace.",
        "biggest_opportunity": f"{opp[0]['name']}: ~{opp[0]['opportunity_s']:.2f}s/lap "
                               f"available (pace gap {opp[0]['pace_gap_s']:.2f}s + "
                               f"inconsistency cost {opp[0]['consistency_cost_s']:.2f}s).",
        "weakest_sector": f"{worst_sector['name']} — consistency "
                          f"{worst_sector['consistency_score']:.0f}/100 "
                          f"(σ {worst_sector['std_s']:.2f}s).",
        "weakest_turns": [f"T{t['num']} (score {t['consistency_score']:.0f}/100, "
                          f"line σ {t['line_spread_m']:.1f}m, apex {t['apex_speed_mph_mean']:.0f}±"
                          f"{t['apex_speed_mph_std']:.0f} mph)" for t in worst_turns],
        "strongest_turns": [f"T{t['num']} (score {t['consistency_score']:.0f}/100)"
                            for t in best_turns],
    }

    # forward strategy: top 3 actionable focuses next session
    strategy = []
    for t in worst_turns:
        tc = next((c for c in cues if c["num"] == t["num"]), None)
        focus = tc["cues"][0] if tc else "Lock in a repeatable line and apex speed."
        strategy.append({"priority": len(strategy) + 1,
                         "where": f"T{t['num']} ({t['sector']})",
                         "why": f"lowest consistency ({t['consistency_score']:.0f}/100)",
                         "do": focus})
    # add the biggest-opportunity sector as a strategic theme
    strategy.append({"priority": len(strategy) + 1,
                     "where": opp[0]["name"],
                     "why": f"most lap-time available (~{opp[0]['opportunity_s']:.2f}s)",
                     "do": "Prioritise this sector: drive 3-4 laps focusing only here, "
                           "same line every lap, then add pace."})
    session_plan = [
        "Out-lap + 2 laps: scrub in, fix ONE reference per corner (brake marker/apex).",
        f"Next 4 laps: focus ONLY on {worst_turns[0]['name'] if worst_turns else 'your weakest turn'} — "
        "same line, same brake point, same minimum speed.",
        f"Next 4 laps: attack {opp[0]['name']} — carry minimum speed, early throttle.",
        "Final laps: put it together, chase the theoretical-best by linking best sectors.",
    ]
    return debrief, strategy, session_plan


def run(venue: str = "gateway-kartplex") -> dict:
    print("=" * 64)
    print(f"[coaching] Stage B  venue={venue}")
    print("=" * 64)
    sheets = {s["session_key"]: s for s in ts_mod.run(venue)}
    out = {}
    for key in sheets:
        ds = OUTPUT / venue / key / "dataset"
        if not (ds / "analytics.json").exists():
            continue
        analytics = load_json(ds / "analytics.json")
        sectors_json = load_json(ds / "sectors.json")
        fused = pd.read_csv(ds / "fused_trace.csv")
        laps_df = pd.read_csv(ds / "laps.csv")
        st = pd.read_csv(ds / "sector_times.csv")

        corners = analyze_corners(fused, laps_df, st, sectors_json,
                                  exclude_laps=analytics.get("incident_laps", []))
        sec_cons = sector_consistency(analytics)
        cues = best_practice_cues(corners, analytics["lookahead_head_orientation_proxy"])
        debrief, strategy, plan = build_debrief(analytics, sec_cons, corners, cues, laps_df, st)

        # incidents: slow laps (the reliable signal) + impact g-event LOCATIONS
        incident_laps = analytics.get("incident_laps", [])
        lap_peak_g = analytics.get("lap_peak_g", {})
        best_t = st.lap_time.min()
        slow_laps = []
        for r in st.itertuples():
            if int(r.lap) in incident_laps:
                slow_laps.append({"lap": int(r.lap), "lap_time": float(r.lap_time),
                                  "lost_s": round(float(r.lap_time - best_t), 2),
                                  "peak_g": lap_peak_g.get(str(int(r.lap))),
                                  "likely": "spin / big time loss"})
        # impact locations from render.json (acc_mag peaks, with nearest turn)
        impact_locs = []
        rj_path = ds / "render" / "render.json"
        if rj_path.exists():
            rj = load_json(rj_path)
            apexes = rj.get("apexes", [])
            for imp in rj.get("impacts", []):
                near = min(apexes, key=lambda a: (a["x"]-imp["x"])**2+(a["y"]-imp["y"])**2) \
                    if apexes else None
                impact_locs.append({"t": imp["t"], "g": imp["g"],
                                    "nearest_turn": f"T{near['num']}" if near else None})

        coaching = {
            "venue": venue, "session_key": key,
            "debrief": debrief,
            "next_session_strategy": strategy,
            "session_plan": plan,
            "sector_consistency": sec_cons,
            "turn_consistency": corners,
            "best_practice_cues": cues,
            "incidents": {"incident_laps": slow_laps,
                          "n_clean_laps": analytics.get("n_clean_laps"),
                          "n_laps": analytics.get("n_laps"),
                          "impact_locations": impact_locs},
            "honesty_notes": {
                "lookahead": "head-ORIENTATION (AirPods yaw) proxy for gaze, approximate.",
                "rpm": "engine RPM not reliably recoverable from this audio; excluded.",
                "line_spread": "apex-position scatter (m); dominated by ~3.5m GPS noise, "
                               "so used only as a soft secondary signal - the consistency "
                               "score is driven mainly by repeatable APEX SPEED.",
                "incidents": "incident laps = significantly slower laps (>5% off best, "
                             "i.e. spins / big time loss); excluded from consistency. "
                             "Impact g-events (kerb strikes, the hairpin wall hit) are "
                             "reported as LOCATIONS, not used to invalidate laps.",
            },
        }
        write_json(ds / "coaching.json", coaching)
        out[key] = coaching
        print(f"[coaching] {key}: {debrief['biggest_opportunity']}")
        print(f"           weakest turns: {', '.join(debrief['weakest_turns'])}")
        print(f"           sector consistency: " +
              " ".join(f"{v['name'].split()[0]}={v['consistency_score']:.0f}"
                       for v in sec_cons.values()))
    print("-" * 64)
    print(f"[coaching] STATUS: PASS ({len(out)} sessions)")
    print("-" * 64)
    return out


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "gateway-kartplex")
