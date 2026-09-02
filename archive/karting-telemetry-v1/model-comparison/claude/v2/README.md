# Kart Telemetry → F1-Style Audio-Synced Dashboard

Turn a **Sensor Logger** recording of a karting session into a self-contained,
F1-style dashboard where every value is driven by the **engine audio** as you
play it back. The track map is GPS+IMU sensor-fused (smoothed), and you get
speed, longitudinal/lateral g, a friction circle, bank/lean, lap times, and a
multi-channel trace — all scrubbing in lock-step with the engine sound.

> **Heads up:** I only received your folder *screenshot*, not the actual CSVs.
> So this is a small pipeline you run **locally on your own machine**, right
> inside the session folder. Open `dashboard_DEMO.html` first to see the look —
> it's built from synthetic data so the play button and all the gauges work
> immediately.

---

## What's in here

| File | What it is |
|------|------------|
| `dashboard_DEMO.html` | **Open this first.** A working dashboard built from synthetic kart data, with engine audio embedded so it plays on double-click. This is exactly what yours will look like. |
| `build_dashboard.py` | The pipeline. Reads the Sensor Logger CSVs, does the sensor fusion, and writes a finished `dashboard.html`. |
| `dashboard_template.html` | The UI template `build_dashboard.py` fills in. Keep it next to the script. |

## Quick start (your real data)

1. Put `build_dashboard.py` and `dashboard_template.html` together somewhere.
2. Point the script at your session folder (the one with `Location.csv`,
   `Accelerometer.csv`, `Microphone.mp4`, etc.):

   ```bash
   python build_dashboard.py "/path/to/World_Wide_Technology_Raceway-2026-06-25_21-02-36"
   ```

   …or just drop the script into that folder and run `python build_dashboard.py`.

3. It writes `dashboard.html` **into that folder**. Double-click it. The engine
   audio (`Microphone.mp4`) is referenced from the same folder, so keep them
   together — or use `--embed-audio` to bake the sound into the HTML:

   ```bash
   python build_dashboard.py /path/to/session --embed-audio
   ```

Only `numpy` and `pandas` are required:
```bash
pip install numpy pandas
```

## Using it

- **Play button** drives the engine audio *and* the whole dashboard together.
  The audio is the master clock — there's no separate time slider.
- **Scrubber** is the engine-loudness waveform; click/drag anywhere to seek.
- **Space** = play/pause, **←/→** = seek, **0.5× / 1× / 2×** = playback speed.
- **sync ±** nudges the audio-vs-data alignment if they drift (this happens if
  you paused mid-recording in Sensor Logger — the audio and sensor streams can
  start to disagree; nudge until a known event lines up).
- **Load engine audio** — if a browser blocks the local `Microphone.mp4` over
  `file://`, click this and pick the MP4 by hand. If there's no audio at all,
  the dashboard falls back to a virtual clock so everything still plays.

## Options

```
python build_dashboard.py [folder] [--units mph|kmh|ms] [--hz 30]
                          [--out dashboard.html] [--embed-audio]
                          [--audio Microphone.mp4] [--template dashboard_template.html] [--json]
```

- `--units` speed units on the dashboard (default **mph**).
- `--hz` resample rate for the smoothed grid (default 30; 60 for silkier motion,
  bigger file).
- `--embed-audio` inlines the MP4 as a data URI → one fully self-contained file.
- `--json` also dumps `telemetry.json` if you want the processed channels.

## How the smoothing works (brief)

GPS alone is jumpy (±3–5 m) and only ~1 Hz; the IMU is fast (~100 Hz) but drifts.
The script first **rejects GPS outliers** — impossible speeds (the bogus 300+ km/h
spikes), position teleports, and low-accuracy fixes — then fuses what's left with
a constant-velocity **Kalman filter + RTS smoother** over [E, N, vE, vN], gated by
an innovation test so a stray fix can't yank the line. GPS position and velocity
are weighted by their reported accuracy; the IMU's dynamic-acceleration magnitude
drives **adaptive process noise** (tighter on straights, responsive in corners).
G-forces are derived from the *smoothed* trajectory (longitudinal = dv/dt, lateral
= v·yaw-rate), so they're independent of how the phone was mounted — which matters
because a phone in your pocket is not bolted to the kart. (`Orientation.csv` is
ignored for exactly this reason: pocket attitude ≠ kart attitude.)

**The track silhouette** is built by isolating only the parts of the session where
you were actually driving (above walking pace, inside the repeatedly-driven
corridor — so pit idling, walking around, and the parking-lot detour drop out),
splitting that into individual laps by counting full revolutions around the track
centre, phase-aligning the laps and taking their median. The result is one clean
closed outline, coloured by the speed you typically carry at each point. Your live
position is projected onto that outline as a single dot; when you're off-track the
dot hides and the map shows **OFF TRACK**. Lap times come from the same
revolution boundaries.

## Notes & quirks

- Speed shows in **mph** by default (`--units kmh` or `--units ms` to change).
- All Sensor Logger files share a UTC `time` column in epoch **nanoseconds** —
  that's what aligns the sensors. The dashboard clock is anchored to when
  `Microphone.csv`/`Microphone.mp4` started.
- Channels are stored at reduced precision (cm / 0.1-unit) to keep the file small
  and the playback light — no spurious 9-digit noise.
- Optional channels degrade gracefully: no barometer → no elevation trace; no
  `Microphone.csv` loudness → a flat scrubber ribbon; etc.
- If a session has no clean laps (a one-way blast, not a circuit), the map falls
  back to the longest continuous on-track run as an open outline.
