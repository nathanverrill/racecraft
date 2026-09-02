# notebooks

Exploratory analysis, kept for the ideas in it rather than as production code. The
pipeline in [`../telemetry/`](../telemetry/) is where anything that worked ended up.

## karting/

- **`pipeline/`** — the SQLite-era ingest: merging Sensor Logger exports into one
  database, geofenced sector assignment from LineString definitions, and lap
  extraction by start/finish crossing. `race-analysis.ipynb` is the cross-venue view,
  tracking ProSkill rating change across visits.
- **`gateway/`** — the deepest single-venue work. Corner and braking-zone extraction,
  a **racing-line optimizer**, circuit GeoJSON with barriers and boundary pins, and a
  multi-driver dashboard comparing four drivers over the same laps.
- **`cota/`** — COTA karting, including H3 spatial indexing of the trace and sector
  GeoJSON.
- **`boschertown/`** — a third venue, with its own geofence.

## f1/

FastF1 work: gear shifts mapped onto the track, position changes across a race, and
2025 session telemetry. `replay-viewer/` is a browser-based race replay.

Four notebooks here had outputs stripped for size — see [`../docs/DATA.md`](../docs/DATA.md).
