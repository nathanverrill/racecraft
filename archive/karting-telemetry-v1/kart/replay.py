"""Synchronized telemetry replay renderer.
dashboard 

Produces an MP4: moving dot on the track + live data channels, with the
original Microphone.mp4 audio muxed in so it plays in lockstep.

Audio and sensors share the same `seconds_elapsed` clock (recording start
= 0). So a frame at sensor-time T uses audio at T. We clip the audio to the
rendered window with ffmpeg.

Usage:
    python replay.py --start 590 --end 615 --out spin_clip.mp4 --fps 30
    python replay.py --start 56  --end 845 --out full_session.mp4 --fps 30
"""
import argparse
import subprocess
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
VISIT = HERE.parent
CLIPPED = VISIT / "clipped"
# Clipped audio is already trimmed to the racing window, so its t=0 == race t=0.
AUDIO = CLIPPED / "Microphone_clipped.mp4"
G = 9.81

# All replay times are RACE-RELATIVE seconds (0 = first gate crossing).
TCOL = "seconds_elapsed_race"


def load_trace():
    df = pd.read_csv(CLIPPED / "fused_trace.csv")
    # derived channels
    df["speed_kmh"] = df.speed * 3.6
    # lateral accel = v * yaw_rate (m/s^2) -> g
    df["lat_g"] = (df.speed * df.yaw_rate) / G
    # facing-vs-course divergence (spin indicator), de-biased on fast driving
    cu = np.unwrap(np.radians(df.course_deg.values))
    fu = np.unwrap(np.radians(df.facing_raw_deg.values))
    fast = df.speed.values > 6
    A = np.polyfit(df[TCOL].values[fast], (fu - cu)[fast], 1)
    fu_corr = fu - np.polyval(A, df[TCOL].values)
    div = np.degrees(np.angle(np.exp(1j * (fu_corr - cu))))
    df["slip_deg"] = div

    # EVENT flags for replay visuals.
    # impact: very large raw jolt. Do NOT gate on fused speed (it's smoothed
    # and undershoots at the hit). A high jolt threshold separates real
    # wall/kerb hits from normal pocket vibration.
    df["impact"] = df.acc_mag > 50.0
    # spin: high yaw rate
    df["spin"] = df.yaw_rate.abs() > 4.0
    return df


    df = load_trace()
    full = df  # faint full-track background
    seg = df[(df[TCOL] >= start) & (df[TCOL] <= end)].reset_index(drop=True)
    if len(seg) == 0:
        raise SystemExit("No samples in window")

    # frame times (race-relative)
    ft = np.arange(start, end, 1.0 / fps)
    idx = np.searchsorted(df[TCOL].values, ft)
    idx = np.clip(idx, 0, len(df) - 1)

    # layout
    fig = plt.figure(figsize=(12.8, 7.2), dpi=100)
    gs = fig.add_gridspec(4, 2, width_ratios=[1.4, 1.0])
    ax_trk = fig.add_subplot(gs[:, 0])
    ax_sp = fig.add_subplot(gs[0, 1])
    ax_yaw = fig.add_subplot(gs[1, 1])
    ax_lg = fig.add_subplot(gs[2, 1])
    ax_slip = fig.add_subplot(gs[3, 1])

    # static track background
    ax_trk.plot(full.E, full.N, color="0.82", lw=0.8, zorder=1)
    ax_trk.set_aspect("equal"); ax_trk.axis("off")
    ax_trk.set_title("Track replay", fontsize=11)
    trail, = ax_trk.plot([], [], color="tab:blue", lw=2.2, alpha=0.9, zorder=3)
    # spin halo (orange ring that appears when spinning)
    halo, = ax_trk.plot([], [], "o", ms=26, color="orange", alpha=0.0, zorder=4,
                        markerfacecolor="none", markeredgewidth=3)
    # impact ring (expands briefly at a wall hit)
    impact_ring, = ax_trk.plot([], [], "o", ms=10, color="red", alpha=0.0,
                               zorder=6, markerfacecolor="none", markeredgewidth=4)
    dot, = ax_trk.plot([], [], "o", ms=11, color="red", zorder=7,
                       markeredgecolor="white", markeredgewidth=1.2)

    # precompute impact event times (for ring animation). Cluster nearby
    # impact samples and set each event time to the PEAK jolt within the
    # cluster (the true impact instant), not the first over-threshold sample.
    imp_mask = df.impact.values
    tt_all = df[TCOL].values
    acc_all = df.acc_mag.values
    idx_imp = np.where(imp_mask)[0]
    events = []
    if len(idx_imp):
        cluster = [idx_imp[0]]
        for k in idx_imp[1:]:
            if tt_all[k] - tt_all[cluster[-1]] <= 0.5:
                cluster.append(k)
            else:
                pk = cluster[int(np.argmax(acc_all[cluster]))]
                events.append(tt_all[pk])
                cluster = [k]
        pk = cluster[int(np.argmax(acc_all[cluster]))]
        events.append(tt_all[pk])
    events = np.array(events)
    print("impact events (peak-jolt) at t=", np.round(events, 2))

    # channel setup
    def setup(ax, series, label, color, ylim=None):
        ax.plot(df[TCOL], series, color=color, lw=0.6, alpha=0.35)
        ph = ax.axvline(start, color="k", lw=1)
        mk, = ax.plot([], [], "o", ms=6, color=color)
        ax.set_xlim(start, end)
        if ylim: ax.set_ylim(*ylim)
        ax.set_ylabel(label, fontsize=9); ax.tick_params(labelsize=7)
        ax.grid(alpha=0.25)
        return ph, mk

    sp_ph, sp_mk = setup(ax_sp, df.speed_kmh, "Speed km/h", "tab:green")
    yaw_ph, yaw_mk = setup(ax_yaw, df.yaw_rate, "Yaw rad/s", "tab:purple")
    lg_ph, lg_mk = setup(ax_lg, df.lat_g, "Lateral G", "tab:orange")
    slip_ph, slip_mk = setup(ax_slip, df.slip_deg, "Slip deg", "tab:red")
    ax_slip.set_xlabel("time (s)", fontsize=8)

    txt = ax_trk.text(0.02, 0.98, "", transform=ax_trk.transAxes,
                      va="top", ha="left", fontsize=11, family="monospace",
                      bbox=dict(boxstyle="round", fc="white", alpha=0.7))

    frames_dir = HERE / "_frames"
    frames_dir.mkdir(exist_ok=True)
    for f in frames_dir.glob("*.png"):
        f.unlink()

    E = df.E.values; N = df.N.values
    te = df[TCOL].values

    for fi, (tnow, i) in enumerate(zip(ft, idx)):
        # trail: samples within last 3s
        lo = te[i] - 3.0
        tm = (te <= te[i]) & (te >= lo)
        trail.set_data(E[tm], N[tm])
        dot.set_data([E[i]], [N[i]])

        # spin halo: fade in with yaw-rate magnitude
        yr = abs(df.yaw_rate.values[i])
        halo.set_data([E[i]], [N[i]])
        halo.set_alpha(min(0.9, max(0.0, (yr - 2.0) / 4.0)))   # appears >2 rad/s

        # impact ring: PRE-TRIGGER so the flash peaks exactly AT impact.
        # Window spans [-0.12s, +0.45s] around the event; brightness peaks at
        # the event instant, so the eye catches it in sync with the bang.
        ring_a, ring_ms = 0.0, 10
        if len(events):
            dtv = tnow - events                      # +ve after impact
            near = dtv[(dtv >= -0.12) & (dtv < 0.45)]
            if len(near):
                age = near[np.argmin(np.abs(near))]  # closest event
                if age < 0:                          # pre-impact: ramp up fast
                    ring_a = 1.0 + age / 0.12        # 0 -> 1 over 0.12s
                    ring_ms = 30
                else:                                # post-impact: expand+fade
                    ring_a = 1.0 - age / 0.45
                    ring_ms = 30 + age * 160
        impact_ring.set_data([E[i]], [N[i]])
        impact_ring.set_alpha(max(0.0, min(1.0, ring_a)))
        impact_ring.set_markersize(ring_ms)
        for ph in (sp_ph, yaw_ph, lg_ph, slip_ph):
            ph.set_xdata([tnow, tnow])
        sp_mk.set_data([tnow], [df.speed_kmh.values[i]])
        yaw_mk.set_data([tnow], [df.yaw_rate.values[i]])
        lg_mk.set_data([tnow], [df.lat_g.values[i]])
        slip_mk.set_data([tnow], [df.slip_deg.values[i]])
        txt.set_text(f"t={tnow:6.1f}s\n{df.speed_kmh.values[i]:5.1f} km/h\n"
                     f"slip {df.slip_deg.values[i]:+5.0f}")
        fig.savefig(frames_dir / f"f{fi:06d}.png")
    plt.close(fig)
    print(f"Rendered {len(ft)} frames")

    # mux frames + clipped audio. AUDIO is already race-relative (t=0 at race
    # forward so the bang lands with the ring.
    out_path = HERE / out
    audio_start = max(0.0, start + audio_offset)
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps), "-i", str(frames_dir / "f%06d.png"),
        "-ss", str(audio_start), "-to", str(end + audio_offset), "-i", str(AUDIO),
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest",
        str(out_path),
    ]
    print("muxing:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    print("WROTE", out_path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=float, required=True)
    ap.add_argument("--end", type=float, required=True)
    ap.add_argument("--out", default="replay.mp4")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--audio-offset", type=float, default=0.0,
                    help="shift audio (s); -ve pulls audio earlier to sync the bang")
    a = ap.parse_args()
    render(a.start, a.end, a.out, a.fps, a.audio_offset)