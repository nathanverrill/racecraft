# Kart Telemetry v2 - Stage A BUILD LOG

## 2026-07-02 - REVERSED-CIRCUIT EVENT (`gateway-kartplex-reversed`) + sessions HOME PAGE

Processed the first race event on the REVERSED Gateway Kartplex T1 layout and added a
sessions home page. The June-25 `gateway-kartplex` venue is untouched and still runs.

### Inputs (inbox/gateway-kartplex-reversed/)
- 4 timing sheets (NEW richer JSON schema): practice, qualifying, race1, race2.
  Nested `session/driver/laps/results/field_results` objects; `time_seconds` per lap;
  12h `time`; `configuration:"Reverse"`. Races carry `average_lap_seconds` (the ranking
  metric); practice/quali rank by best lap.
- 3 Sensor Logger recordings (zips, CSVs nested under a top folder):
  - `...22-56-42` driving 6:00:46-6:18:07 PM CDT (practice)
  - `...23-33-04` stationary the whole time -> DISCARDED (no driving)
  - `...02-43-37` driving 9:49:11-9:58:07 PM CDT (race2)
- User-provided reversed S/F line (2 lon/lat endpoints) -> updated `sf_gate_line` in the
  venue geojson.

### Recording <-> session MAPPING (fingerprint, reviewed)
Sheet clock times were approximate/unreliable; the SENSOR wall-clock (epoch ns) is
authoritative. Mapping by structural fit to the real S/F line (median crossing
agreement) + a light duration prior:
- practice (14 laps) <- `22-56-42` (15 clean laps; med_err 0.84s; 53.9s outlier lap
  lines up 1:1)
- race2 (9 laps) <- `02-43-37` (med_err 0.63s; 50.4s incident lap lines up)
- qualifying, race1 -> TIMING-ONLY (no telemetry; shown on home page from the sheet)

### Key design change (simpler + robust for the reversed line)
Lap detection is now SHEET-ANCHORED (the sheet lap times are ground truth):
1. `auto_gate` / real venue S/F line -> detected crossings;
2. anchor the sheet's cumulative lap times to the crossings (single offset);
3. lay lap boundaries from the sheet. No fragile per-crossing RMSE/merge/split DP.
Validation gate = median crossing agreement < 3s (reversed-circuit GPS scatter ~1.2s;
T1 spectator area is within GPS error; the straight is beyond it). CCW venue achieved
0.3s with a fixed gate; that gate is mis-placed for the reversed line, hence the
data-driven gate + looser structural gate here.

### Generalized (backward-compatible) pipeline changes
- `timesheet.py`: parse BOTH the flat (June-25) and nested (reversed) schemas; add
  `avg_lap` (mean of all laps, verbatim if provided), `ranking_metric` (best vs
  average), `configuration`, per-sheet CONSISTENCY (std/CV from sheet lap times so every
  session has a consistency headline even with no telemetry); data-driven validation
  gate (no hardcoded lap counts / bests).
- `ingest.py`: multiple recordings per venue; auto-detect the nested archive root
  (Metadata.csv); per-recording absolute time span; gate n_sheets>=1.
- `sessions.py`: detect windows across all recordings; map each sheet to the best
  window by med_err + duration prior; carry unmatched sheets as telemetry:none.
- `sync/fuse/laps/write_dataset/audio_rpm/render_artifact`: per-session recording
  (session_dir) + per-recording sync fit + per-session recording epoch (multi-recording
  safe). Tolerate empty sensor streams and missing AirPods `head_yaw` (analytics
  lookahead + render degrade gracefully).

### Results (validated)
- fuse: practice max 41.0 mph, p99 lat_g 1.92, bbox 133x228m; race2 max 41.6 mph, p99
  lat_g 2.40, bbox 102x211m. Both PASS.
- laps: practice 14 laps med_err 0.84s; race2 9 laps med_err 0.63s. PASS.
- write_dataset: 20-col parquet (no head_* - AirPods not connected), 11 corners,
  lap_len ~546/556m. PASS.
- Stage B: sectors_timing / analytics / coaching / render / ghost / sector1 / narrate /
  dashboards all PASS for both sessions. analytics clean-lap CV: practice 1.4% (12
  laps), race2 1.4% (7 laps).

### Sessions HOME PAGE (new: kart/stage_b/build_home.py)
- `output/index.html`: scans all venues' `raw/timesheets.json`; cards grouped by venue,
  headlining CONSISTENCY (CV) -> BEST lap -> AVG lap. Telemetry sessions use clean-lap
  CV + link to onboard/coaching/replay/ghost/cockpit/sector1 dashboards via a per-session
  `landing.html`; timing-only sessions (quali, race1) use sheet CV and are labelled.
- Wired into `run_stage_b.py` (regenerates after every Stage B run).
- Serve: `python -m http.server 8800 -d output` -> http://localhost:8800/index.html

### Open follow-ups
- Corner numbering & sector order are still the CCW definitions (T1..T11 / 3 sector
  gates) applied to the reversed direction, so coaching/sector LABELS run backwards.
  Stage A data + consistency/pace analytics are valid; reversed relabeling is deferred.
- Audio: `Microphone.mp4` present but engine-tone RPM regression is LOW-confidence
  (R2~0.1) as expected; RPM not used as truth. No standalone WAV master needed.
- Sync drift for these recordings is ~0 (fit R~0.68) vs the June-25 +0.216%; the audio
  clock behaved differently. Flagged CHECK (not low-confidence); does not affect Stage A
  data (master clock = sensor epoch ns).

---

# (previous) Stage A BUILD LOG


## 2026-06-27 - Stage A COMPLETE (all 7 steps validated, no vision)

Built the canonical per-session dataset for `gateway-kartplex` end-to-end, fully
offline (NO vision / NO image processing). Timing-sheet ground truth came from the
pre-extracted JSON in the inbox; venue geometry from `_venue/gateway_kartplex_t1.*`.
Every step self-validated and is checkpointed linearly in git.

### Definition of done - MET
Two session datasets under
`ingestion/output/gateway-kartplex/{2026-06-25_14-40, 2026-06-25_15-00}/dataset/`,
each with: session.json, timesheet.json, sync.json, sectors.json, fused_trace.csv,
laps.csv, aligned_100hz.parquet. Lap RMSE < 0.3s, sync reported, speed/g in bounds.
No dashboards (Stage B is out of scope).

### Pipeline (ingestion/kart/), chained by run.py
| Step | Module | Result |
|---|---|---|
| 1 ingest | ingest.py | unzip + Metadata + 7/7 required files + 2 timing JSON. PASS |
| 2 timesheet | timesheet.py | 2 sheets loaded; 14 & 13 laps; bests 40.519 / 41.164s. PASS |
| 3 sessions | sessions.py | auto-split 2 windows, matched chronologically to sheets. PASS (gate) |
| 4 sync | sync.py | sensor_t = 1.002164*audio_t - 0.967; drift +0.216%; R=0.894. PASS |
| 5 fuse | fuse.py | 100Hz; max 42.7/43.2 mph; p99 lat_g 2.40/2.41; bbox ~115x215m. PASS |
| 6 laps | laps.py | RMSE 0.279s (14:40) / 0.246s (15:00). PASS (gate, <0.3s) |
| 7 write_dataset | write_dataset.py | 7 files/session; parquet 70100/71501 x 23 cols; 11 corners. PASS |

### Validation numbers achieved
- **Timesheets** (authoritative ground truth, from JSON): 14:40 -> 14 laps, best
  40.519s; 15:00 -> 13 laps, best 41.164s. Matches V2_PLAN exactly.
- **Auto-split**: two GPS moving-windows separated by a ~6.5 min stationary pit
  period. window0 se[58.8,769.8] (701s) <-> 14:40; window1 se[1153.8,1878.8] (715s)
  <-> 15:00. (Windows include out/in laps; trimmed at lap detection.)
- **Sync (audio clock drift)**: audio container 2189.44s vs Microphone.csv span
  2193.64s. Growing-lag regression (35/35 good windows): lag grows -0.1s -> +4.3s
  across the recording => **a = 1.002164 (drift +0.216%)**, b = -0.967s, fit R=0.894.
  This is the 0.193%-class audio-clock drift root cause from V2_PLAN (measured a hair
  higher at 0.216%; within the expected band). NOT a constant offset.
- **Fusion**: GPS spline path (smoothing s = n*sigma^2 from horizontalAccuracy ~3.5m)
  + GPS-`speed`-field as speed truth + ZUPT(<0.6 m/s). 100Hz.
  - max speed 42.7 / 43.2 mph (< 57 mph cap). p99 sustained lat_g 2.40 / 2.41
    (< 2.7 tol). bbox ~115 x 215 m (sane half-mile track). yaw_rate from
    gyro.gravity_unit. acc_mag transient channel preserved (peak 7.4 g, NOT clamped).
- **Laps**: gate seeded from `sf_gate_line`, snapped to GPS, lateral offset tuned
  (+2m / -1m) and crossing-DIRECTION filtered. RMSE vs sheet **0.279s / 0.246s**
  (target <0.3s; v1 ~0.2s). Anomalous slow laps (49s, 53s) line up 1:1 with the
  sheet -> alignment is correct, not coincidental.
- **sectors.json**: gate stored as lat/lon + heading 156.5deg + half_width 12m;
  3 sectors (ESSES/STRAIGHT/HAIRPIN); all 11 corners T1-T11 snapped to the validated
  best lap with monotonically increasing dist_frac (snap 0.6-10.5m) - independent
  confirmation that the fused GPS shape matches the venue layout.

### Key decisions / surprises (vs the v1 carry-over plan)
1. **Speed truth = GPS `speed` field, not differentiated position.** The v1 note
   "speed from spline" differentiates ~3.5m GPS jitter into spurious 30-38 m/s
   spikes (first fuse attempt gave 76 mph / lat_g 4.9 - both failed bounds). Using
   the GPS-reported speed field (max ~19 m/s = 43 mph) is clean and is what V2_PLAN
   calls "speed truth". Spline is used for path shape + heading only.
2. **Crossing-direction filter is essential at this gate.** The racing line dips
   back across the S/F line in the bottom-loop esses right after S/F; an undirected
   crossing test split one lap into a spurious 7.95s + 34.80s pair (RMSE 9.98s).
   Requiring a consistent crossing direction (kart crosses ~one way each lap; venue
   notes say ~WEST) fixed session 1 to RMSE 0.279s.
3. **Sync global FFT-xcorr was too coarse** (engine drone is self-similar, peaked at
   a=1.0). Measuring LOCAL lag in windows across the recording and regressing the
   growing lag recovers the true rate. Lesson matches V2_PLAN: drift is a growing
   lag, not a constant offset.
4. Spline smoothing `s` set from GPS horizontalAccuracy (n*sigma^2) rather than the
   v1 literal `n*1.2^2`, which under-smoothed for this recording's noise level.

### Output layout
```
output/gateway-kartplex/
  _venue/  gateway_kartplex_t1.geojson + .md     (venue reference, provided)
  raw/     ingest.json, timesheets.json, sessions.json, sync.json   (intermediate)
  2026-06-25_14-40/dataset/  session,timesheet,sync,sectors .json + fused_trace.csv
                             + laps.csv + aligned_100hz.parquet
  2026-06-25_15-00/dataset/  (same)
```
`aligned_100hz.parquet` columns (23): t, seconds_elapsed, E, N, lat, lon, speed,
heading_deg, yaw_rate, acc_{x,y,z}, grav_{x,y,z}, gyro_{x,y,z}, head_{yaw,pitch,roll},
mic_dBFS, acc_mag.

### Git checkpoints (linear)
- f042c88 pre-build: switch to JSON timesheets + venue geojson, drop all vision
- 00ec1ec checkpoint(ingest)
- 4cf5561 checkpoint(timesheet)
- 77d9005 checkpoint(sessions)
- ad3804e checkpoint(sync)
- d99332c checkpoint(fuse)
- af9e8b1 checkpoint(laps)
- b645ab2 checkpoint(write_dataset)
- (this commit) Stage A complete: run.py chain + BUILD_LOG.

### Open issues / notes for the human
- **Lap length** comes out ~612-630m on the best lap (GPS driven line, spline-
  smoothed). V2_PLAN cites ~704m measured and ~539m apex-to-apex lower bound; ours
  sits between. The ~704m vs 805m marketing discrepancy is already flagged in the
  plan. Not a blocker for Stage A; revisit if a consumer needs exact lap length.
- **Sync** is recording-level (one a,b for both sessions). Per V2_PLAN the drift is
  ~linear in recording time, so the single linear map covers both windows; the
  per-session residual is small. A future refinement could fit per-session if a
  consumer needs sub-100ms audio alignment in session 2.
- **weather.json** is a Stage B consumer (not built here, by scope).
- Corners are seeded from the venue geojson and snapped to GPS; true apex refinement
  via curvature peaks is left for a consumer (sectors.json already carries usable
  dist_frac per corner).
- To re-run from scratch for this or a new venue:
  `ingestion/.venv/bin/python ingestion/kart/run.py [venue]`

## Stage B review (data/processing sanity vs real-world account)

User confirmed: one HARD wall impact at the hairpin, a few spins/wall grazes, but the
kart never crossed barriers (stayed within the "cock" track shape). Verified:
- Hard impact CONFIRMED: 14:40 se=504.5s, 7.4g, nearest corner = Turn 9 (8.5m), top
  stadium/hairpin complex, speed dropping 17->11 m/s. Matches "hairpin wall impact".
- Several 5-7g transients elsewhere = the grazes (preserved on acc_mag, not clamped).
- Track integrity OK: max inter-sample motion ~0.26 m/sample (~25 m/s, physical); no
  GPS teleport / barrier-crossing artifacts. Fusion shape is coherent.
- Sustained cornering lat_g p99 = 2.40g (track advertises ~2g) - correct. The higher
  "max" sustained value is impact-transient leakage; impacts are reported separately
  on acc_mag, so the cornering channel is not corrupted.
- "Spin" counting by yaw-rate alone is UNRELIABLE (the 180-deg hairpin at ~10 m/s is
  naturally 230-330 deg/s every lap). DECISION: dashboards surface CONFIRMED IMPACTS
  (acc_mag transients) as incident markers + show yaw_rate as a continuous rotation
  channel; we do NOT claim a spin count.
Conclusion: Stage A data + Stage B sector/analytics processing are sound. Proceeding
to render artifact + dashboards + audio-synced animation + video.

## Stage B - END-OF-STAGE deliverables (planned, build last)

### 1. TTS narration plan for the storytelling replay (replay.html)
Goal: an auto-generated voice-over track, synced to the best-lap replay, that narrates
the lap like a race engineer / broadcast commentator.
Approach (documented, build at the very end):
- SOURCE TEXT: generate per-lap narration beats from coaching.json + render.json:
  intro ("Nathan, kart 19, best lap 40.6 - here's where the time went"), per-corner
  callouts triggered at each apex's dist_frac ("Turn 1, carry more minimum speed"),
  sector-split reactions (purple/green/yellow), the hairpin-impact moment, and a closing
  summary (theoretical best, biggest opportunity).
- TIMING: each beat gets a t_session timestamp (apex times already known per lap) so the
  voice lands on the right corner. Keep beats short (<2.5s) to fit corner spacing (~3-6s).
- TTS ENGINE OPTIONS (pick at build): (a) macOS `say` -> AIFF/WAV (offline, zero-dep,
  good enough), (b) ElevenLabs / OpenAI TTS for a broadcast voice (needs key), (c)
  Piper (local neural). Default to macOS `say` for reproducibility; allow an env override.
- MIX: render each beat to a clip, place on a narration track at its timestamp (pydub or
  ffmpeg adelay+amix), DUCK the engine wav under narration (sidechain/-12dB), export
  narration.wav. The replay/video can swap session.wav -> narrated mix via a query param.
- HONESTY: narration uses only validated facts (lap/sector times, consistency, impacts,
  best-practice cues); no invented RPM. Label head-yaw cues as head-orientation.
Deliverable: kart/stage_b/narrate.py -> narration.wav + a captions.json (for subtitles).

### 2. "Lando" creative swing (build last, push creativity)
Open brief: make something cool not explicitly requested - what a top driver would
actually want. Ideas to pick from at build time (ship 1-2 of the best):
- GHOST BATTLE: your best lap vs your own theoretical-best (or 14:40 vs 15:00) racing
  side-by-side as two dots on the same map with a live gap bar - "racing yourself".
- HEAT/CONSISTENCY MAP: the track colored by where you're LEAST consistent lap-to-lap
  (variance heatmap) - instantly shows the messy bits.
- "STEAL THE TIME" IDEAL LAP: stitch the best sectors into a synthetic perfect lap and
  animate it as a gold ghost you chase.
- SHAREABLE HIGHLIGHT REEL: auto-cut a 20-30s vertical (9:16) social clip - fastest
  sector + the hairpin save - with punchy captions + engine audio, sponsor bug.
- DRIVER CARD / season-style stat card (shareable PNG): pace, consistency grade,
  top speed, "skill" rings - trading-card aesthetic.
Decision: implement GHOST BATTLE + a 9:16 SHAREABLE HIGHLIGHT REEL (most "Lando").

### 3. GRAND FINALE (build dead last): Forza-style first-person simulated replay
Goal: a cinematic, game-like onboard view - as if driving the kart in Forza - driven by
the REAL data, sunset Gateway Kartplex vibe.
Spec / approach:
- VIEW: first-person cockpit. Foreground = driver's HANDS on a kart steering wheel
  (SVG/canvas-drawn wheel + simple hand shapes, or sourced cockpit art). The wheel
  ROTATES in sync with steering inferred from data: steering angle ~ proportional to
  yaw_rate / speed (curvature), signed by turn direction; clamp + smooth so it looks
  natural. Hands counter-steer/feed realistically (wheel angle drives hand positions).
- WORLD: a pseudo-3D horizon - sunset gradient sky (orange->magenta->deep blue) behind
  a parallax silhouette of the venue/grandstands; ground plane with a perspective track
  ribbon that curves left/right based on the SAME curvature signal, speed lines / motion
  blur scaling with speed_mph. Not a real 3D engine - a faked Forza-style perspective
  (canvas) that reads the data, so it's reproducible and headless-renderable.
- IMAGERY: try to source Gateway Kartplex / WWT Raceway photos for the backdrop (user
  said "get pictures"); if unavailable offline, generate a stylized sunset skyline so it
  still ships. Store any sourced images under _venue/ and credit them.
- HUD: minimal - speed, gear-less RPM omitted (low-confidence), corner name, lap time;
  keep the sponsor bug.
- SYNC: same render.json + drift-corrected session.wav; __ready/__seekFrame hooks so the
  video exporter renders it to MP4 with engine audio, like the others.
- STEERING MODEL (honest): label as "steering inferred from GPS curvature + yaw", not a
  real wheel sensor. Validate sign against known corner directions (CCW track).
Deliverable: kart/stage_b/templates/cockpit.html + exported cockpit_bestlap.mp4.
Order of end-of-stage extras: (1) ghost battle + 9:16 reel, (2) TTS narration,
(3) THIS Forza-style cockpit LAST.

## Stage B COMPLETE (all consumers + creative finale)

Built and validated end-to-end (run_stage_b.py chains all; each step PASS):
audio_rpm (low-conf, honest) · sectors_timing · analytics (clean-lap) · coaching ·
render_artifact (+ realistic g, speed-gated impacts, inferred steering) · ghost ·
narrate (macOS say) · build_dashboards.

Interactive dashboards (self-contained HTML, audio=master clock, broadcast styling +
sponsor strip Apple/McLaren/Claude/Sodi/Honda/Gateway): onboard, coaching, replay,
ghost (you vs ideal), cockpit (Forza-style first-person, hands+wheel turn from data,
sunset world). All render headless with NO page errors at retina res.

Videos rendered (1080p30 unless noted; git-ignored, regenerable):
- story_bestlap.mp4 (both sessions) · onboard_lap11 / onboard_bestlap /
  onboard_hairpin_incident · story_narrated.mp4 (TTS coaching) ·
  reel_vertical_bestlap.mp4 (1080x1920 social) · cockpit_bestlap.mp4 (sim replay).

Key honesty calls (all documented in artifacts): RPM excluded (audio); g-forces bounded
to realistic Sodi GT5 / 170lb values with impacts on a separate speed-gated channel;
incident laps = slow laps; head-yaw = orientation proxy; steering = inferred from GPS
curvature; line-spread GPS-noise-dominated (soft signal).

Stage B is done. To regenerate: python ingestion/kart/run_stage_b.py ; then export
videos via kart/stage_b/export_video.py. See kart/stage_b/README.md.
