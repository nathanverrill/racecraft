"""Data loading, time-window clipping, and ENU conversion for Sensor Logger karting data."""
import numpy as np
import pandas as pd
from pathlib import Path

# Session window comes from session_config (switch sessions there)
from session_config import WINDOW_START, WINDOW_END

DATA_DIR = Path(__file__).resolve().parent.parent          # visit_6/ (full-precision IMU)
GPS_DIR = DATA_DIR.parent                                   # session root


def _load(name):
    df = pd.read_csv(DATA_DIR / f"{name}.csv")
    return df


def load_location():
    """Load GPS from raw/ (full lat/lon precision), clip to window.

    NOTE: visit_6/Location.csv has lat/lon rounded to 2 decimals (~1km),
    which is unusable. raw/Location.csv preserves full precision.
    """
    df = pd.read_csv(GPS_DIR / "raw" / "Location.csv")
    df = df[(df.seconds_elapsed >= WINDOW_START) & (df.seconds_elapsed <= WINDOW_END)].copy()
    df = df.sort_values("seconds_elapsed").reset_index(drop=True)
    return df


def load_imu():
    """Load and merge 100 Hz IMU streams onto a common timeline."""
    gyro = _load("Gyroscope").rename(columns={"x": "gx", "y": "gy", "z": "gz"})
    grav = _load("Gravity").rename(columns={"x": "grx", "y": "gry", "z": "grz"})
    acc = _load("Accelerometer").rename(columns={"x": "ax", "y": "ay", "z": "az"})
    ori = _load("Orientation")[["seconds_elapsed", "qw", "qx", "qy", "qz", "yaw", "pitch", "roll"]]

    df = gyro[["seconds_elapsed", "gx", "gy", "gz"]]
    for other in (grav[["seconds_elapsed", "grx", "gry", "grz"]],
                  acc[["seconds_elapsed", "ax", "ay", "az"]],
                  ori):
        df = pd.merge_asof(df.sort_values("seconds_elapsed"),
                           other.sort_values("seconds_elapsed"),
                           on="seconds_elapsed", direction="nearest",
                           tolerance=0.02)
    df = df[(df.seconds_elapsed >= WINDOW_START) & (df.seconds_elapsed <= WINDOW_END)].copy()
    df = df.dropna().sort_values("seconds_elapsed").reset_index(drop=True)
    return df


def to_enu(lat, lon, lat0, lon0):
    """Equirectangular local ENU projection (valid for a small track)."""
    R = 6378137.0
    lat0r = np.radians(lat0)
    east = np.radians(lon - lon0) * R * np.cos(lat0r)
    north = np.radians(lat - lat0) * R
    return east, north


if __name__ == "__main__":
    loc = load_location()
    imu = load_imu()
    print("GPS rows:", len(loc), "| span s:", round(loc.seconds_elapsed.iloc[-1] - loc.seconds_elapsed.iloc[0], 1))
    print("IMU rows:", len(imu), "| span s:", round(imu.seconds_elapsed.iloc[-1] - imu.seconds_elapsed.iloc[0], 1))
    lat0, lon0 = loc.latitude.iloc[0], loc.longitude.iloc[0]
    e, n = to_enu(loc.latitude.values, loc.longitude.values, lat0, lon0)
    print("ENU extent (m): E", round(e.min(), 1), "to", round(e.max(), 1),
          "| N", round(n.min(), 1), "to", round(n.max(), 1))