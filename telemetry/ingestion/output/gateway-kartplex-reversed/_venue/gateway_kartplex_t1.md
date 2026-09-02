# Gateway Kartplex — Track 1 (T1) — Venue Reference

Reference for coding agents processing/analyzing kart racing telemetry (Sensor Logger GPS) at this venue. Pairs with `gateway_kartplex_t1.geojson`.

> **Read this first.** Every coordinate in the companion GeoJSON is an **approximate seed** hand-placed on satellite imagery. None of it is survey-grade, and satellite imagery is offset from phone GPS by several meters. Treat the GPS track as geometry truth and use these landmarks only as starting points to snap-and-validate against. See [Provenance & caveats](#provenance--caveats).

## Identity

| Field | Value |
|---|---|
| Venue | Gateway Kartplex |
| Track | Track 1 (T1) |
| Located in | World Wide Technology Raceway |
| Address | 700 Raceway Blvd, Madison, IL 62060 |
| Plus code | JVX7+HX Madison, Illinois |
| Approx. venue center | 38.6486624, -90.135464 (lat, lon) |
| **Racing direction** | **Counterclockwise** |
| CRS | WGS84 (EPSG:4326). GeoJSON uses lon/lat order. |

Approximate landmark footprint (from seed points): ~100 m E–W × ~210 m N–S. The paddock, pit lane, and start/finish all sit on the **west / northwest side** of the circuit, adjacent to the main building and parking lot.

## Layout

The circuit is a single road-course loop run **counterclockwise**, with the pit/paddock complex on the NW side. From the annotated track map, three character zones make up the lap:

1. **Start/finish & technical NW complex** — near the timing tower and building. Tight, low-speed corner work; this is where the S/F gate sits and where pit out-/in-lanes connect.
2. **Connecting esses** — a flowing S/descending section linking the NW complex to the southern end of the property.
3. **Southern technical loop** — the far end of the circuit: a multi-apex hairpin/ess complex (the longest sustained sequence of direction changes), before the track returns north toward S/F.
4. **Track entrance** feeds in near a tight left hairpin (annotated as Turn 1 on the map); **track exit** returns karts to the pit.

### Corners

**11 numbered corners (T1–T11)**, run counterclockwise. Approximate apex seeds are in the GeoJSON as `turn_1`…`turn_11` (each `role: corner`, with a `seq` field). These are hand-placed on satellite imagery — **derive true apexes from GPS** (curvature / heading-rate peaks); use the seeds only to label/associate.

| Turn | apex lon, lat (approx) | leg into turn | notes |
|---|---|---|---|
| S/F | -90.1351422, 38.6486299 | — | gate, NW side |
| T1 | -90.1354567, 38.6484393 | ~35 m from S/F | left hairpin near track entrance |
| T2 | -90.1346456, 38.6485682 | ~72 m | |
| T3 | -90.1349040, 38.6481618 | ~50 m | southern technical complex |
| T4 | -90.1346133, 38.6481926 | ~25 m | |
| T5 | -90.1344518, 38.6484841 | ~35 m | onto the long straight |
| T6 | -90.1347461, 38.6497594 | **~144 m (long straight)** | top of northern complex |
| T7 | -90.1349902, 38.6497818 | ~21 m | |
| T8 | -90.1350260, 38.6496220 | ~18 m | tight stadium section |
| T9 | -90.1348251, 38.6495856 | ~18 m | |
| T10 | -90.1348574, 38.6492829 | ~34 m | |
| T11 | -90.1348610, 38.6487840 | ~56 m | returns toward S/F |
| (S/F) | — | ~30 m | lap close |

- **Orientation confirmed CCW** by signed-area of the apex loop.
- **Apex-to-apex polyline ≈ 539 m** (S/F→T1…T11→S/F). This is a **lower bound** on lap length — the driven line through the curves is longer.
- The single long straight is **T5 → T6 (~144 m)**, up the east side of the property; everything else is closely-spaced corner work. The southern complex (T1–T5) and the northern stadium complex (T6–T11) are the two technical zones.

## Landmark inventory

All entries below are in the companion GeoJSON, keyed by `id`. All are flagged `approximate`.

| id | role | lon, lat (approx) | pipeline use |
|---|---|---|---|
| `sf_gate` | start/finish gate (derived midpoint) | -90.1351422, 38.6486299 | lap detection |
| `sf_gate_line` | S/F gate **segment** (tower → bottom) | see geojson | lap detection (segment crossing) |
| `sf_top` | timing tower / S/F top endpoint | -90.1351623, 38.6486660 | S/F segment endpoint |
| `sf_bottom` | S/F bottom endpoint | -90.1351221, 38.6485938 | S/F segment endpoint |
| `pit_exit` | pit exit onto track | -90.1350375, 38.6480659 | out-lap detection |
| `pit_entrance` | pit entrance from track | -90.1345114, 38.6493686 | in-lap detection |
| `paddock` | front of paddock / pit | -90.1355781, 38.6486566 | idle/staging context |
| `venue_center` | venue center | -90.135464, 38.6486624 | map centering only |
| `pit_route_out` | pit-out route **sketch** | LineString | context only (which side it loops) |
| `pit_route_in` | pit-in route **sketch** | LineString | context only (which side it loops) |
| `turn_1`…`turn_11` | corner apex seeds (`seq` 1–11) | see geojson | per-corner min-speed, apex timing, mini-sectors |

## Derived start/finish geometry

Computed from the two S/F endpoints (`sf_top`, `sf_bottom`). Approximate — re-fit against GPS.

| Quantity | Approx value |
|---|---|
| Gate midpoint (lon, lat) | -90.1351422, 38.6486299 |
| Gate length | ~8.8 m |
| Gate bearing (top → bottom) | ~156.5° (runs NNW–SSE) |
| Track heading at S/F (⊥ to gate) | ~66.5° or ~246.5° — resolve the sense from the GPS direction of travel |

This supports an **angled, offset-tolerant S/F crossing test** (closest-approach against the gate segment rather than a single point), which is the correct method given GPS jitter and the fact that the line is not square to the track.

## Pipeline integration notes

- **Lap detection** — test for crossings of the `sf_gate_line` **segment**, not proximity to a single point. Use a closest-approach / angled-crossing method that tolerates lateral GPS offset. Tune gate position/angle by **minimizing lap-time RMSE** across crossings.
- **Out-laps** — a lap that begins at `pit_exit` is an out-lap; exclude or flag it. Validate the seed against a **speed/heading discontinuity** where the kart rejoins the racing line.
- **In-laps** — a lap that ends at `pit_entrance` is an in-lap; exclude or flag it. Same speed/heading validation.
- **Direction** — laps run counterclockwise; use this to disambiguate the crossing sense and to sanity-check heading at S/F.
- **Snapping** — for any landmark, snap to the nearest point on the actual GPS track before using it; do not consume raw seed coordinates.

## Provenance & caveats

- **Source of seeds:** points and paths hand-placed on Google Maps satellite imagery by the user to convey **layout and routing**, not precise geometry. Not survey data; not the driven line.
- **Imagery offset:** Google satellite coordinates differ from the phone GPS by several meters. **Phone GPS is the geometry truth.**
- **Use as seeds only:** snap every landmark to the GPS track and validate by data (S/F gate via lap-time RMSE; pit exit/entrance via speed/heading).
- **Pit-route LineStrings** are coarse, few-vertex sketches of *which side* the pit lane loops — not smooth, not to scale, not the driven path.
- **Corner apexes** (`turn_1`…`turn_11`) are approximate seeds hand-placed on imagery; derive **true** apexes from GPS curvature/heading-rate and use the seeds only to label them.
- **Satellite overlay (deferred / Tier-2):** georeferencing the satellite screenshot is a separate, deferred task. The screenshot itself carries no embedded coordinates; its center and scale come from the Maps URL (`@38.6490038,-90.1350350,270m`, 100 ft scale bar visible). The Stage-A dataset build does **not** need the overlay.

## Source files

- `gateway_kartplex_t1.geojson` — companion machine-readable landmarks (this doc's geometry).
- `venue_landmarks.geojson` — original user-supplied seed landmarks.
- `satellite_ref.json` — georeference metadata for the satellite screenshot (deferred Tier-2 overlay).
- Google Maps satellite screenshot + hand-annotated track map (layout reference).
