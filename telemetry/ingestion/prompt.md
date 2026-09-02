# Kickoff prompt - Kart Telemetry v2, Stage A (AUTONOMOUS build)

You are running AUTONOMOUSLY with NO human in the loop. Build Stage A end to end, commit
git checkpoints as you go, self-validate against known ground truth, and stop cleanly if a
validation gate fails rather than producing confidently-wrong output.

## NO VISION / NO IMAGE PROCESSING

Timing-sheet data is ALREADY extracted to JSON files in the inbox (e.g.
`2026-06-25_1440.json`, `2026-06-25_1500.json`). Venue geometry (S/F gate, 11 corners,
pit routes) is ALREADY in `ingestion/output/gateway-kartplex/_venue/gateway_kartplex_t1.geojson`

- `gateway_kartplex_t1.md`. Do NOT read, classify, or OCR any images. Do NOT call any vision
  gateway or vision-capable model. There are no budget concerns - the build runs fully offline.

## RESUMING an interrupted run

Do NOT restart from scratch. First run `git log --oneline` and read ingestion/BUILD_LOG.md to
see what is already checkpointed; reuse an existing ingestion/.venv; pick up at the first
incomplete step in the Build order.

## Read first (do not skip)

- `ingestion/V2_PLAN.md` - COMPLETE standalone brief: domain context, the proven v1 pipeline,
  verified findings (incl. the 0.193% audio-clock-DRIFT root cause), and the full v2 spec.
- `ingestion/output/gateway-kartplex/_venue/gateway_kartplex_t1.geojson` and
  `gateway_kartplex_t1.md` - venue geometry: S/F gate segment (`sf_gate_line`), 11 corner
  apex seeds (`turn_1`..`turn_11`), pit routes, racing direction (CCW).
  > > > Those landmarks/paths are APPROXIMATE SEEDS (read each file's `_README`). DO NOT be literal:
  > > > do not fit to, snap precisely to, or treat their coordinates/vertices/lengths as truth. Derive
  > > > REAL geometry from the phone GPS; use the sketches only to disambiguate intent (e.g. "in-lap
  > > > loops the outside of the head").

## Scope

- BUILD: Stage A only = turn `ingestion/inbox/gateway-kartplex/` into a clean CANONICAL per-session
  dataset (see V2_PLAN "dataset/" spec). PURE DATA.
- DO NOT BUILD: Stage B (dashboards/plots/visualization) or the dashboard port. Dataset only.
- Work inside `ingestion/`. Code goes in `ingestion/kart/`. Outputs in `ingestion/output/<venue>/...`.

## Environment

- Create a venv: `python3 -m venv ingestion/.venv` and install `ingestion/requirements.txt`.
- Run everything with that venv's python. The recording zip is large (~90MB) and git-ignored;
  it stays on disk in inbox. raw_sessions/ is git-ignored (it's unzipped reference, regenerable).

## GIT CHECKPOINT DISCIPLINE (this is my rollback safety net - linear commits, I'm the only dev)

- Repo: /Users/nathanverrill/karting-repos/karting (branch main). Commit LINEARLY.
- FIRST: commit the current clean pre-build state.
- Commit a checkpoint after EACH pipeline step that RUNS and SELF-VALIDATES. Clear messages, e.g.
  "checkpoint(ingest): unzipped, 2 timing sheets loaded, metadata read - OK".
- If a step FAILS its validation gate: do NOT thrash or pile on speculative fixes. Commit a WIP
  with a clear message, append a dated entry to `ingestion/BUILD_LOG.md` explaining what failed and
  your best hypothesis, and STOP. Leave the last good checkpoint intact.
- Keep `ingestion/BUILD_LOG.md` updated as you go (what you did, numbers, decisions, surprises).

## Build order - ONE step at a time; each must self-validate (print numeric sanity) before the next

1. ingest: scan inbox flat. Inputs = exactly one .zip + one-or-more pre-extracted timing-sheet
   \*.json; IGNORE stray files (.DS_Store, .sqlite, images, etc) gracefully. NO vision / NO image
   classification. Unzip -> raw_sessions/<name>/. Read metadata.csv (device, schema v, recording
   epoch+tz, sensor list, per-sensor sampleRateMs). CONFIRM the zip actually contains Headphone.csv
   - Microphone.mp4 + Location/Accelerometer/Gyroscope/Gravity/Microphone.csv. VALIDATE: print
     file inventory + rates + timing-sheet count (expect 2 here).
2. timesheet: LOAD the pre-extracted \*.json (no vision/OCR) -> per sheet: datetime (AUTHORITATIVE,
   from the JSON `date`+`time` fields), all fields (kart#, per-lap times, best, #laps, ProSkill,
   position, visitNumber/raceNumber [capture but mark UNRELIABLE]) -> copy verbatim into
   timesheet.json. VALIDATE: 2 sheets parsed; lap counts ~14 and ~13.
3. session-window / AUTO-SPLIT: detect the 2 sessions in the recording (GPS gaps/pit periods +
   lap clustering), match each to its sheet by lap-time fingerprint. VALIDATION GATE: must find
   two sessions matching ~14 laps/best ~40.5s and ~13 laps/best ~41.2s, lap-time RMSE < 0.5s.
   If not -> log + STOP.
4. sync: fit sensor_t = a\*audio_t + b via xcorr(Microphone.csv dBFS @sensor-clock vs audio RMS).
   Report a, b, peak r. EXPECT a to reflect ~0.193% drift (audio ~4.24s short over ~36.5min).
   If peak r is low (<~0.5) -> flag low-confidence in sync.json + BUILD_LOG; do NOT fabricate.
5. fuse: lat/lon->ENU (store anchor); GPS smoothing SPLINE (keeps track shape - NOT a corner-
   rounding Kalman) + ZUPT (speed<0.6 m/s). 100 Hz. VALIDATE vs ground-truth bounds: max speed
   < ~57 mph (~25.5 m/s); sustained lat_g <~2.2 (impacts can exceed - that's fine); track bbox sane.
6. laps: seed gate from the venue geojson `sf_gate_line` segment -> snap to GPS track ->
   gate-crossing detection + AUTO-ALIGN to the timesheet (slide window, drop out-lap). Mark flyers;
   isolate out/in/pit using the pit-exit/entrance landmark corridors. VALIDATE: detected lap times
   match sheet (RMSE < ~0.3s,
   like v1's 0.2s).
7. write dataset/ per session: session.json, timesheet.json, sync.json, sectors.json (gate as
   lat/lon+heading; sectors fractions; corners[] left for later if track-map mapping not done),
   fused_trace.csv, laps.csv, aligned_100hz.parquet. VALIDATE: files exist, row counts/columns sane.

## General rules

- Reuse the PROVEN v1 logic described in V2_PLAN (spline+ZUPT, gyro.gravity yaw, distance-aligned
  delta, gate auto-align). Don't reinvent settled decisions; the plan says why they were made.
- Use `time` (epoch ns) as the master clock for cross-sensor/audio alignment.
- After each step, print a SHORT numeric sanity check (counts, ranges, RMSE, r).
- Prefer small, composable scripts in ingestion/kart/ (ingest.py, timesheet.py, sessions.py,
  sync.py, fuse.py, laps.py, write_dataset.py) + a run.py that chains them.
- When DONE or STOPPED: write a final BUILD_LOG.md summary - what works, what's checkpointed
  (git log), validation numbers achieved, and any open issues for the human to review.

## Definition of done (Stage A)

Two session datasets under ingestion/output/gateway-kartplex/<sheet-datetime>/dataset/, each
self-validated (lap RMSE < ~0.3s, sync r reported, speed/g within bounds), every step checkpointed
in git, BUILD_LOG.md current. No dashboards. Stop and summarize.
