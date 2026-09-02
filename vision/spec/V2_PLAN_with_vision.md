# Kart Telemetry v2 - Plan & Findings

> READ THIS CONTEXT FIRST, then the spec sections below. This doc is a standalone brief:
> a fresh session should be able to build the dataset pipeline AND reason about the domain
> well enough to suggest new analyses, from this file alone.

## ==================== CONTEXT & DATA INVENTORY ====================

### Who / what / why (the bigger picture)
- Driver/user: Nathan Verrill, improving his own kart driving. PURPOSE = COACHING &
  SELF-IMPROVEMENT ("where do I lose time, what should I do differently"), not telemetry for
  its own sake. Proactive, actionable driving insight is welcome.
- Vehicle: **Sodi GT5** gas-powered OUTDOOR rental kart, Honda GX390 (4-stroke, single-cyl,
  ~389cc), **SINGLE-SPEED** centrifugal clutch (NO gearbox). Single-speed = key physics prior:
  above clutch engagement engine RPM is ~LINEAR with ground speed -> validates audio RPM.
  Karts are tuned to tight specs for EQUAL performance -> differences are DRIVER, not machine.
  Engine may be remotely "dialed back" by stewards (audible exhaust pops); did NOT happen here.
- Track: Gateway Kartplex Track 1, World Wide Technology Raceway, Madison IL. Outdoor.
  Official blurb: "fastest in the St. Louis area, up to **55 mph** down the **700-foot back
  straight**, up to **2 lateral g** on the **11-turn half-mile** road course."
  Our measured lap ~704 m (note: blurb says ~half-mile/805m - treat 11-turn/2g/55mph as the
  authoritative GROUND-TRUTH BOUNDS; lap-length discrepancy is marketing vs racing-line, flag it).
  Layout: bottom esses -> long right (back) straight -> top hairpin/loop -> descent -> S/F (bottom).
- Sessions: arrive-and-drive (A&D), 10-min sessions. Types: FP1/FP2, Qualifying, Race. Printed
  timing sheet per session (driver, kart#, per-lap times, best, #laps, ProSkill rank, datetime).
- Rig: iPhone 17 Pro Max in pocket (Sensor Logger 1.60.1); AirPods in-helmet capture ENGINE
  AUDIO + head motion. One recording can span MULTIPLE sessions (this one had 2: ~2:40 & 3:00pm).

### GROUND-TRUTH VALIDATION BOUNDS (from official track facts - use as sanity checks)
- Top speed ~55 mph (~88.5 km/h / ~24.6 m/s). Fusion speed should not exceed ~57 mph; if it does,
  suspect GPS/spline error. (v1 session2 peaked 84.9 km/h = 52.7 mph - consistent.)
- Lateral (CORNERING) G up to ~2.0 SUSTAINED. lat_g = v*yaw_rate sustained >~2.2 -> suspect
  noise/spin artifact. BUT this bound is for SUSTAINED cornering ONLY.
- IMPACT G is different: a transient spike on RAW accelerometer magnitude (acc_mag) at a
  wall/kart contact can be FAR higher (v1 crash hit ~76 m/s^2 ~= 7.7 g for ~30ms). Do NOT
  discard high TRANSIENT total-accel as noise - it is the impact signal (most interesting
  event). Separate channels: sustained lat_g (cornering, ~2g cap) vs peak transient acc_mag
  (impacts, can be many g). Report both; never let the cornering cap suppress impacts.
- Back straight ~700 ft (~213 m) -> cross-check the S2 "straight" sector length.
- 11 turns -> corner identity (sectors.json corners[]) should land ~11 numbered turns.

### Analytical north star (what "good" looks like)
- Per-lap & per-corner: where time is gained/lost vs the driver's own best (distance-aligned delta).
- Ideal/theoretical lap (sum of best sectors) as target. Racing line vs map's ideal line; apex
  hit/miss; entry/exit speed.
- Eventually driver GAZE (AirPods head yaw vs track heading) - "was I looking through the corner".
- Engine RPM/throttle from audio, validated vs GPS speed (single-speed linearity).
- Incidents: spins (high yaw), contact (accel jolt).

### SENSOR INVENTORY (in the zip; native rate; what it's GOOD FOR)
All files have `time`(epoch ns, MASTER CLOCK) + `seconds_elapsed`. Rates from metadata sampleRateMs.
- Location.csv      ~1 Hz  lat,lon,altitude,speed(m/s),bearing,horizontalAccuracy,speedAccuracy,
                           bearingAccuracy,verticalAccuracy. speed -1 = unknown. -> trajectory,
                           speed truth, lap timing. (USE FULL PRECISION lat/lon, 7+ dp.)
- Accelerometer.csv 100Hz x,y,z calibrated device accel. -> impacts, long/lat accel.
- AccelerometerUncalibrated.csv 100Hz raw. -> only if recalibrating.
- Gravity.csv       100Hz x,y,z gravity vector. -> phone attitude; gyro projection.
- Gyroscope.csv     100Hz x,y,z rotation rate. -> gyro . gravity_unit = yaw rate (spin-robust).
- GyroscopeUncalibrated.csv 100Hz raw+drift.
- Orientation.csv   100Hz roll,pitch,yaw,qx..qw device attitude (standardisation:false - check signs).
- Magnetometer.csv  100Hz x,y,z field. -> heading aid; noisy near engine/metal.
- MagnetometerUncalibrated.csv 100Hz raw.
- Compass.csv       100Hz magnetic/trueBearing. -> heading sanity.
- Barometer.csv     (chk) pressure, relativeAltitude. -> elevation (track fairly flat).
- Microphone.mp4    16kHz ENGINE AUDIO (in-helmet AirPods). -> RPM/throttle + immersive sound.
                          AirPod voice processing may high-pass/thin the engine fundamental.
- Microphone.csv    ~9.5Hz dBFS loudness ON SENSOR CLOCK. -> the BRIDGE to sync audio<->sensors.
- Headphone.csv     ~50Hz AirPods head IMU: roll,pitch,yaw, rotationRate, accel, gravity,
                          quaternion, devicelocation. -> DRIVER GAZE through corners.
                          (v1 misnamed this HeadMotion.csv - use ORIGINAL name Headphone.csv.)
- Annotation.csv          user timestamped text marks. Pedometer/Activity -> ignore for driving.
- Watch*/HeartRate        in sensor list but likely empty unless Apple Watch worn.
- metadata.csv            device, app/schema version, recording epoch+tz, sensor list,
                          per-sensor sampleRateMs, standardisation flag. READ on ingest.

### Why key v1 design choices were made (don't re-litigate without reason)
- GPS-SPLINE path (not CV Kalman): Kalman rounded hairpins; light smoothing spline through raw
  GPS preserves recognizable track shape (user preference).
- YAW from gyro . gravity_unit (not Orientation.yaw): robust to pocket orientation +
  standardisation:false sign issues; clean spin signature.
- ZUPT on GPS speed<0.6 m/s: kart actually stops at the wall without noisy accel stop-detection.
- Start/finish GATE bottom-center (NOT the obvious right straight): user identified real S/F from
  the pit-trace break; validated by matching official lap times to ~0.2s RMSE.
- Distance-aligned delta (not time): proper F1 "where on track am I gaining/losing".

### HELPFUL LINKS
- Sensor Logger toolkit / docs (timestamps, units, coords, audio, alignment):
  https://github.com/tszheichoi/awesome-sensor-logger
  - Units:  https://github.com/tszheichoi/awesome-sensor-logger/blob/main/UNITS.md
  - Coords: https://github.com/tszheichoi/awesome-sensor-logger/blob/main/COORDINATES.md
  - Cross-platform: https://github.com/tszheichoi/awesome-sensor-logger/blob/main/CROSSPLATFORM.md
- Sensor Logger app: https://www.tszheichoi.com/sensorlogger
- Gateway Kartplex (track facts): the official site/blurb (55mph, 700ft straight, 2 lat-g, 11 turns).
- librosa (audio RPM/FFT): https://librosa.org/doc/latest/index.html

## Goal / workflow (the whole point)
Walk into office -> photograph timing sheet -> on phone, drop the **Sensor Logger ZIP**
+ the **timing-sheet photo(s)** into a watched folder on the Mac -> visualizations and
analysis appear automatically. No manual renaming, no code edits per session.

## Directory layout (kart_v2/)
```
inbox/          <- DROP ZONE: put SensorLogger .zip + timing_sheet_*.jpg here
raw_sessions/   <- pipeline unzips each ZIP here (one subfolder per recording)
output/         <- dashboards, plots, per-session analysis land here
kart/           <- the v2 code (ingest, fuse, laps, dashboard, audio, sync)
```

## VERIFIED FINDINGS (evidence-backed, from v1 investigation)

### Device / export
- iPhone 17 Pro Max, Sensor Logger 1.60.1, schema **version 3**, platform iOS 26.5.1.
- `standardisation: false` -> RAW iOS axis/sign conventions. See repo UNITS.md / COORDINATES.md
  before trusting accel/orientation signs. (We only used gyro-dot-gravity yaw + GPS, robust to this.)
- timezone America/Chicago. recording epoch start = 1782421356199 ms.

### Clocks & timestamps (CRITICAL)
- Every sensor CSV has BOTH `time` (UNIX epoch **nanoseconds**, UTC) and `seconds_elapsed`
  (s since Start tapped). **Use `time` (epoch ns) as the master clock for cross-sensor / audio sync.**
- Per-sensor BUFFERING offsets are REAL: GPS first sample is at seconds_elapsed = -45.36s
  (pre-buffered ~45s before the tap). Mic dBFS starts +0.019s. So sensors do NOT all start at 0.
- NTP sync optional (~tens of ms). Don't assume sub-10ms absolute accuracy.

### *** THE AUDIO SYNC BUG (root cause, finally) ***
- Microphone.mp4 container duration = **2189.44 s** (sample_rate 16000, start_time 0).
- Microphone.csv dBFS timeline spans seconds_elapsed 0.019 -> **2193.68 s**.
- => audio is **4.24 s shorter** than the sensor timeline over ~36.5 min = **0.193% CLOCK-RATE DRIFT**.
- This is NOT a constant offset. Desync grows ~ 0.00193 * t_into_recording:
  - session 1 (rec-time ~110-719s): ~0.2s -> ~1.4s drift across the session.
  - session 2 (rec-time ~1241-1800s): ~2.4s -> ~3.5s drift.
- EXPLAINS: why the -0.15s offset worked for session-1's crash (~rec-time 604s) but
  session 2 looked badly out of sync, and why "same phone, same offset" intuition still saw drift.
- FIX in v2: resample/stretch the audio to the sensor clock. Map audio_t -> sensor_t via the
  ratio 2193.68/2189.44, OR (better) cross-correlate Microphone.csv dBFS (sensor clock, ~9.5Hz)
  against audio-derived RMS to fit BOTH offset and rate (linear: sensor_t = a*audio_t + b).
  Then mux video with a rate-corrected audio (ffmpeg atempo / aresample async, or pre-stretch).

### Audio engine telemetry (from v1 out/ work) - UNVALIDATED until drift fixed
- RPM extracted from exhaust harmonic; config HARMONIC_TRACKED=1, RPM_PER_HZ=120, rpm_median~4190, max 5652.
- Governor assumption (~4500) is UNCERTAIN - user notes engine was NOT dialed back this session
  (no steward pops). So do NOT reject 5652 as impossible on governor grounds.
- Harmonic question must be settled by the SINGLE-SPEED physics: regress audio RPM vs GPS speed
  (near-linear, no gearbox). Slope/intercept/R^2 give true scale & whether a 2x/3x harmonic was tracked.
  MUST be done on drift-corrected, aligned data, else R^2 smears.
- HeadMotion.csv in v1 was a USER RENAME of the real export **Headphone.csv** (AirPods head IMU:
  roll/pitch/yaw, rotationRate, accel, gravity, devicelocation=right). v2 must use ORIGINAL names.

### Sessions (this recording has TWO ~10-min A&D sessions)
- Session 1 (2:40 PM): rec-time window ~[110.25, 719.0]s; 14 laps; best L11 40.519s; sheet RMSE 0.224s.
- Session 2 (3:00 PM): rec-time window ~[1241.55, 1800.67]s; 13 laps; best L8 41.164s; sheet RMSE 0.203s.
- Same track: Gateway Kartplex T1. Start/finish gate (ENU, anchored at GPS[0]):
  GATE_XY=[12,-12], GATE_DIR=[-1,0] (West crossing), half_width 12 m. Sectors frac [0,0.33,0.63,1.0]
  = S1 ESSES, S2 STRAIGHT, S3 HAIRPIN. (These are anchor-relative; v2 must re-derive gate per recording
  since ENU origin = each recording's first GPS fix. Better: store gate in lat/lon and convert.)

## PROVEN PIPELINE (carry over from v1, in visit_6/kart/)
- loaders: window-clip + ENU (lat/lon -> local meters via equirectangular at anchor).
- fuse: GPS spline path (keeps recognizable track shape) + ZUPT (GPS speed<0.6 -> stop). 100Hz.
  (Avoid the heavy CV Kalman - it rounded corners. Spline through raw GPS, s=n*1.2^2.)
- laps: fixed gate crossing detection + AUTO-ALIGN to official (slide window, drop out-lap).
- clip_session: clip all CSVs + audio to [first gate, last gate]; rebase seconds_elapsed_race=0.
- telemetry: distance model, distance-aligned delta vs best, sectors, theoretical-best, flags(unused).
- dashboard: dark F1 style. Track map (gold best-ghost line, speed tail, red dot + faded ghost dot,
  corner labels), big SPEED mph + DELTA, sector delta bars, SPEED TRACE (you vs ghost), MAX G,
  lap chart + IDEAL(theoretical best). Audio muxed; ffmpeg -ss a_start -t dur (NOT -to).
  Flags were removed (timing felt off). audio offset was a constant -0.15 fudge - REPLACE with
  drift-corrected mapping in v2.

## GOTCHAS (learned the hard way)
- Use raw full-precision Location (lat/lon 7+ dp). The visit_6/Location.csv was rounded to 2dp -> garbage.
- Clear __pycache__ when switching session config (stale imports gave wrong/old output).
- Inline python -c with newlines fails in this shell; write a .py and run it.
- ffmpeg: -ss before -i with -c copy snaps to packet (~21ms); fine, but the real issue was rate drift.
- Edits to files sometimes silently reverted in v1 - re-read/grep to confirm.

## V2 BUILD PLAN
1. **ingest.py**: watch inbox/ -> for each .zip: unzip to raw_sessions/<name>/; read metadata.csv;
   keep ORIGINAL filenames; OCR or prompt-match timing_sheet_*.jpg -> official lap times.
   Auto-detect multiple sessions within one recording (gap analysis on GPS + lap clustering).
2. **timing_sheet.py**: parse the dropped photo. Either Vision/OCR (numbers like 'NN-42.137') or a
   small manual confirm step. Output OFFICIAL[] + best lap per session.
3. **sync.py**: fit sensor_t = a*audio_t + b via Microphone.csv dBFS <-> audio RMS xcorr.
   Produce a rate-corrected audio for muxing. Store (a,b) per recording.
4. Port fuse/laps/clip/telemetry/dashboard; make gate lat/lon-based; everything config-free per session.
5. **One command**: `python kart/run.py inbox/<file>.zip` -> writes output/<session>/dashboard.mp4 + plots.
   Stretch: a tiny watcher (watchdog) so dropping a file Just Works.

## OPEN QUESTIONS for next session
- Confirm engine governor behavior (affects RPM ceiling sanity, not the regression method).
- Decide RPM harmonic via regression once drift-fixed.
- Two-session side-by-side "battle" dashboard (F1 split-screen) - was the Tier-2 idea.


## ==================== FINALIZED v2 SPEC (read this) ====================

### Export (decided)
- **CSV in Zip File is the ONLY required export.** Free tier. Contains all per-sensor CSVs at
  native rates, the epoch-ns `time` master clock, metadata.csv, Annotation.csv, and the audio
  (Microphone.mp4) + Headphone.csv (AirPods head motion).
- Naming Pattern: **Name + UTC** (gives a date/time fallback in the zip filename).
- Combined-CSV was evaluated and REJECTED: its resample/avg/forward-fill pre-aligns sensors
  (destroys the audio-clock-drift signal we must measure), collapses 100Hz IMU + impact spikes,
  and can strip sign/direction. We align deliberately in code, per-purpose. Do NOT use it.

### Real filename examples (drive the ingest logic)
- Recording zip:  `World_Wide_Technology_Raceway-2026-06-25_21-02-36.zip`  (= Name + UTC)
  -> zip name yields venue-ish name + a UTC datetime FALLBACK only.
- Timesheet photo: `IMG_1084.heic`  (generic iOS name -> NO info in filename).
  -> date/time AND official lap times MUST be read from INSIDE the photo (vision/OCR),
     with the timesheet's printed datetime as the authoritative session date/time.

### INPUT: FLAT venue folder; sheet-driven AUTO-SPLIT (no pre-splitting, no renaming)
You create ONE folder per venue and drop everything in flat. You do NOT split sessions or
label FP1/FP2 - the pipeline figures out sessions from the data + timing sheets.
```
inbox/
  gateway-kartplex/
    World_Wide_Technology_Raceway-2026-06-25_21-02-36.zip  <- the ONE recording (may hold N sessions)
    IMG_1084.heic   <- timing sheet for session A (any iPhone name)
    IMG_1099.heic   <- timing sheet for session B
    IMG_1090.heic   <- track map (optional)
```
FILE IDENTITY BY TYPE + CONTENT (position no longer needed; flat folder):
- `.zip`            = the Sensor Logger recording (exactly one per venue drop).
- image that looks like a RESULTS TABLE (rows of "NN-42.137" lap times) = a TIMING SHEET.
- image that looks like a MAP (track outline, TRACK ENTRANCE/EXIT) = the TRACK MAP.
  (vision classifies each image; do not rely on filename.)

### AUTO-SPLIT logic (handles 1 or N sessions in one recording, self-validating)
1. Detect candidate session WINDOWS in the recording: long GPS gaps / stationary pit periods
   between sessions + lap clustering -> approximate [t0,t1] per session on the master clock.
2. Read EACH timing sheet -> datetime (AUTHORITATIVE, see below) + lap-count + lap-time fingerprint.
3. MATCH each sheet to a window by lap-time fingerprint (lowest RMSE, like v1's 0.2s), using the
   sheet DATETIME to order/tiebreak (earlier sheet -> earlier window). This BOTH assigns the sheet
   AND validates the split. If a sheet matches no window well -> flag for manual review.
4. One matched (window + sheet) pair = one session -> one output dataset.
This same logic trivially handles the single-session case (one sheet -> one window).

### AUTHORITATIVE session datetime (from the sheet header)
The sheet header reads e.g. `Laptimes (10 min A&D) 6/25/2026 2:40 PM`. USE THIS DATE+TIME (next
to "Laptimes (10 min A&D)") as the authoritative session identity / ordering / output name /
weather lookup. The sheet also shows VISIT # and RACE # (e.g. 6th visit, 15th race) - CAPTURE
these into timesheet.json but they are SOMETIMES WRONG: never use visit#/race# for splitting,
ordering, or naming. There is NO FP1/FP2 label on A&D sheets -> name sessions by datetime.

The pipeline writes (named by the sheet datetime; type appended only if the sheet states one):
```
output/
  gateway-kartplex/
    2026-06-25_14-40/          <- {sheet-datetime}; (+_Type only if sheet states one)
      raw/                     <- untouched unzipped export (reference; original filenames)
      dataset/                 <- THE CANONICAL PRODUCT (consumers read this, never re-derive)
        session.json           <- venue, type, date/time, device, source files, + a copy of
                                  timesheet.json (all extracted sheet fields + handwritten notes)
        timesheet.json         <- EVERYTHING read from the sheet photo (laps, kart#, datetime,
                                  driver, ProSkill, position, notes verbatim, per-field confidence)
        weather.json           <- looked up from datetime+venue location (see consumer below)
        sync.json              <- audio<->sensor map sensor_t=a*audio_t+b, confidence, method
        sectors.json           <- gate (stored as lat/lon + heading) + sector fractions
        fused_trace.csv        <- 100Hz: t (master clock), E,N, lat,lon, speed, heading, yaw_rate
        laps.csv               <- flying laps: lap#, t_start, t_end, lap_time, validated, is_flyer
        aligned_100hz.parquet  <- all streams resampled to 100Hz master clock (GPS spline, IMU,
                                  head-motion, mic-dBFS) - convenience table for consumers
      (consumers later write here: dashboard.mp4, gaze/, audio_rpm/, compare/ ...)
```
OUTPUT FOLDER NAME = sheet datetime, e.g. `2026-06-25_14-40/` and `2026-06-25_15-00/`.
No FP1/FP2 (sheets don't carry it). If a future Race/Qual sheet prints a type, append it:
`2026-06-25_15-00_Race/`. Sorts chronologically; unambiguous.

### TWO-STAGE ARCHITECTURE (hard separation)
**Stage A - build the dataset** (this is the priority; visualization is NOT part of it):
  ingest(zip+photo) -> raw/ -> derive datetime -> sync(drift fit) -> fuse(GPS spline+ZUPT)
  -> detect+validate flying laps vs timesheet -> write dataset/. Pure data. No plots.
**Stage B - consumers** (separate, built later, each reads dataset/ independently):
  dashboard renderer | driver-gaze (Headphone.csv head yaw vs track heading) | audio RPM/throttle
  (single-speed RPM<->speed regression, drift-corrected) | session-vs-session battle |
  WEATHER (look up historical conditions from timesheet datetime + venue lat/lon).
Design every step as discrete with documented in/out so new consumers slot in without touching A.

### PIPELINE STEPS (Stage A), each discrete & documented
1. ingest: scan inbox/<venue>/ flat. INPUTS = exactly one .zip (recording) + images
   (.heic/.jpg/.png). IGNORE everything else gracefully (.DS_Store, stray .sqlite, etc - do not
   error). Unzip -> raw/; read metadata.csv (device, schema v, recording epoch, sensor list/rates).
   Vision-CLASSIFY each image: results-table=timing sheet (expect >=1, here 2), hand-drawn=track
   map, top-down ortho=satellite (pair with _venue/satellite_ref.json).
2. timesheet: vision-read IMG_*.heic -> extract EVERYTHING (not just lap times). The sheet is a
   rich doc; pull all printed fields AND handwritten notes into timesheet.json:
   - datetime (authoritative session date/time) + venue + session format (e.g. "10 min A&D")
   - driver name, KART NUMBER (matters; even "equal" karts vary), position/result
   - per-lap times[], best_lap, #laps, gap, ProSkill rank+points, "best of week" board
   - HANDWRITTEN NOTES verbatim (coaching cues, e.g. "better line to white box", "lift
     hair and keep on revs during turn") -> these are driver intent/self-coaching, keep them.
   - confidence per field; flag low-confidence OCR for manual confirm.
3. session-window: find this session's [t0,t1] in the recording (GPS gap + lap clustering; match
   timesheet lap count/times). Save window on master clock.
4. sync: fit sensor_t=a*audio_t+b via xcorr(Microphone.csv dBFS @sensor-clock, audio RMS).
   Report (a,b,r). a encodes the ~0.193% drift. Low r -> flag low-confidence.
5. fuse: lat/lon->ENU (anchor = first GPS fix of session, store anchor); GPS spline path (s=n*1.2^2)
   + ZUPT (speed<0.6). 100Hz. Keep recognizable track shape (NOT the corner-rounding CV Kalman).
6. laps: fixed gate (lat/lon based) crossing + auto-align to timesheet (slide window, drop out-lap).
   Mark flyers; isolate from out/in/pit.
7. write dataset/ (+ aligned_100hz.parquet). Done. Hand off to consumers.

### Gate / sectors (make venue-relative, not anchor-relative)
v1 gate was ENU coords tied to one recording's anchor. v2: store gate as **lat/lon point + heading**
and half-width; convert to each session's ENU at fuse time. Sectors as fractions [0,0.33,0.63,1.0]
= S1 ESSES, S2 STRAIGHT, S3 HAIRPIN (Gateway Kartplex T1). Re-validate per venue.


## ==================== WEATHER CONSUMER (Stage B) ====================

- Reads timesheet.json datetime (authoritative) + venue location (Gateway Kartplex,
  Madison IL ~38.65,-90.13 from the GPS anchor) -> fetch HISTORICAL weather for that
  date/time -> weather.json: temp, track-relevant humidity, wind, precip, conditions,
  pressure. Outdoor track -> conditions affect grip/lap time; lets us compare sessions
  fairly (e.g. a hot slick afternoon vs cool morning) and correlate pace with weather.
- Free historical APIs: Open-Meteo archive (no key) https://open-meteo.com/ ;
  or Meteostat. Use venue lat/lon + the session datetime+timezone (America/Chicago).
- Note: timesheet datetime is LOCAL; convert with metadata timezone for the API.

## ==================== VENUE SETUP: GATEWAY KARTPLEX T1 ====================

Provided ONCE per venue (coords by user; do NOT resolve shortlinks in code). The pipeline
CONSUMES this config: snaps each landmark to the nearest GPS-track point, then validates
(gate via lap-time RMSE). Coords are APPROXIMATE seeds - good for ballpark, refined by data.

### Landmark coordinates (lat, lon) - APPROXIMATE SEEDS (read the warning!)
- Venue center (Gateway Kartplex):  38.6486653,          -90.1354529
- Front of paddock / pit:           38.648656619119365,  -90.13557806036687
- Pit EXIT onto track:              38.648065935814756,  -90.13503748291448
- Pit ENTRANCE from track:          38.64936856149834,   -90.13451136518044
- Timing tower (TOP of S/F line):   38.64866604562608,   -90.13516231798133
- S/F line BOTTOM (approx crossing):38.64859377570983,   -90.13512208484727

### *** APPROXIMATE / ROUGH SKETCH - DO NOT BE LITERAL ***
These coords come from Google Maps pins. Google imagery coordinates and the PHONE's GPS fixes
will NOT agree exactly - different reference/registration + GPS error -> easily several meters
apart. So EVERY landmark is a SEED: snap it to the nearest point on the actual phone GPS track,
then validate by data (gate via lap-time RMSE; pit exit/entrance via speed/heading change). Never
use a raw pin coordinate as an exact gate/boundary. Sanity: S/F line = tower(38.64867,-90.13516)
-> bottom(38.64859,-90.13512) is a SHORT ~9 m segment, perpendicular to track, kart crosses ~WEST
(matches v1 gate_dir=[-1,0]). Pit entrance is up at N 38.6494 (top, "head") consistent with the
in-lap routing. Collision from the earlier draft is RESOLVED.

### Start/Finish GATE geometry (authoritative definition)
- The S/F crossing is the line from TIMING TOWER (top) to the BOTTOM point above, and it is
  **PERPENDICULAR TO THE TRACK**, NOT north-south. Kart crosses heading roughly WEST (matches
  v1 gate_dir=[-1,0]). Use the tower->bottom segment as the gate line; half-width ~12 m.
- This sits at the bottom-center of the circuit (consistent with v1 hand-tuned gate, validated
  to ~0.2s lap-time RMSE). v2: seed gate from these coords, snap to GPS track, lap-time-validate.

### Venue GeoJSON (user-confirmed on satellite) - THE reference for landmarks/paths
File: output/gateway-kartplex/_venue/venue_landmarks.geojson (9 features, validated on geojson.io).
  >>> ROUGH SKETCH ONLY. The points AND the two path LineStrings are HAND-PLACED on satellite
  >>> imagery to show LAYOUT & ROUTING (which way the pit lane loops), NOT precise geometry.
  >>> They are NOT the driven line, NOT survey-accurate, NOT to scale. The ~93.5 m / ~268.2 m
  >>> lengths and vertex positions are INDICATIVE, not measurements. Do NOT fit, snap to, or
  >>> validate against the sketch vertices. ALWAYS derive real geometry from the phone GPS;
  >>> use the sketch only to DISAMBIGUATE intent (e.g. "in-lap loops the outside of the head").
  >>> The GeoJSON file carries the same warning in its _README + per-feature notes.
Contains: 6 landmark points, the S/F gate LineString (tower->bottom, ~8.8 m, perpendicular,
crosses ~WEST), and TWO approximate pit-lane paths:
- "approx enter to track from pit"  ~93.5 m: paddock -> DOWN around the bottom-left -> pit exit.
  Stays south/low (lat ~38.6481-38.6486).
- "approx return to pit from track" ~268.2 m: track -> UP around the TOP ("head", reaches lat
  ~38.6499, ABOVE the pit-entrance pin) on the OUTSIDE pit lane -> back down to paddock.
KEY: the in-lap (268 m) is ~3x the out-lap (93 m) and loops above the head -> track-adjacent
pit pavement that LOOKS like racing track in GPS. v2 uses these corridors to classify out-lap
/in-lap and bound flying laps robustly (not gap-inference alone). Snap-validate against phone GPS.

### Pit lane routing (CRITICAL - it is NOT a simple in/out)
The pit lane runs ALL THE WAY AROUND THE OUTSIDE of the top loop ("the head"). Specifically:
- OUT-LAP: leave pit -> pit exit joins the track and goes DOWN AROUND THE LEFT bottom loop
  (the "left testicle" = bottom-left esses) before reaching the racing portion.
- IN-LAP: leave the racing line -> go UP AROUND THE TOP HAIRPIN ("head of the cock") on the
  OUTSIDE pit lane -> then DOWN to a RIGHT TURN into the pit/paddock.
=> The out/in laps traverse track-adjacent pit lane that LOOKS like track in GPS. Session-window
   detection must use the pit-exit / pit-entrance landmarks (not just "first/last motion") to
   correctly bound flying laps, and the gate-crossing count must match the timing sheet lap count.

### Track shape narrative (informal, matches GPS + hand map + satellite)
Outdoor ~704 m, 11 turns. From S/F (bottom-center) the lap runs: bottom ESSES (the two "bottom
loops"/testicles) -> up the long RIGHT-side BACK STRAIGHT (~213 m, ~55 mph top) -> into the TOP
HAIRPIN/loop ("the head") -> descent -> back to S/F. (The "cock/testicles" shorthand is the
user-recognizable shape: top loop = head, two bottom loops = testicles.)

### Venue reference inputs the user provides at kickoff (all venue-level, set ONCE)
1. Landmark COORDS above (paddock, pit-exit, pit-entrance, timing-tower-top, S/F-line-bottom).
2. Satellite SCREENSHOT (top-down; scale bar visible, e.g. ~50 ft) + its Google Maps URL
   (URL encodes center @lat,lon + scale -> lets us compute image bounds for FUTURE overlay).
3. Hand-drawn TRACK MAP from the track (numbered corners + ideal racing line + entrance/exit).
These three are complementary: satellite=accurate geometry/coords, hand map=corner numbers+line,
pins=gate & pit seeds. Store all in output/<venue>/_venue/ + a venue.json with the coords.

## ==================== TRACK MAP & CORNER IDENTITY ====================

### Track map = VENUE-level reference (not per session)
- User drops a track-map photo into the flat `inbox/<venue>/` folder, ANY iPhone name
  (e.g. IMG_1090.heic). Vision classifies it as the MAP (track outline + TRACK ENTRANCE/EXIT),
  distinct from timing-sheet images (results tables). Optional - may be absent.
- Pipeline copies it to a venue reference: `output/<venue>/_venue/track_map.<ext>`.
- The Gateway Kartplex T1 map shows: numbered corners (~1-10), hand-drawn racing line,
  apex/kerb markers (red dashes), and labeled TRACK ENTRANCE / TRACK EXIT. It visually
  matches our reverse-engineered GPS shape (independent validation of fusion).

### sectors.json carries REAL corner identity (do this in v2)
Replace/augment generic S1/S2/S3 with named, numbered corners mapped to distance-% along the
validated best lap. Goal: analysis speaks driver language ("lost 0.2s in Turn 4") not "sector 2".
Schema (per venue, reused across that venue's sessions):
```
sectors.json = {
  "venue": "gateway-kartplex",
  "lap_length_m": 704,
  "gate": {"lat":..., "lon":..., "heading_deg":..., "half_width_m":12},
  "sectors": [
    {"id":"S1","name":"ESSES",      "dist_frac":[0.00,0.33]},
    {"id":"S2","name":"STRAIGHT",   "dist_frac":[0.33,0.63]},
    {"id":"S3","name":"HAIRPIN",    "dist_frac":[0.63,1.00]}
  ],
  "corners": [   # turn-level granularity from the track map, mapped to dist-% on the lap
    {"num":1, "name":"...", "dist_frac":0.xx, "sector":"S1"},
    ... up to ~10 ...
  ]
}
```
- Corner dist-% are assigned by reading the track map against the speed-colored GPS lap
  (TASK for the v2 session, with map + GPS together). From v1 the lap runs:
  bottom esses -> up the long right straight -> top hairpin/loop -> descent -> back to S/F.
- Consumers (dashboard, delta, gaze) read corner identity from sectors.json; never hardcode.

### Georeferencing the map = LATER (explicitly deferred)
- Tier 2 (future consumer): warp map image to GPS frame via homography (3-4 correspondence
  points) to overlay actual line on the map + place corner numbers spatially. Hand-drawn,
  perspective-skewed -> limited precision. NOT in the Stage-A dataset build. Note only.


