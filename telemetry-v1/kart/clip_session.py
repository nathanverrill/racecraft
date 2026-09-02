"""Clip all sensor CSVs and the audio to the flying-lap racing window.

The racing window = [first gate crossing, last gate crossing] using the
validated real start/finish gate (bottom-center). This removes the out-lap
(track entry + pit-out) and the in-lap / end-of-session pit visit.

Outputs go to visit_6/clipped/:
  * each sensor CSV, rows with seconds_elapsed in [race_lo, race_hi]
  * Microphone_clipped.mp4, audio trimmed to the same window
  * a new seconds_elapsed_race column rebased to 0 at race_lo

Audio and sensors share the recording clock, so the same [lo,hi] applies.
"""
import subprocess
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
VISIT = HERE.parent
AUDIO = VISIT / "Microphone.mp4"
OUT = VISIT / "clipped"
SENSORS = ["Accelerometer", "Gravity", "Gyroscope", "Orientation",
           "Magnetometer", "Compass"]


def get_race_window():
    bounds = np.load(HERE / "lap_bounds.npy")     # (14, 2) [start,end] per lap
    race_lo = float(bounds[0, 0])
    race_hi = float(bounds[-1, 1])
    return race_lo, race_hi, bounds


def clip_csvs(race_lo, race_hi):
    OUT.mkdir(exist_ok=True)
    for name in SENSORS:
        src = VISIT / f"{name}.csv"
        if not src.exists():
            print(f"  skip {name} (not found)")
            continue
        df = pd.read_csv(src)
        m = (df.seconds_elapsed >= race_lo) & (df.seconds_elapsed <= race_hi)
        clipped = df[m].copy()
        clipped["seconds_elapsed_race"] = clipped.seconds_elapsed - race_lo
        clipped.to_csv(OUT / f"{name}.csv", index=False)
        print(f"  {name}: {len(df)} -> {len(clipped)} rows")

    # also clip the fused trace
    ft = pd.read_csv(HERE / "fused_trace.csv")
    m = (ft.seconds_elapsed >= race_lo) & (ft.seconds_elapsed <= race_hi)
    ftc = ft[m].copy()
    ftc["seconds_elapsed_race"] = ftc.seconds_elapsed - race_lo
    ftc.to_csv(OUT / "fused_trace.csv", index=False)
    print(f"  fused_trace: {len(ft)} -> {len(ftc)} rows")


def clip_audio(race_lo, race_hi):
    out_audio = OUT / "Microphone_clipped.mp4"
    dur = race_hi - race_lo
    cmd = ["ffmpeg", "-y", "-ss", f"{race_lo}", "-t", f"{dur}",
           "-i", str(AUDIO), "-c", "copy", str(out_audio)]
    print("  audio:", " ".join(cmd))
    subprocess.run(cmd, check=True, capture_output=True)
    print(f"  wrote {out_audio.name} ({dur:.1f}s)")


def main():
    race_lo, race_hi, bounds = get_race_window()
    print(f"Racing window: [{race_lo:.2f}, {race_hi:.2f}]s  "
          f"= {race_hi-race_lo:.1f}s ({(race_hi-race_lo)/60:.1f} min), 14 laps")
    print("\nClipping CSVs:")
    clip_csvs(race_lo, race_hi)
    print("\nClipping audio:")
    clip_audio(race_lo, race_hi)

    # save lap bounds rebased to race time for downstream tools
    rebased = bounds - race_lo
    np.save(OUT / "lap_bounds_race.npy", rebased)
    print("\nDone. Clipped session in", OUT)
    print("Lap start/stop times (race-relative seconds):")
    for i, (a, b) in enumerate(rebased):
        print(f"  lap {i+1:>2}: {a:7.2f} -> {b:7.2f}  ({b-a:.3f}s)")


if __name__ == "__main__":
    main()