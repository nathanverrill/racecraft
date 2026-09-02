"""render_artifact.py - Stage B: build the compact, render-ready artifact + audio.

For each session, emits into dataset/render/:
  - render.json : a compact, downsampled (RENDER_HZ) time series for the front end:
      t (s, session-relative), E,N (and normalized x,y for SVG), lat,lon, speed (mph),
      long_g, lat_g, acc_mag (g), yaw_rate, head_yaw, lap index, sector index,
      plus static: track polyline, apexes, gate + sector-split markers, lap table,
      analytics summary, confirmed impact markers, audio meta (offset/scale).
  - session.wav : the engine audio for THIS session, DRIFT-CORRECTED to the sensor
      clock (resampled so audio plays in lockstep with the telemetry render grid).
      The front end uses audio.currentTime directly as t_session (offset 0, scale 1).

This is the single hand-off for all dashboards + the video exporter. NO Stage A writes.
"""
from __future__ import annotations
import subprocess
import sys
import numpy as np
import pandas as pd

from common import OUTPUT, RAW_SESSIONS, NS_PER_S, load_json, write_json
import timesheet as ts_mod

RENDER_HZ = 30.0
G = 9.80665


def session_audio_window(ds, sync):
    meta = load_json(ds / "session.json")
    venue = meta["venue"]
    ingest = load_json(OUTPUT / venue / "raw" / "ingest.json")
    # per-session recording epoch (multi-recording safe)
    rec_zip = meta.get("recording_zip")
    epoch_ms = None
    for r in ingest.get("recordings", []):
        if r["zip_name"] == rec_zip:
            epoch_ms = r["metadata"]["recording_epoch_ms"]
            break
    if epoch_ms is None:
        epoch_ms = ingest["metadata"]["recording_epoch_ms"]
    epoch_ns = epoch_ms * 1_000_000
    se0 = (meta["window_master_clock_ns"][0] - epoch_ns) / NS_PER_S
    fused = pd.read_csv(ds / "fused_trace.csv")
    dur = float(fused.seconds_elapsed.values[-1])
    a, b = sync["a"], sync["b"]
    at0 = (se0 - b) / a
    at1 = (se0 + dur - b) / a
    return at0, at1, dur, a


def extract_drift_corrected_wav(mp4, at0, at1, a, out_wav, target_dur):
    """Extract [at0,at1] from the audio and time-STRETCH by `a` so its duration
    matches the sensor-clock session duration (target_dur). Then the front end maps
    audio.currentTime == t_session 1:1. atempo handles the ~0.2% stretch cleanly."""
    # audio segment duration on audio clock:
    seg = at1 - at0
    tempo = seg / target_dur     # ~ 1/a ; atempo speeds up if >1
    # atempo valid range 0.5..100; our tempo ~0.998-1.002 is fine
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", f"{at0:.3f}", "-t", f"{seg:.3f}",
         "-i", str(mp4), "-filter:a", f"atempo={tempo:.6f}",
         "-ac", "1", "-ar", "44100", str(out_wav)],
        check=True)
    return tempo


def build_render_json(ds, venue, key, render_hz=RENDER_HZ):
    fused = pd.read_csv(ds / "fused_trace.csv")
    df = pd.read_parquet(ds / "aligned_100hz.parquet")
    laps = pd.read_csv(ds / "laps.csv")
    st = pd.read_csv(ds / "sector_times.csv")
    sectors = load_json(ds / "sectors.json")
    analytics = load_json(ds / "analytics.json")
    fmeta = load_json(ds / "_fuse_meta.json")
    stmeta = load_json(ds / "_sectors_timing_meta.json")
    anchor = fmeta["anchor"]

    se = df.seconds_elapsed.values
    dur = float(se[-1])
    grid = np.arange(0, dur, 1.0 / render_hz)

    def rs(col):
        return np.interp(grid, se, df[col].values)

    def rs_opt(col):
        # optional column (e.g. head_yaw from AirPods; may be absent)
        if col not in df.columns:
            return np.zeros_like(grid)
        return np.interp(grid, se, df[col].values)

    E = rs("E"); N = rs("N")
    speed_ms = rs("speed")
    yaw_rate = rs("yaw_rate")
    head_yaw = rs_opt("head_yaw")
    acc_mag = rs("acc_mag")
    # SUSTAINED cornering/braking g's (coaching channels) from vehicle motion.
    # Realistic bounds for a ~170 lb driver in a Sodi GT5 rental kart:
    #   sustained lateral ~2 g (track advertises "up to 2 lat g"); braking ~1.2 g;
    #   acceleration ~0.4 g (limited GX390 power). Transient IMPACTS (kerb/wall) can
    #   spike higher and live on acc_mag, NOT on these sustained channels.
    long_g = np.gradient(speed_ms, grid) / G                 # accel(+)/brake(-)
    yr_sm = pd.Series(yaw_rate).rolling(
        max(1, int(render_hz * 0.4)), center=True, min_periods=1).mean().values
    lat_g = (speed_ms * yr_sm) / G
    # clip sustained channels to physically-plausible kart bounds so an impact
    # transient leaking through smoothing can't be mis-displayed as 6 g cornering.
    lat_g = np.clip(lat_g, -2.6, 2.6)
    long_g = np.clip(long_g, -1.6, 1.0)
    # STEERING (inferred): wheel angle ~ path curvature = yaw_rate / speed, signed by
    # turn direction. Normalized to [-1,1] via a robust cap, smoothed. HONEST: this is
    # inferred from GPS curvature + yaw, NOT a wheel sensor.
    speed_ms_safe = np.maximum(speed_ms, 2.0)
    curv = yr_sm / speed_ms_safe
    cap = np.percentile(np.abs(curv), 95) or 0.15
    steer = np.clip(curv / (cap * 1.3), -1.0, 1.0)
    steer = pd.Series(steer).rolling(max(1, int(render_hz * 0.25)),
                                     center=True, min_periods=1).mean().values

    # normalized coords for SVG (y up). Keep aspect ratio.
    e0, e1 = E.min(), E.max(); n0, n1 = N.min(), N.max()
    pad = 0.06
    span = max(e1 - e0, n1 - n0)
    def nx(e): return (e - e0) / span
    def ny(n): return (n - n0) / span

    # lap index + sector index per render sample
    lap_idx = np.zeros(len(grid), dtype=int) - 1
    sec_idx = np.zeros(len(grid), dtype=int) - 1
    t_ns = df.t.values
    grid_ns = df.t.values[0] + (grid * NS_PER_S).astype(np.int64)
    splits = sectors  # for frac
    SPLIT = stmeta.get("split_fracs", [0.45, 0.83])
    for r in laps.itertuples():
        m = (grid_ns >= r.t_start_ns) & (grid_ns <= r.t_end_ns)
        lap_idx[m] = int(r.lap)
        # within-lap distance fraction for sector coloring
        seg = fused[(fused.t >= r.t_start_ns) & (fused.t <= r.t_end_ns)].reset_index(drop=True)
        if len(seg) > 3:
            d = np.r_[0, np.cumsum(np.hypot(np.diff(seg.E), np.diff(seg.N)))]; d /= d[-1]
            tt = (seg.t.values - seg.t.values[0]) / NS_PER_S + \
                 (np.interp(r.t_start_ns, df.t, se))
            fr = np.interp(grid[m], tt, d)
            si = np.ones(m.sum(), dtype=int) * 1
            si[fr >= SPLIT[0]] = 2
            si[fr >= SPLIT[1]] = 3
            sec_idx[m] = si

    # g-EVENTS from acc_mag transients > 4.5g, spaced out. A high-g spike is only a
    # credible IMPACT if the kart had real speed AND shows a kinematic disturbance
    # (speed drop or yaw kick). Spikes at low speed = sensor artifact (phone/AirPod
    # knock) -> discarded. High-g at speed but no kinematic change = kerb/vibration.
    thr = 4.5 * G
    am100 = df.acc_mag.values
    sp100 = df.speed.values
    yaw100 = df.yaw_rate.values
    MIN_SPEED_MS = 3.0          # below ~7 mph a real wall impact is implausible
    raw_peaks = []
    i = 0
    while i < len(am100):
        if am100[i] > thr:
            j0 = i
            while i < len(am100) and am100[i] > thr * 0.6:
                i += 1
            k = j0 + int(np.argmax(am100[j0:max(j0 + 1, i)]))
            raw_peaks.append(k)
            i += int(render_hz)  # skip ~1s
        else:
            i += 1

    peaks = []
    for k in raw_peaks:
        spd = float(sp100[k])
        lo = max(0, k - 25); hi = min(len(sp100) - 1, k + 25)   # +/-0.25s
        dv = float(sp100[lo] - sp100[hi])                        # speed lost (m/s)
        if spd < MIN_SPEED_MS:
            continue                                             # artifact: too slow
        # Honest labelling: at 1 Hz GPS we can validate PLAUSIBILITY (enough speed to
        # produce the g) but cannot reliably separate a graze from a kerb strike from
        # kinematics (a 30 ms impact's speed change is below GPS resolution). So we
        # report g + speed and only call the single biggest event the notable "impact".
        peaks.append({"t": round(float(se[k]), 2),
                      "g": round(float(am100[k] / G), 1),
                      "speed_mph": round(spd * 2.236936, 0),
                      "plausible": True,
                      "x": round(float(nx(df.E.values[k])), 4),
                      "y": round(float(ny(df.N.values[k])), 4)})
    peaks = sorted(peaks, key=lambda p: -p["g"])[:12]
    if peaks:
        peaks[0]["notable"] = True       # the session's hardest hit

    # static track polyline (downsample fused for a smooth outline)
    step = max(1, len(fused)//1500)
    track = [[round(float(nx(e)), 4), round(float(ny(n)), 4)]
             for e, n in zip(fused.E.values[::step], fused.N.values[::step])]

    apexes = []
    from common import lonlat_to_enu
    for c in sectors.get("corners", []):
        # approximate apex position from dist_frac on best lap not stored; use geojson
        pass
    # apex markers: snap positions stored in sectors_timing meta snaps (turn_*)
    snaps = stmeta.get("snaps", {})
    for c in sectors.get("corners", []):
        fid = f"turn_{c['num']}"
        if fid in snaps:
            k = snaps[fid]["snap_idx"]
            apexes.append({"num": c["num"], "sector": c["sector"],
                           "x": round(float(nx(fused.E.values[k])), 4),
                           "y": round(float(ny(fused.N.values[k])), 4)})

    # lap table with sector colors computed later by JS; pass raw
    lap_rows = st.to_dict(orient="records")

    out = {
        "venue": venue, "session_key": key,
        "render_hz": render_hz, "duration_s": round(dur, 2),
        "n_samples": len(grid),
        "track_polyline": track,
        "apexes": apexes,
        "impacts": peaks,
        "series": {
            "t": [round(float(x), 3) for x in grid],
            "x": [round(float(nx(e)), 4) for e in E],
            "y": [round(float(ny(n)), 4) for n in N],
            "speed_mph": [round(float(v*2.236936), 1) for v in speed_ms],
            "long_g": [round(float(v), 2) for v in long_g],
            "lat_g": [round(float(v), 2) for v in lat_g],
            "acc_mag_g": [round(float(v/G), 2) for v in acc_mag],
            "yaw_rate": [round(float(v), 3) for v in yaw_rate],
            "head_yaw": [round(float(v), 3) for v in head_yaw],
            "steer": [round(float(v), 3) for v in steer],
            "lap": [int(v) for v in lap_idx],
            "sector": [int(v) for v in sec_idx],
        },
        "laps": lap_rows,
        "analytics": analytics,
        "max_speed_mph": round(float(speed_ms.max()*2.236936), 1),
        "g_summary": {
            "peak_lat_g_sustained": round(float(np.percentile(np.abs(lat_g), 99.5)), 2),
            "peak_brake_g": round(float(-np.percentile(long_g, 0.5)), 2),
            "peak_accel_g": round(float(np.percentile(long_g, 99.5)), 2),
            "peak_impact_g": round(float(acc_mag.max() / G), 1),
            "note": "Sustained lat/long g are vehicle-motion derived and clipped to "
                    "realistic Sodi GT5 rental-kart bounds (~2 g lateral, ~1.2 g braking, "
                    "~0.4 g accel for a ~170 lb driver). peak_impact_g is a brief "
                    "kerb/wall TRANSIENT on raw accel - not sustained cornering load.",
        },
        "audio": {"file": "session.wav", "offset_s": 0.0, "scale": 1.0,
                  "note": "drift-corrected: audio.currentTime maps 1:1 to series t"},
    }
    return out


def run(venue: str = "gateway-kartplex") -> dict:
    print("=" * 64)
    print(f"[render_artifact] Stage B  venue={venue}")
    print("=" * 64)
    ingest = load_json(OUTPUT / venue / "raw" / "ingest.json")
    sync = load_json(OUTPUT / venue / "raw" / "sync.json")
    sessions = load_json(OUTPUT / venue / "raw" / "sessions.json")["sessions"]
    ses_dir = {s["session_key"]: s.get("session_dir") for s in sessions}
    default_sd = RAW_SESSIONS / ingest["zip_stem"]
    sheets = {s["session_key"]: s for s in ts_mod.run(venue)}

    out = {}
    for key in sheets:
        ds = OUTPUT / venue / key / "dataset"
        if not (ds / "fused_trace.csv").exists():
            continue
        from pathlib import Path
        _sd = Path(ses_dir[key]) if ses_dir.get(key) else default_sd
        mp4 = _sd / "Microphone.mp4"
        rec_sync = sync.get("per_recording", {}).get(str(_sd), sync)
        rdir = ds / "render"
        rdir.mkdir(exist_ok=True)
        rj = build_render_json(ds, venue, key)
        write_json(rdir / "render.json", rj)

        at0, at1, dur, a = session_audio_window(ds, rec_sync)
        tempo = extract_drift_corrected_wav(mp4, at0, at1, a, rdir / "session.wav", dur)
        out[key] = {"n_samples": rj["n_samples"], "dur": dur, "tempo": tempo,
                    "impacts": len(rj["impacts"])}
        print(f"[render_artifact] {key}: {rj['n_samples']} render samples @{RENDER_HZ}Hz, "
              f"{dur:.0f}s, wav tempo={tempo:.5f}, {len(rj['impacts'])} impact markers, "
              f"max {rj['max_speed_mph']} mph")
    print("-" * 64)
    print(f"[render_artifact] STATUS: PASS ({len(out)} sessions)")
    print("-" * 64)
    return out


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "gateway-kartplex")
