"""Generate deliverable plots:
  1. Full session fused trace vs raw GPS (shape validation)
  2. Speed-colored track map
  3. Clean-lap overlay with best lap (11) highlighted
  4. Spin detection: facing vs course divergence
"""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from loaders import load_location, to_enu

OFFICIAL = [42.450, 41.136, 49.209, 41.834, 41.564, 42.189, 41.056,
            40.968, 42.535, 42.583, 40.519, 53.899, 41.600, 46.750]
SPIN_LAPS = {3, 12}          # known bad laps from timing sheet
OUTLAP, INLAP = 1, 14


def load():
    df = pd.read_csv("kart/fused_trace.csv")
    ct = np.load("kart/lap_crossings.npy")
    return df, ct


def lap_index(df, ct):
    """Assign each sample a lap number (1..14) based on crossing times."""
    t = df.seconds_elapsed.values
    lap = np.zeros(len(t), int)
    for i in range(len(ct) - 1):
        lap[(t >= ct[i]) & (t < ct[i + 1])] = i + 1
    return lap


def plot_trace_vs_gps(df):
    loc = load_location()
    lat0, lon0 = loc.latitude.iloc[0], loc.longitude.iloc[0]
    ge, gn = to_enu(loc.latitude.values, loc.longitude.values, lat0, lon0)
    fig, ax = plt.subplots(1, 2, figsize=(12, 9), sharex=True, sharey=True)
    ax[0].plot(ge, gn, '-o', ms=2, lw=0.6, color='tab:red', alpha=0.6)
    ax[0].set_title("Raw GPS (1 Hz, 789 pts)")
    ax[1].plot(df.E, df.N, '-', lw=0.7, color='tab:blue')
    ax[1].set_title("Fused trace (100 Hz, smoothed)")
    for a in ax:
        a.set_aspect('equal'); a.grid(alpha=0.3); a.set_xlabel("East (m)")
    ax[0].set_ylabel("North (m)")
    fig.suptitle("Track shape: raw GPS vs GPS+IMU fused", fontsize=13)
    fig.tight_layout()
    fig.savefig("kart/01_trace_vs_gps.png", dpi=130)
    print("saved 01_trace_vs_gps.png")


def plot_speed_map(df):
    pts = np.column_stack([df.E, df.N])
    segs = np.stack([pts[:-1], pts[1:]], axis=1)
    spd_kmh = df.speed.values[:-1] * 3.6
    lc = LineCollection(segs, cmap='turbo', norm=plt.Normalize(0, spd_kmh.max()))
    lc.set_array(spd_kmh); lc.set_linewidth(1.8)
    fig, ax = plt.subplots(figsize=(7, 11))
    ax.add_collection(lc); ax.autoscale(); ax.set_aspect('equal')
    ax.grid(alpha=0.3); ax.set_xlabel("East (m)"); ax.set_ylabel("North (m)")
    cb = fig.colorbar(lc, ax=ax, shrink=0.6); cb.set_label("Speed (km/h)")
    ax.set_title("Speed map (full session)")
    fig.tight_layout(); fig.savefig("kart/02_speed_map.png", dpi=130)
    print("saved 02_speed_map.png")


def plot_lap_overlay(df, lap):
    clean = [l for l in range(1, 15) if l not in SPIN_LAPS and l not in (OUTLAP, INLAP)]
    fig, ax = plt.subplots(figsize=(7, 11))
    for l in clean:
        m = lap == l
        ax.plot(df.E[m], df.N[m], lw=0.8, alpha=0.5, color='gray')
    mb = lap == 11
    ax.plot(df.E[mb], df.N[mb], lw=2.4, color='tab:red',
            label=f"Best lap 11 ({OFFICIAL[10]:.3f}s)")
    ax.set_aspect('equal'); ax.grid(alpha=0.3)
    ax.set_xlabel("East (m)"); ax.set_ylabel("North (m)")
    ax.legend(loc='upper left')
    ax.set_title(f"Clean-lap overlay (laps {clean}) + best lap")
    fig.tight_layout(); fig.savefig("kart/03_lap_overlay.png", dpi=130)
    print("saved 03_lap_overlay.png")


def plot_spins(df, lap):
    # course-over-ground vs integrated facing -> divergence flags spins
    course = df.course_deg.values
    # de-bias facing to course during clean fast driving (anchor)
    facing = df.facing_raw_deg.values.copy()
    fast = df.speed.values > 6
    # crude continuous anchor: remove slow linear drift between facing & course
    cu = np.unwrap(np.radians(course))
    fu = np.unwrap(np.radians(facing))
    # fit facing-drift on fast samples
    A = np.polyfit(df.seconds_elapsed.values[fast], (fu - cu)[fast], 1)
    fu_corr = fu - np.polyval(A, df.seconds_elapsed.values)
    diverge = np.degrees(np.abs((np.degrees(fu_corr) - np.degrees(cu) + 180) % 360 - 180))
    diverge = np.degrees(np.angle(np.exp(1j*(fu_corr - cu))))
    diverge = np.abs(diverge)

    fig, ax = plt.subplots(figsize=(7, 11))
    pts = np.column_stack([df.E, df.N])
    segs = np.stack([pts[:-1], pts[1:]], axis=1)
    lc = LineCollection(segs, cmap='inferno', norm=plt.Normalize(0, 90))
    lc.set_array(diverge[:-1]); lc.set_linewidth(1.8)
    ax.add_collection(lc); ax.autoscale(); ax.set_aspect('equal'); ax.grid(alpha=0.3)
    cb = fig.colorbar(lc, ax=ax, shrink=0.6); cb.set_label("|facing - course| (deg)")
    ax.set_xlabel("East (m)"); ax.set_ylabel("North (m)")
    ax.set_title("Slide/spin indicator (high = sideways)")
    fig.tight_layout(); fig.savefig("kart/04_spin_map.png", dpi=130)
    print("saved 04_spin_map.png")


def main():
    df, ct = load()
    lap = lap_index(df, ct)
    plot_trace_vs_gps(df)
    plot_speed_map(df)
    plot_lap_overlay(df, lap)
    plot_spins(df, lap)
    print("All plots written to kart/")


if __name__ == "__main__":
    main()