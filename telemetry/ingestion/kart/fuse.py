"""fuse.py - Stage A Step 5 (GPS fusion -> 100 Hz fused trace, per session).

For each session window [t0,t1] (master clock, epoch ns):
  - Clip Location to the window; use FULL-PRECISION lat/lon.
  - ENU about an anchor = first GPS fix of the session (store anchor lon/lat).
  - GPS SPLINE path (smoothing spline through raw GPS) -> keeps the recognizable
    track shape (NOT a corner-rounding CV Kalman). Parameterize by GPS time so we
    can resample to a uniform 100 Hz master-clock grid. Smoothing is set from the
    GPS horizontalAccuracy (~3.5 m) so the path is clean but not corner-rounded.
  - SPEED comes from the GPS `speed` field (V2_PLAN: "speed truth"), interpolated to
    100 Hz, NOT from differentiating the noisy position spline (3.5 m GPS jitter
    differentiates into spurious 30+ m/s spikes). ZUPT: where GPS speed < 0.6 m/s,
    force speed 0 (kart actually stops at the wall).
  - Heading from path tangent; yaw_rate from gyro . gravity_unit (spin-robust),
    resampled to the 100 Hz grid.

VALIDATE vs ground-truth bounds: max speed < ~25.5 m/s (~57 mph); sustained lat_g
<~2.2 (transient impacts may exceed - reported separately, not clamped); bbox sane.

Output (per session): output/<venue>/<key>/dataset/fused_trace.csv  (+ returns meta)
Columns: t (epoch ns), seconds_elapsed, E, N, lat, lon, speed, heading_deg, yaw_rate
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.interpolate import splprep, splev, UnivariateSpline

from common import (RAW_SESSIONS, OUTPUT, NS_PER_S, MAX_SPEED_MS,
                    SUSTAINED_LATG_CAP, write_json, load_json,
                    lonlat_to_enu, enu_to_lonlat)

FS = 100.0           # output rate Hz
ZUPT_SPEED = 0.6     # m/s
G = 9.80665


def _yaw_rate_series(sd):
    """gyro . gravity_unit -> scalar yaw rate (rad/s) on IMU clock (epoch ns)."""
    gy = pd.read_csv(sd / "Gyroscope.csv")
    gr = pd.read_csv(sd / "Gravity.csv")
    # align by index (same 100Hz cadence, identical timestamps per inspection)
    t = gy.time.values.astype(np.int64)
    gvec = gr[["x", "y", "z"]].values
    gnorm = gvec / (np.linalg.norm(gvec, axis=1, keepdims=True) + 1e-9)
    wvec = gy[["x", "y", "z"]].values
    yaw_rate = np.sum(wvec * gnorm, axis=1)   # rad/s about gravity (vertical) axis
    return t, yaw_rate


def fuse_session(sd, window, anchor=None):
    loc = pd.read_csv(sd / "Location.csv")
    t0, t1 = window["t0_ns"], window["t1_ns"]
    m = (loc.time >= t0) & (loc.time <= t1)
    seg = loc[m].copy().reset_index(drop=True)
    # drop unknown/poor fixes
    seg = seg[seg.latitude.notna() & seg.longitude.notna()].reset_index(drop=True)
    tg = seg.time.values.astype(np.int64)
    lat = seg.latitude.values.astype(float)
    lon = seg.longitude.values.astype(float)
    gps_speed = seg.speed.values.astype(float)

    if anchor is None:
        anchor = {"lon": float(lon[0]), "lat": float(lat[0])}
    E, N = lonlat_to_enu(lon, lat, anchor["lon"], anchor["lat"])
    E = np.asarray(E); N = np.asarray(N)

    # time in seconds from window start (for spline parameterization)
    ts = (tg - tg[0]) / NS_PER_S
    n = len(ts)

    # smoothing spline of E(t), N(t). UnivariateSpline's s is the SUM of squared
    # residuals budget; set it from GPS horizontal accuracy so the path is clean
    # (rejects ~few-meter jitter) without rounding corners. s ~= n * sigma^2.
    hacc = seg.horizontalAccuracy.values.astype(float)
    sigma = float(np.nanmedian(hacc)) if np.isfinite(hacc).any() else 3.5
    sigma = max(2.0, min(sigma, 6.0))          # clamp to sane GPS range
    s_factor = n * (sigma ** 2)
    # ensure strictly increasing t for spline
    uniq = np.concatenate(([True], np.diff(ts) > 0))
    ts_u, E_u, N_u = ts[uniq], E[uniq], N[uniq]
    spl_E = UnivariateSpline(ts_u, E_u, k=3, s=s_factor)
    spl_N = UnivariateSpline(ts_u, N_u, k=3, s=s_factor)

    # 100 Hz uniform grid on master clock
    grid_s = np.arange(0, ts[-1], 1.0 / FS)
    grid_ns = tg[0] + (grid_s * NS_PER_S).astype(np.int64)
    Eg = spl_E(grid_s)
    Ng = spl_N(grid_s)

    # heading from path tangent (deg, math convention 0=E CCW)
    dE = np.gradient(Eg, grid_s)
    dN = np.gradient(Ng, grid_s)
    heading = np.degrees(np.arctan2(dN, dE))

    # SPEED = GPS speed field (truth), interpolated to grid; ZUPT to 0 when stopped
    gsp = np.where(gps_speed >= 0, gps_speed, np.nan)
    gsp = pd.Series(gsp).interpolate(limit_direction="both").values
    speed = np.interp(grid_s, ts, gsp)
    stopped = speed < ZUPT_SPEED
    speed[stopped] = 0.0

    # yaw rate from gyro.gravity, resampled to grid
    ti, yr = _yaw_rate_series(sd)
    yaw_rate = np.interp(grid_ns, ti, yr)

    lon_g, lat_g_coord = enu_to_lonlat(Eg, Ng, anchor["lon"], anchor["lat"])

    df = pd.DataFrame({
        "t": grid_ns,
        "seconds_elapsed": grid_s,
        "E": Eg, "N": Ng,
        "lat": lat_g_coord, "lon": lon_g,
        "speed": speed,
        "heading_deg": heading,
        "yaw_rate": yaw_rate,
    })

    # lateral g (SUSTAINED cornering) = v * yaw_rate / g, lightly smoothed so the
    # ~2.2 g sustained bound isn't tripped by single-sample gyro spikes. Transient
    # impacts live on raw accelerometer (acc_mag) and are intentionally NOT clamped.
    yr_s = pd.Series(df.yaw_rate.values).rolling(25, center=True, min_periods=1).mean().values
    latg = np.abs(df.speed.values * yr_s) / G
    meta = {
        "anchor": anchor,
        "n_gps": int(n),
        "n_100hz": int(len(df)),
        "max_speed_ms": float(np.nanmax(speed)),
        "max_speed_mph": float(np.nanmax(speed) * 2.236936),
        "p99_latg": float(np.nanpercentile(latg, 99)),
        "max_latg": float(np.nanmax(latg)),
        "bbox_E": [float(Eg.min()), float(Eg.max())],
        "bbox_N": [float(Ng.min()), float(Ng.max())],
        "s_factor": s_factor,
    }
    return df, meta


def run(venue: str = "gateway-kartplex") -> dict:
    print("=" * 64)
    print(f"[fuse] STEP 5  venue={venue}")
    print("=" * 64)
    ingest = load_json(OUTPUT / venue / "raw" / "ingest.json")
    sessions = load_json(OUTPUT / venue / "raw" / "sessions.json")["sessions"]
    default_sd = RAW_SESSIONS / ingest["zip_stem"]

    all_ok = True
    out = {}
    for ses in sessions:
        key = ses["session_key"]
        sd = Path(ses["session_dir"]) if ses.get("session_dir") else default_sd
        df, meta = fuse_session(sd, ses["window"])
        ds_dir = OUTPUT / venue / key / "dataset"
        ds_dir.mkdir(parents=True, exist_ok=True)
        df.to_csv(ds_dir / "fused_trace.csv", index=False)

        bbox_e = meta["bbox_E"][1] - meta["bbox_E"][0]
        bbox_n = meta["bbox_N"][1] - meta["bbox_N"][0]
        speed_ok = meta["max_speed_ms"] <= MAX_SPEED_MS + 1.0
        latg_ok = meta["p99_latg"] <= SUSTAINED_LATG_CAP + 0.5
        bbox_ok = 50 < bbox_e < 400 and 50 < bbox_n < 400
        ok = speed_ok and latg_ok and bbox_ok
        all_ok &= ok
        print(f"[fuse] {key}: {meta['n_gps']} GPS -> {meta['n_100hz']} @100Hz | "
              f"max_speed {meta['max_speed_ms']:.1f} m/s ({meta['max_speed_mph']:.1f} mph) "
              f"speed_ok={speed_ok} | p99 lat_g {meta['p99_latg']:.2f} "
              f"(max {meta['max_latg']:.2f}) latg_ok={latg_ok} | "
              f"bbox {bbox_e:.0f}x{bbox_n:.0f}m bbox_ok={bbox_ok}")
        out[key] = meta
        write_json(ds_dir / "_fuse_meta.json", meta)

    print("-" * 64)
    print(f"[fuse] STATUS: {'PASS' if all_ok else 'CHECK'}")
    print("-" * 64)
    return out


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "gateway-kartplex")
