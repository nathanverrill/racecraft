# vision — deriving track knowledge from images alone

The premise: a session leaves behind photographs, not just sensor logs. You walk
into the office and photograph the printed timing sheet. Someone sketches the
circuit on a whiteboard. A satellite screenshot pins the venue. Each of those is
an image that carries hard numbers — lap times, corner order, georeference — and
the question is whether a model can read them well enough to anchor a telemetry
pipeline without a human transcribing anything.

## Status: specified, partly proven, then deliberately cut

This is honest history, not a roadmap fiction.

The v2 karting pipeline was originally designed vision-first. The design is in
[`spec/V2_PLAN_with_vision.md`](spec/V2_PLAN_with_vision.md) and
[`spec/prompt_with_vision.md`](spec/prompt_with_vision.md) — both recovered from
the commit *before* the vision path was removed (`f042c88`, "drop all vision/image
processing"). They specify:

- **Classification by content, never filename.** iPhone gives you `IMG_1084.heic`
  and nothing else. An image that looks like a results table (rows of `NN-42.137`)
  is a timing sheet; an image that looks like a track outline with an entrance and
  exit marked is the track map; a top-down view is the satellite reference. The
  pipeline classifies each dropped image and routes it.
- **Reading the sheet as the authoritative clock.** Session date, time, kart number,
  driver, per-lap times, best lap, ProSkill rank and finishing position all come out
  of the photograph. That datetime then *names the output folder* and drives weather
  lookup — so a misread date corrupts everything downstream. Hence per-field
  confidence scores and an explicit low-confidence flag for manual confirm.
- **Homography from map photo to GPS frame** (Tier 2): warp the hand-drawn or
  satellite image into the GPS coordinate frame via 3–4 correspondences, so corner
  labels drawn on a picture land on real telemetry.

What actually got built and validated: the **image-derived venue geometry** in
[`recovered-artifacts/`](recovered-artifacts/) — the start/finish gate, eleven corner
apex seeds, and pit routes, digitized from satellite imagery and Google Maps pins,
plus the georeference metadata tying a coordinate-free screenshot back to lat/lon.
That geometry survived the cut and still seeds the production pipeline's gate
detection. So the images-alone approach demonstrably worked for *geometry*.

What did not survive: `vision.py` and `wait_for_budget.py`. They were never committed —
only the commit message that removed them records that they existed. The timing-sheet
reading was replaced with hand-extracted JSON, and the pipeline was rebuilt with a
hard `NO VISION / NO IMAGE PROCESSING` constraint at the top of its build prompt.

## Why it was cut, and why that matters

The cut was not a verdict that vision failed. It was a *build-discipline* decision:
the v2 Stage A run was autonomous with no human in the loop, and a vision step that
silently misreads a lap time produces confidently-wrong output that every later stage
inherits. Pre-extracting the sheets to JSON removed the one step that could fail
quietly, so the pipeline could be validated end to end against ground truth (it hit
0.2–0.3 s lap RMSE). Vision was traded away for a clean validation gate.

That trade is the interesting result. Re-adding vision means earning back the gate:
the sheet read has to be *checkable* — cross-validated against detected S/F crossings
rather than trusted — before it is allowed to anchor anything.

## Rebuilding it

The input set is catalogued in [`IMAGE_CORPUS.md`](IMAGE_CORPUS.md) (photos live on
disk, not in git). `43081-sheet.HEIC` is a timing sheet with a known answer —
`43.081` is in its own filename — which makes it the natural first test: read the
sheet cold, compare to the filename, and to the lap times the telemetry pipeline
already derived independently for that session.

The validation loop is the point. A lap time read from a photograph can be checked
against a gate crossing computed from GPS; agreement to a few hundredths is a real
result, and disagreement localizes the failure to a specific field on a specific
sheet.
