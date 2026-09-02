# Prompt: cross-validate kart audio telemetry against Sensor Logger GPS

You are validating driving conclusions I extracted from an **in-helmet AirPods recording** of a Sodi GT5 rental kart (Honda GX390, 4-stroke single, **single-speed** clutch drive) against **Sensor Logger GPS/IMU telemetry** from the same session at Gateway Kartplex Track 1.

## Inputs
Audio-derived (from `out/`):
- `audio_timeseries.csv` - frame-level ~43 Hz. Cols: `t_audio_s` (s from recording start), `firing_hz`, `rpm`, `rpm_confidence` (0-1), `engine_on` (1=reliable), `rms`, `rms_db`, `spectral_centroid_hz`.
- `throttle_events.csv` - `t_audio_s`, `event` (on/off), `slope`.
- `lap_summary.csv` - per-lap audio aggregates (`lap_source` says whether boundaries are GPS-authoritative or audio-estimated/approximate).
- `session_summary.json` - config, headline conclusions, caveats.

Sensor Logger (I will attach): GPS Location (time as epoch ns or `seconds_elapsed`, latitude, longitude, speed m/s, course) plus my pipeline's lap numbers and S/F-crossing times; optionally Accelerometer/Gravity/Gyroscope.

## Step 1 - clock alignment (do this first)
The audio clock (t=0 at recording start) and the Sensor Logger clock are NOT synced. Find an offset `delta` mapping `t_audio_s -> t_gps`:
a. Resample audio `rms` (or `rpm`) and GPS `speed` to a common grid and cross-correlate; the lag at peak = `delta`.
b. If that's weak, align the audio-estimated lap period to the GPS lap period and match a distinctive feature (e.g. the slowest corner).
Report `delta`, the method, and the peak correlation. If r < ~0.5, say alignment is weak and mark all downstream results low-confidence.

## Step 2 - exploit the single-speed prior (the main validation)
No gearbox => engine RPM and ground speed are near-linear above clutch engagement. On reliable frames (`engine_on==1`):
- Regress audio `rpm` on GPS `speed`. Report slope, intercept, R^2.
- High R^2 validates the audio RPM extraction. If audio `rpm` is ~2x or ~3x the scale the regression implies, I tracked a harmonic - tell me the corrected `HARMONIC_TRACKED`.
- Flag low-speed departures from linearity as clutch slip / corner exit.

## Step 3 - comparisons
1. RPM vs speed correlation + regression (above) - headline.
2. Throttle-off events vs GPS deceleration: for each audio `off`, is there a speed drop / negative longitudinal accel within +/-1 s? Report hit rate and median timing error. Same for `on` vs corner-exit acceleration.
3. Lap times: compare `estimated_lap_time_s` and per-lap `lap_time_s` to my GPS S/F splits. Table: lap | GPS | audio | delta. Separate systematic bias from noise.
4. Per-lap pace: do audio `rpm_mean`/`rms_mean` rank laps the same way GPS lap time does? Spearman rho.
5. Corners: do audio RPM dips coincide with GPS low-speed points? Spot-check the slowest 3.

## Step 4 - diagnose disagreements (don't paper over them)
Attribute each mismatch to the most likely cause: wind/road noise (low `rpm_confidence`), AirPod fundamental dropout, clutch slip, GPS speed lag/error, or misalignment. Name the specific frames/laps.

## Output
- Applied `delta` + alignment confidence.
- RPM<->speed regression (slope, intercept, R^2) and the verdict on `HARMONIC_TRACKED`.
- Lap-time comparison table.
- Throttle-event <-> GPS-accel hit rates.
- Concrete notebook config changes for the next run (FMIN/FMAX/HARMONIC_TRACKED/confidence threshold).
Keep it terse and quantitative. Where the audio is low-confidence, say so plainly instead of over-claiming.
