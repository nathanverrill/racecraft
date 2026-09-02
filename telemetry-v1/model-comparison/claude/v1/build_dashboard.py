#!/usr/bin/env python3
"""
build_dashboard.py  --  Kart telemetry -> F1-style audio-synced dashboard
==========================================================================

Reads a Sensor Logger (https://github.com/tszheichoi/awesome-sensor-logger)
export folder (the unzipped CSVs + Microphone.mp4) and produces a single,
self-contained `dashboard.html` whose readouts are driven by the engine
audio playback.

What it does
------------
1. Loads the per-sensor CSVs (each has its own rate / timestamps).
2. Aligns everything on the shared UNIX-epoch `time` column (nanoseconds),
   anchored to when the microphone (engine audio) started.
3. Fuses GPS position + velocity with the IMU using a constant-velocity
   Kalman filter followed by an RTS (forward-backward) smoother, with the
   process noise modulated by the phone's dynamic acceleration so the racing
   line stays tight on straights and responsive through corners. This is the
   "smoothed position using IMU + GPS for error correction" step.
4. Derives speed, heading, longitudinal/lateral g, bank angle, distance,
   elevation, GPS quality, engine loudness (dBFS) and best-effort lap splits.
5. Resamples to a uniform grid and writes them, embedded, into the dashboard.

Usage
-----
    python build_dashboard.py                 # run inside the session folder
    python build_dashboard.py /path/to/folder
    python build_dashboard.py /path/to/folder --hz 30 --out dashboard.html

Only needs: numpy, pandas  (pip install numpy pandas)
"""

import argparse
import base64
import glob
import json
import math
import os
import sys

import numpy as np
import pandas as pd

G = 9.80665  # m/s^2


# --------------------------------------------------------------------------- #
#  CSV loading helpers
# --------------------------------------------------------------------------- #
def _find(folder, *names):
    """Case-insensitive lookup of the first existing file among `names`."""
    listing = {f.lower(): f for f in os.listdir(folder)}
    for n in names:
        hit = listing.get(n.lower())
        if hit:
            return os.path.join(folder, hit)
    return None


def _read_csv(path):
    if path is None or not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path)
    except Exception as e:
        print(f"  ! could not read {os.path.basename(path)}: {e}")
        return None
    if "time" in df.columns:
        df["time"] = pd.to_numeric(df["time"], errors="coerce")
        df = df.dropna(subset=["time"]).sort_values("time")
        # drop duplicate / non-increasing timestamps (caching artefacts)
        df = df[df["time"].diff().fillna(1) > 0]
    return df.reset_index(drop=True)


def _col(df, *names):
    """Return the first matching column as float ndarray, or None."""
    if df is None:
        return None
    for n in names:
        for c in df.columns:
            if c.lower() == n.lower():
                return pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=float)
    return None


# --------------------------------------------------------------------------- #
#  Small signal utilities
# --------------------------------------------------------------------------- #
def gaussian_smooth(y, sigma):
    """1-D Gaussian smoothing, NaN-safe, edge-preserving."""
    y = np.asarray(y, dtype=float)
    if sigma <= 0 or y.size < 3:
        return y
    radius = max(1, int(round(sigma * 3)))
    k = np.exp(-0.5 * (np.arange(-radius, radius + 1) / sigma) ** 2)
    k /= k.sum()
    good = np.isfinite(y).astype(float)
    yy = np.where(np.isfinite(y), y, 0.0)
    num = np.convolve(yy, k, mode="same")
    den = np.convolve(good, k, mode="same")
    out = np.where(den > 1e-9, num / den, np.nan)
    return out


def interp_to_grid(t_src, y_src, t_grid):
    """Linear interpolation onto the grid with finite-value guarding + hold."""
    if t_src is None or y_src is None:
        return None
    m = np.isfinite(t_src) & np.isfinite(y_src)
    if m.sum() < 2:
        return None
    return np.interp(t_grid, t_src[m], y_src[m])


# --------------------------------------------------------------------------- #
#  Kalman filter + RTS smoother  (constant-velocity, IMU-modulated noise)
# --------------------------------------------------------------------------- #
def fuse_position(t_grid, gps, accel_dyn):
    """
    State = [E, N, vE, vN]. Predicts at the grid rate; corrects with GPS
    position (R from horizontalAccuracy) and GPS velocity (from speed+bearing,
    R from speedAccuracy). `accel_dyn` (per-grid dynamic accel magnitude from
    the IMU) scales the process noise so corners are tracked more eagerly.
    Returns smoothed E, N, vE, vN arrays on the grid.
    """
    n = len(t_grid)
    dt = float(np.median(np.diff(t_grid)))
    F = np.array([[1, 0, dt, 0],
                  [0, 1, 0, dt],
                  [0, 0, 1, 0],
                  [0, 0, 0, 1]], dtype=float)

    # Constant-velocity process-noise template (acceleration drives velocity)
    q1 = np.array([[dt**4 / 4, dt**3 / 2],
                   [dt**3 / 2, dt**2]], dtype=float)

    def Qmat(accel_psd):
        Q = np.zeros((4, 4))
        Q[np.ix_([0, 2], [0, 2])] = q1 * accel_psd
        Q[np.ix_([1, 3], [1, 3])] = q1 * accel_psd
        return Q

    # map each GPS sample to the nearest grid step it should update on
    gps_t = gps["t"]
    gps_by_step = {}
    for i, gt in enumerate(gps_t):
        if gt < t_grid[0] - dt or gt > t_grid[-1] + dt:
            continue
        step = int(np.clip(round((gt - t_grid[0]) / dt), 0, n - 1))
        gps_by_step.setdefault(step, []).append(i)

    # initial state from first GPS fix
    x = np.array([gps["E"][0], gps["N"][0], 0.0, 0.0])
    P = np.diag([50.0, 50.0, 25.0, 25.0])

    base_psd = 1.5            # baseline accel spectral density (m^2/s^3-ish)
    accel_gain = 4.0          # how much IMU dynamics open up the model

    xs_pred = np.zeros((n, 4)); Ps_pred = np.zeros((n, 4, 4))
    xs_upd = np.zeros((n, 4));  Ps_upd = np.zeros((n, 4, 4))

    for k in range(n):
        # ---- predict ----
        a = accel_dyn[k] if (accel_dyn is not None and np.isfinite(accel_dyn[k])) else 0.0
        psd = base_psd * (1.0 + accel_gain * min(a / G, 2.0))
        x = F @ x
        P = F @ P @ F.T + Qmat(psd)
        xs_pred[k] = x; Ps_pred[k] = P

        # ---- update with any GPS sample on this step ----
        for gi in gps_by_step.get(k, []):
            # position update
            zp = np.array([gps["E"][gi], gps["N"][gi]])
            Hp = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=float)
            sp = float(np.clip(gps["hacc"][gi] if np.isfinite(gps["hacc"][gi]) else 12.0, 2.0, 60.0))
            Rp = np.diag([sp**2, sp**2])
            yk = zp - Hp @ x
            S = Hp @ P @ Hp.T + Rp
            Kk = P @ Hp.T @ np.linalg.inv(S)
            x = x + Kk @ yk
            P = (np.eye(4) - Kk @ Hp) @ P

            # velocity update (only when a trustworthy GPS velocity exists)
            ve, vn, vok = gps["vE"][gi], gps["vN"][gi], gps["vok"][gi]
            if vok:
                zv = np.array([ve, vn])
                Hv = np.array([[0, 0, 1, 0], [0, 0, 0, 1]], dtype=float)
                sv = float(np.clip(gps["sacc"][gi] if np.isfinite(gps["sacc"][gi]) else 1.5, 0.3, 6.0))
                Rv = np.diag([sv**2, sv**2])
                yk = zv - Hv @ x
                S = Hv @ P @ Hv.T + Rv
                Kk = P @ Hv.T @ np.linalg.inv(S)
                x = x + Kk @ yk
                P = (np.eye(4) - Kk @ Hv) @ P

        xs_upd[k] = x; Ps_upd[k] = P

    # ---- RTS backward smoother ----
    xs = xs_upd.copy()
    for k in range(n - 2, -1, -1):
        C = Ps_upd[k] @ F.T @ np.linalg.inv(Ps_pred[k + 1])
        xs[k] = xs_upd[k] + C @ (xs[k + 1] - xs_pred[k + 1])

    return xs[:, 0], xs[:, 1], xs[:, 2], xs[:, 3]


# --------------------------------------------------------------------------- #
#  Lap detection (best effort)
# --------------------------------------------------------------------------- #
def detect_laps(t, E, N, speed):
    moving = speed > 2.0
    if moving.sum() < 30:
        return []
    start_i = int(np.argmax(moving))          # first moving sample
    sx, sy = E[start_i], N[start_i]
    dist_to_start = np.hypot(E - sx, N - sy)

    R_IN, R_OUT = 18.0, 55.0
    laps, lap_start = [], t[start_i]
    armed = False
    for i in range(start_i + 1, len(t)):
        if dist_to_start[i] > R_OUT:
            armed = True
        if armed and dist_to_start[i] < R_IN:
            lt = t[i] - lap_start
            if lt > 8.0:                       # ignore implausibly short laps
                laps.append({"start": round(float(lap_start), 2),
                             "end": round(float(t[i]), 2),
                             "time": round(float(lt), 3)})
                lap_start = t[i]
                armed = False
    return laps if len(laps) >= 1 else []


# --------------------------------------------------------------------------- #
#  Main processing
# --------------------------------------------------------------------------- #
def process(folder, out_hz):
    print(f"Reading session: {folder}")

    loc = _read_csv(_find(folder, "Location.csv"))
    acc = _read_csv(_find(folder, "Accelerometer.csv", "AccelerometerUncalibrated.csv"))
    grav = _read_csv(_find(folder, "Gravity.csv"))
    baro = _read_csv(_find(folder, "Barometer.csv"))
    mic = _read_csv(_find(folder, "Microphone.csv"))
    meta = _read_csv(_find(folder, "Metadata.csv"))

    if loc is None or len(loc) < 5:
        sys.exit("ERROR: Location.csv missing or too short - GPS is required for the track map.")

    # ---- clock anchor: when the engine audio (microphone) started ----
    if mic is not None and "time" in mic.columns and len(mic):
        audio_t0 = float(mic["time"].min())
        anchor = "microphone start"
    else:
        audio_t0 = float(loc["time"].min())
        anchor = "first GPS fix (no microphone CSV found)"
    print(f"  audio anchor: {anchor}")

    def rel(df):  # seconds relative to audio start
        return ((df["time"].to_numpy(dtype=float) - audio_t0) / 1e9) if df is not None else None

    # ---- GPS -> local ENU metres ----
    lat = _col(loc, "latitude"); lon = _col(loc, "longitude")
    good = np.isfinite(lat) & np.isfinite(lon) & ~((lat == 0) & (lon == 0))
    if good.sum() < 5:
        sys.exit("ERROR: not enough valid GPS fixes (lat/lon all zero?).")
    lat, lon = lat[good], lon[good]
    lat0, lon0 = float(np.median(lat)), float(np.median(lon))
    m_lat = 111320.0
    m_lon = 111320.0 * math.cos(math.radians(lat0))
    E = (lon - lon0) * m_lon
    N = (lat - lat0) * m_lat

    gt = rel(loc)[good]
    gspeed = _col(loc, "speed"); gspeed = gspeed[good] if gspeed is not None else None
    gbear = _col(loc, "bearing"); gbear = gbear[good] if gbear is not None else None
    hacc = _col(loc, "horizontalAccuracy"); hacc = hacc[good] if hacc is not None else np.full(good.sum(), 12.0)
    sacc = _col(loc, "speedAccuracy"); sacc = sacc[good] if sacc is not None else np.full(good.sum(), 1.5)
    galt = _col(loc, "altitude"); galt = galt[good] if galt is not None else None

    # GPS velocity vector from speed + bearing (bearing: deg clockwise from N)
    if gspeed is not None and gbear is not None:
        br = np.radians(gbear)
        vE = gspeed * np.sin(br)
        vN = gspeed * np.cos(br)
        vok = np.isfinite(vE) & np.isfinite(vN) & (gspeed >= 0)
    else:
        vE = np.zeros_like(E); vN = np.zeros_like(E); vok = np.zeros(len(E), bool)

    gps = {"t": gt, "E": E, "N": N, "vE": vE, "vN": vN, "vok": vok,
           "hacc": hacc, "sacc": sacc}

    # ---- uniform output grid (audio time, starts at 0) ----
    t_end = float(gt.max())
    dt = 1.0 / out_hz
    t_grid = np.arange(0.0, t_end + dt, dt)
    n = len(t_grid)
    print(f"  GPS fixes: {len(E)} | session: {t_end:.1f}s | grid: {n} @ {out_hz}Hz")

    # ---- IMU dynamic acceleration magnitude (mounting-invariant) ----
    accel_dyn = None
    vibration = None
    if acc is not None:
        at = rel(acc)
        ax = _col(acc, "x"); ay = _col(acc, "y"); az = _col(acc, "z")
        if ax is not None and ay is not None and az is not None:
            axg = interp_to_grid(at, ax, t_grid)
            ayg = interp_to_grid(at, ay, t_grid)
            azg = interp_to_grid(at, az, t_grid)
            if axg is not None:
                # remove low-frequency component (gravity / orientation bias)
                lp = max(1, int(round(out_hz * 1.0)))   # ~1 s window
                def hp(v):
                    base = gaussian_smooth(v, lp / 3.0)
                    return v - base
                dyn = np.sqrt(hp(axg) ** 2 + hp(ayg) ** 2 + hp(azg) ** 2)
                accel_dyn = gaussian_smooth(dyn, out_hz * 0.15)
                # engine vibration proxy: short-window energy of the dynamic accel
                w = max(3, int(round(out_hz * 0.25)))
                pad = np.pad(dyn, (w, w), mode="edge")
                vib = np.array([pad[i:i + 2 * w + 1].std() for i in range(n)])
                vibration = gaussian_smooth(vib, out_hz * 0.2)

    # ---- sensor fusion: smoothed position + velocity ----
    print("  fusing GPS + IMU (Kalman + RTS smoother)...")
    Ef, Nf, vEf, vNf = fuse_position(t_grid, gps, accel_dyn)

    # ---- derived channels (from the smooth trajectory: mounting-invariant) ---
    Ef = gaussian_smooth(Ef, out_hz * 0.12)
    Nf = gaussian_smooth(Nf, out_hz * 0.12)
    speed = np.hypot(vEf, vNf)                      # m/s
    speed = gaussian_smooth(speed, out_hz * 0.25)
    speed = np.clip(speed, 0, None)

    # heading from velocity where moving, else hold
    heading = np.degrees(np.arctan2(vEf, vNf)) % 360.0
    slow = speed < 1.2
    hd = heading.copy()
    last = hd[~slow][0] if (~slow).any() else 0.0
    for i in range(n):
        if slow[i]:
            hd[i] = last
        else:
            last = hd[i]
    heading = hd

    # longitudinal g = d(speed)/dt
    a_long = np.gradient(speed, t_grid)
    g_lon = gaussian_smooth(a_long, out_hz * 0.3) / G

    # lateral g = speed * yaw_rate (unwrapped heading derivative)
    psi = np.unwrap(np.radians(heading))
    yaw_rate = np.gradient(psi, t_grid)
    a_lat = speed * yaw_rate
    g_lat = gaussian_smooth(a_lat, out_hz * 0.3) / G
    g_lat = np.clip(g_lat, -3.5, 3.5)
    g_lon = np.clip(g_lon, -3.5, 3.5)

    bank = np.degrees(np.arctan2(a_lat, G))         # artificial-horizon tilt
    bank = np.clip(gaussian_smooth(bank, out_hz * 0.3), -45, 45)

    # distance travelled
    dist = np.concatenate([[0.0], np.cumsum(speed[1:] * np.diff(t_grid))])

    # elevation: barometer preferred, else GPS altitude
    elevation = None
    if baro is not None:
        bt = rel(baro)
        rel_alt = _col(baro, "relativeAltitude")
        if rel_alt is not None:
            elevation = interp_to_grid(bt, rel_alt, t_grid)
    if elevation is None and galt is not None:
        elevation = interp_to_grid(gt, galt, t_grid)
    if elevation is not None:
        elevation = gaussian_smooth(elevation, out_hz * 0.5)
        elevation = elevation - np.nanmin(elevation)

    # GPS quality (horizontal accuracy, metres)
    gps_acc = interp_to_grid(gt, hacc, t_grid)

    # engine loudness (dBFS) from Microphone.csv
    loudness = None
    if mic is not None:
        mt = rel(mic)
        for cand in ("dBFS", "dbfs", "loudness", "value"):
            v = _col(mic, cand)
            if v is not None:
                loudness = interp_to_grid(mt, v, t_grid)
                break
        if loudness is None:  # fall back to first non-time numeric column
            for c in mic.columns:
                if c.lower() in ("time", "seconds_elapsed"):
                    continue
                v = pd.to_numeric(mic[c], errors="coerce").to_numpy(float)
                if np.isfinite(v).any():
                    loudness = interp_to_grid(mt, v, t_grid)
                    break

    # ---- laps ----
    laps = detect_laps(t_grid, Ef, Nf, speed)
    print(f"  laps detected: {len(laps)}")

    # ---- assemble payload ----
    def r(arr, nd):
        if arr is None:
            return None
        a = np.where(np.isfinite(arr), arr, 0.0)
        return [round(float(v), nd) for v in a]

    speed_kmh = speed * 3.6
    session_name = os.path.basename(os.path.realpath(folder))
    dev = None
    if meta is not None:
        for c in meta.columns:
            if "device" in c.lower():
                try:
                    dev = str(meta[c].dropna().iloc[0])
                except Exception:
                    pass

    payload = {
        "meta": {
            "name": session_name,
            "device": dev,
            "duration": round(t_end, 2),
            "hz": out_hz,
            "n": n,
            "audioEpochNs": audio_t0,
            "lat0": lat0, "lon0": lon0,
            "bounds": {
                "minX": float(np.min(Ef)), "maxX": float(np.max(Ef)),
                "minY": float(np.min(Nf)), "maxY": float(np.max(Nf)),
            },
            "maxSpeed": round(float(np.max(speed_kmh)), 1),
            "maxLatG": round(float(np.max(np.abs(g_lat))), 2),
            "maxLonAccel": round(float(np.max(g_lon)), 2),
            "maxBrake": round(float(np.min(g_lon)), 2),
            "totalDist": round(float(dist[-1]), 1),
            "hasLoudness": loudness is not None,
            "hasElevation": elevation is not None,
            "hasVibration": vibration is not None,
            "laps": laps,
        },
        "t": r(t_grid, 3),
        "x": r(Ef, 2), "y": r(Nf, 2),
        "speed": r(speed_kmh, 2),
        "gLat": r(g_lat, 3), "gLon": r(g_lon, 3),
        "heading": r(heading, 1),
        "bank": r(bank, 2),
        "dist": r(dist, 1),
        "elev": r(elevation, 2) if elevation is not None else None,
        "gpsAcc": r(gps_acc, 1),
        "loud": r(loudness, 1) if loudness is not None else None,
        "vib": r(vibration, 4) if vibration is not None else None,
    }
    return payload


# --------------------------------------------------------------------------- #
#  HTML assembly
# --------------------------------------------------------------------------- #
def build_html(payload, template_path, audio_src, embed_audio_path=None):
    with open(template_path, "r", encoding="utf-8") as f:
        tpl = f.read()
    data_js = json.dumps(payload, separators=(",", ":"))
    html = tpl.replace("/*__TELEMETRY__*/null", data_js)
    if embed_audio_path and os.path.exists(embed_audio_path):
        ext = os.path.splitext(embed_audio_path)[1].lower().lstrip(".")
        mime = {"mp4": "audio/mp4", "m4a": "audio/mp4", "caf": "audio/x-caf",
                "3gp": "audio/3gpp", "wav": "audio/wav", "mp3": "audio/mpeg"}.get(ext, "audio/mp4")
        with open(embed_audio_path, "rb") as af:
            b64 = base64.b64encode(af.read()).decode("ascii")
        html = html.replace("__AUDIO_SRC__", f"data:{mime};base64,{b64}")
    else:
        html = html.replace("__AUDIO_SRC__", audio_src)
    return html


def main():
    ap = argparse.ArgumentParser(description="Build an audio-synced kart telemetry dashboard from Sensor Logger data.")
    ap.add_argument("folder", nargs="?", default=".", help="Session folder (default: current dir)")
    ap.add_argument("--hz", type=int, default=30, help="Output sample rate (default 30)")
    ap.add_argument("--out", default="dashboard.html", help="Output HTML filename")
    ap.add_argument("--audio", default=None, help="Audio filename to reference (default: auto-detect Microphone.mp4)")
    ap.add_argument("--template", default=None, help="Path to dashboard_template.html")
    ap.add_argument("--json", action="store_true", help="Also write telemetry.json")
    ap.add_argument("--embed-audio", action="store_true",
                    help="Inline the engine audio into the HTML as a data URI (fully self-contained, plays on file:// double-click)")
    args = ap.parse_args()

    folder = os.path.realpath(args.folder)
    template = args.template or os.path.join(os.path.dirname(os.path.realpath(__file__)), "dashboard_template.html")
    if not os.path.exists(template):
        sys.exit(f"ERROR: template not found at {template}")

    audio = args.audio
    if audio is None:
        hit = _find(folder, "Microphone.mp4", "Microphone.m4a", "Microphone.caf", "Microphone.3gp")
        audio = os.path.basename(hit) if hit else "Microphone.mp4"

    payload = process(folder, args.hz)

    if args.json:
        jp = os.path.join(folder, "telemetry.json")
        with open(jp, "w") as f:
            json.dump(payload, f, separators=(",", ":"))
        print(f"  wrote {jp}")

    embed_path = None
    if args.embed_audio:
        hit = _find(folder, audio, "Microphone.mp4", "Microphone.m4a", "Microphone.caf", "Microphone.3gp")
        if hit:
            embed_path = hit
            print(f"  embedding audio: {os.path.basename(hit)} ({os.path.getsize(hit)/1e6:.1f} MB)")
        else:
            print("  --embed-audio requested but no audio file found; referencing by name instead")

    html = build_html(payload, template, audio, embed_audio_path=embed_path)
    out_path = os.path.join(folder, args.out)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    size_mb = os.path.getsize(out_path) / 1e6
    print(f"\nDone -> {out_path}  ({size_mb:.2f} MB)")
    print(f"Audio referenced: {audio}")
    print("Open dashboard.html in your browser (Chrome/Safari/Firefox).")
    print("If the audio doesn't load from file://, use the 'Load engine audio' button in the player.")


if __name__ == "__main__":
    main()
