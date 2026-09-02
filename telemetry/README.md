# telemetry

The karting pipeline, its web front end and Dockerfile. See the
[top-level README](../README.md) for the quickstart and a description of each stage.

- `Dockerfile`, `docker-entrypoint.sh`: the image behind `ghcr.io/nathanverrill/racecraft`.
- `ingestion/kart/`: Stage A (`run.py`), Stage B (`run_stage_b.py`), the browser
  front end (`webapp.py`) and the terminal debrief (`show_coaching.py`).
- `ingestion/kart/stage_b/README.md`: per-module detail for Stage B and video export.
- `ingestion/inbox/<venue>/`: recording ZIP plus timing-sheet JSON. The sample session is here.
- `ingestion/output/<venue>/`: venue geometry in `_venue/`, one directory per session.
- `ingestion/V2_PLAN.md`, `ingestion/prompt.md`, `ingestion/BUILD_LOG.md`: the plan
  and build notes the pipeline was written from.
