"""common.py - shared paths, constants, and small helpers for the Stage A pipeline.

NO VISION anywhere. Timing data comes from pre-extracted *.json; venue geometry
from _venue/*.geojson. The master clock is `time` (epoch nanoseconds).
"""
from __future__ import annotations
import json
import math
from pathlib import Path

# ---- paths ---------------------------------------------------------------
REPO = Path(__file__).resolve().parents[1]          # ingestion/
INBOX = REPO / "inbox"
RAW_SESSIONS = REPO / "raw_sessions"
OUTPUT = REPO / "output"

REQUIRED_CSVS = [
    "Location.csv", "Accelerometer.csv", "Gyroscope.csv",
    "Gravity.csv", "Microphone.csv", "Headphone.csv",
]
AUDIO_FILE = "Microphone.mp4"
METADATA_FILE = "Metadata.csv"

NS_PER_S = 1_000_000_000

# Ground-truth bounds (from official track facts; see V2_PLAN)
MAX_SPEED_MS = 25.5          # ~57 mph cap on fused speed
SUSTAINED_LATG_CAP = 2.2     # sustained cornering g (impacts may exceed)


# ---- json helpers --------------------------------------------------------
def load_json(p: Path) -> dict:
    with open(p) as f:
        return json.load(f)


def write_json(p: Path, obj: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(obj, f, indent=2)


# ---- ENU conversion (equirectangular about an anchor) --------------------
EARTH_R = 6_371_000.0  # m


def lonlat_to_enu(lon, lat, lon0, lat0):
    """Vectorizable equirectangular lon/lat (deg) -> local ENU meters about anchor.
    E = east, N = north. Good for a ~200 m track."""
    import numpy as np
    lat_r = math.radians(lat0)
    e = np.radians(np.asarray(lon) - lon0) * EARTH_R * math.cos(lat_r)
    n = np.radians(np.asarray(lat) - lat0) * EARTH_R
    return e, n


def enu_to_lonlat(e, n, lon0, lat0):
    """Inverse of lonlat_to_enu."""
    import numpy as np
    lat_r = math.radians(lat0)
    lon = lon0 + np.degrees(np.asarray(e) / (EARTH_R * math.cos(lat_r)))
    lat = lat0 + np.degrees(np.asarray(n) / EARTH_R)
    return lon, lat


def venue_geojson(venue: str) -> dict:
    """Load the venue landmark geojson (gate, corners, pit routes)."""
    # the file is named gateway_kartplex_t1.geojson for this venue
    vdir = OUTPUT / venue / "_venue"
    cands = sorted(vdir.glob("*_t1.geojson")) or sorted(vdir.glob("*.geojson"))
    if not cands:
        raise FileNotFoundError(f"no venue geojson in {vdir}")
    return load_json(cands[0])


def venue_feature(gj: dict, fid: str) -> dict | None:
    for ft in gj.get("features", []):
        if ft.get("properties", {}).get("id") == fid:
            return ft
    return None
