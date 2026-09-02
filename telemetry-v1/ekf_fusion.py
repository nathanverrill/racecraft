"""
Loosely-coupled GPS + IMU Extended Kalman Filter for Sensor Logger data.

State vector x = [pE, pN, vE, vN]   (position east/north meters, velocity m/s)

Prediction: driven by linear acceleration (Accelerometer - Gravity) rotated
            into the world ENU frame using the Orientation quaternion.
Update:     GPS position (lat/lon -> local ENU) and optional GPS speed/bearing.

Outputs Position.csv at IMU frequency.
"""

import sys
import numpy as np
import pandas as pd

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------
# Usage: python3.11 ekf_fusion.py [folder]
#   folder defaults to "clean". Pass "session1" / "session2" for split data.
BASE = sys.argv[1] if len(sys.argv) > 1 else "clean"
OUT = f"{BASE}/Position.csv" if BASE != "clean" else "Position.csv"

# Tunable noise parameters --------------------------------------------------
ACCEL_NOISE_STD = 0.5       # m/s^2  process noise from accel (raise if jittery)
GPS_POS_STD_FALLBACK = 5.0  # m      used if horizontalAccuracy missing
GPS_SPEED_STD = 0.5         # m/s    measurement noise on GPS speed (trust it)
USE_GPS_SPEED = True        # fuse the speed/bearing channel too

EARTH_R = 6378137.0         # meters


# ----------------------------------------------------------------------
# LOAD DATA
# ----------------------------------------------------------------------
def load(name):
    return pd.read_csv(f"{BASE}/{name}")


loc = load("Location.csv")
accel = load("Accelerometer.csv")
grav = load("Gravity.csv")
orient = load("Orientation.csv")

# Filter invalid GPS rows (-1.0 sentinels on accuracy)
loc = loc[loc["horizontalAccuracy"] > 0].copy()
loc = loc.sort_values("time").reset_index(drop=True)

# Sort IMU streams by time
for d in (accel, grav, orient):
    d.sort_values("time", inplace=True)


# ----------------------------------------------------------------------
# GEO -> LOCAL ENU (equirectangular, fine for a single track)
# ----------------------------------------------------------------------
lat0 = loc["latitude"].iloc[0]
lon0 = loc["longitude"].iloc[0]
cos_lat0 = np.cos(np.radians(lat0))


def geo_to_enu(lat, lon):
    e = np.radians(lon - lon0) * EARTH_R * cos_lat0
    n = np.radians(lat - lat0) * EARTH_R
    return e, n


loc["E"], loc["N"] = geo_to_enu(loc["latitude"].values, loc["longitude"].values)


# ----------------------------------------------------------------------
# ALIGN IMU STREAMS ONTO ACCEL TIMEBASE (interpolation)
# ----------------------------------------------------------------------
t_imu = accel["time"].values.astype(np.float64)


def interp_to(master_t, df, cols):
    src_t = df["time"].values.astype(np.float64)
    return {c: np.interp(master_t, src_t, df[c].values) for c in cols}


orient_i = interp_to(t_imu, orient, ["qw", "qx", "qy", "qz"])

# NOTE: Sensor Logger's Accelerometer.csv is ALREADY gravity-compensated
# (it is the user/linear acceleration stream, magnitude ~0 at rest).
# Do NOT subtract Gravity.csv again -- doing so injects a ~9.8 m/s^2 bias.
lin_x = accel["x"].values.astype(float)
lin_y = accel["y"].values.astype(float)
lin_z = accel["z"].values.astype(float)

# Remove residual constant bias (vehicle nets ~0 acceleration over a session)
lin_x -= lin_x.mean()
lin_y -= lin_y.mean()
lin_z -= lin_z.mean()


# ----------------------------------------------------------------------
# ROTATE BODY ACCEL -> WORLD (ENU) using quaternion
# v_world = R(q) * v_body
# ----------------------------------------------------------------------
def quat_rotate(qw, qx, qy, qz, vx, vy, vz):
    norm = np.sqrt(qw * qw + qx * qx + qy * qy + qz * qz)
    norm[norm == 0] = 1.0
    qw, qx, qy, qz = qw / norm, qx / norm, qy / norm, qz / norm

    r00 = 1 - 2 * (qy * qy + qz * qz)
    r01 = 2 * (qx * qy - qz * qw)
    r02 = 2 * (qx * qz + qy * qw)
    r10 = 2 * (qx * qy + qz * qw)
    r11 = 1 - 2 * (qx * qx + qz * qz)
    r12 = 2 * (qy * qz - qx * qw)
    r20 = 2 * (qx * qz - qy * qw)
    r21 = 2 * (qy * qz + qx * qw)
    r22 = 1 - 2 * (qx * qx + qy * qy)

    wx = r00 * vx + r01 * vy + r02 * vz
    wy = r10 * vx + r11 * vy + r12 * vz
    wz = r20 * vx + r21 * vy + r22 * vz
    return wx, wy, wz


# World-frame acceleration. Sensor Logger world frame is ENU:
# X = East, Y = North, Z = Up.
aE, aN, aU = quat_rotate(
    orient_i["qw"], orient_i["qx"], orient_i["qy"], orient_i["qz"],
    lin_x, lin_y, lin_z,
)


# ----------------------------------------------------------------------
# MERGED EVENT TIMELINE (IMU predict + GPS update)
# ----------------------------------------------------------------------
events = []  # (time_ns, type, idx)
for i in range(len(t_imu)):
    events.append((t_imu[i], "imu", i))
for j in range(len(loc)):
    events.append((float(loc["time"].iloc[j]), "gps", j))
events.sort(key=lambda e: e[0])


# ----------------------------------------------------------------------
# KALMAN FILTER   state x = [E, N, vE, vN]
# ----------------------------------------------------------------------
x = np.zeros(4)
x[0] = loc["E"].iloc[0]
x[1] = loc["N"].iloc[0]
P = np.diag([10.0, 10.0, 5.0, 5.0])

I4 = np.eye(4)
qa = ACCEL_NOISE_STD ** 2

results = []
prev_t = events[0][0]

for t_ns, kind, idx in events:
    dt = (t_ns - prev_t) * 1e-9  # ns -> s
    if dt < 0:
        dt = 0.0
    prev_t = t_ns

    # ---- PREDICT ----
    if dt > 0:
        F = np.array([
            [1, 0, dt, 0],
            [0, 1, 0, dt],
            [0, 0, 1, 0],
            [0, 0, 0, 1],
        ])
        if kind == "imu":
            aE_k, aN_k = aE[idx], aN[idx]
        else:
            aE_k = aN_k = 0.0
        B = np.array([0.5 * dt * dt, 0.5 * dt * dt, dt, dt])
        u = np.array([aE_k, aN_k, aE_k, aN_k])
        x = F @ x + B * u

        G = np.array([0.5 * dt * dt, 0.5 * dt * dt, dt, dt])
        Q = np.outer(G, G) * qa
        P = F @ P @ F.T + Q

    # ---- UPDATE (GPS) ----
    if kind == "gps":
        row = loc.iloc[idx]
        hacc = row["horizontalAccuracy"]
        pos_std = hacc if hacc and hacc > 0 else GPS_POS_STD_FALLBACK

        z = np.array([row["E"], row["N"]])
        H = np.array([[1, 0, 0, 0],
                      [0, 1, 0, 0]])
        R = np.diag([pos_std ** 2, pos_std ** 2])
        y = z - H @ x
        S = H @ P @ H.T + R
        K = P @ H.T @ np.linalg.inv(S)
        x = x + K @ y
        P = (I4 - K @ H) @ P

        # optionally fuse GPS speed via bearing decomposition
        if USE_GPS_SPEED and row.get("speed", -1) >= 0:
            spd = row["speed"]
            bearing = row.get("bearing", -1)
            if bearing is not None and bearing >= 0:
                br = np.radians(bearing)  # 0 = North, clockwise
                vE_meas = spd * np.sin(br)
                vN_meas = spd * np.cos(br)
                zv = np.array([vE_meas, vN_meas])
                Hv = np.array([[0, 0, 1, 0],
                               [0, 0, 0, 1]])
                Rv = np.diag([GPS_SPEED_STD ** 2, GPS_SPEED_STD ** 2])
                yv = zv - Hv @ x
                Sv = Hv @ P @ Hv.T + Rv
                Kv = P @ Hv.T @ np.linalg.inv(Sv)
                x = x + Kv @ yv
                P = (I4 - Kv @ Hv) @ P

    if kind == "imu":
        results.append((t_ns, x[0], x[1], x[2], x[3]))


# ----------------------------------------------------------------------
# SAVE
# ----------------------------------------------------------------------
out = pd.DataFrame(results, columns=["time", "E", "N", "vE", "vN"])
out["speed"] = np.sqrt(out["vE"] ** 2 + out["vN"] ** 2)

# Convert fused ENU back to lat/lon for mapping convenience
out["latitude"] = lat0 + np.degrees(out["N"] / EARTH_R)
out["longitude"] = lon0 + np.degrees(out["E"] / (EARTH_R * cos_lat0))

out = out.round({"E": 3, "N": 3, "vE": 3, "vN": 3, "speed": 3,
                 "latitude": 7, "longitude": 7})
out.to_csv(OUT, index=False)
print(f"Wrote {len(out)} fused samples -> {OUT}")
print(out.head())