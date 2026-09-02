# karting-telemetry-v1 (archived)

> **Archived.** Superseded by `telemetry/`. Not maintained; paths point at
> recordings on disk.

The first karting pipeline, kept because `telemetry/` was rebuilt *from* it and its
plan document ("don't re-litigate these without reason") cites decisions made here.

Everything is code only; the recordings it ran against are on disk (see
[`../../docs/DATA.md`](../../docs/DATA.md)).

## What was settled here

- **GPS spline, not a Kalman filter.** A constant-velocity Kalman rounded the hairpins
  into something that no longer looked like the circuit. A light smoothing spline
  through raw GPS keeps the track shape recognizable, with zero-velocity update when
  GPS speed drops under 0.6 m/s (the kart genuinely stops at the wall).
- **Yaw from gyroscope · gravity, not `Orientation.yaw`.** The phone rides loose in a
  pocket, and the export's `standardisation:false` flag makes the orientation signs
  untrustworthy. Projecting the gyro onto the gravity unit vector is robust to both
  and gives a clean spin signature.
- **Distance-aligned delta, not time-aligned.** The F1 question is "where on track am
  I losing this," which only distance answers.
- **The start/finish gate is at the bottom of the circuit,** not the obvious main
  straight — found by reading the pit-lane break in the trace, confirmed by matching
  official lap times to 0.2 s RMSE.

The `diag_*.py` and `probe_*.py` scripts are the investigation itself: separate probes
for gate crossings, spins, pit entry, impact location and clock lag.

## model-comparison/

Claude and Gemini given the same session and asked to build a telemetry dashboard,
three iterations deep on the Claude side. Kept as an artifact of how differently the
two approached the same data.

## audio-vs-gps-validation-prompt.md

The cross-validation that made audio telemetry credible. A Sodi GT5 is single-speed —
no gearbox, centrifugal clutch — so above clutch engagement, engine RPM is close to
linear in ground speed. That prior turns "is my audio RPM extraction real?" into a
regression with an R² you can report, and it catches harmonic tracking: if the audio
RPM is 2× or 3× the scale the regression implies, you locked onto the wrong harmonic.
