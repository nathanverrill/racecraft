# Where the data lives

Roughly 34 GB of raw and derived data backs this repo and none of it is in git.
Individual files run to 400 MB, which GitHub rejects outright, and all of it is
either a raw capture (irreplaceable, belongs in backup, not version control) or
regenerable by running the pipeline.

Paths are as of 2026-09-01, on this Mac.

## Karting — raw captures

| what | where |
|---|---|
| Gateway Kartplex, 2026-06-25 (2 sessions) + reversed layout, 2026-07-01 | `~/Documents/Trips & Photos/karting/kart_v2/inbox/` |
| The same, unpacked, plus the v1 working tree | `~/Documents/Trips & Photos/karting/World_Wide_Technology_Raceway-2026-06-25_21-02-36/` |
| COTA, 2025-09-21 (Sensor Logger ZIPs + derived JSON) | `~/Downloads/Projects & Code/cota-karting/` |
| Gateway / COTA / Boschertown SQLite exports, 2025 season | `~/Downloads/Projects & Code/Karting/data/`, `Karting/Gateway/`, `Karting/COTA/` |
| AMP karting | `~/Downloads/Projects & Code/amp-karting/` |
| Photographs (timing sheets, track sketches, event) | `~/Downloads/Projects & Code/karting-repos/karting/Kartplex First Race iDrive/` — catalogued in [`../vision/IMAGE_CORPUS.md`](../vision/IMAGE_CORPUS.md) |

To run `telemetry/`, drop a recording ZIP plus its pre-extracted timing-sheet JSON
into `telemetry/ingestion/inbox/<venue>/`, flat. The pipeline splits sessions itself.

## F1

| what | where |
|---|---|
| f1db results dump, FastF1 cache | `~/Downloads/Projects & Code/f1/` |
| RAG corpus: race results, aero/composites/Cosworth PDFs (94 MB) | `~/Downloads/Projects & Code/f1-ai/rag/data/` |
| Scraped race reports and commentary | `~/Downloads/Projects & Code/F1 Music/australia/` |

FastF1 re-downloads its own cache on demand, so nothing there is precious.

## Notebook outputs

Four notebooks had their outputs stripped to get under GitHub's 1 MB render limit
(`karting_notebook_v2`, `karting-notebook-amp`, `karting-notebook`, `boschertown` —
21 MB, 13.5 MB, 4.5 MB and 11.4 MB respectively). The originals, with plots intact,
are at the paths above. Re-running against the local data regenerates them.
