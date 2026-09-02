"""
Detect the two on-track sessions from the microphone loudness (dBFS) envelope,
then split every sensor stream into per-session CSVs.

Loud  = engine running / on track.
Quiet = paddock / idle.
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

BASE = "clean"

# ---- tunables ----
SMOOTH_S = 3.0        # rolling window (seconds) to smooth the envelope
GAP_MERGE_S = 30.0    # merge loud segments separated by < this many seconds
MIN_SESSION_S = 120.0 # discard detected segments shorter than this
BUFFER_S = 10.0       # padding added before/after each session
# Threshold is auto-picked between quiet & loud levels, but can override:
THRESHOLD_DBFS = None  # e.g. -40.0 to force

mic = pd.read_csv(f"{BASE}/Microphone.csv").sort_values("seconds_elapsed")
t = mic["seconds_elapsed"].values
db = mic["dBFS"].values.astype(float)

# sample rate of mic
dt = np.median(np.diff(t))
win = max(1, int(SMOOTH_S / dt))
db_s = pd.Series(db).rolling(win, center=True, min_periods=1).median().values

# auto threshold: midpoint between 20th and 80th percentile of loudness
if THRESHOLD_DBFS is None:
    lo, hi = np.percentile(db_s, 25), np.percentile(db_s, 75)
    thr = (lo + hi) / 2.0
else:
    thr = THRESHOLD_DBFS
print(f"mic rate ~{1/dt:.1f} Hz | threshold = {thr:.1f} dBFS")

loud = db_s > thr

# find contiguous loud segments
segments = []
start = None
for i, v in enumerate(loud):
    if v and start is None:
        start = i
    elif not v and start is not None:
        segments.append((start, i - 1))
        start = None
if start is not None:
    segments.append((start, len(loud) - 1))

# convert to times
segs_t = [(t[a], t[b]) for a, b in segments]

# merge segments separated by small gaps
merged = []
for s, e in segs_t:
    if merged and s - merged[-1][1] < GAP_MERGE_S:
        merged[-1] = (merged[-1][0], e)
    else:
        merged.append((s, e))

# drop short ones
sessions = [(s, e) for s, e in merged if (e - s) >= MIN_SESSION_S]

print(f"\nDetected {len(sessions)} session(s):")
for k, (s, e) in enumerate(sessions, 1):
    print(f"  Session {k}: {s:.1f}s -> {e:.1f}s  (duration {e-s:.1f}s)")

# ---- plot envelope with detected sessions ----
fig, ax = plt.subplots(figsize=(16, 5))
ax.plot(t, db, color="lightgray", linewidth=0.5, label="dBFS raw")
ax.plot(t, db_s, color="navy", linewidth=1.0, label=f"dBFS smoothed ({SMOOTH_S}s)")
ax.axhline(thr, color="red", linestyle="--", linewidth=1, label=f"threshold {thr:.1f}")
for k, (s, e) in enumerate(sessions, 1):
    ax.axvspan(s, e, color="green", alpha=0.15)
    ax.text((s + e) / 2, ax.get_ylim()[1] - 5, f"Session {k}",
            ha="center", color="green", fontweight="bold")
ax.set_xlabel("seconds_elapsed")
ax.set_ylabel("dBFS")
ax.set_title("Microphone Loudness -> Session Detection")
ax.legend(loc="lower right")
ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig("sessions_envelope.png", dpi=120)
print("\nSaved sessions_envelope.png")

# ---- split every sensor stream by session (with buffer) ----
STREAMS = [
    "Accelerometer.csv", "Gravity.csv", "Gyroscope.csv",
    "Magnetometer.csv", "Orientation.csv", "Location.csv", "Microphone.csv",
]

import os
for k, (s, e) in enumerate(sessions, 1):
    s_buf, e_buf = s - BUFFER_S, e + BUFFER_S
    outdir = f"session{k}"
    os.makedirs(outdir, exist_ok=True)
    for fname in STREAMS:
        path = f"{BASE}/{fname}"
        if not os.path.exists(path):
            continue
        d = pd.read_csv(path)
        if "seconds_elapsed" not in d.columns:
            continue
        mask = (d["seconds_elapsed"] >= s_buf) & (d["seconds_elapsed"] <= e_buf)
        sub = d[mask].copy()
        # re-zero seconds_elapsed within the session for convenience
        sub["session_elapsed"] = sub["seconds_elapsed"] - s
        sub.to_csv(f"{outdir}/{fname}", index=False)
    print(f"Wrote {outdir}/  ({s_buf:.1f}s -> {e_buf:.1f}s, buffer {BUFFER_S}s)")

plt.show()