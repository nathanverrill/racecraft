# How this repo was assembled

Consolidated 2026-09-01 from work scattered across `~/Downloads/Projects & Code/`
and `~/Documents/Trips & Photos/karting/`. Recorded here so the provenance of each
directory is traceable.

## Sources

| here | from | note |
|---|---|---|
| `telemetry/` | `karting-repos/karting` (github.com/nathanverrill/karting) | merged via `git subtree`; all 33 commits preserved |
| `telemetry-v1/` | `.../World_Wide_Technology_Raceway-2026-06-25_21-02-36/` | code only — `visit_6/kart/`, root scripts, `claude/` and `gemini/` build comparison |
| `vision/spec/` | `karting` repo at `f042c88^` | the vision-first plan and build prompt, recovered from before vision was removed |
| `vision/recovered-artifacts/` | same commit | `venue_landmarks.geojson`, `satellite_ref.json` — geometry digitized from satellite imagery |
| `strategy-ai/` | `f1-ai/` | code and notebooks only; the 94 MB PDF corpus stayed on disk |
| `notebooks/karting/` | `Karting/`, `cota-karting/` | notebooks plus small GeoJSON/CSV config; SQLite and multi-hundred-MB JSON excluded |
| `notebooks/f1/` | `f1/`, `Karting/f1.ipynb` | FastF1 analysis and the replay viewer |
| `narrative/` | `F1 Music/` | scrapers, glossary, and three race-report corpora |

## Excluded, deliberately

- **`f1-race-replay/`** (2.1 GB) — a clean clone of `IAmTomShaw/f1-race-replay` with
  zero local commits. Not my work; the Bayesian tyre-degradation model in it is
  upstream's.
- **`Karting/f1/2025/`** — TracingInsights' published 2025 telemetry dataset.
- All raw data — see [`DATA.md`](DATA.md).

## Secrets

A Gemini API key was hardcoded in `f1-ai/chat.py` and had also leaked into
`f1-ai/rag/hybrid.ipynb`. Both were scrubbed before the first commit here; the key
reads from the environment now. **That key was in plaintext on disk and should be
rotated in Google AI Studio regardless** — nothing in this repo makes it safe again.
