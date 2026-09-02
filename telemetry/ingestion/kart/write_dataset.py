"""write_dataset.py - Stage A Step 7 (assemble the canonical dataset/ per session).

Writes, per session, under output/<venue>/<key>/dataset/:
  - session.json          venue/type/datetime/device/source + embedded timesheet
  - timesheet.json        copy of the pre-extracted sheet (canonical fields)
  - sync.json             copy of the recording-level audio<->sensor fit (a,b,r)
  - sectors.json          gate (lat/lon + heading + half-width), sector fractions,
                          corners[] (T1..T11 from venue geojson, dist-% on best lap)
  - fused_trace.csv       (already written in Step 5)
  - laps.csv              (already written in Step 6)
  - aligned_100hz.parquet all streams resampled to the 100 Hz master-clock grid:
                          fused (E,N,lat,lon,speed,heading,yaw_rate) + IMU accel +
                          gravity + gyro + head-motion (yaw/pitch/roll) + mic dBFS

VALIDATE: every file exists; parquet row counts/columns sane.
"""
from __future__ import annotations
import sys
import math
from pathlib import Path
import numpy as np
import pandas as pd

from common import (RAW_SESSIONS, OUTPUT, NS_PER_S, load_json, write_json,
                    venue_geojson, venue_feature, lonlat_to_enu)
import timesheet as ts_mod

# sector fractions for Gateway Kartplex T1 (V2_PLAN): S1 ESSES, S2 STRAIGHT, S3 HAIRPIN
SECTORS = [
    {"id": "S1", "name": "ESSES", "dist_frac": [0.00, 0.33]},
    {"id": "S2", "name": "STRAIGHT", "dist_frac": [0.33, 0.63]},
    {"id": "S3", "name": "HAIRPIN", "dist_frac": [0.63, 1.00]},
]


def _resample_csv(path, grid_ns, cols, prefix):
    # some Sensor Logger streams can be empty (e.g. no Headphone/AirPods connected);
    # tolerate missing/empty files and just skip those columns.
    try:
        if not path.exists() or path.stat().st_size == 0:
            return {}
        df = pd.read_csv(path)
    except (pd.errors.EmptyDataError, FileNotFoundError):
        return {}
    if "time" not in df.columns or len(df) == 0:
        return {}
    t = df.time.values.astype(np.int64)
    out = {}
    for c in cols:
        if c in df.columns:
            out[f"{prefix}{c}"] = np.interp(grid_ns, t, df[c].values.astype(float))
    return out


def build_aligned(sd, fused, grid_ns):
    data = {
        "t": fused.t.values.astype(np.int64),
        "seconds_elapsed": fused.seconds_elapsed.values,
        "E": fused.E.values, "N": fused.N.values,
        "lat": fused.lat.values, "lon": fused.lon.values,
        "speed": fused.speed.values,
        "heading_deg": fused.heading_deg.values,
        "yaw_rate": fused.yaw_rate.values,
    }
    data.update(_resample_csv(sd / "Accelerometer.csv", grid_ns, ["x", "y", "z"], "acc_"))
    data.update(_resample_csv(sd / "Gravity.csv", grid_ns, ["x", "y", "z"], "grav_"))
    data.update(_resample_csv(sd / "Gyroscope.csv", grid_ns, ["x", "y", "z"], "gyro_"))
    data.update(_resample_csv(sd / "Headphone.csv", grid_ns,
                              ["yaw", "pitch", "roll"], "head_"))
    data.update(_resample_csv(sd / "Microphone.csv", grid_ns, ["dBFS"], "mic_"))
    # acc_mag (transient impact channel; NOT clamped)
    if all(f"acc_{a}" in data for a in "xyz"):
        data["acc_mag"] = np.sqrt(data["acc_x"]**2 + data["acc_y"]**2 + data["acc_z"]**2)
    return pd.DataFrame(data)


def sectors_json(venue, gate_coords, fused, laps_df, anchor):
    # gate as lat/lon + heading (perpendicular-to-track crossing line)
    (lon0, lat0), (lon1, lat1) = gate_coords[0], gate_coords[1]
    midlon, midlat = (lon0 + lon1) / 2, (lat0 + lat1) / 2
    # heading of gate line (deg from north)
    e, n = lonlat_to_enu([lon0, lon1], [lat0, lat1], anchor["lon"], anchor["lat"])
    gate_bearing = (math.degrees(math.atan2(e[1] - e[0], n[1] - n[0]))) % 360
    # corners from venue geojson, mapped to dist-% on the best lap
    gj = venue_geojson(venue)
    corners = []
    # find best lap (min lap_time) -> its [t_start,t_end]; build distance profile
    best = laps_df.loc[laps_df.lap_time_s.idxmin()]
    seg = fused[(fused.t >= best.t_start_ns) & (fused.t <= best.t_end_ns)].reset_index(drop=True)
    if len(seg) > 10:
        dE = np.diff(seg.E.values); dN = np.diff(seg.N.values)
        dist = np.concatenate([[0], np.cumsum(np.sqrt(dE**2 + dN**2))])
        total = dist[-1]
        for ft in gj["features"]:
            p = ft["properties"]
            if p.get("role") != "corner":
                continue
            clon, clat = ft["geometry"]["coordinates"]
            ce, cn = lonlat_to_enu([clon], [clat], anchor["lon"], anchor["lat"])
            d2 = (seg.E.values - ce[0])**2 + (seg.N.values - cn[0])**2
            k = int(np.argmin(d2))
            frac = float(dist[k] / total) if total > 0 else 0.0
            # assign sector by fraction
            sec = next((s["id"] for s in SECTORS
                        if s["dist_frac"][0] <= frac < s["dist_frac"][1]), "S3")
            corners.append({"num": p.get("seq"), "name": p.get("name"),
                            "dist_frac": round(frac, 3), "sector": sec,
                            "snap_dist_m": round(float(math.sqrt(d2[k])), 1)})
        corners.sort(key=lambda c: c["dist_frac"])
    return {
        "venue": venue,
        "lap_length_m": round(float(total), 1) if len(seg) > 10 else None,
        "racing_direction": gj.get("metadata", {}).get("racing_direction"),
        "gate": {"lat": round(midlat, 8), "lon": round(midlon, 8),
                 "heading_deg": round(gate_bearing, 1), "half_width_m": 12,
                 "endpoints_lonlat": gate_coords,
                 "note": "S/F gate line (tower->bottom), perpendicular to track; "
                         "seed from venue geojson, lateral offset tuned to min lap RMSE."},
        "sectors": SECTORS,
        "corners": corners,
        "corners_note": "T1..T11 apex seeds from venue geojson snapped to the validated "
                        "best-lap GPS; dist_frac is position along that lap (0=S/F).",
    }


def run(venue: str = "gateway-kartplex") -> dict:
    print("=" * 64)
    print(f"[write_dataset] STEP 7  venue={venue}")
    print("=" * 64)
    ingest = load_json(OUTPUT / venue / "raw" / "ingest.json")
    sessions = load_json(OUTPUT / venue / "raw" / "sessions.json")["sessions"]
    sync = load_json(OUTPUT / venue / "raw" / "sync.json")
    sheets = {s["session_key"]: s for s in ts_mod.run(venue)}
    default_sd = RAW_SESSIONS / ingest["zip_stem"]
    gj = venue_geojson(venue)
    gate_coords = venue_feature(gj, "sf_gate_line")["geometry"]["coordinates"]

    all_ok = True
    for ses in sessions:
        key = ses["session_key"]
        sd = Path(ses["session_dir"]) if ses.get("session_dir") else default_sd
        # per-recording sync fit if available, else the top-level (first) fit
        rec_sync = (sync.get("per_recording", {}).get(str(sd), sync))
        ds = OUTPUT / venue / key / "dataset"
        fused = pd.read_csv(ds / "fused_trace.csv")
        laps_df = pd.read_csv(ds / "laps.csv")
        fmeta = load_json(ds / "_fuse_meta.json")
        lmeta = load_json(ds / "_laps_meta.json")
        anchor = fmeta["anchor"]
        sheet = sheets[key]

        # timesheet.json (canonical copy)
        write_json(ds / "timesheet.json", sheet)
        # sync.json (recording-level for THIS session's recording)
        write_json(ds / "sync.json", rec_sync)
        # sectors.json
        sec = sectors_json(venue, gate_coords, fused, laps_df, anchor)
        write_json(ds / "sectors.json", sec)
        # session.json
        session = {
            "venue": venue,
            "session_key": key,
            "datetime_local": sheet["datetime_local"],
            "type": sheet.get("session_type"),
            "event": sheet["event"],
            "configuration": sheet.get("configuration"),
            "device": ingest["metadata"]["device"],
            "schema_version": ingest["metadata"]["version"],
            "timezone": ingest["metadata"]["timezone"],
            "recording_zip": ses.get("recording", ingest.get("zip_name")),
            "source_timesheet_json": sheet["source_json"],
            "window_master_clock_ns": [ses["window"]["t0_ns"], ses["window"]["t1_ns"]],
            "anchor_lonlat": anchor,
            "results": {
                "ranking_metric": sheet.get("ranking_metric"),
                "best_lap_s": sheet.get("best_lap"),
                "avg_lap_s": sheet.get("avg_lap"),
                "position": sheet.get("position"),
                "field_size": sheet.get("field_size"),
                "consistency": sheet.get("consistency"),
            },
            "fusion": {"rate_hz": 100, "max_speed_mph": round(fmeta["max_speed_mph"], 1),
                       "p99_lat_g": round(fmeta["p99_latg"], 2)},
            "laps": {"n_flying": int(len(laps_df)),
                     "rmse_vs_sheet_s": round(lmeta["rmse"], 3),
                     "best_detected_s": round(lmeta["best_detected"], 3),
                     "sheet_best_s": lmeta["sheet_best"]},
            "sync": {"a": rec_sync["a"], "b": rec_sync["b"], "fit_R": rec_sync["fit_R"],
                     "drift_pct": rec_sync["drift_pct"],
                     "low_confidence": rec_sync["low_confidence"]},
            "timesheet": sheet,
            "dataset_files": ["session.json", "timesheet.json", "sync.json",
                              "sectors.json", "fused_trace.csv", "laps.csv",
                              "aligned_100hz.parquet"],
        }
        write_json(ds / "session.json", session)

        # aligned_100hz.parquet
        grid_ns = fused.t.values.astype(np.int64)
        aligned = build_aligned(sd, fused, grid_ns)
        aligned.to_parquet(ds / "aligned_100hz.parquet", index=False)

        # validate files + parquet
        need = ["session.json", "timesheet.json", "sync.json", "sectors.json",
                "fused_trace.csv", "laps.csv", "aligned_100hz.parquet"]
        missing = [f for f in need if not (ds / f).exists()]
        n_rows = len(aligned)
        n_cols = aligned.shape[1]
        ok = (not missing and n_rows == len(fused) and n_cols >= 20
              and len(sec["corners"]) >= 9)
        all_ok &= ok
        print(f"[write_dataset] {key}: files={'all' if not missing else missing} | "
              f"parquet {n_rows} rows x {n_cols} cols | corners mapped={len(sec['corners'])} "
              f"| lap_len~{sec['lap_length_m']}m | {'OK' if ok else 'CHECK'}")

    print("-" * 64)
    print(f"[write_dataset] STATUS: {'PASS' if all_ok else 'CHECK'}")
    print("-" * 64)
    return {"ok": all_ok}


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "gateway-kartplex")
