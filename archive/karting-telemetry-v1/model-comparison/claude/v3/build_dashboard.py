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
            # position update (skip rejected fixes; gate huge innovations)
            if gps["pos_ok"][gi]:
                zp = np.array([gps["E"][gi], gps["N"][gi]])
                Hp = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=float)
                sp = float(np.clip(gps["hacc"][gi] if np.isfinite(gps["hacc"][gi]) else 12.0, 2.0, 60.0))
                Rp = np.diag([sp**2, sp**2])
                yk = zp - Hp @ x
                S = Hp @ P @ Hp.T + Rp
                maha = float(yk @ np.linalg.inv(S) @ yk)   # innovation gate
                if maha < 80.0:
                    Kk = P @ Hp.T @ np.linalg.inv(S)
                    x = x + Kk @ yk
                    P = (np.eye(4) - Kk @ Hp) @ P

            # velocity update (only when a trustworthy GPS velocity exists)
            ve, vn, vok = gps["vE"][gi], gps["vN"][gi], gps["vok"][gi]
            if vok and gps["pos_ok"][gi]:
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
def detect_laps(t, E, N, speed, ontrack=None, start=None):
    moving = speed > 2.0
    if ontrack is not None:
        moving = moving & ontrack
    if moving.sum() < 30:
        return []
    if start is not None:
        sx, sy = float(start[0]), float(start[1])
    else:
        start_i = int(np.argmax(moving))
        sx, sy = E[start_i], N[start_i]
    dist_to_start = np.hypot(E - sx, N - sy)
    first_i = int(np.argmax(moving))

    R_IN, R_OUT = 18.0, 55.0
    laps, lap_start = [], t[first_i]
    armed = False
    for i in range(first_i + 1, len(t)):
        if ontrack is not None and not ontrack[i]:
            continue
        if dist_to_start[i] > R_OUT:
            armed = True
        if armed and dist_to_start[i] < R_IN:
            lt = t[i] - lap_start
            if lt > 8.0:
                laps.append({"start": round(float(lap_start), 2),
                             "end": round(float(t[i]), 2),
                             "time": round(float(lt), 3)})
                lap_start = t[i]
                armed = False
    return laps if len(laps) >= 1 else []


# --------------------------------------------------------------------------- #
#  Track silhouette extraction (F1-style single outline + position projection)
# --------------------------------------------------------------------------- #
def _resample_path(xy, m):
    """Resample an (k,2) path to m points evenly by arc length."""
    d = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(xy[:, 0]), np.diff(xy[:, 1])))])
    if d[-1] <= 0:
        return np.repeat(xy[:1], m, axis=0)
    u = np.linspace(0, d[-1], m, endpoint=False)
    return np.column_stack([np.interp(u, d, xy[:, 0]), np.interp(u, d, xy[:, 1])])


def _smooth_closed(xy, sigma):
    """Periodic Gaussian smoothing of a closed polyline."""
    m = len(xy)
    if sigma <= 0 or m < 5:
        return xy
    r = max(1, int(round(sigma * 3)))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2); k /= k.sum()
    out = np.empty_like(xy)
    for j in range(xy.shape[1]):
        ext = np.concatenate([xy[-r:, j], xy[:, j], xy[:r, j]])
        out[:, j] = np.convolve(ext, k, mode="same")[r:r + m]
    return out


def _seg_cross(p1, p2, A, B):
    d1x, d1y = p2[0] - p1[0], p2[1] - p1[1]
    abx, aby = B[0] - A[0], B[1] - A[1]
    denom = d1x * aby - d1y * abx
    if abs(denom) < 1e-12:
        return None
    dpx, dpy = A[0] - p1[0], A[1] - p1[1]
    tt = (dpx * aby - dpy * abx) / denom
    uu = (dpx * d1y - dpy * d1x) / denom
    if 0.0 <= tt <= 1.0 and 0.0 <= uu <= 1.0:
        return 1 if (d1x * aby - d1y * abx) > 0 else -1
    return None


def _line_cross_idx(t, x, y, idx, A, B):
    """Return [(grid_index_after_crossing, dir_sign)] for the path (over idx)
    crossing the extended start/finish line A->B."""
    mx, my = (A[0] + B[0]) / 2, (A[1] + B[1]) / 2
    Ae = (mx + (A[0] - mx) * 1.6, my + (A[1] - my) * 1.6)
    Be = (mx + (B[0] - mx) * 1.6, my + (B[1] - my) * 1.6)
    out = []
    for k in range(len(idx) - 1):
        i, j = idx[k], idx[k + 1]
        if j - i > 1 and (t[j] - t[i]) > 3.0:      # skip across big time gaps
            continue
        s = _seg_cross((x[i], y[i]), (x[j], y[j]), Ae, Be)
        if s is not None:
            out.append((j, s))
    return out


def _lap_period(t, x, y, tmin=20.0, tmax=80.0):
    """Lap time = period at which position repeats. Works on concave/twisty
    layouts where winding-around-centre fails. Returns seconds or None."""
    if len(t) < 5 or (t[-1] - t[0]) < tmin * 1.5:
        return None
    dt = 0.5
    g = np.arange(t[0], t[-1], dt)
    px = np.interp(g, t, x); py = np.interp(g, t, y)
    Lmin = int(tmin / dt); Lmax = min(int(tmax / dt), len(g) - 5)
    if Lmax <= Lmin + 2:
        return None
    lags = np.arange(Lmin, Lmax)
    D = np.array([np.hypot(px[L:] - px[:-L], py[L:] - py[:-L]).mean() for L in lags])
    gmin = D.min()
    for i in range(1, len(D) - 1):
        if D[i] <= D[i - 1] and D[i] <= D[i + 1] and D[i] <= 1.10 * gmin:
            return float(lags[i] * dt)
    return float(lags[int(np.argmin(D))] * dt)


def _lap_segments(t, E, N, speed, idx, anchor=None, sf_line=None):
    """Split the driving indices `idx` into per-lap (start,end) grid-index spans.
    Prefers crossings of the real start/finish line; else returns past a fixed
    reference point (anchor) or the fastest point. Returns (segments, period)."""
    if len(idx) < 20:
        return [], None
    td, xd, yd, vd = t[idx], E[idx], N[idx], speed[idx]
    T = _lap_period(td, xd, yd)
    if T is None:
        return [], None
    # 1) real start/finish line crossings (most accurate)
    if sf_line is not None:
        cr = _line_cross_idx(t, E, N, idx, sf_line[0], sf_line[1])
        if len(cr) >= 3:
            cidx = sorted(j for j, s in cr)
            # collapse wobble (crossings within 4 s -> one pass)
            cen = [cidx[0]]
            for j in cidx[1:]:
                if t[j] - t[cen[-1]] > 4.0:
                    cen.append(j)
            if len(cen) >= 3:
                gaps = np.diff([t[j] for j in cen]); med = float(np.median(gaps))
                segs = []
                for k in range(len(cen) - 1):
                    if (t[cen[k + 1]] - t[cen[k]]) > 0.5 * med:
                        segs.append((cen[k], cen[k + 1]))
                if len(segs) >= 2:
                    return segs, T
    # 2) returns past a fixed point
    if anchor is not None:
        sx, sy = anchor
    else:
        ai = int(np.argmax(vd)); sx, sy = xd[ai], yd[ai]
    d2s = np.hypot(E - sx, N - sy)
    bbox = float(np.hypot(xd.max() - xd.min(), yd.max() - yd.min()))
    R = max(12.0, 0.10 * bbox)
    dd = d2s[idx]                              # distance to anchor, in time order
    cross = []; last = -1e9
    for k in range(1, len(idx) - 1):
        if dd[k] < R and dd[k] <= dd[k - 1] and dd[k] <= dd[k + 1] and (t[idx[k]] - last) > 0.55 * T:
            cross.append(int(idx[k])); last = t[idx[k]]
    segs = [(cross[k], cross[k + 1]) for k in range(len(cross) - 1)
            if 0.5 * T < (t[cross[k + 1]] - t[cross[k]]) < 2.5 * T]
    if len(segs) >= 2:
        return segs, T
    t0 = t[idx[0]]; n = max(0, int(round((t[idx[-1]] - t0) / T)))
    segs = []
    for k in range(n):
        a = int(np.searchsorted(t, t0 + k * T)); b = int(np.searchsorted(t, t0 + (k + 1) * T))
        if b - a > 5:
            segs.append((a, b))
    return segs, T


def extract_track(t, E, N, speed, n_pts=260, anchor=None, sf_line=None):
    """
    Build a clean closed track silhouette by isolating the repeatedly-driven
    laps, splitting them by full revolutions around the track centre (robust to
    GPS noise and to the start/finish never being re-approached closely), and
    median-averaging the phase-aligned laps. Also returns clean lap splits.

    Returns poly (M,2), polyspeed (M,), start [x,y], dotx/doty (position on the
    silhouette, NaN off-track), ontrack (bool/grid), closed (bool), laps (list).
    """
    nG = len(t)
    dt = (t[1] - t[0]) if nG > 1 else 1.0
    DRIVE_V = 4.0  # m/s (~14 km/h): above walking/idle, so detours drop out
    moving = speed > DRIVE_V

    # rough lap count (shape-agnostic period detection) to size the density gate
    rough_segs, _ = _lap_segments(t, E, N, speed, np.where(moving)[0])
    n_rev = max(1, len(rough_segs))

    # spatial density: keep cells visited on multiple passes (drops one-off detours)
    on_dense = moving.copy()
    if moving.sum() > 50:
        from collections import Counter
        cell = 6.0
        ix = np.floor(E / cell).astype(int); iy = np.floor(N / cell).astype(int)
        cnt = Counter(zip(ix[moving].tolist(), iy[moving].tolist()))
        thr = max(2, int(round(0.35 * n_rev)))
        keep = np.array([cnt[(a, b)] >= thr for a, b in zip(ix.tolist(), iy.tolist())])
        on_dense = moving & keep

    idx = np.where(on_dense)[0]
    segments, _T = _lap_segments(t, E, N, speed, idx, anchor=anchor, sf_line=sf_line)

    # resample each lap span to a common arc-length parameterisation
    lap_paths, lap_speeds, loop_starts = [], [], []
    for (a, b) in segments:
        sel = np.arange(a, b)
        if len(sel) < 20:
            continue
        seg = np.column_stack([E[sel], N[sel]]); sp = speed[sel]
        d = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(seg[:, 0]), np.diff(seg[:, 1])))])
        if d[-1] < 1.0:
            continue
        loop_starts.append(int(a))
        lap_paths.append(_resample_path(seg, n_pts))
        lap_speeds.append(np.interp(np.linspace(0, d[-1], n_pts, endpoint=False), d, sp))

    if lap_paths:
        lens = [np.hypot(np.diff(p[:, 0]), np.diff(p[:, 1])).sum() for p in lap_paths]
        # use the median-length lap as the alignment reference (robust)
        ref = lap_paths[int(np.argsort(lens)[len(lens) // 2])]

        def best_roll(Lp, Rp):
            npn = len(Lp); c = np.zeros(npn)
            for d in range(2):
                FL = np.fft.rfft(Lp[:, d] - Lp[:, d].mean())
                FR = np.fft.rfft(Rp[:, d] - Rp[:, d].mean())
                c += np.fft.irfft(FR * np.conj(FL), npn)
            s = int(np.argmax(c))
            return min([s, s - npn], key=lambda ss: ((np.roll(Lp, ss, axis=0) - Rp) ** 2).sum())

        aligned, aligned_sp = [], []
        for p, sp in zip(lap_paths, lap_speeds):
            s = best_roll(p, ref)
            aligned.append(np.roll(p, s, axis=0)); aligned_sp.append(np.roll(sp, s))
        poly = np.median(np.stack(aligned), axis=0)
        polyspeed = np.median(np.stack(aligned_sp), axis=0)
        poly = _smooth_closed(poly, 2.5)
        polyspeed = _smooth_closed(polyspeed[:, None], 2.5)[:, 0]
        closed = True
    else:
        # fallback: longest contiguous on-track run as an open outline
        if len(idx) > 30:
            runs = np.split(idx, np.where(np.diff(idx) > 1)[0] + 1)
            run = max(runs, key=len)
            poly = _resample_path(np.column_stack([E[run], N[run]]), n_pts)
            polyspeed = np.interp(np.linspace(0, 1, n_pts), np.linspace(0, 1, len(run)), speed[run])
        else:
            poly = np.column_stack([E, N]); polyspeed = speed.copy()
        closed = False

    # project every grid sample onto the silhouette (nearest segment)
    A = poly
    B = np.roll(poly, -1, axis=0) if closed else np.vstack([poly[1:], poly[-1]])
    AB = B - A
    AB2 = (AB ** 2).sum(1) + 1e-9
    bestd = np.full(nG, np.inf); bx = np.full(nG, np.nan); by = np.full(nG, np.nan)
    for j in range(len(A)):
        apx = E - A[j, 0]; apy = N - A[j, 1]
        tt = np.clip((apx * AB[j, 0] + apy * AB[j, 1]) / AB2[j], 0.0, 1.0)
        qx = A[j, 0] + tt * AB[j, 0]; qy = A[j, 1] + tt * AB[j, 1]
        dd = (E - qx) ** 2 + (N - qy) ** 2
        upd = dd < bestd
        bestd[upd] = dd[upd]; bx[upd] = qx[upd]; by[upd] = qy[upd]
    dist_to_track = np.sqrt(bestd)

    CORRIDOR = 22.0  # m
    ontrack = (dist_to_track < CORRIDOR) & (speed > DRIVE_V)
    ontrack = gaussian_smooth(ontrack.astype(float), 6.0) > 0.4   # de-flicker
    dotx = np.where(ontrack, bx, np.nan)
    doty = np.where(ontrack, by, np.nan)

    # clean lap times: consecutive full-revolution boundaries
    laps_out = []
    for k in range(len(loop_starts) - 1):
        i0, i1 = loop_starts[k], loop_starts[k + 1]
        lt = float(t[i1] - t[i0])
        if 5.0 < lt < 1200.0:
            laps_out.append({"start": round(float(t[i0]), 2),
                             "end": round(float(t[i1]), 2), "time": round(lt, 3)})

    start_xy = [float(anchor[0]), float(anchor[1])] if anchor is not None else [float(poly[0, 0]), float(poly[0, 1])]
    return {"poly": poly, "polyspeed": polyspeed,
            "start": start_xy,
            "dotx": dotx, "doty": doty, "ontrack": ontrack,
            "closed": bool(closed), "laps": laps_out}


# --------------------------------------------------------------------------- #
#  Main processing
# --------------------------------------------------------------------------- #
def process(folder, out_hz, units="mph", track_config=None, driver=None, name=None):
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

    # ---- robust GPS outlier rejection ------------------------------------ #
    # Karts top out well under this; anything faster is a GPS glitch (the
    # bogus 300+ km/h spikes that otherwise blow out the speed colour ramp).
    SPEED_CAP = 36.0  # m/s  (~130 km/h)
    pos_ok = np.isfinite(E) & np.isfinite(N)
    # 1) reject reported-speed spikes from the velocity measurement
    if gspeed is not None:
        vok = vok & (gspeed < SPEED_CAP)
    # 2) reject position "teleports": a fix implying an impossible jump from
    #    its neighbours on both sides is almost certainly bad.
    if len(E) >= 3:
        dtg = np.diff(gt)
        dtg = np.where(dtg > 1e-3, dtg, 1e-3)
        step = np.hypot(np.diff(E), np.diff(N))
        v_imp = step / dtg                      # implied speed between fixes
        bad_fwd = np.concatenate([[False], v_imp > SPEED_CAP])
        bad_bwd = np.concatenate([v_imp > SPEED_CAP, [False]])
        teleport = bad_fwd & bad_bwd            # off on both sides => spike
        pos_ok = pos_ok & ~teleport
    # 3) reject fixes with hopeless reported accuracy
    pos_ok = pos_ok & (np.where(np.isfinite(hacc), hacc, 99) < 35.0)
    n_rej = int((~pos_ok).sum())
    if n_rej:
        print(f"  rejected {n_rej} GPS outlier fix(es) (spikes / teleports / low accuracy)")

    gps = {"t": gt, "E": E, "N": N, "vE": vE, "vN": vN, "vok": vok,
           "hacc": hacc, "sacc": sacc, "pos_ok": pos_ok}

    # ensure the filter initialises from a *good* fix
    if not pos_ok[0]:
        first_good = int(np.argmax(pos_ok)) if pos_ok.any() else 0
        E[0], N[0] = E[first_good], N[first_good]

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

    # ---- optional track config: real start/finish + incident zones -> ENU ----
    anchor = None; incidents = []; cfg_name = None; cfg = None; sf_line = None
    if track_config and os.path.exists(track_config):
        try:
            cfg = json.load(open(track_config))
        except Exception as e:
            print(f"  ! could not read track config: {e}")
    if cfg:
        cfg_name = cfg.get("name")
        sf = cfg.get("start_finish")
        if sf and "a" in sf and "b" in sf:
            A = ((sf["a"]["lon"] - lon0) * m_lon, (sf["a"]["lat"] - lat0) * m_lat)
            B = ((sf["b"]["lon"] - lon0) * m_lon, (sf["b"]["lat"] - lat0) * m_lat)
            sf_line = (A, B)
            anchor = ((A[0] + B[0]) / 2, (A[1] + B[1]) / 2)
        elif sf and "lat" in sf:
            anchor = ((sf["lon"] - lon0) * m_lon, (sf["lat"] - lat0) * m_lat)
        for z in cfg.get("incident_zones", []):
            incidents.append({
                "x": round((z["lon"] - lon0) * m_lon, 1),
                "y": round((z["lat"] - lat0) * m_lat, 1),
                "r": z.get("radius_m", 20),
                "label": z.get("label", "incident"),
            })
        if sf_line is not None:
            print(f"  track config: timing laps at the start/finish line ({cfg.get('name','')})")
        elif anchor is not None:
            print(f"  track config: anchoring laps at start/finish point ({cfg.get('name','')})")

    # ---- track silhouette + clean lap times ----
    track = extract_track(t_grid, Ef, Nf, speed, anchor=anchor, sf_line=sf_line)
    laps = track["laps"]
    if not laps:  # geometric split found nothing; fall back to distance detector
        laps = detect_laps(t_grid, Ef, Nf, speed, ontrack=track["ontrack"], start=track["start"])
    on_frac = float(track["ontrack"].mean())
    print(f"  laps detected: {len(laps)} | on-track: {on_frac*100:.0f}% of session "
          f"| silhouette: {len(track['poly'])} pts ({'closed' if track['closed'] else 'open'})")

    # ---- units ----
    UNIT = {"mph": (2.2369362921, "mph"), "kmh": (3.6, "km/h"), "ms": (1.0, "m/s")}
    uf, ulabel = UNIT.get(units, UNIT["mph"])

    # ---- assemble payload ----
    def r(arr, nd):
        if arr is None:
            return None
        a = np.where(np.isfinite(arr), arr, 0.0)
        return [round(float(v), nd) for v in a]

    def rnan(arr, nd):
        """Round but preserve NaN as null (for off-track dot position)."""
        if arr is None:
            return None
        return [None if not np.isfinite(v) else round(float(v), nd) for v in arr]

    # robust top speed (on-track, 99.5th pct) so a stray spike can't blow the scale
    spd_disp = speed * uf
    ontrack = track["ontrack"]
    spd_on = spd_disp[ontrack] if ontrack.any() else spd_disp
    max_speed = float(np.percentile(spd_on, 99.5)) if len(spd_on) else float(np.max(spd_disp))

    session_name = name or cfg_name or os.path.basename(os.path.realpath(folder))
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
            "driver": driver,
            "device": dev,
            "duration": round(t_end, 2),
            "hz": out_hz,
            "n": n,
            "audioEpochNs": audio_t0,
            "lat0": lat0, "lon0": lon0,
            "speedUnit": ulabel,
            "bounds": {
                "minX": float(np.min(track["poly"][:, 0])), "maxX": float(np.max(track["poly"][:, 0])),
                "minY": float(np.min(track["poly"][:, 1])), "maxY": float(np.max(track["poly"][:, 1])),
            },
            "trackClosed": track["closed"],
            "start": [round(track["start"][0], 2), round(track["start"][1], 2)],
            "startLine": ([[round(sf_line[0][0], 2), round(sf_line[0][1], 2)],
                           [round(sf_line[1][0], 2), round(sf_line[1][1], 2)]] if sf_line else None),
            "incidents": incidents,
            "maxSpeed": round(max_speed, 1),
            "maxLatG": round(float(np.percentile(np.abs(g_lat[ontrack]) if ontrack.any() else np.abs(g_lat), 99.5)), 2),
            "maxLonAccel": round(float(np.max(g_lon)), 2),
            "maxBrake": round(float(np.min(g_lon)), 2),
            "totalDist": round(float(np.nansum(np.hypot(np.diff(track["dotx"]), np.diff(track["doty"])))), 1),
            "hasLoudness": loudness is not None,
            "hasElevation": elevation is not None,
            "hasVibration": vibration is not None,
            "laps": laps,
        },
        "t": r(t_grid, 2),
        "track": [[round(float(px), 1), round(float(py), 1)] for px, py in track["poly"]],
        "trackSpeed": r(track["polyspeed"] * uf, 1),
        "dotx": rnan(track["dotx"], 1), "doty": rnan(track["doty"], 1),
        "speed": r(spd_disp, 1),
        "gLat": r(g_lat, 2), "gLon": r(g_lon, 2),
        "heading": r(heading, 1),
        "bank": r(bank, 1),
        "dist": r(dist, 1),
        "elev": r(elevation, 1) if elevation is not None else None,
        "gpsAcc": r(gps_acc, 1),
        "loud": r(loudness, 1) if loudness is not None else None,
        "vib": r(vibration, 3) if vibration is not None else None,
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
    ap.add_argument("--units", choices=["mph", "kmh", "ms"], default="mph",
                    help="Speed units shown on the dashboard (default mph)")
    ap.add_argument("--track-config", default=None,
                    help="Track JSON (real start/finish + incident zones), e.g. gateway_t1.json")
    ap.add_argument("--driver", default=None, help="Driver name shown in the header")
    ap.add_argument("--name", default=None, help="Session name shown in the header")
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

    payload = process(folder, args.hz, units=args.units, track_config=args.track_config,
                      driver=args.driver, name=args.name)

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
