# racecraft

Exploratory work on racing telemetry, analysis and AI tooling. Two subjects:

- **Karting.** Rental-kart sessions recorded with a phone (Sensor Logger app: 100 Hz
  IMU, 1 Hz GPS) and AirPods (engine audio, head motion), turned into lap times,
  sector splits, coaching output and replay visuals. Validated against the venue's
  printed timing sheet.
- **Formula 1.** Public telemetry via FastF1, a retrieval system over F1 history and
  engineering literature, and a scraped corpus of race commentary.

> **Status: exploratory.** Nothing here is a product or a library. Scripts and
> notebooks are research code, kept because the ideas and results are useful. Expect
> hardcoded paths, one-off diagnostics and venue-specific assumptions.

## Repository layout

| Directory | Contents |
|---|---|
| [`telemetry/`](telemetry/) | Current karting pipeline. Sensor Logger ZIP in, per-session dataset and HTML/MP4 dashboards out. |
| [`telemetry-v1/`](telemetry-v1/) | Earlier version of the karting pipeline, plus diagnostic probes and a Claude-vs-Gemini dashboard build comparison. |
| [`vision/`](vision/) | Spec and recovered artifacts for reading timing sheets and track maps from photographs. Not part of the current pipeline. |
| [`strategy-ai/`](strategy-ai/) | Hybrid BM25 + dense-vector retrieval over F1 results and engineering PDFs, using OpenSearch and Gemini. |
| [`notebooks/`](notebooks/) | Jupyter notebooks: karting at Gateway, COTA and Boschertown; FastF1 for Formula 1. |
| [`narrative/`](narrative/) | Scrapers and a small corpus of race reports and transcripts for generating race commentary. |
| [`docs/`](docs/) | Where the raw data lives on disk and how the repo is organised. |

## telemetry: the karting pipeline

Two stages. Stage A produces a validated dataset. Stage B consumes it and never
writes back.

**Stage A** (`ingestion/kart/run.py`), in order:

1. `ingest.py` unpacks the Sensor Logger export.
2. `timesheet.py` loads the pre-extracted timing-sheet JSON from `inbox/<venue>/`.
3. `sessions.py` splits one recording into separate stints. Hard gate.
4. `sync.py` fits the audio clock to the sensor clock as a drift rate, not a constant offset. Measured drift is about 0.2 %.
5. `fuse.py` fuses GPS and IMU into a 100 Hz trace using a smoothing spline with zero-velocity updates.
6. `laps.py` detects laps against the venue's start/finish gate. Hard gate. Lap times match the official sheet to roughly 0.2 to 0.3 s RMSE.
7. `write_dataset.py` writes `dataset/` (parquet trace, laps, sectors, sync and fuse metadata).

**Stage B** (`ingestion/kart/run_stage_b.py`) reads `dataset/` and writes alongside it:

| Module | Produces |
|---|---|
| `audio_rpm.py` | Engine RPM from in-helmet audio. Flagged low-confidence. |
| `sectors_timing.py` | Three sectors split by distance fraction, per-lap sector table. |
| `analytics.py` | Pace, consistency, theoretical best lap, clean-lap filtering, per-corner metrics. |
| `coaching.py`, `sector1_coaching.py` | Debrief and next-session strategy. |
| `ghost.py` | Ghost battle against an ideal lap stitched from best sectors. |
| `narrate.py` | Race-engineer narration via macOS text-to-speech. |
| `render_artifact.py` | 30 Hz render series and drift-corrected session audio. |
| `stage_b/build_dashboards.py` | Interactive HTML: onboard, cockpit, replay, ghost, coaching, sector 1. |
| `stage_b/export_video.py` | Headless Playwright capture to MP4 with synced audio. |

Derived quantities are labelled by what they are. Steering is inferred from GPS
curvature and yaw. Head yaw is an orientation proxy, not gaze. Racing-line spread is
GPS-noise dominated. Cornering g and impact g are kept on separate channels.

Venue geometry (gate, corner apexes, pit routes) lives in
`ingestion/output/<venue>/_venue/`. Two Gateway Kartplex sessions from 2026-06-25
are checked in as worked examples under `ingestion/output/gateway-kartplex/`.

### Running it

```bash
cd telemetry
python3 -m venv .venv
.venv/bin/pip install -r ingestion/requirements.txt

# Stage A, then Stage B (default venue: gateway-kartplex)
.venv/bin/python ingestion/kart/run.py
.venv/bin/python ingestion/kart/run_stage_b.py

# view dashboards
.venv/bin/python -m http.server 8800 -d ingestion/output/gateway-kartplex
# e.g. http://localhost:8800/2026-06-25_14-40/dataset/render/onboard.html
```

Stage A needs a raw recording ZIP plus its timing-sheet JSON in
`ingestion/inbox/<venue>/`. Raw recordings are not in git; see
[`docs/DATA.md`](docs/DATA.md). Video export additionally needs Playwright with
Chromium and ffmpeg.

## telemetry-v1

Earlier pipeline the current one was rebuilt from. Code only. Contains the GPS
spline fusion, gyro-based yaw, distance-aligned lap deltas, and the diagnostic
scripts (`diag_*.py`, `probe_*.py`) used to locate the start/finish gate, spins,
pit entry and impacts. `model-comparison/` holds dashboards built from the same
session by Claude and Gemini. `audio-vs-gps-validation-prompt.md` describes the
RPM-vs-speed regression used to check audio-derived RPM.

## vision

A design for reading timing sheets, hand-drawn track maps and satellite screenshots
directly from photographs, so the pipeline needs no manual transcription. The spec
is in `spec/`. What was built and kept is the image-derived venue geometry in
`recovered-artifacts/`, which still seeds gate detection in `telemetry/`. Sheet
reading was replaced with hand-extracted JSON so the pipeline could be validated
end to end. `IMAGE_CORPUS.md` catalogues the photographs on disk.

## strategy-ai

Retrieval over two layers of F1 knowledge: a 1950 to 2020 results database for what
happened, and engineering literature for why. Lexical and dense retrieval are
combined in one OpenSearch query because driver codes and lap numbers need exact
matching while questions about aerodynamics or tyres are semantic.

```bash
cd strategy-ai
docker compose up -d
export GEMINI_API_KEY=...
python chat.py
```

`hybrid.ipynb` builds the index. `hybrid-2.ipynb` iterates on the retrieval mix. The
PDF corpus is on disk, not in git.

## notebooks

- `karting/pipeline/` SQLite-based ingest, geofenced sectors, lap extraction, cross-venue ProSkill tracking.
- `karting/gateway/` Corner and braking-zone extraction, a racing-line optimizer, circuit GeoJSON with barriers, a multi-driver dashboard.
- `karting/cota/` COTA karting with H3 spatial indexing and sector GeoJSON.
- `karting/boschertown/` A third venue with its own geofence.
- `f1/` FastF1 notebooks: gear shifts on track, position changes, 2025 telemetry. `replay-viewer/` is a Flask API plus HTML page for browser race replay.

Some notebooks have outputs stripped for size. See [`docs/DATA.md`](docs/DATA.md).

## narrative

`scrape_racefans.py` and `extract_racefans.py` pull race reports. `youtube_scraper.py`
pulls transcripts. `combine_txt.py` merges them into one per-race corpus.
`glossary.txt` and `themes-and-memes.txt` are vocabulary and tone references for
generation. `corpus/` has three examples: Australia 2025, China 2025 and Singapore
qualifying.

## Data

About 34 GB of raw recordings, SQLite exports, PDFs, photographs and rendered video
back this repo and none of it is committed. [`docs/DATA.md`](docs/DATA.md) lists
where each set lives and what is regenerable.
