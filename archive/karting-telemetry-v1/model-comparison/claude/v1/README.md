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
python build_dashboard.py [folder] [--hz 30] [--out dashboard.html]
                          [--audio Microphone.mp4] [--embed-audio]
                          [--template dashboard_template.html] [--json]
```

- `--hz` resample rate for the smoothed grid (default 30; 60 for silkier motion,
  bigger file).
- `--embed-audio` inlines the MP4 as a data URI → one fully self-contained file.
- `--json` also dumps `telemetry.json` if you want the processed channels.

## How the smoothing works (brief)

GPS alone is jumpy (±3–5 m) and only ~1 Hz; the IMU is fast (~100 Hz) but drifts.
The script fuses them with a constant-velocity **Kalman filter + RTS smoother**
over [East, North, vEast, vNorth]: GPS position and GPS velocity (from
speed+bearing) are the measurements, weighted by their own reported accuracy,
while the IMU's dynamic-acceleration magnitude drives **adaptive process noise**
— the filter tightens on straights and stays responsive through corners. G-forces
are derived from the *smoothed* trajectory (longitudinal = dv/dt, lateral =
v·yaw-rate), which keeps them independent of how the phone was mounted. Pre-GPS-fix
rows (lat/lon = 0) are dropped, timestamps are de-glitched, and everything is
resampled onto one uniform time grid for instant lookup during playback.

## Notes & quirks

- All Sensor Logger files share a UTC `time` column in epoch **nanoseconds** —
  that's what aligns the sensors. The dashboard clock is anchored to when
  `Microphone.csv`/`Microphone.mp4` started.
- Optional channels degrade gracefully: no barometer → no elevation trace; no
  `Microphone.csv` loudness → a flat scrubber ribbon; etc.
- Lap detection is best-effort (return-to-start-region). On an open/point-to-point
  run it may find one "lap" = the whole session.
