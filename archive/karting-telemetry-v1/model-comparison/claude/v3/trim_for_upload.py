#!/usr/bin/env python3
"""
trim_for_upload.py  --  shrink a Sensor Logger session for easy upload
======================================================================

The high-rate IMU files (Accelerometer / Gyroscope / Gravity, ~100 Hz) and
Microphone.csv are what make a session big. This script makes a trimmed COPY of
the folder where those fast sensors are *decimated* down to a target rate, and
(optionally) the whole thing is clipped to a time window. It never touches your
originals, never interpolates, and keeps the exact `time` (epoch-nanosecond)
column intact so the data still aligns perfectly when I process it.

It only copies .csv files — the big Microphone.mp4 is skipped, which is fine:
I don't need the audio to rebuild the track, laps, speed and g-forces.

Examples
--------
    # whole session, fast sensors thinned to 25 Hz, zipped for upload
    python trim_for_upload.py /path/to/SessionFolder

    # just one good 5-minute window starting 8 minutes in
    python trim_for_upload.py /path/to/SessionFolder --start-min 8 --minutes 5

    # only the file I most need (the GPS track), untouched
    python trim_for_upload.py /path/to/SessionFolder --only Location

No dependencies — standard library only. Works on huge files (streams row by row).
"""

import argparse
import csv
import io
import os
import sys
import zipfile


def _time_seconds(row, idx_se, idx_time):
    """Return a seconds value for a row, preferring seconds_elapsed."""
    if idx_se is not None:
        try:
            return float(row[idx_se])
        except (ValueError, IndexError):
            pass
    if idx_time is not None:
        try:
            return float(row[idx_time]) / 1e9   # epoch nanoseconds -> seconds
        except (ValueError, IndexError):
            pass
    return None


def trim_csv(src, dst, hz, t_start, t_end):
    """Stream-copy src -> dst, decimating to ~hz and clipping to [t_start,t_end].
    Returns (rows_in, rows_out)."""
    rows_in = rows_out = 0
    min_gap = (1.0 / hz) if hz and hz > 0 else 0.0
    with open(src, "r", newline="", encoding="utf-8", errors="replace") as fin, \
         open(dst, "w", newline="", encoding="utf-8") as fout:
        reader = csv.reader(fin)
        writer = csv.writer(fout)
        try:
            header = next(reader)
        except StopIteration:
            return 0, 0
        writer.writerow(header)
        lower = [h.lower() for h in header]
        idx_se = lower.index("seconds_elapsed") if "seconds_elapsed" in lower else None
        idx_time = lower.index("time") if "time" in lower else None

        # find the recording origin so --start-min is relative to the session start
        origin = None
        last_kept = None
        for row in reader:
            rows_in += 1
            ts = _time_seconds(row, idx_se, idx_time)
            if ts is None:                      # no usable timestamp: keep as-is
                writer.writerow(row); rows_out += 1
                continue
            # use seconds_elapsed directly; if only epoch time, rebase to first row
            if idx_se is not None:
                rel = ts
            else:
                if origin is None:
                    origin = ts
                rel = ts - origin
            if t_start is not None and rel < t_start:
                continue
            if t_end is not None and rel > t_end:
                break
            if last_kept is not None and (rel - last_kept) < min_gap - 1e-9:
                continue
            writer.writerow(row); rows_out += 1
            last_kept = rel
    return rows_in, rows_out


def human(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def main():
    ap = argparse.ArgumentParser(
        description="Trim a Sensor Logger session (decimate fast sensors / clip time) for upload.")
    ap.add_argument("folder", help="Path to the unzipped session folder (the one with Location.csv)")
    ap.add_argument("--hz", type=float, default=25.0,
                    help="Target max rate for fast sensors (default 25; use 0 to disable thinning)")
    ap.add_argument("--start-min", type=float, default=None,
                    help="Clip: start this many minutes into the recording")
    ap.add_argument("--minutes", type=float, default=None,
                    help="Clip: keep only this many minutes (from --start-min, or from the start)")
    ap.add_argument("--only", nargs="+", default=None,
                    help="Only include these files (names without .csv, e.g. --only Location Accelerometer)")
    ap.add_argument("--out", default=None, help="Output folder (default: <folder>_upload)")
    ap.add_argument("--no-zip", action="store_true", help="Don't also create a .zip")
    args = ap.parse_args()

    folder = os.path.realpath(args.folder)
    if not os.path.isdir(folder):
        sys.exit(f"Not a folder: {folder}")

    out = args.out or (folder.rstrip("/\\") + "_upload")
    os.makedirs(out, exist_ok=True)

    t_start = (args.start_min * 60.0) if args.start_min else 0.0 if args.minutes else None
    t_end = None
    if args.minutes is not None:
        t_end = (t_start or 0.0) + args.minutes * 60.0

    csvs = sorted(f for f in os.listdir(folder) if f.lower().endswith(".csv"))
    if args.only:
        wanted = {n.lower().replace(".csv", "") for n in args.only}
        csvs = [f for f in csvs if f.lower().replace(".csv", "") in wanted]
    if not csvs:
        sys.exit("No matching .csv files found.")

    print(f"Source: {folder}")
    print(f"Output: {out}")
    print(f"Thinning fast sensors to ~{args.hz:g} Hz"
          + ("" if args.hz else " (disabled)")
          + (f"; window {args.start_min or 0:g}–"
             f"{((args.start_min or 0) + (args.minutes or 0)):g} min" if args.minutes else "")
          + "\n")
    print(f"{'file':28} {'in rows':>10} {'out rows':>10} {'in':>9} {'out':>9}")
    print("-" * 70)

    tot_in = tot_out = 0
    for f in csvs:
        src = os.path.join(folder, f); dst = os.path.join(out, f)
        in_sz = os.path.getsize(src)
        ri, ro = trim_csv(src, dst, args.hz, t_start, t_end)
        out_sz = os.path.getsize(dst)
        tot_in += in_sz; tot_out += out_sz
        print(f"{f:28} {ri:>10,} {ro:>10,} {human(in_sz):>9} {human(out_sz):>9}")

    print("-" * 70)
    print(f"{'TOTAL':28} {'':>10} {'':>10} {human(tot_in):>9} {human(tot_out):>9}")

    zpath = None
    if not args.no_zip:
        zpath = out + ".zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for f in csvs:
                z.write(os.path.join(out, f), arcname=f)
        print(f"\nZipped -> {zpath}  ({human(os.path.getsize(zpath))})")

    final = os.path.getsize(zpath) if zpath else tot_out
    print(f"\nUpload {'the .zip' if zpath else 'the folder'} above.")
    if final > 25 * 1024 * 1024:
        print("Still big — re-run with a lower --hz (e.g. 15) or a --minutes window to shrink further.")
    elif args.hz and any(f.lower().startswith(("accelerometer", "gyroscope", "gravity", "microphone")) for f in csvs):
        print("Tip: Location.csv alone is enough to check the track silhouette and lap times if you want the smallest possible upload (--only Location).")


if __name__ == "__main__":
    main()