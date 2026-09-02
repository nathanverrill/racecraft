#!/usr/bin/env python3
"""
data_stats.py  --  summarise a Sensor Logger session into an uploadable report
==============================================================================

Reads every CSV in a session folder and writes a compact `stats.md` (and prints
it). It's a small text file you can upload so I can see the *shape* of your data
— sample rates, value ranges, GPS accuracy, speed spikes, an estimate of how many
laps you actually drove, and where the recording paused — without the raw files.
This is what I use to tune the outlier-rejection and track-extraction thresholds.

Usage
-----
    python data_stats.py /path/to/SessionFolder
    python data_stats.py /path/to/SessionFolder --out stats.md

Needs: numpy, pandas.
"""

import argparse
import math
import os
import sys

import numpy as np
import pandas as pd

MS_TO_MPH = 2.2369362921


def load(path):
    try:
        df = pd.read_csv(path)
    except Exception as e:
        return None, f"  ! could not read: {e}"
    return df, None


def rate_hz(df):
    """Median sample rate from the time (ns) or seconds_elapsed column."""
    for col, scale in (("time", 1e-9), ("seconds_elapsed", 1.0)):
        if col in df.columns:
            t = pd.to_numeric(df[col], errors="coerce").dropna().to_numpy() * scale
            t = np.sort(t)
            d = np.diff(t)
            d = d[d > 0]
            if len(d):
                return 1.0 / np.median(d), t[-1] - t[0]
    return None, None


def fmt(v, nd=2):
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    return f"{v:.{nd}f}"


def numeric_table(df, skip=("time", "seconds_elapsed")):
    lines = []
    for c in df.columns:
        if c.lower() in skip:
            continue
        v = pd.to_numeric(df[c], errors="coerce").to_numpy()
        v = v[np.isfinite(v)]
        if v.size == 0:
            continue
        lines.append(f"| {c} | {fmt(v.min())} | {fmt(v.max())} | {fmt(v.mean())} | "
                     f"{fmt(v.std())} | {fmt(np.percentile(v,50))} |")
    if not lines:
        return ""
    head = "| column | min | max | mean | std | median |\n|---|---|---|---|---|---|\n"
    return head + "\n".join(lines) + "\n"


def gps_summary(df):
    """The bits that matter for track/outlier tuning."""
    out = []
    lat = pd.to_numeric(df.get("latitude"), errors="coerce").to_numpy() if "latitude" in df else None
    lon = pd.to_numeric(df.get("longitude"), errors="coerce").to_numpy() if "longitude" in df else None
    if lat is None or lon is None:
        return "  (no latitude/longitude columns)\n"
    n = len(lat)
    zero = int(np.sum((lat == 0) & (lon == 0)))
    good = np.isfinite(lat) & np.isfinite(lon) & ~((lat == 0) & (lon == 0))
    out.append(f"- GPS fixes: **{n}**  (pre-fix lat/lon=0 rows: {zero})")
    if good.sum() < 5:
        return "\n".join(out) + "\n"
    la, lo = lat[good], lon[good]
    lat0, lon0 = float(np.median(la)), float(np.median(lo))
    mlat = 111320.0; mlon = 111320.0 * math.cos(math.radians(lat0))
    E = (lo - lon0) * mlon; N = (la - lat0) * mlat
    out.append(f"- bounding box: **{E.max()-E.min():.0f} m × {N.max()-N.min():.0f} m**  "
               f"(centre {lat0:.5f}, {lon0:.5f})")

    spd = pd.to_numeric(df.get("speed"), errors="coerce").to_numpy()[good] if "speed" in df else None
    if spd is not None and np.isfinite(spd).any():
        s = spd[np.isfinite(spd)] * MS_TO_MPH
        pct = np.percentile(s, [50, 90, 99, 99.9, 100])
        out.append(f"- GPS speed (mph): median {pct[0]:.1f} · p90 {pct[1]:.1f} · "
                   f"p99 {pct[2]:.1f} · p99.9 {pct[3]:.1f} · **max {pct[4]:.1f}**")
        spikes = int(np.sum(s > 130))
        out.append(f"- implausible-speed fixes (>130 mph, treated as glitches): **{spikes}**")

    hacc = pd.to_numeric(df.get("horizontalAccuracy"), errors="coerce").to_numpy()[good] if "horizontalAccuracy" in df else None
    if hacc is not None and np.isfinite(hacc).any():
        h = hacc[np.isfinite(hacc)]
        pct = np.percentile(h, [50, 90, 99])
        out.append(f"- horizontal accuracy (m): median {pct[0]:.1f} · p90 {pct[1]:.1f} · p99 {pct[2]:.1f}")

    # estimated laps via revolutions around the centre, on driving samples only
    if spd is not None and np.isfinite(spd).any():
        drv = np.isfinite(spd) & (spd > 4.0)
        if drv.sum() > 30:
            cx, cy = np.median(E[drv]), np.median(N[drv])
            ang = np.unwrap(np.arctan2(N[drv] - cy, E[drv] - cx))
            revs = abs(ang[-1] - ang[0]) / (2 * math.pi)
            out.append(f"- driving fraction (speed>4 mph-ish): **{100*drv.mean():.0f}%** of fixes")
            out.append(f"- estimated laps (revolutions while driving): **≈ {revs:.1f}**")

    # recording pauses / multiple sessions: large gaps in seconds_elapsed
    se = pd.to_numeric(df.get("seconds_elapsed"), errors="coerce").to_numpy()
    if np.isfinite(se).any():
        se = np.sort(se[np.isfinite(se)])
        gaps = np.diff(se)
        big = np.where(gaps > 30)[0]
        if len(big):
            out.append(f"- recording gaps >30 s: **{len(big)}** "
                       f"(largest {gaps.max():.0f} s) — likely separate sessions / pauses")
        else:
            out.append("- recording gaps >30 s: none")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Summarise a Sensor Logger session into stats.md")
    ap.add_argument("folder", help="Session folder (with the CSVs)")
    ap.add_argument("--out", default=None, help="Output markdown file (default: <folder>/stats.md)")
    args = ap.parse_args()

    folder = os.path.realpath(args.folder)
    if not os.path.isdir(folder):
        sys.exit(f"Not a folder: {folder}")
    csvs = sorted(f for f in os.listdir(folder) if f.lower().endswith(".csv")
                  and not f.lower().startswith("stats"))
    if not csvs:
        sys.exit("No CSV files found.")

    md = [f"# Sensor Logger session stats", "", f"`{os.path.basename(folder)}`", ""]

    # quick index of files / rates
    md.append("## Sensors")
    md.append("| file | rows | duration (s) | rate (Hz) | columns |")
    md.append("|---|---|---|---|---|")
    dfs = {}
    for f in csvs:
        df, err = load(os.path.join(folder, f))
        if df is None:
            md.append(f"| {f} | — | — | — | {err} |"); continue
        dfs[f] = df
        hz, dur = rate_hz(df)
        cols = ", ".join([c for c in df.columns if c.lower() not in ("time", "seconds_elapsed")])
        md.append(f"| {f} | {len(df):,} | {fmt(dur,0)} | {fmt(hz,1)} | {cols} |")
    md.append("")

    # GPS / track summary first (most useful)
    loc = next((f for f in dfs if f.lower() == "location.csv"), None)
    if loc:
        md.append("## GPS / track summary")
        md.append(gps_summary(dfs[loc]))

    # metadata passthrough
    metaf = next((f for f in dfs if f.lower() == "metadata.csv"), None)
    if metaf:
        md.append("## Metadata")
        try:
            row = dfs[metaf].iloc[0].to_dict()
            for k, v in row.items():
                md.append(f"- **{k}**: {v}")
        except Exception:
            pass
        md.append("")

    # per-file numeric ranges
    md.append("## Value ranges")
    for f in csvs:
        if f not in dfs or f.lower() in ("metadata.csv",):
            continue
        tbl = numeric_table(dfs[f])
        if tbl:
            md.append(f"### {f}")
            md.append(tbl)

    text = "\n".join(md)
    out = args.out or os.path.join(folder, "stats.md")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(text)

    print(text)
    print(f"\n[wrote {out}  ({os.path.getsize(out)/1024:.1f} KB) — upload this]")


if __name__ == "__main__":
    main()
