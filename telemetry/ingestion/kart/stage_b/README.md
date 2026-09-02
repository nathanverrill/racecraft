# Kart Telemetry v2 — Stage B (consumers): analysis, dashboards, video

Stage B reads the canonical per-session `dataset/` produced by Stage A and turns it
into **coaching analysis** and **broadcast-grade visuals**. It never modifies Stage A.

> Driver focus: **consistency & where to find time.** Best line, where to look,
> per-sector and per-turn consistency, biggest opportunities, karting best-practice
> cues, and a next-session strategy — plus cinematic, shareable, audio-synced replays.

## Run everything

```bash
# 1) build all consumer artifacts (analysis + render data + dashboards)
ingestion/.venv/bin/python ingestion/kart/run_stage_b.py gateway-kartplex

# 2) view the interactive dashboards (static server at the venue root)
ingestion/.venv/bin/python -m http.server 8800 -d ingestion/output/gateway-kartplex
#   then open:
#   http://localhost:8800/2026-06-25_14-40/dataset/render/onboard.html   (onboard broadcast)
#   http://localhost:8800/2026-06-25_14-40/dataset/render/coaching.html  (debrief)
#   http://localhost:8800/2026-06-25_14-40/dataset/render/replay.html    (cinematic best lap)

# 3) export a video (headless render + synced engine audio)
ingestion/.venv/bin/python ingestion/kart/stage_b/export_video.py \
  ingestion/output/gateway-kartplex/2026-06-25_14-40/dataset/render \
  --html onboard.html --lap 11 --fps 30
```

## Pipeline (each module reads dataset/, writes alongside it)

| Module | Output | What it does |
|---|---|---|
| `audio_rpm.py` | `audio_rpm.{csv,json}` | best-effort engine RPM from audio — **flagged low-confidence** (AirPod audio thins the engine tone; tone-vs-speed R²≈0.1). Not used as truth. |
| `sectors_timing.py` | `sector_times.csv`, sector gates in venue geojson | 3 physical sectors (S1 S/F→T5, S2 straight→T9, S3 T9→S/F) via **distance-fraction** splits (robust to line variation / GPS jolts). |
| `analytics.py` | `analytics.json` | pace + **consistency (std/CV)** per lap & sector, theoretical best, opportunity ranking, priority quadrant, delta-vs-ghost, per-corner apex/line/braking, **clean-lap filtering** (incident = slow lap). |
| `coaching.py` | `coaching.json` | **debrief + next-session strategy**: per-turn consistency scores, where-to-look cues, best-practice rules, incidents (slow laps + impact locations). |
| `render_artifact.py` | `render/render.json`, `render/session.wav` | compact 30 Hz series + **drift-corrected** per-session WAV (audio.currentTime maps 1:1 to telemetry t). |
| `stage_b/build_dashboards.py` | `render/*.html` | copies interactive dashboards next to their data. |
| `stage_b/export_video.py` | `video/*.mp4` | Playwright headless frame capture → ffmpeg → mux synced audio. |
| `stage_b/design_mock.py` | `dashboards/design_{A,B}.png` | static design mockups (matplotlib). |
| `stage_b/shoot.py` | PNG | headless screenshot/QA of any dashboard at time t. |

## Dashboards

- **onboard.html** — broadcast onboard: track map + glowing moving dot + speed-colored
  trail, big speed, rev-light strip, speed/g traces, g-g circle, live F1 sector panel
  (purple/green/yellow), impact ★ markers, play/scrub/speed/lap-jump. **Audio = master clock.**
- **coaching.html** — the debrief: improvement-priority quadrant (hero), opportunity
  bars, per-sector consistency ratings, per-turn consistency table with where-to-look
  cues, incidents, next-session strategy + 10-min session plan.
- **replay.html** — cinematic camera-follow **best-lap** replay; shareable.
- **ghost.html** — **GHOST BATTLE**: race your best lap (cyan) vs the IDEAL lap (gold,
  best of every sector) with a live gap bar.
- **cockpit.html** — **Forza-style first-person SIM REPLAY**: sunset Gateway world,
  perspective track that curves with your steering, hands on a wheel that rotate from
  the inferred steering signal, engine audio. (Steering is inferred from GPS curvature
  + yaw — not a wheel sensor.)

All carry a subtle motorsport **sponsor strip** (Apple · McLaren · Claude · Sodi ·
Honda · Gateway Kartplex).

## Videos (kart/stage_b/export_video.py)

Rendered into each session's `video/` (git-ignored, regenerable). Flags: `--html`,
`--lap N` or `--t0/--t1`, `--fps`, `--w/--h` (e.g. 1080×1920 for a vertical reel),
`--relative-seek` (replay/cockpit), `--audio narration.wav`.
Examples produced: `onboard_*.mp4`, `story_bestlap.mp4`, `story_narrated.mp4`,
`reel_vertical_bestlap.mp4` (9:16), `cockpit_bestlap.mp4`.

## Narration (kart/narrate.py)

TTS race-engineer voice-over for the best lap: coaching beats timed to apexes,
synthesized via macOS `say` (override voice with `KART_TTS_VOICE`), engine audio ducked
under speech → `render/narration.wav` + `render/captions.json`. Export a narrated video
with `--audio narration.wav`.

## Honesty / data-quality notes (baked into the artifacts)

- **RPM** is not reliably recoverable from the in-helmet AirPod audio → flagged, excluded.
- **g-forces** are bounded to realistic Sodi GT5 / ~170 lb-driver values: sustained
  lateral ~2 g, braking ~1.2 g, accel ~0.4 g. High transients (kerb/wall, incl. the
  7.4 g hairpin hit at T9) live on a **separate impact channel** and are **speed-gated**
  (a high-g event is only kept if the kart had the speed to produce it).
- **Incident laps** = significantly slower laps (>5% off best); excluded from consistency
  stats. Impact **locations** are reported, not used to invalidate laps.
- **Head-yaw / "where to look"** is a **head-orientation proxy** (AirPods), not eye-tracking.
- **Line spread (m)** is GPS-noise-dominated → soft secondary signal; consistency score is
  driven mainly by repeatable **apex speed**.

## Re-tuning

- **Sector split points**: `SPLIT_FRACS` in `sectors_timing.py` (default 0.45, 0.83).
- **Gate**: Stage A tunes the S/F gate offset; sector gates are derived + written into
  `_venue/gateway_kartplex_t1.geojson` as `sector_2_gate` / `sector_3_gate`.
- **Incident threshold**: `best*1.05` in `analytics.py`.
- **Render rate**: `RENDER_HZ` in `render_artifact.py` (default 30).

## Planned (end-of-stage extras, see BUILD_LOG.md)
TTS narration for the replay; ghost-battle + 9:16 highlight reel; and a **Forza-style
first-person cockpit replay** (hands + steering wheel turning from the data, sunset
Gateway backdrop).
