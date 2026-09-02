"""F1-style telemetry dashboard replay (sexy edition).

LEFT : track map - best-lap ghost (gold), current-lap trace, speed-colored
       tail, live dot + faded ghost dot, sector markers.
RIGHT: big SPEED (mph) + delta, sector deltas, SPEED TRACE (current vs best
       ghost), MAX-G readout, full lap chart (all 14 times, live highlight).
Audio (clipped, race-relative) muxed with -0.15s calibrated offset.
"""
import argparse, subprocess
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from telemetry import (BestRef, load, lap_slice, add_distance,
                       longitudinal_g, compute_delta, G, SECTOR_FRAC, BEST_LAP,
                       detect_flags, per_lap_sector_times)

HERE = Path(__file__).resolve().parent
CLIPPED = HERE.parent / "clipped"
AUDIO = CLIPPED / "Microphone_clipped.mp4"
TCOL = "seconds_elapsed_race"
MPH = 2.237
AUDIO_OFFSET = -0.15

from session_config import OFFICIAL, SESSION

# palette
BG = "#0a0e14"; FG = "#e6edf3"; GOLD = "#f5c518"; GREEN = "#19d27a"
RED = "#ff4d6d"; CYAN = "#39d0d8"; DIM = "#2a3340"; PURPLE = "#b15cff"
YELLOW = "#ffd400"
SECTOR_NAMES = ["ESSES", "STRAIGHT", "HAIRPIN"]
HEADER = f"KARTPLEX T1  \u2022  {SESSION.upper()}  \u2022  LAP TIME ANALYSIS"


def build_dataframe():
    df, bounds = load()
    ref = BestRef()
    df = df.reset_index(drop=True)
    t = df[TCOL].values
    df["speed_mph"] = df.speed.values * MPH
    df["lat_g"] = (df.speed.values * df.yaw_rate.values) / G
    lap_id = np.zeros(len(df), int); lap_t = np.full(len(df), np.nan)
    delta = np.full(len(df), np.nan); sect = np.zeros(len(df), int)
    long_g = np.zeros(len(df))
    for li in range(len(bounds)):
        lo, hi = bounds[li]; m = (t >= lo) & (t <= hi)
        if not m.any():
            continue
        s = df[m].copy(); s["lap_t"] = s[TCOL] - lo
        d, sc, _ = compute_delta(s.assign(lap_t=s["lap_t"]), ref)
        lap_id[m] = li + 1; lap_t[m] = s["lap_t"].values
        delta[m] = d; sect[m] = sc; long_g[m] = longitudinal_g(s)
    df["lap_id"] = lap_id; df["lap_t"] = lap_t; df["delta"] = delta
    df["sector"] = sect; df["long_g"] = long_g
    # combined g magnitude (lat + long), for MAX-G readout
    df["g_mag"] = np.hypot(df.lat_g.values, df.long_g.values)
    df["flag"] = detect_flags(df, TCOL)
    return df, bounds, ref


def best_sector_times(ref):
    bt = []
    for k in range(3):
        m = (ref.dist >= ref.sector_dist[k]) & (ref.dist < ref.sector_dist[k+1])
        bt.append(ref.lap_t[m][-1]-ref.lap_t[m][0] if m.any() else 0.0)
    return bt


def best_speed_by_lapt(ref, lap_t_grid):
    # best-lap speed (mph) resampled onto a lap-time grid
    return np.interp(lap_t_grid, ref.lap_t, ref.speed_mph)


def render(start, end, out, fps, audio_offset=AUDIO_OFFSET):
    df, bounds, ref = build_dataframe()
    t = df[TCOL].values; E, N = df.E.values, df.N.values
    best_sec = best_sector_times(ref)
    sec_all, sess_best_sec, theo_best = per_lap_sector_times(df, bounds, ref, TCOL)
    flag_arr = df["flag"].values
    ft = np.arange(start, end, 1.0 / fps)
    idx = np.clip(np.searchsorted(t, ft), 0, len(df) - 1)

    plt.rcParams.update({"font.family": "DejaVu Sans"})
    fig = plt.figure(figsize=(12.8, 7.2), dpi=100, facecolor=BG)
    # F1-style header banner
    fig.text(0.03, 0.965, "\u25B6 RACELINE", fontsize=13, weight="bold",
             color=GOLD, va="center")
    fig.text(0.16, 0.965, HEADER, fontsize=12, weight="bold", color=FG, va="center")
    fig.add_artist(plt.Line2D([0.02, 0.98], [0.94, 0.94], color=DIM, lw=1))
    gs = fig.add_gridspec(6, 3, width_ratios=[1.6, 1.0, 0.8],
                          hspace=0.9, wspace=0.4,
                          left=0.02, right=0.97, top=0.90, bottom=0.06)
    a_trk = fig.add_subplot(gs[:, 0]); a_trk.set_facecolor(BG)
    a_spd = fig.add_subplot(gs[0, 1]); a_sec = fig.add_subplot(gs[1, 1])
    a_st  = fig.add_subplot(gs[2:4, 1]); a_g = fig.add_subplot(gs[0, 2])
    a_lap = fig.add_subplot(gs[1:, 2]); a_info = fig.add_subplot(gs[4:, 1])
    for a in (a_spd, a_sec, a_g, a_info): a.axis("off"); a.set_facecolor(BG)

    # ---- TRACK ----
    a_trk.plot(df.E, df.N, color=DIM, lw=0.6, zorder=1)
    a_trk.plot(ref.E, ref.N, color=GOLD, lw=1.6, alpha=0.4, zorder=2)
    for f in SECTOR_FRAC[1:-1]:
        j = int(np.searchsorted(ref.dist, f*ref.total))
        a_trk.plot(ref.E[j], ref.N[j], "o", color=CYAN, ms=6, zorder=4)
    a_trk.plot(ref.E[0], ref.N[0], "|", color=FG, ms=22, mew=3, zorder=4)
    a_trk.set_aspect("equal"); a_trk.axis("off")
    # corner / segment labels at each sector's midpoint
    for k in range(3):
        d0, d1 = ref.sector_dist[k], ref.sector_dist[k+1]
        jmid = int(np.searchsorted(ref.dist, (d0+d1)/2))
        jmid = min(jmid, len(ref.E)-1)
        a_trk.annotate(SECTOR_NAMES[k], (ref.E[jmid], ref.N[jmid]),
                       fontsize=7, color=CYAN, weight="bold", alpha=0.7,
                       ha="center", zorder=4)
    # delta-colored racing line (green=gaining vs best, red=losing). Drawn as
    # a LineCollection that builds up over the current lap.
    dline = LineCollection([], zorder=3)
    dline.set_linewidth(2.6); a_trk.add_collection(dline)
    tail = LineCollection([], cmap="turbo", norm=plt.Normalize(0, df.speed_mph.max()))
    tail.set_linewidth(3.2); a_trk.add_collection(tail)
    cur_trace, = a_trk.plot([], [], color=FG, lw=0.6, alpha=0.25, zorder=2)


    ghost, = a_trk.plot([], [], "o", ms=11, color=GOLD, mec="white", mew=0.8, alpha=0.45, zorder=5)
    dot, = a_trk.plot([], [], "o", ms=13, color=RED, mec="white", mew=1.6, zorder=6)

    # ---- SPEED + DELTA ----
    spd_txt = a_spd.text(0.0, 0.4, "", fontsize=46, weight="bold", color=FG, va="center")
    a_spd.text(0.0, -0.18, "MPH", fontsize=11, color="#7d8590")
    delta_lbl = a_spd.text(1.0, 0.72, "DELTA", fontsize=9, color="#7d8590", ha="right")
    delta_txt = a_spd.text(1.0, 0.25, "", fontsize=30, weight="bold", ha="right", va="center")

    # ---- SECTOR DELTAS ----
    a_sec.set_xlim(0, 3); a_sec.set_ylim(-1, 1.2)
    sec_bars = [a_sec.barh(0.1, 0, left=k+0.1, height=0.5, color=DIM)[0] for k in range(3)]
    for k in range(3):
        a_sec.text(k+0.5, 0.95, f"S{k+1}", ha="center", fontsize=9, color="#7d8590", weight="bold")
    sec_val = [a_sec.text(k+0.5, -0.6, "", ha="center", fontsize=9, weight="bold", color=FG) for k in range(3)]

    # ---- SPEED TRACE (current vs best ghost) ----
    a_st.set_facecolor("#0d1320"); a_st.set_title("SPEED TRACE", fontsize=9, color="#7d8590", pad=4)
    a_st.tick_params(colors="#55606e", labelsize=6)
    for sp in a_st.spines.values(): sp.set_color(DIM)
    a_st.set_xlabel("lap time (s)", fontsize=7, color="#55606e")
    a_st.set_ylim(0, df.speed_mph.max()*1.05)
    best_line, = a_st.plot([], [], color=GOLD, lw=1.2, alpha=0.6, label="best")
    cur_line, = a_st.plot([], [], color=CYAN, lw=1.6, label="now")
    a_st.legend(fontsize=6, loc="lower right", framealpha=0)

    # ---- MAX G ----
    a_g.text(0.5, 0.78, "MAX G", fontsize=10, color="#7d8590", ha="center")
    g_txt = a_g.text(0.5, 0.32, "", fontsize=34, weight="bold", color=GOLD, ha="center", va="center")

    # ---- LAP CHART ----
    a_lap.set_facecolor("#0d1320"); a_lap.set_title("LAPS", fontsize=9, color="#7d8590", pad=4)
    a_lap.set_xlim(0, max(OFFICIAL)*1.05); a_lap.set_ylim(14.5, 0.5)
    a_lap.tick_params(colors="#55606e", labelsize=6)
    for sp in a_lap.spines.values(): sp.set_color(DIM)
    bestlap_val = min(OFFICIAL)
    lap_bar_objs = []
    for li, lt in enumerate(OFFICIAL):
        col = GOLD if (li+1)==BEST_LAP else "#3a4658"
        b = a_lap.barh(li+1, lt, height=0.7, color=col)[0]
        lap_bar_objs.append(b)
        a_lap.text(0.5, li+1, f"{li+1:2d}", va="center", fontsize=6, color=BG, weight="bold")
        a_lap.text(lt+0.4, li+1, f"{lt:.2f}", va="center", fontsize=6, color="#9aa5b1")
    a_lap.axvline(bestlap_val, color=GOLD, lw=0.8, ls=":", alpha=0.5)
    # theoretical-best (sum of fastest sectors) on the lap chart
    a_lap.axvline(theo_best, color=PURPLE, lw=1.0, ls="--", alpha=0.8)
    a_lap.text(theo_best, 0.6, f"IDEAL {theo_best:.2f}", fontsize=6,
               color=PURPLE, ha="center", weight="bold")

    a_info_txt = a_info.text(0.0, 0.62, "", fontsize=12, color=FG, va="center", family="monospace")
    theo_txt = a_info.text(0.0, 0.12, f"IDEAL {theo_best:5.2f}s",
                           fontsize=10, color=PURPLE, va="center", family="monospace")

    frames_dir = HERE / "_frames"; frames_dir.mkdir(exist_ok=True)
    for f in frames_dir.glob("*.png"): f.unlink()

    def ghost_pos(lap_time):
        j = int(np.clip(np.searchsorted(ref.lap_t, lap_time), 0, len(ref.lap_t)-1))
        return ref.E[j], ref.N[j]

    for fi, (tnow, i) in enumerate(zip(ft, idx)):
        lap = int(df.lap_id.values[i]); lt = df.lap_t.values[i]
        dl = df.delta.values[i]; spd = df.speed_mph.values[i]

        lo = t[i]-2.5; tm = (t<=t[i])&(t>=lo)
        pts = np.column_stack([E[tm], N[tm]])
        if len(pts)>1:
            segs=np.stack([pts[:-1],pts[1:]],axis=1)
            tail.set_segments(segs); tail.set_array(df.speed_mph.values[tm][:-1])
        dot.set_data([E[i]],[N[i]])

        if lap>0:
            lo_l=bounds[lap-1][0]; lm=(t>=lo_l)&(t<=t[i])
            cur_trace.set_data(E[lm],N[lm])
            gx,gy=ghost_pos(lt); ghost.set_data([gx],[gy])
            # delta-colored racing line built so far this lap (green gaining,
            # red losing vs best at that track point)
            le=E[lm]; ln=N[lm]; ldd=df.delta.values[lm]
            if len(le)>1:
                dpts=np.column_stack([le,ln])
                dsegs=np.stack([dpts[:-1],dpts[1:]],axis=1)
                # gradient of delta -> are we gaining (slope<0) or losing
                dgrad=np.gradient(ldd)
                cols=[GREEN if g<=0 else RED for g in dgrad[:-1]]
                dline.set_segments(dsegs); dline.set_color(cols)
            # speed trace
            cur_lt=df.lap_t.values[lm]; cur_sp=df.speed_mph.values[lm]
            cur_line.set_data(cur_lt,cur_sp)
            grid=np.linspace(0,max(lt,1),200)
            best_line.set_data(grid,best_speed_by_lapt(ref,grid))
            a_st.set_xlim(0, max(ref.best_time, lt))
            # max G so far this lap
            gmax=df.g_mag.values[lm].max()
            g_txt.set_text(f"{gmax:.1f}")
            # highlight current lap in chart
            for li,b in enumerate(lap_bar_objs):
                if (li+1)==lap: b.set_color(CYAN)
                elif (li+1)==BEST_LAP: b.set_color(GOLD)
                else: b.set_color("#3a4658")
        else:
            cur_trace.set_data([],[]); ghost.set_data([],[])
            cur_line.set_data([],[]); best_line.set_data([],[]); g_txt.set_text("")
            dline.set_segments([])

        spd_txt.set_text(f"{spd:3.0f}")
        if np.isnan(dl) or lap==0:
            delta_txt.set_text("--"); delta_txt.set_color(FG)
        else:
            delta_txt.set_text(f"{dl:+.2f}")
            delta_txt.set_color(GREEN if dl<=0 else RED)
        for k in range(3):
            sd=df[(df.lap_id==lap)&(df.sector==k+1)]
            if lap>0 and len(sd):
                cur=sd[sd[TCOL]<=t[i]]
                if len(cur):
                    dh=cur.delta.values[-1]
                    sec_bars[k].set_width(np.clip(abs(dh),0,0.85))
                    sec_bars[k].set_color(GREEN if dh<=0 else RED)
                    sec_val[k].set_text(f"{dh:+.2f}"); sec_val[k].set_color(GREEN if dh<=0 else RED)
        bs=best_sec
        a_info_txt.set_text(f"LAP {lap:2d}   {lt:5.2f}s\nbest {ref.best_time:5.2f}s\n"
                            f"S1 {bs[0]:.1f}  S2 {bs[1]:.1f}  S3 {bs[2]:.1f}")

        fig.savefig(frames_dir/f"f{fi:06d}.png", facecolor=BG)
    plt.close(fig); print(f"Rendered {len(ft)} frames")

    out_path=HERE/out; a_start=max(0.0,start+audio_offset); dur=end-start
    cmd=["ffmpeg","-y","-framerate",str(fps),"-i",str(frames_dir/"f%06d.png"),
         "-ss",str(a_start),"-t",str(dur),"-i",str(AUDIO),
         "-map","0:v","-map","1:a","-c:v","libx264","-pix_fmt","yuv420p",
         "-c:a","aac","-shortest",str(out_path)]
    subprocess.run(cmd,check=True,capture_output=True)
    print("WROTE",out_path)


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--start",type=float,required=True)
    ap.add_argument("--end",type=float,required=True)
    ap.add_argument("--out",default="dashboard.mp4")
    ap.add_argument("--fps",type=int,default=30)
    ap.add_argument("--audio-offset",type=float,default=AUDIO_OFFSET,
                    help="shift audio (s); -ve pulls audio EARLIER, +ve delays it")
    a=ap.parse_args()
    render(a.start,a.end,a.out,a.fps,a.audio_offset)
