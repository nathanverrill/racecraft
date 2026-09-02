#!/usr/bin/env python3
"""
find_sessions.py  --  locate the driving sessions inside a long recording
=========================================================================

You left the recorder running before / between / after your timed runs. This
reads Location.csv, ignores the idle + walking + parking-lot stretches, and finds
the contiguous blocks where you were actually lapping (your practice sessions).
For each it prints the time window, wall-clock start, lap count + best lap,
detected spinouts/stops, and a ready-to-run trim_for_upload.py command.

It is robust to:
  - Sensor Logger -1 "no reading" sentinels (speed / bearing)
  - concave / twisty layouts (lap timing by position period, not winding)
  - SPINOUTS: a brief on-track stop no longer splits a session; a real break
    (kart returns to pits / parking, or a long stop) still does. Spinouts are
    detected and reported.

    python find_sessions.py /path/to/session --laptimes session_laptimes.json

Needs: numpy, pandas.
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

MS_TO_MPH = 2.2369362921
SPEED_CAP = 36.0          # m/s, reject GPS speed glitches
DRIVE_V = 4.0             # m/s (~9 mph): above walking/idle
SPIN_V = 2.0              # m/s: at/below this on-track = a stop/spinout


def load_location(folder):
    for f in os.listdir(folder):
        if f.lower() == "location.csv":
            return pd.read_csv(os.path.join(folder, f))
    sys.exit("No Location.csv in that folder.")


def project(df):
    lat = pd.to_numeric(df["latitude"], errors="coerce").to_numpy()
    lon = pd.to_numeric(df["longitude"], errors="coerce").to_numpy()
    se = pd.to_numeric(df.get("seconds_elapsed"), errors="coerce").to_numpy()
    if not np.isfinite(se).any():
        t = pd.to_numeric(df["time"], errors="coerce").to_numpy() / 1e9
        se = t - np.nanmin(t)
    good = np.isfinite(lat) & np.isfinite(lon) & ~((lat == 0) & (lon == 0)) & np.isfinite(se)
    lat, lon, se = lat[good], lon[good], se[good]
    order = np.argsort(se); lat, lon, se = lat[order], lon[order], se[order]
    lat0, lon0 = float(np.median(lat)), float(np.median(lon))
    mlat = 111320.0; mlon = 111320.0 * math.cos(math.radians(lat0))
    E = (lon - lon0) * mlon; N = (lat - lat0) * mlat
    spd = None
    if "speed" in df:
        spd = pd.to_numeric(df["speed"], errors="coerce").to_numpy()[good][order]
    return se, E, N, spd, (lat0, lon0, mlat, mlon)


def latlon_to_en(lat, lon, origin):
    lat0, lon0, mlat, mlon = origin
    return (lon - lon0) * mlon, (lat - lat0) * mlat


def clean_speed(se, E, N, spd):
    if spd is None or not np.isfinite(spd).any():
        d = np.hypot(np.diff(E), np.diff(N)); dt = np.diff(se); dt[dt <= 0] = 1e-3
        v = np.concatenate([[0.0], d / dt])
    else:
        v = spd.astype(float).copy()
    v[~np.isfinite(v)] = 0.0
    v[v < 0] = 0.0            # -1 "no reading" sentinel -> treat as stopped
    v[v > SPEED_CAP] = 0.0    # glitch
    return v


# ---------------------------------------------------------------- lap timing
def estimate_period(t, x, y, tmin=20.0, tmax=80.0):
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


def _seg_cross(p1, p2, A, B):
    """If segment p1->p2 crosses segment A->B, return (param_t, dir_sign), else None."""
    d1x, d1y = p2[0] - p1[0], p2[1] - p1[1]
    abx, aby = B[0] - A[0], B[1] - A[1]
    denom = d1x * aby - d1y * abx
    if abs(denom) < 1e-12:
        return None
    dpx, dpy = A[0] - p1[0], A[1] - p1[1]
    tt = (dpx * aby - dpy * abx) / denom
    uu = (dpx * d1y - dpy * d1x) / denom
    if 0.0 <= tt <= 1.0 and 0.0 <= uu <= 1.0:
        return tt, (1 if (d1x * aby - d1y * abx) > 0 else -1)
    return None


def line_crossings(t, x, y, A, B):
    """Times the path crosses the (extended) start/finish line, with direction."""
    mx, my = (A[0] + B[0]) / 2, (A[1] + B[1]) / 2
    Ae = (mx + (A[0] - mx) * 1.6, my + (A[1] - my) * 1.6)   # extend ends so an
    Be = (mx + (B[0] - mx) * 1.6, my + (B[1] - my) * 1.6)   # off-centre kart trips it
    cr = []
    for i in range(len(t) - 1):
        r = _seg_cross((x[i], y[i]), (x[i + 1], y[i + 1]), Ae, Be)
        if r is not None:
            tt, sgn = r
            cr.append((t[i] + tt * (t[i + 1] - t[i]), sgn))
    return cr


def laps_from_line(t, x, y, A, B, T=None):
    # upsample so crossings aren't skipped at low GPS rates (1 Hz steps ~10 m)
    if len(t) > 4:
        g = np.arange(t[0], t[-1], 0.25)
        x = np.interp(g, t, x); y = np.interp(g, t, y); t = g
    cr = line_crossings(t, x, y, A, B)
    times = sorted(ct for ct, _ in cr)
    if len(times) < 2:
        return []
    # collapse wobble: several crossings within a few seconds = one pass
    centers = [times[0]]
    for ct in times[1:]:
        if ct - centers[-1] > 4.0:
            centers.append(ct)
    if len(centers) < 2:
        return []
    diffs = np.diff(centers)
    med = float(np.median(diffs))               # empirical lap time, robust
    return [float(d) for d in diffs if d > 0.5 * med]


def laps_from_anchor(td, xd, yd, sx, sy, T):
    """Offset-tolerant: each lap has one closest approach to the reference point,
    even if that point is 10-20 m off the true racing line. Returns lap times."""
    if len(td) < 5:
        return []
    g = np.arange(td[0], td[-1], 0.25)
    xg = np.interp(g, td, xd); yg = np.interp(g, td, yd)
    d = np.hypot(xg - sx, yg - sy)
    thr = float(np.percentile(d, 55))           # only count genuine close passes
    times = []; last = -1e9
    for k in range(1, len(d) - 1):
        if d[k] <= d[k - 1] and d[k] < d[k + 1] and d[k] < thr and (g[k] - last) > 0.55 * T:
            times.append(g[k]); last = g[k]
    return [times[k + 1] - times[k] for k in range(len(times) - 1)
            if 0.5 * T < (times[k + 1] - times[k]) < 3.0 * T]


def estimate_laps(t, x, y, v, anchor=None, sf_line=None):
    drv = v > DRIVE_V
    if drv.sum() < 20:
        return [], None
    td, xd, yd, vd = t[drv], x[drv], y[drv], v[drv]
    T = estimate_period(td, xd, yd)
    if T is None:
        return [], None
    # 1) most accurate: actual start/finish line crossing
    if sf_line is not None:
        laps = laps_from_line(td, xd, yd, sf_line[0], sf_line[1], T)
        if len(laps) >= 2:
            return laps, T
    # 2) offset-tolerant: closest approach to the S/F (or fastest) point each lap
    if anchor is not None:
        sx, sy = anchor
    else:
        ai = int(np.argmax(vd)); sx, sy = xd[ai], yd[ai]
    laps = laps_from_anchor(td, xd, yd, sx, sy, T)
    if len(laps) >= 2:
        return laps, T
    # 3) last resort: uniform period count
    n = max(0, int(round((td[-1] - td[0]) / T)))
    return [T] * n, T


# ------------------------------------------------------------- session blocks
def session_blocks(se, v, gap):
    """Split driving into sessions purely on gap duration: a spinout is a short
    on-track stop (seconds) and stays within a session; a real break (pit /
    parking / engine off) is a long quiet gap and starts a new session."""
    di = np.where(v > DRIVE_V)[0]
    if len(di) == 0:
        return []
    blocks = []; s = 0
    for k in range(1, len(di)):
        if se[di[k]] - se[di[k - 1]] > gap:
            blocks.append((di[s], di[k - 1])); s = k
    blocks.append((di[s], di[-1]))
    return blocks


def detect_spinouts(se, v):
    """Brief near-stops (spinouts) inside a session: speed dips <= SPIN_V then
    recovers, lasting a few seconds (not a long pit stop)."""
    spins = []; i = 0; n = len(v)
    while i < n:
        if v[i] <= SPIN_V:
            j = i
            while j < n and v[j] < DRIVE_V:
                j += 1
            dur = se[min(j, n - 1)] - se[i]
            if 1.0 <= dur <= 25.0:
                spins.append((float(se[i]), float(dur)))
            i = max(j, i + 1)
        else:
            i += 1
    return spins


def rec_start_dt(folder):
    mp = os.path.join(folder, "Metadata.csv")
    if not os.path.exists(mp):
        return None
    try:
        row = pd.read_csv(mp).iloc[0].to_dict()
    except Exception:
        return None
    tzname = None
    for k, val in row.items():
        if "timezone" in k.lower():
            tzname = str(val).strip()
    # prefer the epoch (unambiguous), then convert to the recording timezone
    for k, val in row.items():
        if "epoch" in k.lower():
            try:
                dt = datetime.fromtimestamp(float(val) / 1000.0, tz=timezone.utc)
                try:
                    from zoneinfo import ZoneInfo
                    if tzname:
                        dt = dt.astimezone(ZoneInfo(tzname))
                except Exception:
                    pass
                return dt
            except Exception:
                pass
    for k, val in row.items():
        if "recording time" in k.lower():
            for fmt in ("%Y-%m-%d_%H-%M-%S", "%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S"):
                try:
                    return datetime.strptime(str(val).strip(), fmt)
                except ValueError:
                    continue
    return None


def extract_session(src_folder, out_folder, t_start, t_end, hz, only):
    """Write a trimmed copy of the session (fast sensors decimated, clipped to the
    [t_start,t_end] window) to out_folder + a .zip. Reuses trim_for_upload."""
    import zipfile
    here = os.path.dirname(os.path.realpath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    try:
        import trim_for_upload as TU
    except Exception:
        print("   ! trim_for_upload.py not found next to find_sessions.py; cannot --extract")
        return out_folder
    os.makedirs(out_folder, exist_ok=True)
    csvs = sorted(f for f in os.listdir(src_folder) if f.lower().endswith(".csv"))
    if only:
        keep = {n.lower().replace(".csv", "") for n in only}
        csvs = [f for f in csvs if f.lower().replace(".csv", "") in keep]
    for f in csvs:
        TU.trim_csv(os.path.join(src_folder, f), os.path.join(out_folder, f), hz, t_start, t_end)
    with zipfile.ZipFile(out_folder + ".zip", "w", zipfile.ZIP_DEFLATED) as z:
        for f in csvs:
            z.write(os.path.join(out_folder, f), arcname=f)
    return out_folder


def main():
    ap = argparse.ArgumentParser(description="Find driving sessions in a Sensor Logger recording.")
    ap.add_argument("folder", help="Session folder (with Location.csv)")
    ap.add_argument("--gap", type=float, default=75.0,
                    help="Quiet gap (s) that separates sessions; longer than a spinout, "
                         "shorter than a pit break (default 75)")
    ap.add_argument("--min-laps", type=int, default=3, help="Ignore blocks with fewer laps")
    ap.add_argument("--laptimes", default=None, help="Optional session_laptimes.json to cross-check")
    ap.add_argument("--track-config", default=None,
                    help="Optional track JSON (start_finish + incident_zones), e.g. gateway_t1.json")
    ap.add_argument("--extract", action="store_true",
                    help="Also WRITE each session to its own trimmed folder + .zip (ready to upload)")
    ap.add_argument("--extract-hz", type=float, default=25.0,
                    help="Decimate fast sensors to this rate when extracting (default 25)")
    ap.add_argument("--extract-only", nargs="+", default=None,
                    help="When extracting, keep only these CSVs (e.g. Location Accelerometer Gyroscope)")
    args = ap.parse_args()

    folder = os.path.realpath(args.folder)
    df = load_location(folder)
    se, E, N, spd, origin = project(df)
    v = clean_speed(se, E, N, spd)
    total = se[-1] - se[0]
    rec0 = rec_start_dt(folder)

    # optional track landmarks -> data ENU frame
    anchor = None; sf_line = None; zones = []
    if args.track_config and os.path.exists(args.track_config):
        cfg = json.load(open(args.track_config))
        sf = cfg.get("start_finish")
        if sf and "a" in sf and "b" in sf:
            A = latlon_to_en(sf["a"]["lat"], sf["a"]["lon"], origin)
            B = latlon_to_en(sf["b"]["lat"], sf["b"]["lon"], origin)
            sf_line = (A, B)
            anchor = ((A[0] + B[0]) / 2, (A[1] + B[1]) / 2)
        elif sf and "lat" in sf:
            anchor = latlon_to_en(sf["lat"], sf["lon"], origin)
        for z in cfg.get("incident_zones", []):
            ze, zn = latlon_to_en(z["lat"], z["lon"], origin)
            zones.append((z.get("label", "zone"), ze, zn, z.get("radius_m", 25)))

    blocks = session_blocks(se, v, args.gap)
    print(f"Recording: {folder}")
    print(f"  total logged: {total/60:.1f} min   |   GPS fixes: {len(se)}   |   "
          f"driving: {100*np.mean(v>DRIVE_V):.0f}%")
    print(f"  detected {len(blocks)} session block(s)\n")

    sessions = []
    for (a, b) in blocks:
        m = (se >= se[a]) & (se <= se[b])
        laps, T = estimate_laps(se[m], E[m], N[m], v[m], anchor=anchor, sf_line=sf_line)
        if len(laps) < args.min_laps:
            continue
        spins = detect_spinouts(se[m], v[m])
        # label each spinout by nearest incident zone (if config provided)
        spin_labeled = []
        sem, Em, Nm, vm = se[m], E[m], N[m], v[m]
        for (st, dur) in spins:
            lab = None
            if zones:
                si = int(np.argmin(np.abs(sem - st)))
                best = min(zones, key=lambda z: math.hypot(Em[si] - z[1], Nm[si] - z[2]))
                if math.hypot(Em[si] - best[1], Nm[si] - best[2]) < best[3] + 25:
                    lab = best[0]
            spin_labeled.append((st, dur, lab))
        sessions.append({"t0": float(se[a]), "t1": float(se[b]), "laps": laps,
                         "period": T, "spins": spin_labeled})

    if not sessions:
        print("No driving sessions met the lap threshold. Try --min-laps 2 or a larger --gap.")
        return

    names = ["FP1", "FP2", "FP3", "FP4", "FP5", "FP6"]
    for i, s in enumerate(sessions):
        t0, t1, laps = s["t0"], s["t1"], s["laps"]
        dur = t1 - t0; nm = names[i] if i < len(names) else f"S{i+1}"
        wall = ""
        if rec0:
            wc = rec0 + timedelta(seconds=t0)
            try:
                wall = "  (~" + wc.strftime("%-I:%M %p") + " " + (wc.tzname() or "") + ")"
            except ValueError:
                wall = "  (~" + wc.strftime("%I:%M %p").lstrip("0") + ")"
        measured = len(set(round(x, 2) for x in laps)) > 1
        print(f"== {nm} ==  {t0/60:.1f}-{t1/60:.1f} min{wall}")
        if measured:
            print(f"   {dur/60:.1f} min driving · ~{len(laps)} laps · best {min(laps):.2f}s · "
                  f"median {np.median(laps):.2f}s")
        else:
            print(f"   {dur/60:.1f} min driving · ~{len(laps)} laps · ~{s['period']:.1f}s/lap (estimate)")
        if s["spins"]:
            parts = []
            for (st, d, lab) in s["spins"]:
                tag = f" @ {lab}" if lab else ""
                parts.append(f"{st/60:.1f}min({d:.0f}s){tag}")
            print(f"   spinouts/stops: {len(s['spins'])}  ->  " + ", ".join(parts))
        pad = 20.0
        sm = max(0.0, t0 - pad) / 60.0; mins = (dur + 2 * pad) / 60.0
        if args.extract:
            out = extract_session(folder, f"{folder}_{nm}", max(0.0, t0 - pad), t1 + pad,
                                  args.extract_hz, args.extract_only)
            print(f"   extracted -> {out}  (+ {os.path.basename(out)}.zip)  ready to upload\n")
        else:
            print(f"   -> python trim_for_upload.py \"{folder}\" "
                  f"--start-min {sm:.2f} --minutes {mins:.2f} --out \"{folder}_{nm}\"\n")

    if args.laptimes and os.path.exists(args.laptimes):
        ref = json.load(open(args.laptimes))
        print("Cross-check vs timing sheets:")
        for i, s in enumerate(sessions):
            if i >= len(ref.get("sessions", [])):
                break
            o = ref["sessions"][i]
            sheet_spins = sum(1 for L in o["laps"] if L > 1.15 * np.median(o["laps"]))
            print(f"   {o['label']}: sheet {o['lap_count']} laps / best {o['best_lap']:.3f}s / "
                  f"{sheet_spins} slow laps   vs   GPS ~{len(s['laps'])} laps / "
                  f"best {min(s['laps']):.2f}s / {len(s['spins'])} spinouts")
        print("\n(The driving block usually spans MORE laps than the timed sheet — it includes\n"
              " your out/in and warm-up laps. The timed run is a clean subset; once you upload a\n"
              " session I can lock the lap strip to the official splits.)")


if __name__ == "__main__":
    main()
