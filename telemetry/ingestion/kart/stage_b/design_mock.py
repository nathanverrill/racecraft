"""design_mock.py - Stage B: static DESIGN MOCKUPS of the dashboards (PNG).

Renders two full 1920x1080 dashboard concepts from the real render.json, in the dark
F1-broadcast aesthetic, so the visual direction is locked BEFORE the interactive build.

  Dashboard A - ONBOARD / BROADCAST: track map + moving dot + speed trail, big speed +
                delta readout, speed trace, g-g friction circle, live sector strip
                (purple/green/yellow), rev-style LED strip, impact markers.
  Dashboard B - CONSISTENCY / COACHING: priority quadrant (hero), opportunity ranking
                bars, per-sector std/CV, theoretical-best gap, delta-vs-ghost, lap table.

Run: python kart/stage_b/design_mock.py [venue] [session_key]
Out: output/<venue>/<key>/dashboards/design_A.png, design_B.png
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyBboxPatch
from matplotlib.collections import LineCollection
import matplotlib.font_manager as fm

REPO = Path(__file__).resolve().parents[2]
OUTPUT = REPO / "output"

# palette
BG = "#07090d"
PANEL = "#0e1218"
PANEL2 = "#141a22"
GRID = "#1e2630"
CYAN = "#00e5ff"
MAGENTA = "#ff2bd6"
WHITE = "#e8eef5"
DIM = "#7d8a9a"
PURPLE = "#b14cff"
GREEN = "#21e065"
YELLOW = "#ffd23f"
RED = "#ff3b3b"


def load(venue, key):
    ds = OUTPUT / venue / key / "dataset" / "render" / "render.json"
    return json.load(open(ds))


def speed_color(v, vmax):
    # blue(slow)->cyan->yellow->magenta(fast)
    import matplotlib.colors as mc
    cmap = mc.LinearSegmentedColormap.from_list(
        "spd", ["#1b3a8f", CYAN, YELLOW, MAGENTA])
    return cmap(np.clip(v / vmax, 0, 1))


def panel(ax, title=None):
    ax.set_facecolor(PANEL)
    for s in ax.spines.values():
        s.set_color(GRID); s.set_linewidth(0.8)
    ax.tick_params(colors=DIM, labelsize=8)
    if title:
        ax.set_title(title, color=DIM, fontsize=10, loc="left",
                     fontweight="bold", pad=6)


def dashboard_A(d, out_png):
    s = d["series"]
    t = np.array(s["t"]); spd = np.array(s["speed_mph"])
    # pick a dramatic moment: the hairpin impact time
    timp = d["impacts"][0]["t"] if d["impacts"] else t[len(t)//2]
    i = int(np.argmin(np.abs(t - timp)))
    vmax = d["max_speed_mph"]

    fig = plt.figure(figsize=(19.2, 10.8), dpi=100)
    fig.patch.set_facecolor(BG)
    gs = fig.add_gridspec(12, 12, left=0.025, right=0.985, top=0.93, bottom=0.05,
                          hspace=0.9, wspace=0.9)

    # ---- header ----
    fig.text(0.025, 0.965, "GATEWAY KARTPLEX  T1", color=WHITE, fontsize=20,
             fontweight="bold", family="monospace")
    fig.text(0.025, 0.945, f"KART #19   ONBOARD   {d['session_key']}", color=CYAN,
             fontsize=11, family="monospace")
    fig.text(0.80, 0.955, "● REC", color=RED, fontsize=12, family="monospace")

    # ---- track map (big, left) ----
    axm = fig.add_subplot(gs[1:9, 0:6]); panel(axm)
    axm.set_aspect("equal"); axm.axis("off")
    tr = np.array(d["track_polyline"])
    # speed-colored trail (use full lap speed sampled along polyline approx by index)
    axm.plot(tr[:, 0], tr[:, 1], color="#223", lw=8, solid_capstyle="round", zorder=1)
    # colored progress trail up to i
    xs = np.array(s["x"]); ys = np.array(s["y"])
    seg = np.stack([np.c_[xs[:i], ys[:i]][:-1], np.c_[xs[:i], ys[:i]][1:]], axis=1) \
        if i > 2 else None
    if seg is not None and len(seg):
        lc = LineCollection(seg, colors=[speed_color(v, vmax) for v in spd[:i-1]],
                            linewidths=3.5, zorder=2)
        axm.add_collection(lc)
    # apex markers
    for a in d["apexes"]:
        axm.scatter([a["x"]], [a["y"]], s=60, facecolor="none",
                    edgecolor=DIM, linewidth=1.2, zorder=3)
        axm.text(a["x"], a["y"]+0.018, f"T{a['num']}", color=DIM, fontsize=7,
                 ha="center", family="monospace")
    # impacts
    for imp in d["impacts"][:6]:
        axm.scatter([imp["x"]], [imp["y"]], s=180, marker="*", color=RED,
                    edgecolor=WHITE, linewidth=0.6, zorder=4)
    # car dot
    axm.scatter([xs[i]], [ys[i]], s=240, color=WHITE, edgecolor=CYAN,
                linewidth=2.5, zorder=6)
    axm.scatter([xs[i]], [ys[i]], s=900, color=CYAN, alpha=0.18, zorder=5)
    axm.set_xlim(-0.05, max(tr[:,0].max(), 1.0)+0.05)
    axm.set_ylim(-0.05, tr[:,1].max()+0.05)
    axm.set_title("TRACK MAP  ·  speed trail  ·  ★ impact", color=DIM, fontsize=10,
                  loc="left", fontweight="bold")

    # ---- big speed readout (top right) ----
    axs = fig.add_subplot(gs[1:4, 6:9]); panel(axs); axs.axis("off")
    axs.text(0.5, 0.62, f"{spd[i]:.0f}", color=WHITE, fontsize=72,
             ha="center", va="center", fontweight="bold", family="monospace")
    axs.text(0.5, 0.16, "MPH", color=CYAN, fontsize=16, ha="center", family="monospace")

    # ---- delta / lap (top right 2) ----
    axd = fig.add_subplot(gs[1:4, 9:12]); panel(axd); axd.axis("off")
    lap_now = s["lap"][i]
    axd.text(0.5, 0.7, f"LAP {lap_now if lap_now>0 else '-'}", color=WHITE,
             fontsize=24, ha="center", fontweight="bold", family="monospace")
    best = d["analytics"]["actual_best_lap_s"]
    axd.text(0.5, 0.32, f"BEST {best:.3f}s", color=GREEN, fontsize=16, ha="center",
             family="monospace")

    # ---- rev-style LED strip ----
    axr = fig.add_subplot(gs[4:5, 6:12]); panel(axr); axr.axis("off")
    n_led = 20
    frac = np.clip(spd[i] / vmax, 0, 1)
    for k in range(n_led):
        on = k / n_led <= frac
        col = GREEN if k < 12 else (YELLOW if k < 17 else RED)
        axr.add_patch(FancyBboxPatch((k/n_led*0.96+0.01, 0.3), 0.035, 0.4,
                      boxstyle="round,pad=0.005", linewidth=0,
                      facecolor=col if on else "#20262e"))
    axr.text(0.0, 0.0, "THROTTLE / LOAD (speed-proxy; RPM low-confidence)", color=DIM,
             fontsize=7, family="monospace")

    # ---- speed trace (mid right) ----
    axt = fig.add_subplot(gs[5:8, 6:12]); panel(axt, "SPEED TRACE")
    axt.plot(t, spd, color=CYAN, lw=1.0)
    axt.axvline(t[i], color=WHITE, lw=1.0, alpha=0.8)
    axt.fill_between(t[:i], spd[:i], color=CYAN, alpha=0.10)
    axt.set_xlim(t[0], t[-1]); axt.set_ylim(0, vmax*1.1)
    axt.grid(color=GRID, lw=0.5)
    axt.set_ylabel("mph", color=DIM, fontsize=8)

    # ---- g-g friction circle (bottom left of right block) ----
    axg = fig.add_subplot(gs[9:12, 6:9]); panel(axg, "g-g  (long vs lat)")
    axg.set_aspect("equal"); axg.set_xlim(-2.5, 2.5); axg.set_ylim(-2.5, 2.5)
    for rg in (1, 2):
        axg.add_patch(Circle((0, 0), rg, fill=False, edgecolor=GRID, lw=0.8))
    lat = np.array(s["lat_g"]); lon = np.array(s["long_g"])
    axg.scatter(lat[max(0,i-150):i], lon[max(0,i-150):i], s=6, color=CYAN, alpha=0.25)
    axg.scatter([lat[i]], [lon[i]], s=120, color=MAGENTA, edgecolor=WHITE, zorder=5)
    axg.axhline(0, color=GRID, lw=0.5); axg.axvline(0, color=GRID, lw=0.5)
    axg.tick_params(labelsize=7)

    # ---- live sector panel (bottom right) ----
    axsec = fig.add_subplot(gs[9:12, 9:12]); panel(axsec, "SECTORS"); axsec.axis("off")
    an = d["analytics"]; sn = an["sector_names"]
    cols = [PURPLE, GREEN, YELLOW]
    cur_sec = s["sector"][i]
    for k, skey in enumerate(["sector_1", "sector_2", "sector_3"]):
        ss = an["sectors"][skey]
        y = 0.78 - k*0.28
        hot = (cur_sec == k+1)
        axsec.add_patch(FancyBboxPatch((0.04, y-0.02), 0.92, 0.2,
                        boxstyle="round,pad=0.01", linewidth=1.5 if hot else 0.5,
                        edgecolor=CYAN if hot else GRID, facecolor=PANEL2))
        axsec.text(0.08, y+0.11, f"S{k+1}", color=cols[k], fontsize=13,
                   fontweight="bold", family="monospace", va="center")
        axsec.text(0.30, y+0.13, f"best {ss['best']:.2f}", color=WHITE, fontsize=10,
                   family="monospace", va="center")
        axsec.text(0.30, y+0.02, f"σ {ss['std']:.2f}s  cv {ss['cv']*100:.1f}%",
                   color=DIM, fontsize=8, family="monospace", va="center")

    fig.text(0.985, 0.012, "DESIGN MOCK A · onboard/broadcast", color=DIM, fontsize=8,
             ha="right", family="monospace")
    fig.savefig(out_png, facecolor=BG)
    plt.close(fig)


def dashboard_B(d, out_png):
    an = d["analytics"]
    fig = plt.figure(figsize=(19.2, 10.8), dpi=100)
    fig.patch.set_facecolor(BG)
    gs = fig.add_gridspec(12, 12, left=0.04, right=0.97, top=0.92, bottom=0.06,
                          hspace=1.1, wspace=1.1)

    fig.text(0.04, 0.955, "CONSISTENCY  ·  WHERE TO FIND TIME", color=WHITE,
             fontsize=22, fontweight="bold", family="monospace")
    fig.text(0.04, 0.93, f"KART #19   {d['session_key']}   "
             f"best {an['actual_best_lap_s']:.3f}s   theoretical {an['theoretical_best_lap_s']:.3f}s"
             f"   gap {an['gap_to_theoretical_s']:.3f}s", color=CYAN, fontsize=11,
             family="monospace")

    # ---- priority quadrant (hero, big left) ----
    axq = fig.add_subplot(gs[1:8, 0:7]); panel(axq, "IMPROVEMENT PRIORITY  (pace gap × inconsistency)")
    pq = an["priority_quadrant"]
    xs = [p["x_pace_gap"] for p in pq]; ys = [p["y_std"] for p in pq]
    xm = max(xs)*1.25+0.1; ym = max(ys)*1.25+0.1
    axq.axvspan(xm/2, xm, ymin=0.5, ymax=1.0, color=RED, alpha=0.06)
    axq.axhline(ym/2, color=GRID, lw=0.8, ls="--"); axq.axvline(xm/2, color=GRID, lw=0.8, ls="--")
    for p in pq:
        axq.scatter([p["x_pace_gap"]], [p["y_std"]], s=420, color=CYAN,
                    edgecolor=WHITE, linewidth=1.5, zorder=5)
        axq.text(p["x_pace_gap"], p["y_std"]+ym*0.03, p["name"].split()[0],
                 color=WHITE, fontsize=13, ha="center", fontweight="bold",
                 family="monospace")
    axq.set_xlim(0, xm); axq.set_ylim(0, ym)
    axq.set_xlabel("PACE GAP  (mean − best)  →  slower", color=DIM, fontsize=9)
    axq.set_ylabel("INCONSISTENCY  (σ)  →", color=DIM, fontsize=9)
    axq.grid(color=GRID, lw=0.4)
    axq.text(xm*0.97, ym*0.95, "BIGGEST\nOPPORTUNITY", color=RED, fontsize=10,
             ha="right", va="top", fontweight="bold", family="monospace")
    axq.text(xm*0.03, ym*0.05, "HOLD\n(fast+consistent)", color=GREEN, fontsize=9,
             ha="left", va="bottom", family="monospace")

    # ---- opportunity ranking bars (right top) ----
    axo = fig.add_subplot(gs[1:5, 7:12]); panel(axo, "OPPORTUNITY  (s/lap on the table)")
    opp = an["opportunity_ranking"]
    names = [o["name"].split()[0] for o in opp]
    vals = [o["opportunity_s"] for o in opp]
    y = np.arange(len(names))[::-1]
    axo.barh(y, vals, color=[RED if k==0 else CYAN for k in range(len(vals))],
             height=0.55)
    for k, (yy, v) in enumerate(zip(y, vals)):
        axo.text(v+0.02, yy, f"{v:.2f}s", color=WHITE, va="center", fontsize=10,
                 family="monospace")
    axo.set_yticks(y); axo.set_yticklabels(names, color=WHITE, family="monospace")
    axo.set_xlim(0, max(vals)*1.25); axo.grid(color=GRID, lw=0.4, axis="x")

    # ---- per-sector std/cv table (right mid) ----
    axt = fig.add_subplot(gs[5:8, 7:12]); panel(axt, "PACE + CONSISTENCY"); axt.axis("off")
    hdr = ["SECTOR", "BEST", "MEAN", "σ", "CV%"]
    xcol = [0.02, 0.34, 0.50, 0.66, 0.82]
    for x, h in zip(xcol, hdr):
        axt.text(x, 0.86, h, color=DIM, fontsize=9, family="monospace", fontweight="bold")
    for k, skey in enumerate(["sector_1", "sector_2", "sector_3"]):
        ss = an["sectors"][skey]; y = 0.66 - k*0.18
        row = [f"S{k+1}", f"{ss['best']:.2f}", f"{ss['mean']:.2f}",
               f"{ss['std']:.3f}", f"{ss['cv']*100:.1f}"]
        for x, val in zip(xcol, row):
            axt.text(x, y, val, color=WHITE, fontsize=11, family="monospace")
    # lap row
    lp = an["lap"]; y = 0.66 - 3*0.18
    axt.text(0.02, y, "LAP", color=CYAN, fontsize=11, family="monospace", fontweight="bold")
    for x, val in zip(xcol[1:], [f"{lp['best']:.2f}", f"{lp['mean']:.2f}",
                                 f"{lp['std']:.3f}", f"{lp['cv']*100:.1f}"]):
        axt.text(x, y, val, color=CYAN, fontsize=11, family="monospace")

    # ---- delta vs reference (bottom wide) ----
    axd = fig.add_subplot(gs[8:12, 0:7]); panel(axd, "DELTA vs BEST LAP  (cumulative, by distance)")
    dv = an["delta_vs_reference"]; grid = dv["_grid"]
    ref = an["reference_lap"]
    laps_plot = [k for k in dv.keys() if k != "_grid"][:14]
    for lk in laps_plot:
        arr = dv[lk]
        is_ref = int(lk) == ref
        axd.plot(grid, arr, color=(GREEN if is_ref else "#3a4654"), lw=1.0,
                 alpha=1.0 if is_ref else 0.5)
    axd.axhline(0, color=WHITE, lw=1.0)
    axd.set_xlabel("lap distance (0→1)", color=DIM, fontsize=9)
    axd.set_ylabel("Δt (s)  + slower", color=DIM, fontsize=9)
    axd.grid(color=GRID, lw=0.4)
    axd.text(0.01, 0.02, f"ghost = best valid lap (L{ref})", color=GREEN, fontsize=9,
             transform=axd.transAxes, family="monospace")

    # ---- lap table (bottom right) ----
    axl = fig.add_subplot(gs[8:12, 7:12]); panel(axl, "LAPS"); axl.axis("off")
    laps = d["laps"]
    best_lap_t = min(l["lap_time"] for l in laps)
    axl.text(0.02, 0.92, "LAP", color=DIM, fontsize=8, family="monospace")
    axl.text(0.30, 0.92, "TIME", color=DIM, fontsize=8, family="monospace")
    axl.text(0.62, 0.92, "S1·S2·S3", color=DIM, fontsize=8, family="monospace")
    show = laps[:13]
    for k, l in enumerate(show):
        y = 0.85 - k*0.063
        is_best = abs(l["lap_time"]-best_lap_t) < 1e-6
        col = PURPLE if is_best else WHITE
        axl.text(0.02, y, f"{l['lap']}", color=col, fontsize=9, family="monospace")
        axl.text(0.30, y, f"{l['lap_time']:.3f}", color=col, fontsize=9, family="monospace")
        if l.get("sectors_valid"):
            axl.text(0.62, y, f"{l['sector_1']:.1f}·{l['sector_2']:.1f}·{l['sector_3']:.1f}",
                     color=DIM, fontsize=8, family="monospace")

    fig.text(0.97, 0.015, "DESIGN MOCK B · consistency/coaching", color=DIM, fontsize=8,
             ha="right", family="monospace")
    fig.savefig(out_png, facecolor=BG)
    plt.close(fig)


def run(venue="gateway-kartplex", key="2026-06-25_14-40"):
    d = load(venue, key)
    out = OUTPUT / venue / key / "dashboards"
    out.mkdir(exist_ok=True)
    dashboard_A(d, out / "design_A.png")
    dashboard_B(d, out / "design_B.png")
    print(f"[design_mock] wrote {out/'design_A.png'}")
    print(f"[design_mock] wrote {out/'design_B.png'}")


if __name__ == "__main__":
    venue = sys.argv[1] if len(sys.argv) > 1 else "gateway-kartplex"
    key = sys.argv[2] if len(sys.argv) > 2 else "2026-06-25_14-40"
    run(venue, key)
